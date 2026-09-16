"""Manual mail-to-reminder workflow, using synthetic content only."""
import json
import unittest
from unittest.mock import patch
from openai import AsyncOpenAI
from agents import SQLiteSession
from agents.tool_context import ToolContext
from sdk_mail import read_message, MailError
from sdk_reminder_drafts import ReminderDrafts, validate_due
from sdk_reminders import RemindersError
from sdk_demo import build_agent, RUN_CONFIG
from sdk_capabilities import RuntimeState

class BodyTests(unittest.TestCase):
    def test_plain_body_and_read_only_command(self):
        raw = b'Subject: Application\r\nDate: Tue, 15 Sep 2026 12:00:00 -0700\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nDeadline: September 17, 5pm Pacific.\r\n'
        commands = []
        def runner(cmd, *args):
            commands.append(cmd); return raw
        result = read_message('school', '42', allowed_ids={'42'}, _run=runner)
        self.assertIn('5pm Pacific', result['text'])
        self.assertNotIn('--seen', commands[0])
        self.assertEqual(commands[0][-1], '42')
        self.assertIn('ucsb', commands[0])
        self.assertTrue(result['seen_unchanged'])

    def test_unlisted_and_injected_ids_never_run(self):
        with patch('sdk_mail._run_himalaya') as backend:
            for value in ('43', '--seen', '../42', '', 42):
                with self.assertRaises(MailError):
                    read_message('school', value, allowed_ids={'42'})
            backend.assert_not_called()

    def test_attachment_not_returned_and_html_not_fetched(self):
        raw = b'Subject: Test\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=x\n\n--x\nContent-Type: text/plain\n\nReal body\n--x\nContent-Type: text/plain\nContent-Disposition: attachment; filename=secret.txt\n\nATTACHMENT_SECRET\n--x--\n'
        result = read_message('school', '1', allowed_ids={'1'}, _run=lambda *args: raw)
        self.assertIn('Real body', result['text'])
        self.assertNotIn('ATTACHMENT_SECRET', result['text'])
        html = b'Subject: HTML\nContent-Type: text/html\n\n<img src="https://example.invalid/track">'
        result = read_message('school', '1', allowed_ids={'1'}, _run=lambda *args: html)
        self.assertEqual(result['body_status'], 'no_plain_text')
        self.assertEqual(result['text'], '')

    def test_truncation_and_invalid_body(self):
        raw = b'Subject: Long\nContent-Type: text/plain\n\n' + b'x' * 13000
        result = read_message('school', '1', allowed_ids={'1'}, _run=lambda *args: raw)
        self.assertTrue(result['truncated']); self.assertEqual(len(result['text']), 12000)
        with self.assertRaises(MailError):
            read_message('school', '1', allowed_ids={'1'}, _run=lambda *args: b'not mail')

