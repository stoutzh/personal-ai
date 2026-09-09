"""Provider-independent tool loop; a provider implements complete(messages, tools)."""
import copy
import json
from file_tools import DEFINITIONS
from sessions import utc_now

STARTED_AT = utc_now()

MAX_ROUNDS = 4
MAX_CALLS = 8


def run_turn(provider, file_tools, history, user_text, report=print):
    messages = copy.deepcopy(history) + [{"role": "user", "content": user_text}]
    events = []
    calls_used = 0
    seen_ids = set()
    for round_index in range(MAX_ROUNDS + 1):
        # Generated facts are transient; restored messages remain historical records.
        runtime = {
            'process_started_at': STARTED_AT, 'now': utc_now(),
            'current_turn_tool_results': events,
        }
        status = "程序运行事实：当前会话正在运行；以下是本轮实际工具执行记录。" \
                 "旧对话及文件快照不代表现在的文件状态。若本轮操作已成功，承认该操作已验证，" \
                 "不要仅照搬旧文档要求重复验证；这不证明其他功能也已验证。\n" + json.dumps(runtime, ensure_ascii=False)
        reply = provider.complete([{'role': 'system', 'content': status}] + messages, DEFINITIONS)
        calls = reply.get('tool_calls') or []
        if not calls:
            text = reply.get('content')
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("模型没有返回文字或工具请求。")
            messages.append({"role": "assistant", "content": text})
            return text, messages
        if round_index == MAX_ROUNDS or calls_used + len(calls) > MAX_CALLS:
            raise RuntimeError("达到本轮工具调用上限，请缩小问题范围；本轮未加入历史。")
        # Validate the whole batch before executing any request.
        batch_ids = set()
        for call in calls:
            try:
                valid = (call['type'] == 'function' and isinstance(call['id'], str) and bool(call['id'])
                         and isinstance(call['function']['name'], str)
                         and isinstance(call['function']['arguments'], str))
                if not valid or call['id'] in seen_ids | batch_ids:
                    raise ValueError()
                batch_ids.add(call['id'])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError("模型返回了无效的工具调用格式；本轮未执行该批工具。") from None
        seen_ids.update(batch_ids)
        messages.append({"role": "assistant", "content": reply.get('content'), "tool_calls": calls})
        for call in calls:
            function = call['function']
            result = file_tools.execute(function['name'], function['arguments'])
            # Display paths only after validation; never print arbitrary model arguments.
            event = {'tool': function['name'], 'ok': result['ok'], 'at': utc_now()}
            if result.get('path'):
                event['path'] = result['path']
            if result['ok'] and 'entries' in result:
                event['entry_count'] = len(result['entries'])
                event['truncated'] = result['truncated']
            events.append(event)
            label = result.get('path', '请求被拒绝')
            report(f"[只读工具] {function['name']!r} → {label!r}：{'完成' if result['ok'] else '失败'}")
            messages.append({"role": "tool", "tool_call_id": call['id'],
                             "content": json.dumps(result, ensure_ascii=False)})
            calls_used += 1
    raise RuntimeError("工具调用未完成。")
