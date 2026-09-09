"""Chat Completions wire adapter. Provider-specific settings live in aion.json."""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_provider(config):
    if not isinstance(config, dict) or config.get('api_format') != 'chat_completions':
        raise ValueError('目前只支持 chat_completions 接口格式。')
    for field in ('name', 'endpoint', 'model', 'api_key_env'):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError('provider 缺少有效配置：' + field)
    url = urlsplit(config['endpoint'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('provider.endpoint 必须是不含密钥、查询参数的 HTTPS 地址。')
    extra = config.get('extra_body', {})
    if not isinstance(extra, dict) or set(extra) & {'model', 'messages', 'tools', 'tool_choice', 'stream', 'max_tokens'}:
        raise ValueError('extra_body 不能覆盖核心请求字段。')


class ChatCompletionsProvider:
    def __init__(self, config, key, instructions, model=None):
        validate_provider(config)
        self.endpoint = config['endpoint']
        self.model = model or config['model']
        self.key = key
        self.instructions = instructions
        self.extra = config.get('extra_body', {})

    def complete(self, messages, definitions):
        payload = {**self.extra, 'model': self.model,
                   'messages': [{'role': 'system', 'content': self.instructions}] + messages,
                   'tools': [{'type': 'function', 'function': definition} for definition in definitions],
                   'tool_choice': 'auto', 'stream': False, 'max_tokens': 2000}
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            hints = {401: "密钥无效，请检查 API key。", 403: "账户无权限访问。",
                     402: "API 余额不足，请检查平台余额。",
                     404: "模型不可用，请使用 --model 指定账户可用的模型。",
                     429: "额度不足或请求过快，请检查账户额度或稍后再试。"}
            hint = hints.get(exc.code, "API 请求失败。")
            detail = "服务端未提供可解析的错误详情。"
            try:
                body = json.loads(exc.read(16384))
                error = body.get("error", {}) if isinstance(body, dict) else {}
                if isinstance(error, dict):
                    fields = [error.get("code"), error.get("type"), error.get("message")]
                    text = " | ".join(value for value in fields if isinstance(value, str) and value)
                    if text:
                        # Redact before truncating; never print headers or raw HTML bodies.
                        text = text.replace(self.key, "[密钥已隐藏]") if self.key else text
                        text = re.sub(r"sk-[A-Za-z0-9_.*-]+", "[密钥已隐藏]", text)
                        text = re.sub(r"(?i)Bearer\s+\S+", "Bearer [已隐藏]", text)
                        detail = " ".join("".join(c for c in text if c.isprintable() or c.isspace()).split())[:1000]
            except (ValueError, OSError):
                pass
            finally:
                exc.close()
            raise RuntimeError(f"HTTP {exc.code}：{hint}\n服务端详情：{detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("网络连接失败或超时，请检查网络后重试。") from None
        except (ValueError, UnicodeError):
            raise RuntimeError("API 返回了无法解析的内容。") from None
        try:
            choice = data['choices'][0]
            message = choice['message']
            if message.get('role') != 'assistant':
                raise ValueError()
            calls = message.get('tool_calls') or []
            content = message.get('content')
            if not isinstance(calls, list) or (content is not None and not isinstance(content, str)):
                raise ValueError()
            if choice.get('finish_reason') not in ('stop', 'tool_calls'):
                raise RuntimeError('回复未完成或被过滤；本轮未加入历史。')
            if choice.get('finish_reason') == 'tool_calls' and not calls:
                raise ValueError()
            return {'role': 'assistant', 'content': content, 'tool_calls': calls}
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            raise RuntimeError('API 返回了无法识别的回复格式。') from None
