"""Offline wire-adapter, real tool execution, and SDK Session integration checks."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from agents import Runner, SQLiteSession
from sdk_demo import build_agent, load_startup, RUN_CONFIG, smoke


class PrototypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_and_session_through_chat_completions(self):
        requests = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('fixture')
            config = {'provider': {'model': 'provider-test', 'extra_body': {}}, 'tools': {'allowed_paths': ['README.md']}}
            (root / 'context').mkdir()
            (root / 'context/note.md').write_text('STARTUP_FIXTURE')
            (root / 'context/unselected.md').write_text('NOT_SELECTED_FIXTURE')
            (root / 'aion.json').write_text(json.dumps({'files': ['context/note.md']}))
            async def completion(**kwargs):
                requests.append(kwargs)
                self.assertEqual(kwargs['model'], 'provider-test')
                self.assertEqual({t['function']['name'] for t in kwargs['tools']}, {'list_directory', 'read_text_file'})
                system = '\n'.join(m['content'] for m in kwargs['messages'] if m['role'] in {'system', 'developer'})
                self.assertIn('STARTUP_FIXTURE', system)
                self.assertNotIn('NOT_SELECTED_FIXTURE', system)
                self.assertIn('Session 仅在内存', system)
                facts = json.loads(system.split('<runtime_capabilities>\n')[1].split('\n')[0])
                self.assertEqual(facts['available_tools'], ['list_directory', 'read_text_file'])
                self.assertFalse(facts['file_write_tool_present'])
                if len(requests) == 1:
                    self.assertFalse(facts['history_available'])
                if len(requests) >= 3:
                    self.assertTrue(facts['history_available'])
                if len(requests) == 1:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'list_directory', 'arguments': '{"path":"."}'}}]}
                    reason = 'tool_calls'
                elif len(requests) == 4:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_read', 'type': 'function', 'function': {'name': 'read_text_file', 'arguments': '{"path":"README.md"}'}}]}
                    reason = 'tool_calls'
                else:
                    tool_messages = [m for m in kwargs['messages'] if m['role'] == 'tool']
                    self.assertEqual(json.loads(tool_messages[0]['content'])['entries'], [{'name': 'README.md', 'type': 'file'}])
                    if len(requests) == 5:
                        self.assertEqual(json.loads(tool_messages[-1]['content'])['content'], 'fixture')
                    marker = re.search(r'aion-[0-9a-f]+', json.dumps(kwargs['messages'], ensure_ascii=False)).group()
                    message = {'role': 'assistant', 'content': marker}
                    reason = 'stop'
                return ChatCompletion.model_validate({'id': 'offline', 'object': 'chat.completion', 'created': 0, 'model': 'provider-test', 'choices': [{'index': 0, 'finish_reason': reason, 'message': message}]})
            async with AsyncOpenAI(api_key='offline-placeholder', base_url='https://example.invalid/v1') as client:
                agent, events = build_agent(config, client, root=root)
                session = SQLiteSession('test')
                try:
                    with patch.object(client.chat.completions, 'create', AsyncMock(side_effect=completion)):
                        await smoke(agent, events, session, read_file=True)
                    self.assertEqual(len(requests), 5)
                    self.assertTrue(RUN_CONFIG.tracing_disabled)
                finally:
                    session.close()

    async def test_tool_rejects_parent_path(self):
        async with AsyncOpenAI(api_key='offline-placeholder') as client:
            agent, events = build_agent({'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['README.md']}}, client, instructions='test')
            from agents.tool_context import ToolContext
            result = await agent.tools[0].on_invoke_tool(ToolContext(context=None, tool_name="list_directory", tool_call_id="denied", tool_arguments='{"path":"../"}', run_config=RUN_CONFIG), '{"path":"../"}')
            self.assertFalse(json.loads(result)['ok'])

    async def test_read_tool_keeps_boundaries(self):
        from agents.tool_context import ToolContext
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs').mkdir()
            (root / 'docs/big.txt').write_text('x' * 16001)
            (root / 'docs/link.txt').symlink_to(root / 'docs/big.txt')
            async with AsyncOpenAI(api_key='offline-placeholder') as client:
                agent, _ = build_agent({'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['docs']}}, client, root=root, instructions='test')
                tool = next(t for t in agent.tools if t.name == 'read_text_file')
                for path in ['../outside', '/etc/passwd', 'docs/.env', 'unlisted.txt', 'docs/big.txt', 'docs/link.txt']:
                    with self.subTest(path=path):
                        arguments = json.dumps({'path': path})
                        ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id='denied', tool_arguments=arguments, run_config=RUN_CONFIG)
                        self.assertFalse(json.loads(await tool.on_invoke_tool(ctx, arguments))['ok'])

    def test_startup_rejects_outside_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'context').mkdir()
            (root / 'outside.md').write_text('not permitted')
            (root / 'context/link.md').symlink_to(root / 'outside.md')
            for name in ['../outside.md', 'context/link.md']:
                (root / 'aion.json').write_text(json.dumps({'files': [name]}))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    load_startup({'tools': {'allowed_paths': ['README.md']}}, root)

    async def test_mail_registration_and_sdk_round_trip(self):
        from sdk_capabilities import run_agent, RuntimeState
        from sdk_mail import MailError
        config = {'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['README.md']}}
        async with AsyncOpenAI(api_key='offline-placeholder') as client:
            disabled, _ = build_agent(config, client, instructions='test')
            session = SQLiteSession('disabled')
            try:
                facts = await disabled.instructions.facts(disabled, RuntimeState(session, 0))
                self.assertEqual(facts['mail_tools'], [])
                self.assertNotIn('list_unread', facts['available_tools'])
            finally:
                session.close()
            for failed in (False, True):
                agent, _ = build_agent(config, client, instructions='test', mail_accounts=('gmail',))
                session = SQLiteSession('wire')
                responses = []
                async def completion(**kwargs):
                    self.assertIn('list_unread', [t['function']['name'] for t in kwargs['tools']])
                    if not responses:
                        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'mail1', 'type': 'function', 'function': {'name': 'list_unread', 'arguments': '{"account":"gmail","limit":2}'}}]}
                        finish = 'tool_calls'
                    else:
                        result = json.loads(next(m['content'] for m in kwargs['messages'] if m['role'] == 'tool'))
                        self.assertEqual(result['ok'], not failed)
                        if failed:
                            self.assertEqual(result['error_code'], 'mail_error')
                            self.assertIsNone(result['unread_count'])
                        message = {'role': 'assistant', 'content': 'done'}
                        finish = 'stop'
                    responses.append(message)
                    return ChatCompletion.model_validate({'id': 'offline', 'object': 'chat.completion', 'created': 0, 'model': 'test', 'choices': [{'index': 0, 'finish_reason': finish, 'message': message}]})
                try:
                    with patch('sdk_demo.mail_list_unread', return_value={'ok': True, 'account': 'gmail', 'unread': []}, side_effect=MailError('受控错误') if failed else None) as mail, patch.object(client.chat.completions, 'create', AsyncMock(side_effect=completion)), patch('sdk_mail.subprocess.Popen', side_effect=AssertionError('real process forbidden')):
                        await run_agent(agent, '查未读', session=session, run_config=RUN_CONFIG)
                        mail.assert_called_once_with('gmail', 2)
                    self.assertEqual(len(responses), 2)
                finally:
                    session.close()

    async def test_mail_account_boundary_before_backend(self):
        from agents.tool_context import ToolContext
        from sdk_capabilities import RuntimeState
        config = {'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['README.md']}}
        async with AsyncOpenAI(api_key='offline-placeholder') as client:
            agent, _ = build_agent(config, client, instructions='test', mail_accounts=('school',))
            session = SQLiteSession('scope')
            try:
                facts = await agent.instructions.facts(agent, RuntimeState(session, 0))
                self.assertEqual(facts['allowed_mail_accounts'], ['school'])
                tool = next(t for t in agent.tools if t.name == 'list_unread')
                with patch('sdk_demo.mail_list_unread') as backend:
                    for account in ('gmail', 'ucsb', '163', 'unknown'):
                        args = json.dumps({'account': account, 'limit': 3})
                        ctx = ToolContext(context=None, tool_name=tool.name, tool_call_id='scope', tool_arguments=args, run_config=RUN_CONFIG)
                        result = json.loads(await tool.on_invoke_tool(ctx, args))
                        self.assertEqual(result['error_code'], 'account_not_enabled')
                        self.assertIsNone(result['unread_count'])
                    backend.assert_not_called()
                agent.tools.remove(tool)
                facts = await agent.instructions.facts(agent, RuntimeState(session, 0))
                self.assertEqual(facts['allowed_mail_accounts'], [])
                for invalid in (True, 'gmail', ('unknown',)):
                    with self.assertRaises(ValueError):
                        build_agent(config, client, instructions='test', mail_accounts=invalid)
            finally:
                session.close()


if __name__ == '__main__':
    unittest.main()
