"""Read selected Reminders lists through a fixed local EventKit helper."""
import json
import subprocess
from pathlib import Path
from sdk_mail import collect_limited, MailError

HELPER = Path(__file__).resolve().parents[1] / '.aion/bin/aion-reminders'
ERRORS = frozenset({'permission_required', 'list_not_found', 'fetch_failed', 'timeout',
                    'invalid_request', 'invalid_limit'})

class RemindersError(Exception):
    def __init__(self, code):
        super().__init__('提醒事项操作未确认成功，请检查错误分类与本地授权。')
        self.code = code


def validate_lists(lists):
    if not isinstance(lists, (tuple, list, set, frozenset)) or any(
        not isinstance(item, str) or not item or len(item) > 256 or any(ord(c) < 32 for c in item)
        for item in lists
    ):
        raise ValueError('必须指定有效的提醒事项清单 ID。')
    return tuple(sorted(set(lists)))


def _run(list_id, limit):
    try:
        proc = subprocess.Popen([str(HELPER), 'read', list_id, str(limit)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise RemindersError('launch_failed') from None
    proc._aion_process_group = True
    try:
        out, _ = collect_limited(proc, 20, 64 * 1024)
    except MailError as exc:
        raise RemindersError(exc.code) from None
    try:
        result = json.loads(out)
    except (ValueError, UnicodeError):
        raise RemindersError('invalid_response') from None
    if not isinstance(result, dict):
        raise RemindersError('invalid_response')
    if result.get('ok') is not True or proc.returncode != 0:
        code = result.get('error_code')
        raise RemindersError(code if isinstance(code, str) and code in ERRORS else 'helper_failed')
    return result


def list_incomplete(list_id, limit=5, *, allowed_lists, _runner=None):
    allowed = validate_lists(allowed_lists)
    if not isinstance(list_id, str) or list_id not in allowed:
        raise RemindersError('list_not_enabled')
    if type(limit) is not int or not 1 <= limit <= 20:
        raise RemindersError('invalid_limit')
    result = (_runner or _run)(list_id, limit)
    if (not isinstance(result, dict) or result.get('ok') is not True
            or result.get('list_id') != list_id or not isinstance(result.get('items'), list)
            or type(result.get('truncated')) is not bool):
        raise RemindersError('invalid_response')
    items = []
    for item in result['items'][:limit]:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                or not isinstance(item.get('title'), str) or item.get('completed') is not False
                or not isinstance(item.get('due'), dict)):
            raise RemindersError('invalid_response')
        due = {k: v for k, v in item['due'].items()
               if k in ('year', 'month', 'day', 'hour', 'minute') and type(v) is int}
        items.append({'id': item['id'][:256], 'title': item['title'][:512], 'due': due, 'completed': False})
    return {'ok': True, 'list_id': list_id, 'items': items,
            'truncated': result['truncated'] or len(result['items']) > limit}
