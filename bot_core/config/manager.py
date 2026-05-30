"""Configuration loading and hot reload support."""

import json
import logging
import os
import threading
import time


logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when config.json is missing or invalid."""


class ConfigManager(object):
    """Loads config.json and refreshes it when the file changes."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.base_dir = os.path.dirname(self.path)
        self._lock = threading.Lock()
        self._config = None
        self._mtime = None
        self._stop_event = threading.Event()
        self._thread = None

    def load(self):
        config = _load_json(self.path)
        config = _with_defaults(config)
        _validate(config)
        with self._lock:
            self._config = config
            self._mtime = _safe_mtime(self.path)
        return config

    def get(self):
        with self._lock:
            return self._config

    def start_hot_reload(self):
        config = self.get()
        hot_reload = config.get('hot_reload', {}) if config else {}
        if not hot_reload.get('enabled', False):
            return
        if self._thread is not None:
            return
        interval = hot_reload.get('poll_interval_seconds', 2)
        try:
            interval = float(interval)
        except Exception:
            interval = 2.0
        if interval <= 0:
            interval = 2.0
        self._thread = threading.Thread(target=self._reload_loop, args=(interval,))
        self._thread.daemon = True
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def list_ai_models(self):
        config = self.get() or {}
        return list_ai_models(config)

    def current_ai_model(self):
        config = self.get() or {}
        return current_ai_model(config)

    def switch_ai_model(self, model_name):
        """Switches the global active AI model profile and persists config.json."""
        model_name = (model_name or '').strip()
        if not model_name:
            raise ConfigError('model name is required')
        with self._lock:
            config = self._config
            if not config:
                raise ConfigError('config is not loaded')
            ai = config.get('ai', {})
            models = ai.get('models') or {}
            if model_name not in models:
                raise ConfigError('unknown model: %s' % model_name)
            ai['active_model'] = model_name
            _validate(config)
            _save_json(self.path, config)
            self._mtime = _safe_mtime(self.path)
        logger.info('AI model switched globally: %s', model_name)
        return model_name

    def add_ai_model(self, model_name, profile, activate=False):
        """Adds or updates an AI model profile and persists config.json."""
        model_name = (model_name or '').strip()
        if not model_name:
            raise ConfigError('model name is required')
        if not isinstance(profile, dict):
            raise ConfigError('model profile must be an object')
        with self._lock:
            config = self._config
            if not config:
                raise ConfigError('config is not loaded')
            ai = config.setdefault('ai', {})
            models = ai.setdefault('models', {})
            merged = _model_profile_with_defaults(ai, profile)
            _validate_single_model(model_name, merged)
            models[model_name] = merged
            if activate:
                ai['active_model'] = model_name
            _validate(config)
            _save_json(self.path, config)
            self._mtime = _safe_mtime(self.path)
        logger.info('AI model added: %s activate=%s', model_name, activate)
        return model_name

    def update_ai_model(self, model_name, patch, activate=False):
        """Updates fields of an existing AI model profile and persists config.json."""
        model_name = (model_name or '').strip()
        if not model_name:
            raise ConfigError('model name is required')
        if not isinstance(patch, dict):
            raise ConfigError('model patch must be an object')
        with self._lock:
            config = self._config
            if not config:
                raise ConfigError('config is not loaded')
            ai = config.setdefault('ai', {})
            models = ai.setdefault('models', {})
            if model_name not in models:
                raise ConfigError('unknown model: %s' % model_name)
            profile = dict(models.get(model_name) or {})
            profile.update(patch)
            merged = _model_profile_with_defaults(ai, profile)
            _validate_single_model(model_name, merged)
            models[model_name] = merged
            if activate:
                ai['active_model'] = model_name
            _validate(config)
            _save_json(self.path, config)
            self._mtime = _safe_mtime(self.path)
        logger.info('AI model updated: %s activate=%s', model_name, activate)
        return model_name

    def delete_ai_model(self, model_name):
        """Deletes an AI model profile and persists config.json."""
        model_name = (model_name or '').strip()
        if not model_name:
            raise ConfigError('model name is required')
        with self._lock:
            config = self._config
            if not config:
                raise ConfigError('config is not loaded')
            ai = config.setdefault('ai', {})
            models = ai.setdefault('models', {})
            if model_name not in models:
                raise ConfigError('unknown model: %s' % model_name)
            if ai.get('active_model') == model_name:
                raise ConfigError('cannot delete active model, switch to another model first')
            del models[model_name]
            _validate(config)
            _save_json(self.path, config)
            self._mtime = _safe_mtime(self.path)
        logger.info('AI model deleted: %s', model_name)
        return model_name

    def _reload_loop(self, interval):
        while not self._stop_event.is_set():
            time.sleep(interval)
            mtime = _safe_mtime(self.path)
            with self._lock:
                old_mtime = self._mtime
            if mtime is None or old_mtime is None or mtime <= old_mtime:
                continue
            try:
                config = _load_json(self.path)
                config = _with_defaults(config)
                _validate(config)
                with self._lock:
                    self._config = config
                    self._mtime = mtime
                logger.info('Config reloaded: %s', self.path)
            except Exception as exc:
                logger.error('Config reload failed: %s', exc)


