"""OpenAI-compatible chat client using Python standard library only."""

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bot_core.config.manager import get_active_ai_config, get_ai_api_key


logger = logging.getLogger(__name__)


class AiClientError(Exception):
    """Raised when the AI endpoint returns an invalid or failed response."""


class AiClient(object):
    """Small OpenAI-compatible Chat Completions client.

    The implementation intentionally avoids the official OpenAI SDK and third
    party HTTP clients so it can run on CentOS 7 / Python 3.6.8.
    """

    def __init__(self, config_provider):
        self._config_provider = config_provider

    def chat(self, messages):
        """Returns a complete assistant response."""
        config = self._config_provider()
        ai_config = get_active_ai_config(config)
        body = self._build_body(ai_config, messages, stream=False)
        raw_text = self._post_json(ai_config, body)
        data = json.loads(raw_text)
        try:
            return data['choices'][0]['message'].get('content') or ''
        except Exception:
            raise AiClientError('Invalid AI response: missing choices[0].message.content')

    def chat_stream(self, messages):
        """Yields assistant text deltas from an SSE stream."""
        config = self._config_provider()
        ai_config = get_active_ai_config(config)
        body = self._build_body(ai_config, messages, stream=True)
        response = self._open_stream(ai_config, body)
        try:
            for raw_line in response:
                line = _decode_line(raw_line)
                if not line:
                    continue
                line = line.strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                if not payload:
                    continue
                try:
                    chunk = json.loads(payload)
                except Exception:
                    logger.debug('Skip invalid stream payload: %s', payload)
                    continue
                content = _extract_stream_content(chunk)
                if content:
                    yield content
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _build_body(self, ai_config, messages, stream):
        return {
            'model': ai_config.get('model'),
            'messages': messages,
            'stream': bool(stream),
            'max_tokens': int(ai_config.get('max_tokens', 1024)),
            'temperature': float(ai_config.get('temperature', 0.7)),
        }

    def _build_request(self, ai_config, body):
        config = self._config_provider()
        api_key = get_ai_api_key(config)
        url = ai_config.get('chat_completions_url')
        body_bytes = json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = Request(url, data=body_bytes, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', 'Bearer %s' % api_key)
        return req

    def _post_json(self, ai_config, body):
        req = self._build_request(ai_config, body)
        timeout = float(ai_config.get('timeout_seconds', 120))
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8')
        except HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
            raise AiClientError('AI HTTP %s: %s' % (exc.code, detail[:500]))
        except URLError as exc:
            raise AiClientError('AI network error: %s' % exc)

    def _open_stream(self, ai_config, body):
        req = self._build_request(ai_config, body)
        timeout = float(ai_config.get('timeout_seconds', 120))
        try:
            return urlopen(req, timeout=timeout)
        except HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
            raise AiClientError('AI stream HTTP %s: %s' % (exc.code, detail[:500]))
        except URLError as exc:
            raise AiClientError('AI stream network error: %s' % exc)


def _decode_line(raw_line):
    if isinstance(raw_line, bytes):
        return raw_line.decode('utf-8', errors='replace')
    return raw_line


def _extract_stream_content(chunk):
    try:
        choices = chunk.get('choices') or []
        if not choices:
            return ''
        delta = choices[0].get('delta') or {}
        return delta.get('content') or ''
    except Exception:
        return ''