class DraftTests(unittest.TestCase):
    def test_prepare_never_writes_and_confirmation_consumed_once(self):
        drafts = ReminderDrafts(('selected',))
        with patch('sdk_reminder_drafts._create') as create:
            prepared = drafts.prepare('selected', 'Synthetic task', '2026-09-17')
            self.assertFalse(prepared['saved']); create.assert_not_called()
            duplicate = drafts.prepare('selected', 'Synthetic task', '2026-09-17')
            self.assertEqual(duplicate['draft_id'], prepared['draft_id'])
            prepared['preview']['title'] = 'tampered'
            create.return_value = {'ok': True, 'id': 'fixture', 'created': True}
            result = drafts.confirm(prepared['draft_id'])
            self.assertTrue(result['created']); create.assert_called_once()
            self.assertEqual(create.call_args.args[0]['title'], 'Synthetic task')
            with self.assertRaises(RemindersError): drafts.confirm(prepared['draft_id'])

    def test_unknown_outcome_not_retried(self):
        drafts = ReminderDrafts(('selected',)); token = drafts.prepare('selected', 'Test')['draft_id']
        with patch('sdk_reminder_drafts._create', side_effect=RemindersError('write_status_unknown')) as create:
            with self.assertRaises(RemindersError): drafts.confirm(token)
            with self.assertRaises(RemindersError): drafts.confirm(token)
            create.assert_called_once()

    def test_dates_timezones_and_no_invented_time(self):
        self.assertEqual(validate_due('', '', ''), {})
        self.assertEqual(validate_due('2026-09-17', '', ''), {'year': 2026, 'month': 9, 'day': 17})
        due = validate_due('2026-09-17', '17:00', 'America/Los_Angeles')
        self.assertEqual(due['hour'], 17)
        for args in [('2026-02-30','',''), ('2026-09-17','17:00',''), ('2026-09-17','25:00','UTC'), ('','17:00','UTC'), ('2026-11-01','01:30','America/Los_Angeles'), ('2026-03-08','02:30','America/Los_Angeles')]:
            with self.subTest(args=args), self.assertRaises(RemindersError): validate_due(*args)

    def test_native_request_errors_do_not_expose_diagnostics(self):
        from sdk_reminder_drafts import _create
        with patch('sdk_reminder_drafts.subprocess.Popen') as popen, patch('sdk_reminder_drafts.collect_limited') as collect:
            popen.return_value.returncode = 1
            collect.return_value = (b'{"ok":false,"error_code":"/private/SECRET_FIXTURE"}', b'private diagnostic')
            with self.assertRaises(RemindersError) as caught:
                _create({'title':'Fixture'})
            self.assertEqual(caught.exception.code, 'write_status_unknown')
            self.assertNotIn('SECRET_FIXTURE', str(caught.exception))

    def test_scope_cancel_and_restart(self):
        drafts = ReminderDrafts(('selected',))
        with self.assertRaises(RemindersError): drafts.prepare('other', 'Title')
        token = drafts.prepare('selected','Title')['draft_id']
        with self.assertRaises(RemindersError): ReminderDrafts(('selected',)).confirm(token)
        drafts.cancel(token)
        self.assertEqual(drafts.pending(), {})

class WireTests(unittest.IsolatedAsyncioTestCase):
    async def test_separate_permissions_and_no_model_confirmation_tool(self):
        config = {'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['README.md']}}
        async with AsyncOpenAI(api_key='offline-placeholder') as client:
            drafts = ReminderDrafts(('selected',))
            agent, _ = build_agent(config, client, instructions='fixture', mail_accounts=('school',), mail_body_accounts=('school',), reminder_drafts=drafts)
            self.assertNotIn('confirm', [t.name for t in agent.tools])
            session = SQLiteSession('workflow')
            try:
                facts = await agent.instructions.facts(agent, RuntimeState(session, 0))
                self.assertEqual(facts['mail_body_accounts'], ['school'])
                self.assertEqual(facts['reminder_prepare_lists'], ['selected'])
                self.assertEqual(facts['allowed_reminder_lists'], [])
                self.assertTrue(facts['reminder_create_requires_terminal_confirmation'])
                async def invoke(name, args):
                    tool = next(t for t in agent.tools if t.name == name); raw = json.dumps(args)
                    ctx = ToolContext(context=None,tool_name=name,tool_call_id='test',tool_arguments=raw,run_config=RUN_CONFIG)
                    return json.loads(await tool.on_invoke_tool(ctx,raw))
                with patch('sdk_mail._run_himalaya') as backend:
                    result = await invoke('read_email', {'account':'gmail','message_id':'1'})
                    self.assertEqual(result['error_code'],'body_not_enabled')
                    result = await invoke('read_email', {'account':'school','message_id':'1'})
                    self.assertEqual(result['error_code'],'message_not_listed')
                    backend.assert_not_called()
                with patch('sdk_reminder_drafts._create') as creator:
                    result = await invoke('prepare_reminder', {'list_id':'selected','title':'Test'})
                    self.assertFalse(result['saved']); creator.assert_not_called()
            finally: session.close()