def get_active_ai_config(config):
    ai = config.get('ai', {})
    models = ai.get('models') or {}
    active_model = ai.get('active_model') or ''
    if active_model and active_model in models:
        merged = dict(ai)
        profile = dict(models.get(active_model) or {})
        for key in ('models',):
            merged.pop(key, None)
        merged.update(profile)
        merged['active_model'] = active_model
        return merged
    return ai


def get_ai_api_key(config):
    ai = get_active_ai_config(config)
    env_name = ai.get('api_key_env') or ''
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
    return ai.get('api_key') or ''


def list_ai_models(config):
    ai = config.get('ai', {})
    models = ai.get('models') or {}
    names = list(models.keys())
    names.sort()
    return names


def current_ai_model(config):
    ai = config.get('ai', {})
    active_model = ai.get('active_model') or ''
    if active_model:
        return active_model
    return ai.get('model') or ''


def resolve_path(base_dir, path):
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(base_dir, path))


def _load_json(path):
    if not os.path.exists(path):
        raise ConfigError('Config file not found: %s' % path)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_json(path, config):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write('\n')


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except Exception:
        return None


def _with_defaults(config):
    if not isinstance(config, dict):
        raise ConfigError('Config must be a JSON object')
    config.setdefault('wechat', {})
    config.setdefault('ai', {})
    config.setdefault('memory', {})
    config.setdefault('reply', {})
    config.setdefault('hot_reload', {})
    config.setdefault('logging', {})

    wechat = config['wechat']
    wechat.setdefault('account_id', '')
    wechat.setdefault('auto_login', False)
    wechat.setdefault('sdk_path', 'vendor')
    wechat.setdefault('media_dir', 'data/media')
    wechat.setdefault('media_max_age_seconds', 86400)
    wechat.setdefault('media_max_files', 500)
    wechat.setdefault('media_cleanup_interval_seconds', 3600)

    ai = config['ai']
    ai.setdefault('provider', 'openai-compatible')
    ai.setdefault('chat_completions_url', '')
    ai.setdefault('api_key', '')
    ai.setdefault('api_key_env', '')
    ai.setdefault('model', '')
    ai.setdefault('active_model', '')
    ai.setdefault('models', {})
    ai.setdefault('stream', False)
    ai.setdefault('timeout_seconds', 120)
    ai.setdefault('max_tokens', 1024)
    ai.setdefault('temperature', 0.7)
    ai.setdefault('system_prompt', '你是一个有帮助的微信 AI 助手。')
    ai.setdefault('ignore_reasoning_content', True)
    models = ai.get('models') or {}
    for name, profile in models.items():
        if not isinstance(profile, dict):
            raise ConfigError('ai.models.%s must be an object' % name)
        models[name] = _model_profile_with_defaults(ai, profile)

    memory = config['memory']
    memory.setdefault('database_path', 'data/memory.sqlite3')
    memory.setdefault('max_history_messages', 20)
    memory.setdefault('save_user_messages', True)
    memory.setdefault('save_assistant_messages', True)
    memory.setdefault('image_context_enabled', False)
    memory.setdefault('image_context_max_images', 3)
    memory.setdefault('image_context_max_age_seconds', 86400)
    memory.setdefault('image_context_include_user_images', True)
    memory.setdefault('image_context_include_ai_images', True)
    memory.setdefault('auto_summary_enabled', True)
    memory.setdefault('summary_trigger_messages', 40)
    memory.setdefault('summary_keep_recent_messages', 12)
    memory.setdefault('summary_max_chars', 3000)
    memory.setdefault('summary_backup_enabled', True)
    memory.setdefault('summary_backup_dir', 'data/memory_backups')
    memory.setdefault('summary_backup_max_files', 20)
    memory.setdefault('summary_backup_max_age_seconds', 604800)
    memory.setdefault('summary_prompt', '')

    reply = config['reply']
    reply.setdefault('ignore_empty_text', True)
    reply.setdefault('clear_commands', ['/clear', '/清理', '清空记忆'])
    reply.setdefault('menu_commands', ['/菜单'])
    reply.setdefault('model_commands', ['/model', '/模型'])
    reply.setdefault('add_model_commands', ['/add model', '/添加模型'])
    reply.setdefault('list_model_commands', ['/模型列表', '/list models'])
    reply.setdefault('update_model_commands', ['/修改模型', '/update model'])
    reply.setdefault('delete_model_commands', ['/删除模型', '/delete model'])
    reply.setdefault('stream_send_to_wechat', False)
    reply.setdefault('stream_chunk_chars', 120)
    reply.setdefault('stream_chunk_interval_seconds', 1.5)
    reply.setdefault('send_typing', True)
    reply.setdefault('recognize_images', True)
    reply.setdefault('image_recognition_prompt', '请识别这张图片，并简要说明图片内容。')
    reply.setdefault('send_ai_images', True)
    reply.setdefault('generated_image_dir', 'data/generated_images')
    reply.setdefault('generated_image_max_age_seconds', 86400)
    reply.setdefault('generated_image_max_files', 200)
    reply.setdefault('generated_image_cleanup_interval_seconds', 3600)
    reply.setdefault('image_caption', '')

    hot_reload = config['hot_reload']
    hot_reload.setdefault('enabled', True)
    hot_reload.setdefault('poll_interval_seconds', 2)

    logging_config = config['logging']
    logging_config.setdefault('level', 'INFO')
    logging_config.setdefault('file', 'data/bot.log')
    return config


