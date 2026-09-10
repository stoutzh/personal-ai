"""Provider-scoped macOS Keychain credentials; never pass keys in process arguments."""
import ctypes as C
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import warnings


class CredentialError(Exception):
    pass


def identity(provider):
    # Bind credentials to the complete endpoint, so switching providers cannot reuse a key.
    endpoint = provider['endpoint'].rstrip('/')
    digest = hashlib.sha256(endpoint.encode()).hexdigest()[:24]
    return ('Aion.SDK.' + digest).encode(), provider['api_key_env'].encode()


class Keychain:
    def __init__(self):
        if sys.platform != 'darwin':
            raise CredentialError('钥匙串仅支持 macOS；其他系统可使用环境变量。')
        self.security = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFRelease.argtypes = [C.c_void_p]
        self.cf.CFRelease.restype = None
        self.security.SecKeychainFindGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.POINTER(C.c_uint32), C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
        self.security.SecKeychainFindGenericPassword.restype = C.c_int32
        self.security.SecKeychainItemFreeContent.argtypes = [C.c_void_p, C.c_void_p]
        self.security.SecKeychainItemFreeContent.restype = C.c_int32
        self.security.SecKeychainAddGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.POINTER(C.c_void_p)]
        self.security.SecKeychainAddGenericPassword.restype = C.c_int32
        self.security.SecKeychainItemModifyAttributesAndData.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_char_p]
        self.security.SecKeychainItemModifyAttributesAndData.restype = C.c_int32

    def find(self, provider):
        service, account = identity(provider)
        size, data, item = C.c_uint32(), C.c_void_p(), C.c_void_p()
        status = self.security.SecKeychainFindGenericPassword(None, len(service), service, len(account), account, C.byref(size), C.byref(data), C.byref(item))
        if status == -25300:
            return None, None
        if status:
            raise CredentialError(f'钥匙串不可访问（系统状态 {status}）；请解锁登录钥匙串并允许当前 Python 访问。')
        try:
            key = C.string_at(data, size.value).decode('utf-8')
        except BaseException:
            self.cf.CFRelease(item)
            raise
        finally:
            self.security.SecKeychainItemFreeContent(None, data)
        return key, item

    def read(self, provider):
        key, item = self.find(provider)
        if item:
            self.cf.CFRelease(item)
        return key or ''

    def save(self, provider, key):
        service, account = identity(provider)
        raw = key.encode('utf-8')
        _, item = self.find(provider)
        if item:
            try:
                status = self.security.SecKeychainItemModifyAttributesAndData(item, None, len(raw), raw)
            finally:
                self.cf.CFRelease(item)
        else:
            status = self.security.SecKeychainAddGenericPassword(None, len(service), service, len(account), account, len(raw), raw, None)
        if status:
            raise CredentialError(f'钥匙串保存失败（系统状态 {status}）。')


def read_key(provider):
    key = os.environ.get(provider['api_key_env'], '').strip()
    if key:
        return key
    return Keychain().read(provider) if sys.platform == 'darwin' else ''


def main():
    import argparse
    parser = argparse.ArgumentParser(description='一次性保存 Aion API key 到 macOS 钥匙串')
    parser.add_argument('--status', action='store_true', help='仅报告是否可读取，不显示密钥')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from providers import validate_provider
    provider = json.loads((root / 'aion.json').read_text())['provider']
    validate_provider(provider)
    if args.status:
        print('API key 可读取。' if read_key(provider) else '尚未配置 API key。')
        return
    if not sys.stdin.isatty():
        raise CredentialError('请在 Mac 终端运行一次，以隐藏输入密钥。')
    print('服务：' + provider['name'] + ' | 地址：' + provider['endpoint'])
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        key = getpass.getpass('API key（隐藏输入，保存到 macOS 钥匙串）：').strip()
    if not key or any(c.isspace() for c in key):
        raise CredentialError('密钥为空或包含空白，未保存。')
    vault = Keychain()
    vault.save(provider, key)
    if vault.read(provider) != key:
        raise CredentialError('保存后读取校验失败。')
    print('已保存并验证可读取。以后 Aion 自动使用，无需重复输入。')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('已取消。')
    except Exception as exc:
        print(str(exc) if isinstance(exc, CredentialError) else '密钥设置失败：' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
