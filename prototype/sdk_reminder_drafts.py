"""Manual milestone: model prepares drafts; only terminal /confirm can create."""
import copy
from datetime import date, datetime, timezone
import json
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sdk_reminders import RemindersError, validate_lists, HELPER
from sdk_mail import collect_limited, MailError
import subprocess


def validate_due(day, clock, zone):
    if not all(isinstance(v, str) for v in (day, clock, zone)):
        raise RemindersError('invalid_due')
    if not day:
        if clock or zone:
            raise RemindersError('invalid_due')
        return {}
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
            raise ValueError()
        d = date.fromisoformat(day)
        result = {'year': d.year, 'month': d.month, 'day': d.day}
        if clock:
            if not re.fullmatch(r'\d{2}:\d{2}', clock) or not zone:
                raise ValueError()
            tz = ZoneInfo(zone)
            naive = datetime.fromisoformat(day + 'T' + clock)
            local = naive.replace(tzinfo=tz)
            # Reject nonexistent or ambiguous local times; the user must clarify.
            if local.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
                raise ValueError()
            if local.utcoffset() != naive.replace(tzinfo=tz, fold=1).utcoffset():
                raise ValueError()
            result.update(hour=naive.hour, minute=naive.minute, timezone=zone)
        elif zone:
            raise ValueError()
        return result
    except (ValueError, ZoneInfoNotFoundError):
        raise RemindersError('invalid_or_ambiguous_due') from None


def _create(payload):
    wire = json.dumps(payload, ensure_ascii=False).encode()
    if len(wire) > 4096:
        raise RemindersError('draft_too_large')
    try:
        proc = subprocess.Popen([str(HELPER), 'create'], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        raise RemindersError('launch_failed') from None
    proc._aion_process_group = True
    try:
        try:
            proc.stdin.write(wire)
            proc.stdin.close()
        except OSError:
            from sdk_mail import _kill
            _kill(proc)
            raise RemindersError('write_status_unknown') from None
        out, _ = collect_limited(proc, 20, 64 * 1024)
        result = json.loads(out)
        if not isinstance(result, dict) or result.get('ok') is not True or proc.returncode != 0:
            code = result.get('error_code') if isinstance(result, dict) else None
            known = {'permission_required', 'list_not_found', 'read_only_list', 'invalid_request', 'invalid_due', 'save_failed', 'fetch_failed'}
            raise RemindersError(code if isinstance(code, str) and code in known else 'write_status_unknown')
        if not isinstance(result.get('id'), str) or type(result.get('created')) is not bool:
            raise RemindersError('write_status_unknown')
        return {'ok': True, 'id': result['id'], 'created': result.get('created') is True}
    except (MailError, ValueError, UnicodeError):
        # A timeout after save is ambiguous. Never automatically retry.
        raise RemindersError('write_status_unknown') from None
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()


class ReminderDrafts:
    def __init__(self, allowed_lists):
        self.allowed_lists = validate_lists(allowed_lists)
        self._pending = {}

    def prepare(self, list_id, title, due_date='', due_time='', timezone='', source=''):
        if list_id not in self.allowed_lists:
            raise RemindersError('list_not_enabled')
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(ord(c) < 32 for c in title):
            raise RemindersError('invalid_title')
        if not isinstance(source, str) or len(source) > 300 or any(ord(c) < 32 for c in source):
            raise RemindersError('invalid_source')
        if len(self._pending) >= 20:
            raise RemindersError('too_many_drafts')
        payload = {'list_id': list_id, 'title': title.strip(), 'due': validate_due(due_date, due_time, timezone), 'source': source}
        # Repeated model requests with the same content reuse the pending draft.
        for token, existing in self._pending.items():
            if {k: v for k, v in existing.items() if k != 'operation_id'} == payload:
                return {'ok': True, 'draft_id': token, 'preview': copy.deepcopy(existing), 'saved': False}
        token = uuid.uuid4().hex
        payload['operation_id'] = token
        self._pending[token] = payload
        return {'ok': True, 'draft_id': token, 'preview': copy.deepcopy(payload), 'saved': False}

    def pending(self):
        return copy.deepcopy(self._pending)

    def confirm(self, token, _creator=None):
        if token not in self._pending:
            raise RemindersError('draft_not_found')
        payload = self._pending.pop(token)
        # Consume before I/O, so even an ambiguous failure cannot silently repeat.
        return (_creator or _create)(payload)

    def cancel(self, token):
        if token not in self._pending:
            raise RemindersError('draft_not_found')
        del self._pending[token]
