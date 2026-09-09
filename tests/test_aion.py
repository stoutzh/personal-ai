import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from file_tools import FileTools, MAX_BYTES
from chat_loop import run_turn, MAX_ROUNDS
from providers import ChatCompletionsProvider


def call(ident, name='read_text_file', arguments='{"path":"docs/note.md"}'):
    return {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


class FakeProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(copy.deepcopy(messages))
        return next(self.replies)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'docs').mkdir()
        (self.root/'docs/note.md').write_text('你好\nread me', encoding='utf-8')
        (self.root/'outside.txt').write_text('not allowed')
        self.tools = FileTools(self.root, ['docs'])

    def test_read_and_list(self):
        result = self.tools.run('read_text_file', {'path':'docs/note.md'})
        self.assertEqual(result['content'], '你好\nread me')
        entries = self.tools.run('list_directory', {'path':'.'})['entries']
        self.assertEqual(entries, [{'name':'docs', 'type':'directory'}])
        self.assertFalse(self.tools.run('read_text_file', {'path':'docs'})['ok'])

    def test_boundaries(self):
        for path in ['../outside.txt', '/etc/passwd', 'outside.txt', 'docs/../outside.txt', 'docs/.env', 'docs/secrets/key.txt', 'docs/service.key']:
            self.assertFalse(self.tools.run('read_text_file', {'path':path})['ok'], path)
        (self.root/'docs/link.md').symlink_to(self.root/'outside.txt')
        (self.root/'docs/linkdir').symlink_to(self.root, target_is_directory=True)
        for path in ['docs/link.md', 'docs/linkdir/outside.txt']:
            self.assertFalse(self.tools.run('read_text_file', {'path':path})['ok'])
        os.link(self.root/'outside.txt', self.root/'docs/hard.md')
        self.assertFalse(self.tools.run('read_text_file', {'path':'docs/hard.md'})['ok'])
        listed = self.tools.run('list_directory', {'path':'docs'})['entries']
        self.assertNotIn('link.md', [item['name'] for item in listed])

    def test_text_and_size(self):
        for name, content in [('big.txt', b'x'*(MAX_BYTES+1)), ('binary', b'\x00data'), ('invalid', b'\xff')]:
            (self.root/'docs'/name).write_bytes(content)
            self.assertFalse(self.tools.run('read_text_file', {'path':'docs/'+name})['ok'])
        os.mkfifo(self.root/'docs/fifo')
        self.assertFalse(self.tools.run('read_text_file', {'path':'docs/fifo'})['ok'])

    def test_arguments_and_unknown_tool(self):
        for args in ['bad', '[]', '{"path":"docs/note.md","command":"touch x"}']:
            self.assertFalse(self.tools.execute('read_text_file', args)['ok'])
        self.assertFalse(self.tools.execute('shell', '{"path":"docs/note.md"}')['ok'])
        self.assertFalse(self.tools.execute('write_file', '{"path":"docs/note.md"}')['ok'])
        self.assertEqual((self.root/'docs/note.md').read_text(), '你好\nread me')

    def test_listing_limit_and_hidden_files(self):
        for i in range(110):
            (self.root/f'docs/file-{i}.txt').touch()
        (self.root/'docs/.env').write_text('fake-key')
        result = self.tools.run('list_directory', {'path':'docs'})
        self.assertEqual(len(result['entries']), 100)
        self.assertTrue(result['truncated'])
        self.assertNotIn('.env', [e['name'] for e in result['entries']])

    def test_tool_round_trip(self):
        provider = FakeProvider([
            {'content':None,'tool_calls':[call('list', 'list_directory', '{"path":"docs"}')]},
            {'content':None,'tool_calls':[call('read')]},
            {'content':'文件内容是问候。'},
        ])
        history = [{'role':'user','content':'earlier'}, {'role':'assistant','content':'ok'}]
        before = copy.deepcopy(history)
        answer, updated = run_turn(provider, self.tools, history, 'read docs', report=lambda _:None)
        self.assertEqual(answer, '文件内容是问候。')
        self.assertEqual(history, before)
        self.assertEqual(updated[-2]['tool_call_id'], 'read')
        self.assertEqual(json.loads(provider.requests[-1][-1]['content'])['content'], '你好\nread me')

    def test_batch_and_recoverable_errors(self):
        provider = FakeProvider([
            {'content':None,'tool_calls':[call('a', arguments='bad'), call('b')]},
            {'content':'one failed, one read'},
        ])
        _, messages = run_turn(provider, self.tools, [], 'read', report=lambda _:None)
        self.assertEqual([m['tool_call_id'] for m in messages if m['role']=='tool'], ['a','b'])
        self.assertFalse(json.loads(messages[2]['content'])['ok'])

    def test_no_tools_and_round_limit(self):
        provider = FakeProvider([{'content':'你好'}])
        with patch.object(self.tools, 'execute', side_effect=AssertionError('unexpected read')):
            self.assertEqual(run_turn(provider,self.tools,[],'hi')[0], '你好')
        provider = FakeProvider([{'content':None, 'tool_calls':[call(str(i))]} for i in range(MAX_ROUNDS+1)])
        with self.assertRaisesRegex(RuntimeError, '上限'):
            run_turn(provider,self.tools,[],'loop',report=lambda _:None)
        provider = FakeProvider([{'tool_calls':[call('same'),call('same')]}])
        with patch.object(self.tools,'execute',side_effect=AssertionError('invalid batch executed')):
            with self.assertRaisesRegex(RuntimeError,'无效'):
                run_turn(provider,self.tools,[],'read')


class ProviderTests(unittest.TestCase):
    def config(self, **extra):
        return dict(name='Test Provider', api_format='chat_completions', endpoint='https://example.com/v1/chat/completions', model='test-model', api_key_env='TEST_KEY', **extra)

    def test_wire_format_has_no_deepseek_dependency(self):
        response={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[call('a')]}}]}
        provider=ChatCompletionsProvider(self.config(),'test-key','instructions')
        with patch('urllib.request.build_opener') as op:
            op.return_value.open.return_value=io.BytesIO(json.dumps(response).encode())
            reply=provider.complete([{'role':'user','content':'read'}], [])
            req=op.return_value.open.call_args.args[0]
            payload=json.loads(req.data)
            self.assertEqual(req.full_url, self.config()['endpoint'])
            self.assertNotIn('thinking',payload)
            self.assertEqual(payload['messages'][0]['role'],'system')
            self.assertEqual(reply['tool_calls'][0]['id'],'a')

    def test_errors_and_redaction(self):
        provider=ChatCompletionsProvider(self.config(),'test-key','instructions')
        err=urllib.error.HTTPError(provider.endpoint,403,'Forbidden',{},io.BytesIO(json.dumps({'error':{'message':'test-key sk-abc123'}}).encode()))
        with patch('urllib.request.build_opener') as op:
            op.return_value.open.side_effect=err
            with self.assertRaises(RuntimeError) as captured:
                provider.complete([],[])
        self.assertNotIn('test-key',str(captured.exception))
        self.assertNotIn('sk-abc123',str(captured.exception))
        self.assertIn('HTTP 403',str(captured.exception))

    def test_provider_config_validation(self):
        config=self.config(); config['endpoint']='http://example.com'
        with self.assertRaises(ValueError): ChatCompletionsProvider(config,'key','')
        with self.assertRaises(ValueError): ChatCompletionsProvider(self.config(extra_body={'messages':[]}), 'key','')


if __name__ == '__main__':
    unittest.main()
