import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import SQLiteSession
from openai import AsyncOpenAI
from sdk_capabilities import RuntimeState, run_agent
from sdk_demo import build_agent, RUN_CONFIG


class CapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncOpenAI(api_key='offline-placeholder')
        self.agent, _ = build_agent({'provider': {'model': 'test'}, 'tools': {'allowed_paths': ['README.md']}}, self.client, instructions='background')
        self.session = SQLiteSession('test')

    async def asyncTearDown(self):
        self.session.close()
        await self.client.close()

    async def test_registry_changes_no_name_guessing(self):
        facts = self.agent.instructions
        state = RuntimeState(self.session, 0)
        first = await facts.facts(self.agent, state)
        self.assertFalse(first['history_available'])
        self.assertFalse(first['file_write_tool_present'])
        self.assertTrue(first['file_tools_read_only'])
        self.agent.tools[0].name = 'list_files'
        self.agent.tools[1].name = 'read_file'
        renamed = await facts.facts(self.agent, state)
        self.assertEqual(renamed['available_tools'], ['list_files', 'read_file'])
        self.agent.tools[0].is_enabled = False
        self.assertEqual((await facts.facts(self.agent, state))['filesystem_actions'], ['read'])
        self.agent.tools.clear()
        empty = await facts.facts(self.agent, state)
        self.assertEqual(empty['available_tools'], [])
        self.assertFalse(empty['file_tools_read_only'])
        self.assertEqual(empty['allowed_file_paths'], [])

    async def test_unclassified_same_name_tool_rejected(self):
        self.agent.tools[0] = copy.copy(self.agent.tools[0])
        with self.assertRaisesRegex(ValueError, '元数据'):
            await self.agent.instructions.facts(self.agent, RuntimeState(self.session, 0))

    async def test_each_run_samples_same_session_without_mutating_history(self):
        async def runner(agent, message, **kwargs):
            state = kwargs['context']
            self.assertIs(state.session, kwargs['session'])
            return await agent.instructions.facts(agent, state)
        with patch('sdk_capabilities.Runner.run', AsyncMock(side_effect=runner)):
            first = await run_agent(self.agent, 'hi', session=self.session, run_config=RUN_CONFIG)
            self.assertFalse(first['history_available'])
            await self.session.add_items([{'role': 'user', 'content': 'earlier'}])
            before = await self.session.get_items()
            second = await run_agent(self.agent, 'again', session=self.session, run_config=RUN_CONFIG)
            self.assertTrue(second['history_available'])
            self.assertEqual(second['history_items_before_run'], 1)
            self.assertEqual(await self.session.get_items(), before)
            self.assertNotIn('runtime_capabilities', json.dumps(before))

    async def test_disk_storage_not_file_tool_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = SQLiteSession('disk', Path(directory) / 'test.sqlite3')
            try:
                facts = await self.agent.instructions.facts(self.agent, RuntimeState(disk, 2, True))
                self.assertTrue(facts['program_session_persistence'])
                self.assertTrue(facts['restored_at_startup'])
                self.assertFalse(facts['file_write_tool_present'])
                self.assertEqual(facts['filesystem_actions'], ['list', 'read'])
            finally:
                disk.close()


if __name__ == '__main__':
    unittest.main()
