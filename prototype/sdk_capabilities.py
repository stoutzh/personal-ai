"""Runtime-only capability facts. Never stored in conversation history."""
from dataclasses import dataclass
import json

from agents import FunctionTool, Runner, SQLiteSession


@dataclass(frozen=True)
class ToolCapability:
    tool: FunctionTool
    file_actions: frozenset[str]


@dataclass(frozen=True)
class RuntimeState:
    session: SQLiteSession
    history_items_before_run: int
    resumed: bool = False


class CapabilityInstructions:
    def __init__(self, background, registry, allowed_paths):
        self.background = background
        self.registry = tuple(registry)
        self.allowed_paths = tuple(allowed_paths)

    async def facts(self, agent, state):
        if not isinstance(state, RuntimeState):
            raise ValueError('SDK Agent 必须通过 run_agent 提供实际 Session 状态。')
        tools, actions = [], set()
        file_tools = []
        for tool in agent.tools:
            # Current runtime supports boolean activation only. Do not guess future predicates.
            if not isinstance(tool, FunctionTool) or not isinstance(tool.is_enabled, bool):
                raise ValueError('工具类型或启用方式没有能力事实适配。')
            if not tool.is_enabled:
                continue
            spec = next((s for s in self.registry if s.tool is tool), None)
            if spec is None:
                raise ValueError('已注册工具缺少能力元数据。')
            tools.append(tool.name)
            actions.update(spec.file_actions)
            if spec.file_actions:
                file_tools.append(tool.name)
        persistent = str(state.session.db_path) != ':memory:'
        writes = actions & {'create', 'modify', 'delete'}
        return {
            'history_available': state.history_items_before_run > 0,
            'history_items_before_run': state.history_items_before_run,
            'session_storage': 'sqlite_disk' if persistent else 'memory',
            'restored_at_startup': state.resumed,
            'program_session_persistence': persistent,
            'available_tools': tools,
            'file_tools': file_tools,
            'filesystem_actions': sorted(actions),
            'file_write_tool_present': bool(writes),
            'file_tools_read_only': bool(file_tools) and not writes,
            'allowed_file_paths': list(self.allowed_paths) if file_tools else [],
        }

    async def __call__(self, context, agent):
        facts = await self.facts(agent, context.context)
        rules = ('会话记忆表示历史消息可能带入模型上下文，不授予文件写入权限。'
                 '程序保存 Session 与模型文件工具权限是两回事。'
                 '能力判断以本次 runtime facts 为准，不从背景、旧回复推断；不得声称拥有未注册能力。')
        if facts['file_tools_read_only']:
            rules += '当前文件工具仅可在授权范围内列目录/读取（以 filesystem_actions 为准），不能修改、删除或创建本地文件。'
        storage = ('程序自动持久保存会话，退出后 --resume 恢复；新建会话不自动载入旧历史。'
                   if facts['program_session_persistence'] else '本次 Session 仅在内存，退出清除。')
        return self.background + '\n<runtime_capabilities>\n' + json.dumps(facts, ensure_ascii=False) + '\n' + rules + storage + '\n</runtime_capabilities>'


async def run_agent(agent, message, *, session, run_config, max_turns=4, resumed=False):
    """One entry ensures instructions and Runner use the very same Session object."""
    history_count = len(await session.get_items())
    return await Runner.run(agent, message, session=session,
                            context=RuntimeState(session, history_count, resumed),
                            run_config=run_config, max_turns=max_turns)
