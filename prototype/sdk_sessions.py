"""Private storage around the SDK's SQLiteSession; no legacy JSON access."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid

from agents import SQLiteSession


class SessionError(Exception):
    pass


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise SessionError('会话目录不是普通目录。')
    path.chmod(0o700)


def private_fd(path, create=False):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise SessionError('会话文件必须是普通文件，不能是链接。')
    os.fchmod(fd, 0o600)
    return fd


class PrivateSQLiteSession(SQLiteSession):
    """Keep SQLite implementation, redact current credentials before persistence."""
    def __init__(self, session_id, db_path=':memory:', key=''):
        self._key = key
        super().__init__(session_id, db_path)

    async def add_items(self, items):
        def redact(value):
            if isinstance(value, str):
                value = value.replace(self._key, '[密钥已隐藏]') if self._key else value
                return re.sub(r'sk-[A-Za-z0-9_.-]+', '[密钥已隐藏]', value)
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            return value
        await super().add_items(redact(items))


class SessionHandle:
    def __init__(self, root, key='', resume=None, no_save=False):
        self.lock = None
        self.directory = None
        if no_save:
            if resume:
                raise SessionError('--no-save 不能与 --resume 一起使用。')
            self.session = PrivateSQLiteSession('temporary', key=key)
            return
        private_directory(Path(root) / '.aion')
        self.directory = Path(root) / '.aion' / 'sdk-sessions'
        private_directory(self.directory)
        if resume == 'latest':
            try:
                fd = private_fd(self.directory / 'latest')
                with os.fdopen(fd) as stream:
                    resume = stream.read(100).strip()
            except FileNotFoundError:
                raise SessionError('没有已保存的 SDK 会话；请先不带 --resume 开始聊天。') from None
        session_id = resume or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', session_id):
            raise SessionError('SDK 会话编号无效。')
        path = self.directory / (session_id + '.sqlite3')
        if resume and not path.exists():
            raise SessionError('指定的 SDK 会话不存在。')
        self.lock = private_fd(self.directory / (session_id + '.lock'), create=True)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = private_fd(path, create=not resume)
            os.close(fd)
            # Restrict SQLite journal/WAL files as well as the main DB.
            previous = os.umask(0o077)
            try:
                self.session = PrivateSQLiteSession(session_id, path, key)
            finally:
                os.umask(previous)
        except BaseException:
            os.close(self.lock)
            self.lock = None
            raise

    def mark_saved(self):
        if self.directory is None:
            return
        temporary = self.directory / ('latest-' + uuid.uuid4().hex)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(self.session.session_id + '\n')
            os.replace(temporary, self.directory / 'latest')
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        try:
            self.session.close()
        finally:
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None
