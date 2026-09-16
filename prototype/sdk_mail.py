"""Read-only unread-mail listing through the himalaya CLI.

Design rules:
- Credentials live only in macOS keychain + himalaya's config; this module
  never reads, prints, uploads, or logs them.
- The command is a fixed argv array (no shell); the model can never inject an
  arbitrary command, config path, server, or search expression.
- Output is collected with a hard timeout and size cap, and is killed on
  overflow (never captured unbounded then truncated).
- Only envelope metadata (id, sender, subject, date) is returned. Mail fields
  are untrusted external content: they are treated as data, never as
  instructions, and never expand permissions or trigger extra actions.
"""
import json
import os
import select
import signal
import subprocess
import time

HIMALAYA_BIN = '/usr/local/bin/himalaya'
# Logical identity -> local Himalaya account. Addresses, servers and credentials
# remain in Himalaya's private configuration, independent of this identity.
ACCOUNT_BINDINGS = {'school': 'ucsb', 'gmail': 'gmail', 'ucsb': 'ucsb', '163': '163'}
ALLOWED_ACCOUNTS = frozenset(ACCOUNT_BINDINGS)
MIN_LIMIT = 1
MAX_LIMIT = 20
DEFAULT_LIMIT = 5
TIMEOUT_SECONDS = 35.0  # Live Gmail query took 19s; retain a bounded wait.
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KiB


class MailError(Exception):
    """Safe, locally authored error. Never exposes raw stdout/stderr or stack."""

    def __init__(self, message, *, code="mail_error"):
        super().__init__(message)
        self.code = code


def validate_account(account):
    if not isinstance(account, str) or account not in ALLOWED_ACCOUNTS:
        raise MailError('账户必须是 school / gmail / ucsb / 163 之一。', code='invalid_account')


def validate_limit(limit):
    # bool is a subclass of int; reject it so True/False can't slip through.
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise MailError('limit 必须是整数。', code='invalid_limit')
    if not (MIN_LIMIT <= limit <= MAX_LIMIT):
        raise MailError(f'limit 必须在 {MIN_LIMIT}–{MAX_LIMIT} 之间。', code='invalid_limit')


def build_command(account, limit):
    validate_account(account)
    validate_limit(limit)
    # Fixed argv array. `not flag seen` is a single argument (the query DSL).
    return [
        HIMALAYA_BIN,
        'envelope', 'search',
        '-a', ACCOUNT_BINDINGS[account],
        '--json',
        '-s', str(limit),
        'not flag seen order by date desc',
    ]


def _kill(proc):
    try:
        if getattr(proc, '_aion_process_group', False):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=2)
    except (subprocess.TimeoutExpired, OSError):
        pass


def collect_limited(proc, timeout, max_bytes):
    """Read stdout/stderr with hard limits; abort (kill) on timeout or overflow."""
    deadline = time.monotonic() + timeout
    out = bytearray()
    err = bytearray()
    streams = [proc.stdout, proc.stderr]
    open_fds = list(streams)
    try:
        while open_fds:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MailError('himalaya 执行超时，已中止。', code='timeout')
            ready, _, _ = select.select(open_fds, [], [], remaining)
            if not ready:
                raise MailError('himalaya 执行超时，已中止。', code='timeout')
            for fd in ready:
                chunk = os.read(fd.fileno(), min(8192, max_bytes - len(out) - len(err) + 1))
                if not chunk:
                    open_fds.remove(fd)
                    try:
                        fd.close()
                    except OSError:
                        pass
                    continue
                if fd is proc.stdout:
                    out.extend(chunk)
                else:
                    err.extend(chunk)
                if len(out) + len(err) > max_bytes:
                    raise MailError('himalaya 输出超过上限，已中止。', code='output_limit')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MailError('himalaya 执行超时，已中止。', code='timeout')
        proc.wait(timeout=remaining)
        return bytes(out), bytes(err)
    except MailError:
        _kill(proc)
        raise
    except subprocess.TimeoutExpired:
        _kill(proc)
        raise MailError('himalaya 执行超时，已中止。', code='timeout') from None
    except (OSError, ValueError):
        _kill(proc)
        raise MailError('himalaya 读取失败，已中止。', code='io_error') from None
    finally:
        for stream in streams:
            try:
                stream.close()
            except OSError:
                pass


def _run_himalaya(cmd, timeout, max_bytes):
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        raise MailError('无法启动 himalaya。', code='launch_failed') from None
    proc._aion_process_group = True
    out, _err = collect_limited(proc, timeout, max_bytes)
    if proc.returncode != 0:
        raise MailError('himalaya 执行失败。', code='process_failed') from None
    return out


def parse_envelopes(raw):
    """Parse himalaya --json output into the envelope list; never leak raw text."""
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MailError('himalaya 返回无法解析的输出。', code='invalid_json') from None
    if isinstance(payload, dict) and payload.get('error'):
        raise MailError('himalaya 报错，未能列出未读邮件。', code='backend_error') from None
    envelopes = payload.get('envelopes') if isinstance(payload, dict) else None
    if not isinstance(envelopes, list):
        raise MailError('himalaya 返回格式异常，缺少 envelopes。', code='invalid_response') from None
    return envelopes


def format_item(account, envelope):
    """Extract a fixed whitelist of fields from an untrusted envelope. No eval."""
    if not isinstance(envelope, dict):
        return None
    eid = envelope.get('id')
    sender = ''
    frm = envelope.get('from')
    if isinstance(frm, list) and frm:
        first = frm[0]
        if isinstance(first, dict):
            sender = next((v for v in (first.get('name'), first.get('email')) if isinstance(v, str) and v), '')
    subject = envelope.get('subject')
    date = envelope.get('date')
    return {
        'id': eid if isinstance(eid, (str, int)) and not isinstance(eid, bool) else None,
        'sender': sender,
        'subject': subject if isinstance(subject, str) else '',
        'date': date if isinstance(date, str) else '',
    }


def list_unread(account, limit=DEFAULT_LIMIT, _run=None):
    """Return {'ok': True, 'account', 'unread': [...]}; raise MailError on failure."""
    validate_account(account)
    validate_limit(limit)
    cmd = build_command(account, limit)
    runner = _run or _run_himalaya
    out = runner(cmd, TIMEOUT_SECONDS, MAX_OUTPUT_BYTES)
    envelopes = parse_envelopes(out)
    items = [item for item in (format_item(account, e) for e in envelopes[:limit]) if item is not None]
    return {'ok': True, 'account': account, 'unread': items, 'summary_basis': 'envelope_metadata_only', 'body_read': False}
