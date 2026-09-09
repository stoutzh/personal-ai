"""Local successful-turn snapshots; inaccessible to model tools, never a tool."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import uuid

MAX_SESSION_BYTES = 2_000_000
SESSION_NAME = re.compile(r'\d{8}T\d{12}Z-[a-f0-9]{8}\.json\Z')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def redact(value, key):
    if isinstance(value, str):
        value = value.replace(key, '[密钥已隐藏]') if key else value
        return re.sub(r'sk-[A-Za-z0-9_.*-]+', '[密钥已隐藏]', value)
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: redact(item, key) for name, item in value.items()}
    return value


def validate_history(history):
    if not isinstance(history, list):
        raise ValueError('会话格式无效。')
    pending = set()
    for message in history:
        if not isinstance(message, dict) or message.get('role') not in {'user', 'assistant', 'tool'}:
            raise ValueError('保存的会话只能包含用户、助手和工具消息。')
        role = message['role']
        if pending and role != 'tool':
            raise ValueError('会话中的工具结果不完整。')
        if role == 'tool':
            ident = message.get('tool_call_id')
            if ident not in pending:
                raise ValueError('会话中的工具调用 ID 不匹配。')
            pending.remove(ident)
        if role == 'assistant' and message.get('tool_calls'):
            calls = message['tool_calls']
            if not isinstance(calls, list):
                raise ValueError('会话工具格式无效。')
            for call in calls:
                if (not isinstance(call, dict) or call.get('type') != 'function'
                    or not isinstance(call.get('id'), str) or not call['id'] or call['id'] in pending
                    or not isinstance(call.get('function'), dict)
                    or not isinstance(call['function'].get('name'), str)
                    or not isinstance(call['function'].get('arguments'), str)):
                    raise ValueError('会话工具格式无效。')
                pending.add(call['id'])
        content = message.get('content')
        if not isinstance(content, str) and not (role == 'assistant' and pending and content is None):
            raise ValueError('会话文本格式无效。')
    if pending:
        raise ValueError('会话中的工具结果不完整。')


class SessionStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.filename = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ-') + uuid.uuid4().hex[:8] + '.json'

    def directory_fd(self, create=False):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in ('.aion', 'sessions'):
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def load_latest(self):
        try:
            directory = self.directory_fd()
        except FileNotFoundError:
            return [], None
        try:
            names = sorted(name for name in os.listdir(directory) if SESSION_NAME.fullmatch(name))
            if not names:
                return [], None
            fd = os.open(names[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_SESSION_BYTES:
                    raise ValueError('会话文件不是普通文件或超过 2 MB。')
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    raw = stream.read(MAX_SESSION_BYTES + 1)
                if len(raw) > MAX_SESSION_BYTES:
                    raise ValueError('会话超过 2 MB。')
                saved = json.loads(raw)
                if not isinstance(saved, dict) or saved.get('version') != 1:
                    raise ValueError('不支持的会话版本。')
                validate_history(saved.get('messages'))
                return saved['messages'], saved.get('saved_at')
            finally:
                os.close(fd)
        finally:
            os.close(directory)

    def save(self, history, key):
        validate_history(history)
        # Only message history is serialized; never the provider object or environment.
        payload = {'version': 1, 'saved_at': utc_now(), 'messages': redact(history, key)}
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        if len(raw) > MAX_SESSION_BYTES:
            raise ValueError('会话超过 2 MB，未保存本轮；可 /clear 后开启新上下文。')
        directory = self.directory_fd(create=True)
        temporary = '.' + uuid.uuid4().hex + '.tmp'
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.filename, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)
