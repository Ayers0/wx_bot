# -*- coding: utf-8 -*-
"""Test active model image generation response shape.

Usage:
    python scripts/test_image_response.py
    python scripts/test_image_response.py "生成一张小猫在月球上的图片"

This script reads config.json, uses the active AI model profile, sends one Chat
Completions request, prints the raw JSON response, and extracts image URLs from
assistant content.
"""

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


IMAGE_URL_RE = re.compile(r'https?://[^\s\)\]\}"\']+/v1/files/image\?id=[^\s\)\]\}"\']+')


def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    config_path = os.path.join(base_dir, 'config.json')
    prompt = '生成一张图片：一只橘猫穿着宇航服站在月球表面，背景是地球，卡通风格。'
    if len(sys.argv) > 1:
        prompt = sys.argv[1]

    config = load_json(config_path)
    model_profile = get_active_model_profile(config)

    url = model_profile.get('chat_completions_url')
    api_key = get_api_key(model_profile)
    model = model_profile.get('model')
    if not url or not api_key or not model:
        raise RuntimeError('active model requires chat_completions_url, api_key/api_key_env, model')

    body = {
        'model': model,
        'messages': [
            {
                'role': 'user',
                'content': prompt,
            }
        ],
        'stream': False,
        'max_tokens': int(model_profile.get('max_tokens', (config.get('ai') or {}).get('max_tokens', 1024))),
        'temperature': float(model_profile.get('temperature', (config.get('ai') or {}).get('temperature', 0.7))),
    }

    print('URL:', url)
    print('MODEL:', model)
    print('PROMPT:', prompt)
    print('REQUEST BODY:')
    print(json.dumps(mask_body(body), ensure_ascii=False, indent=2))
    print('\n--- RAW RESPONSE ---')

    raw_text = post_json(url, api_key, body, timeout=180)
    print(raw_text)

    print('\n--- PARSED SUMMARY ---')
    try:
        data = json.loads(raw_text)
    except Exception as exc:
        print('JSON parse failed:', exc)
        return 2

    content = extract_content(data)
    reasoning = extract_reasoning_content(data)
    print('assistant.content:')
    print(content or '')
    if reasoning:
        print('\nreasoning_content exists, length:', len(reasoning))

    urls = IMAGE_URL_RE.findall(content or '')
    if urls:
        print('\nimage urls:')
        for item in urls:
            print(item)
    else:
        print('\nNo /v1/files/image?id=... URL found in assistant.content')
    return 0


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_active_model_profile(config):
    ai = config.get('ai') or {}
    models = ai.get('models') or {}
    active_name = ai.get('active_model') or ''
    if active_name and active_name in models:
        profile = dict(ai)
        profile.pop('models', None)
        profile.update(models.get(active_name) or {})
        return profile
    return ai


def get_api_key(profile):
    env_name = profile.get('api_key_env') or ''
    if env_name:
        value = os.environ.get(env_name)
        if value:
            return value
    return profile.get('api_key') or ''


def post_json(url, api_key, body, timeout):
    body_bytes = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=body_bytes, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer %s' % api_key)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
        print('HTTPError:', exc.code)
        print(detail)
        raise
    except URLError as exc:
        print('URLError:', exc)
        raise


def extract_content(data):
    try:
        return data['choices'][0]['message'].get('content') or ''
    except Exception:
        return ''


def extract_reasoning_content(data):
    try:
        return data['choices'][0]['message'].get('reasoning_content') or ''
    except Exception:
        return ''


def mask_body(body):
    return dict(body)


if __name__ == '__main__':
    sys.exit(main())
