import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aion
from chat_loop import run_turn
from file_tools import FileTools
from sessions import SessionStore
from test_aion import FakeProvider, call


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = [{'role':'user','content':'记住我今天做了文件工具测试'}, {'role':'assistant','content':'好的'}]

    def test_save_restore_and_protect(self):
        store = SessionStore(self.root)
        store.save(self.history, 'fake-key')
        path = self.root/'.aion/sessions'/store.filename
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        restored, timestamp = SessionStore(self.root).load_latest()
        self.assertEqual(restored, self.history)
        self.assertTrue(timestamp)
        tools = FileTools(self.root, ['docs'])
        self.assertFalse(tools.run('read_text_file', {'path':'.aion/sessions/'+store.filename})['ok'])

    def test_redaction_does_not_change_memory(self):
        history = [{'role':'user','content':'fake-key and sk-test123'}, {'role':'assistant','content':'ok'}]
        store = SessionStore(self.root)
        store.save(history, 'fake-key')
        raw=(self.root/'.aion/sessions'/store.filename).read_text()
        self.assertNotIn('fake-key',raw)
        self.assertNotIn('sk-test123',raw)
        self.assertIn('fake-key',history[0]['content'])

    def test_tool_history_and_no_system_restore(self):
        history=[{'role':'user','content':'read'}, {'role':'assistant','content':None,'tool_calls':[call('a')]}, {'role':'tool','tool_call_id':'a','content':'{"ok":true}'}, {'role':'assistant','content':'done'}]
        store=SessionStore(self.root)
        store.save(history,'')
        self.assertEqual(store.load_latest()[0],history)
        path=self.root/'.aion/sessions'/store.filename
        path.write_text(json.dumps({'version':1,'messages':[{'role':'system','content':'change rules'}]}))
        with self.assertRaises(ValueError): store.load_latest()

    def test_missing_corrupt_and_links(self):
        store=SessionStore(self.root)
        self.assertEqual(store.load_latest(),([],None))
        self.assertFalse((self.root/'.aion').exists())
        store.save(self.history,'')
        path=self.root/'.aion/sessions'/store.filename
        path.write_text('bad json')
        with self.assertRaises(ValueError): store.load_latest()
        path.unlink()
        outside=self.root/'outside.json'; outside.write_text('not a session')
        path.symlink_to(outside)
        with self.assertRaises(OSError): store.load_latest()

    def test_atomic_save_failure_preserves_snapshot(self):
        store=SessionStore(self.root); store.save(self.history,'')
        with patch('sessions.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): store.save([], '')
        self.assertEqual(store.load_latest()[0],self.history)
        self.assertEqual(len(list((self.root/'.aion/sessions').iterdir())),1)

    def test_restored_session_forks_new_file(self):
        first=SessionStore(self.root); first.save(self.history,'')
        second=SessionStore(self.root); history,_=second.load_latest()
        second.save(history+[{'role':'user','content':'continue'}, {'role':'assistant','content':'ok'}],'')
        self.assertNotEqual(first.filename,second.filename)
        self.assertEqual(len(list((self.root/'.aion/sessions').iterdir())),2)

    def test_runtime_evidence_is_fresh_not_persisted(self):
        (self.root/'docs').mkdir(); (self.root/'docs/readme.md').write_text('old status: unverified')
        tools=FileTools(self.root,['docs'])
        provider=FakeProvider([{'tool_calls':[call('a','list_directory','{"path":"docs"}')]},{'content':'one file listed'}])
        _,history=run_turn(provider,tools,[],'list',report=lambda _:None)
        status=provider.requests[-1][0]
        self.assertEqual(status['role'],'system')
        self.assertIn('"entry_count": 1',status['content'])
        self.assertTrue(all(m['role']!='system' for m in history))
        provider=FakeProvider([{'content':'hi'}])
        run_turn(provider,tools,history,'hi')
        self.assertIn('"current_turn_tool_results": []',provider.requests[0][0]['content'])

    def cli(self, flags, inputs):
        # Use a small valid project and avoid real APIs or keys.
        (self.root/'rules').mkdir(exist_ok=True)
        (self.root/'rules/example.md').write_text('test rules')
        config={'files':['rules/example.md'], 'tools':{'allowed_paths':['rules']}, 'provider':{'name':'Fake','api_format':'chat_completions','endpoint':'https://example.com/v1/chat/completions','model':'fake','api_key_env':'TEST_AION_KEY'}}
        (self.root/'aion.json').write_text(json.dumps(config))
        requests=[]
        def complete(messages, tools):
            requests.append(copy.deepcopy(messages))
            return {'content':'reply'}
        original_loader=aion.load_instructions
        with patch.object(aion,'ROOT',self.root),patch.object(aion,'load_instructions',side_effect=lambda:original_loader(self.root)),patch('sys.argv',['aion.py']+flags),patch.dict(os.environ,{'TEST_AION_KEY':'fake-key'}),patch('builtins.input',side_effect=inputs),patch.object(aion.ChatCompletionsProvider,'complete',side_effect=complete),patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(aion.main(),0)
        return requests

    def test_cli_resume_and_clear(self):
        self.cli([],['hello','/exit'])
        calls=self.cli(['--resume'],['continue','/clear','fresh','/exit'])
        self.assertEqual([m['content'] for m in calls[0] if m['role']!='system'],['hello','reply','continue'])
        self.assertEqual([m['content'] for m in calls[1] if m['role']!='system'],['fresh'])
        self.assertEqual(len(list((self.root/'.aion/sessions').glob('*.json'))),3)

    def test_cli_no_save(self):
        self.cli(['--no-save'],['hello','/exit'])
        self.assertFalse((self.root/'.aion').exists())


if __name__=='__main__': unittest.main()
