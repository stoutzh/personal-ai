"""Real process restart and CLI integration, with only the model API mocked."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sdk_sessions import SessionHandle, SessionError

WORKER = r'''
import asyncio, json, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import sdk_demo
from openai.types.chat import ChatCompletion
sdk_demo.ROOT = Path(sys.argv[1])
stage = sys.argv[2]
inputs = iter(['记住口令 restart-marker 并读取 README.md。', '/exit'] if stage == 'first' else ['刚才的口令是什么？继续聊天。', '/exit'])
count = 0
async def completion(**kwargs):
    global count
    count += 1
    messages = kwargs['messages']
    system = '\n'.join(m['content'] for m in messages if m['role'] in {'system', 'developer'})
    facts = json.loads(system.split('<runtime_capabilities>\n')[1].split('\n')[0])
    assert facts['program_session_persistence']
    assert not facts['file_write_tool_present']
    assert ('BACKGROUND_V1' if stage == 'first' else 'BACKGROUND_V2') in system
    if stage != 'first':
        assert facts['restored_at_startup'] and facts['history_available']
        assert 'BACKGROUND_V1' not in system
        assert 'restart-marker' in json.dumps(messages)
        assert any(m['role'] == 'tool' and 'fixture text' in m['content'] for m in messages)
        assert sum(m['role'] == 'user' for m in messages) >= 2
    if stage == 'first' and count == 1:
        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'read1', 'type': 'function', 'function': {'name': 'read_text_file', 'arguments': '{"path":"README.md"}'}}]}
        finish = 'tool_calls'
    else:
        message = {'role': 'assistant', 'content': 'restart-marker' if stage == 'first' else 'RESTORED_AND_CONTINUED'}
        finish = 'stop'
    return ChatCompletion.model_validate({'id': 'offline', 'object': 'chat.completion', 'created': 0, 'model': 'test', 'choices': [{'index': 0, 'finish_reason': finish, 'message': message}]})
original = sdk_demo.AsyncOpenAI
client = original(api_key='offline-test-key', base_url='https://example.invalid')
args = SimpleNamespace(check=False, smoke=False, smoke_files=False, no_save=False, model=None, resume=None if stage == 'first' else 'latest')
with patch.dict('os.environ', {'TEST_API_KEY': 'offline-test-key'}), patch('builtins.input', side_effect=lambda _: next(inputs)), patch.object(client.chat.completions, 'create', AsyncMock(side_effect=completion)), patch.object(sdk_demo, 'AsyncOpenAI', return_value=client):
    asyncio.run(sdk_demo.run(args))
'''


class SessionTests(unittest.TestCase):
    def test_exit_restart_resume_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'context').mkdir()
            (root / 'context/note.md').write_text('BACKGROUND_V1')
            (root / 'README.md').write_text('fixture text')
            (root / '.aion/sessions').mkdir(parents=True)
            legacy = root / '.aion/sessions/legacy.json'
            legacy.write_bytes(b'legacy must remain unchanged')
            config = {'files': ['context/note.md'], 'tools': {'allowed_paths': ['README.md']}, 'provider': {'name': 'Offline', 'api_format': 'chat_completions', 'endpoint': 'https://example.invalid/chat/completions', 'model': 'test', 'api_key_env': 'TEST_API_KEY'}}
            (root / 'aion.json').write_text(json.dumps(config))
            for stage in ['first', 'second']:
                if stage == 'second':
                    (root / 'context/note.md').write_text('BACKGROUND_V2')
                result = subprocess.run([sys.executable, '-B', '-c', WORKER, directory, stage], cwd=Path(__file__).parent, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if stage == 'second':
                    self.assertIn('RESTORED_AND_CONTINUED', result.stdout)
            self.assertEqual(legacy.read_bytes(), b'legacy must remain unchanged')
            store = root / '.aion/sdk-sessions'
            self.assertEqual(len(list(store.glob('*.sqlite3'))), 1)
            resumed = SessionHandle(root, resume='latest')
            try:
                items = asyncio.run(resumed.session.get_items())
                self.assertEqual(items[-1]['content'][0]['text'], 'RESTORED_AND_CONTINUED')
                self.assertFalse(any(i.get('role') in {'system', 'developer'} for i in items))
            finally:
                resumed.close()
            self.assertEqual(store.stat().st_mode & 0o777, 0o700)
            for path in store.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(b'offline-test-key', path.read_bytes())

    def test_new_temporary_redaction_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(SessionError):
                SessionHandle(root, resume='latest')
            handle = SessionHandle(root, key='example-current-key')
            ident = handle.session.session_id
            asyncio.run(handle.session.add_items([{'role': 'user', 'content': 'example-current-key sk-example-secret-value'}]))
            handle.mark_saved()
            handle.close()
            resumed = SessionHandle(root, resume=ident)
            try:
                content = json.dumps(asyncio.run(resumed.session.get_items()))
                self.assertNotIn('example-current-key', content)
                self.assertNotIn('sk-example-secret-value', content)
                with self.assertRaises(BlockingIOError):
                    SessionHandle(root, resume=ident)
            finally:
                resumed.close()
            fresh = SessionHandle(root)
            try:
                self.assertNotEqual(fresh.session.session_id, ident)
                self.assertEqual(asyncio.run(fresh.session.get_items()), [])
            finally:
                fresh.close()
            before = {p.name: p.read_bytes() for p in (root / '.aion/sdk-sessions').iterdir()}
            temporary = SessionHandle(root, no_save=True)
            asyncio.run(temporary.session.add_items([{'role': 'user', 'content': 'temporary'}]))
            temporary.mark_saved()
            temporary.close()
            after = {p.name: p.read_bytes() for p in (root / '.aion/sdk-sessions').iterdir()}
            self.assertEqual(before, after)

    def test_corrupt_and_linked_database_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handle = SessionHandle(root)
            ident = handle.session.session_id
            handle.close()
            path = root / '.aion/sdk-sessions' / (ident + '.sqlite3')
            path.write_bytes(b'corrupt database')
            with self.assertRaises(Exception):
                SessionHandle(root, resume=ident)
            self.assertEqual(path.read_bytes(), b'corrupt database')
            path.unlink()
            target = root / 'outside'
            target.write_text('untouched')
            path.symlink_to(target)
            with self.assertRaises(OSError):
                SessionHandle(root, resume=ident)
            self.assertEqual(target.read_text(), 'untouched')


if __name__ == '__main__':
    unittest.main()
