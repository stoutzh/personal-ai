"""Synthetic tests: no personal reminders, EventKit access or network."""
import json
import unittest
from unittest.mock import patch
from agents import SQLiteSession
from agents.tool_context import ToolContext
from openai import AsyncOpenAI
import sdk_reminders as r
from sdk_demo import build_agent, RUN_CONFIG
from sdk_capabilities import RuntimeState
from sdk_mail import MailError


def payload(list_id='selected'):
    return {'ok': True, 'list_id': list_id, 'truncated': False, 'items': [
        {'id': 'fixture', 'title': 'Synthetic task', 'due': {'year': 2026, 'month': 9, 'day': 17},
         'completed': False, 'notes': 'PRIVATE_FIXTURE'}]}

class AdapterTests(unittest.TestCase):
    def test_scope_and_limit_before_process(self):
        with patch('sdk_reminders._run') as backend:
            for list_id, limit in [('other', 3), ('selected', True), ('selected', 21), ('selected', 0)]:
                with self.assertRaises(r.RemindersError):
                    r.list_incomplete(list_id, limit, allowed_lists=('selected',))
            backend.assert_not_called()

    def test_fixed_fields_and_quantity(self):
        source = payload(); source['items'] *= 3
        result = r.list_incomplete('selected', 1, allowed_lists=('selected',), _runner=lambda *args: source)
        self.assertEqual(len(result['items']), 1)
        self.assertTrue(result['truncated'])
        self.assertNotIn('PRIVATE_FIXTURE', json.dumps(result))
        self.assertNotIn('notes', result['items'][0])

    def test_malformed_or_wrong_list_rejected(self):
        wrong = payload('other')
        completed = payload(); completed['items'][0]['completed'] = True
        for source in (wrong, completed, [], {'ok': True}):
            with self.assertRaises(r.RemindersError):
                r.list_incomplete('selected', allowed_lists=('selected',), _runner=lambda *args: source)

    def test_errors_sanitized(self):
        with patch('sdk_reminders.subprocess.Popen', side_effect=OSError('/private/SECRET_FIXTURE')):
            with self.assertRaises(r.RemindersError) as caught:
                r._run('selected', 3)
        self.assertEqual(caught.exception.code, 'launch_failed')
        self.assertNotIn('SECRET_FIXTURE', str(caught.exception))
        with patch('sdk_reminders.subprocess.Popen') as popen, patch('sdk_reminders.collect_limited') as collect:
            popen.return_value.returncode = 1
            collect.return_value = (b'{"ok":false,"error_code":"SECRET_FIXTURE"}', b'private stderr')
            with self.assertRaises(r.RemindersError) as caught:
                r._run('selected', 3)
            self.assertEqual(caught.exception.code, 'helper_failed')
            collect.side_effect = MailError('private diagnostic', code='timeout')
            with self.assertRaises(r.RemindersError) as caught:
                r._run('selected', 3)
            self.assertEqual(caught.exception.code, 'timeout')
            self.assertNotIn('private', str(caught.exception))

    def test_invalid_config(self):
        for lists in ('selected', True, [''], ['x\nsecret'], [1]):
            with self.assertRaises(ValueError):
                r.validate_lists(lists)

class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_facts_and_real_tool_boundary(self):
        config = {'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['README.md']}}
        async with AsyncOpenAI(api_key='offline-placeholder') as client:
            disabled, _ = build_agent(config, client, instructions='test')
            self.assertNotIn('list_reminders', [t.name for t in disabled.tools])
            agent, _ = build_agent(config, client, instructions='test', reminder_lists=('selected',))
            session = SQLiteSession('reminder-test')
            try:
                state = RuntimeState(session, 0)
                facts = await agent.instructions.facts(agent, state)
                self.assertEqual(facts['allowed_reminder_lists'], ['selected'])
                self.assertTrue(facts['reminder_tools_read_only'])
                self.assertFalse(facts['file_write_tool_present'])
                tool = next(t for t in agent.tools if t.name == 'list_reminders')
                with patch('sdk_reminders._run', return_value=payload()) as backend:
                    for list_id in ('other', 'selected'):
                        args = json.dumps({'list_id': list_id, 'limit': 3})
                        ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id='test', tool_arguments=args, run_config=RUN_CONFIG)
                        result = json.loads(await tool.on_invoke_tool(ctx, args))
                        if list_id == 'other':
                            self.assertEqual(result['error_code'], 'list_not_enabled')
                            backend.assert_not_called()
                        else:
                            self.assertTrue(result['ok']); backend.assert_called_once_with('selected', 3)
                tool.is_enabled = False
                facts = await agent.instructions.facts(agent, state)
                self.assertEqual(facts['allowed_reminder_lists'], [])
            finally:
                session.close()