def _model_profile_with_defaults(ai, profile):
    profile = dict(profile or {})
    profile.setdefault('provider', ai.get('provider', 'openai-compatible'))
    profile.setdefault('stream', ai.get('stream', False))
    profile.setdefault('timeout_seconds', ai.get('timeout_seconds', 120))
    profile.setdefault('max_tokens', ai.get('max_tokens', 1024))
    profile.setdefault('temperature', ai.get('temperature', 0.7))
    profile.setdefault('system_prompt', ai.get('system_prompt', '你是一个有帮助的微信 AI 助手。'))
    profile.setdefault('ignore_reasoning_content', ai.get('ignore_reasoning_content', True))
    profile.setdefault('supports_vision', ai.get('supports_vision', False))
    return profile


def _validate_single_model(name, profile):
    url = profile.get('chat_completions_url') or ''
    model = profile.get('model') or ''
    env_name = profile.get('api_key_env') or ''
    api_key = profile.get('api_key') or ''
    if not url:
        raise ConfigError('ai.models.%s.chat_completions_url is required' % name)
    if _is_placeholder_value(url):
        raise ConfigError('ai.models.%s.chat_completions_url still uses a placeholder value' % name)
    if not model:
        raise ConfigError('ai.models.%s.model is required' % name)
    if _is_placeholder_value(model):
        raise ConfigError('ai.models.%s.model still uses a placeholder value' % name)
    if api_key and _is_placeholder_value(api_key):
        raise ConfigError('ai.models.%s.api_key still uses a placeholder value' % name)
    if not api_key and not (env_name and os.environ.get(env_name)):
        raise ConfigError('ai.models.%s.api_key or api_key_env is required' % name)


def _is_placeholder_value(value):
    value = (value or '').strip().lower()
    if not value:
        return False
    placeholder_parts = [
        'example.com',
        'your-',
        'your_',
        '你的',
        '<api',
        'sk-xxx',
        'sk-...',
    ]
    for item in placeholder_parts:
        if item in value:
            return True
    return False

def _validate(config):
    root_ai = config.get('ai', {})
    models = root_ai.get('models') or {}
    active_model = root_ai.get('active_model') or ''
    if active_model and active_model not in models:
        raise ConfigError('ai.active_model not found in ai.models: %s' % active_model)
    for name, profile in models.items():
        _validate_single_model(name, profile)
    ai = get_active_ai_config(config)
    if not ai.get('chat_completions_url'):
        raise ConfigError('ai.chat_completions_url is required')
    if not ai.get('model'):
        raise ConfigError('ai.model is required')
    api_key = get_ai_api_key(config)
    if not api_key:
        raise ConfigError('ai.api_key or ai.api_key_env is required')
