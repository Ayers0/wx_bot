"""Session id and model-context construction."""

import logging
import os
import time
from datetime import datetime

from bot_core.media.image_data import image_file_to_data_url

logger = logging.getLogger(__name__)


class SessionManager(object):
    """Builds AI messages and stores user/assistant turns."""

    def __init__(self, config_provider, memory_store):
        self._config_provider = config_provider
        self._memory_store = memory_store

    def get_session_id(self, ctx):
        account_id = ctx.account_id or 'unknown-account'
        original = getattr(ctx, 'original_message', None)
        group_id = getattr(original, 'group_id', None) if original else None
        target = group_id or ctx.from_ or 'unknown-user'
        return '%s:%s' % (account_id, target)

    def build_messages(self, session_id, user_text):
        messages = self._build_base_messages(session_id)
        image_parts = self._build_recent_image_parts(session_id)
        if image_parts:
            image_parts.insert(0, {
                'type': 'text',
                'text': '以下是本会话最近的图片上下文，用户当前消息可能在追问这些图片。',
            })
            messages.append({'role': 'user', 'content': image_parts})
        messages.append({'role': 'user', 'content': user_text})
        return messages

    def build_vision_messages(self, session_id, user_text, image_data_url):
        messages = self._build_base_messages(session_id)
        image_parts = self._build_recent_image_parts(session_id)
        prompt = user_text or self._default_image_prompt()
        content = [{'type': 'text', 'text': prompt}]
        content.extend(image_parts)
        content.append({'type': 'image_url', 'image_url': {'url': image_data_url}})
        messages.append({
            'role': 'user',
            'content': content,
        })
        return messages

    def _build_base_messages(self, session_id):
        config = self._config_provider()
        from bot_core.config.manager import get_active_ai_config
        ai_config = get_active_ai_config(config)
        memory_config = config.get('memory', {})
        max_history = int(memory_config.get('max_history_messages', 20))
        messages = []
        system_prompt = ai_config.get('system_prompt') or ''
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        summary = self._memory_store.get_session_summary(session_id)
        if summary and summary.get('summary'):
            messages.append({
                'role': 'system',
                'content': '以下是本会话较早历史的摘要，请作为长期上下文参考：\n%s' % summary.get('summary')
            })
        history = self._memory_store.get_recent_messages(session_id, max_history)
        messages.extend(history)
        return messages

    def _build_recent_image_parts(self, session_id):
        config = self._config_provider()
        from bot_core.config.manager import get_active_ai_config
        ai_config = get_active_ai_config(config)
        if not ai_config.get('supports_vision', False):
            return []
        memory_config = config.get('memory', {})
        if not memory_config.get('image_context_enabled', False):
            return []
        max_images = int(memory_config.get('image_context_max_images', 3))
        if max_images <= 0:
            return []
        include_sources = []
        if memory_config.get('image_context_include_user_images', True):
            include_sources.append('user')
        if memory_config.get('image_context_include_ai_images', True):
            include_sources.append('assistant_generated')
        if not include_sources:
            return []
        images = self._memory_store.get_recent_images(
            session_id,
            max_images,
            memory_config.get('image_context_max_age_seconds', 86400),
            include_sources,
        )
        parts = []
        for image in images:
            media_path = image.get('media_path') or ''
            if not media_path or not os.path.exists(media_path):
                continue
            try:
                data_url = image_file_to_data_url(media_path, image.get('media_type'))
            except Exception:
                continue
            label = '历史图片'
            if image.get('source') == 'user':
                label = '用户之前发送的图片'
            elif image.get('source') == 'assistant_generated':
                label = 'AI 之前生成的图片'
            parts.append({'type': 'text', 'text': label})
            parts.append({'type': 'image_url', 'image_url': {'url': data_url}})
        return parts

    def _default_image_prompt(self):
        config = self._config_provider()
        return config.get('reply', {}).get('image_recognition_prompt') or '请识别这张图片，并简要说明图片内容。'

    def save_user_image(self, session_id, media_path, media_type=None, message_id=None):
        config = self._config_provider()
        if config.get('memory', {}).get('image_context_enabled', False):
            self._memory_store.add_image(session_id, 'user', media_path, media_type, message_id)

    def save_assistant_image(self, session_id, media_path, media_type=None, message_id=None):
        config = self._config_provider()
        if config.get('memory', {}).get('image_context_enabled', False):
            self._memory_store.add_image(session_id, 'assistant_generated', media_path, media_type, message_id)

    def save_user_message(self, session_id, content, message_id=None):
        config = self._config_provider()
        if config.get('memory', {}).get('save_user_messages', True):
            self._memory_store.add_message(session_id, 'user', content, message_id)

    def save_assistant_message(self, session_id, content, message_id=None):
        config = self._config_provider()
        if config.get('memory', {}).get('save_assistant_messages', True):
            self._memory_store.add_message(session_id, 'assistant', content, message_id)

    def summarize_if_needed(self, session_id, ai_client, force=False):
        config = self._config_provider()
        memory_config = config.get('memory', {})
        if not force and not memory_config.get('auto_summary_enabled', False):
            return False
        trigger_messages = int(memory_config.get('summary_trigger_messages', 40))
        keep_recent = int(memory_config.get('summary_keep_recent_messages', 12))
        count = self._memory_store.get_message_count(session_id)
        if not force and count < trigger_messages:
            return False
        old_messages = self._memory_store.get_old_messages_for_summary(session_id, keep_recent)
        if not old_messages:
            return False
        backup_path = ''
        try:
            if memory_config.get('summary_backup_enabled', True):
                backup_path = self._backup_memory_database(memory_config)
                self.cleanup_summary_backups(memory_config)
            old_summary = self._memory_store.get_session_summary(session_id)
            summary = self._summarize_messages(ai_client, old_summary, old_messages, memory_config)
            if not summary:
                return False
            max_chars = int(memory_config.get('summary_max_chars', 3000))
            summary = summary[:max_chars]
            self._memory_store.upsert_session_summary(session_id, summary, old_messages[-1].get('id'))
            self._memory_store.compact_session_messages(session_id, keep_recent)
            logger.info('Session summarized session=%s messages=%s backup=%s', session_id, len(old_messages), backup_path)
            return True
        except Exception as exc:
            logger.exception('Session summary failed session=%s backup=%s error=%s', session_id, backup_path, exc)
            return False

    def summarize_now(self, session_id, ai_client):
        return self.summarize_if_needed(session_id, ai_client, force=True)

    def get_context_status(self, session_id):
        summary = self._memory_store.get_session_summary(session_id) or {}
        return {
            'message_count': self._memory_store.get_message_count(session_id),
            'summary': summary.get('summary') or '',
            'summary_updated_at': summary.get('updated_at') or '',
            'summarized_until_message_id': summary.get('summarized_until_message_id') or '',
        }

    def _summarize_messages(self, ai_client, old_summary, messages, memory_config):
        prompt = memory_config.get('summary_prompt') or _default_summary_prompt()
        lines = []
        for item in messages:
            lines.append('[%s] %s' % (item.get('role') or '', item.get('content') or ''))
        content = prompt.format(
            old_summary=(old_summary or {}).get('summary') or '无',
            messages='\n'.join(lines)
        )
        return ai_client.chat([
            {'role': 'system', 'content': '你是一个严谨的对话记忆整理助手，只输出摘要本身。'},
            {'role': 'user', 'content': content}
        ])

    def _backup_memory_database(self, memory_config):
        backup_dir = self._resolve_backup_dir(memory_config)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, 'memory_%s.sqlite3' % timestamp)
        self._memory_store.backup_database(backup_path)
        return backup_path

    def cleanup_summary_backups(self, memory_config=None):
        memory_config = memory_config or self._config_provider().get('memory', {})
        backup_dir = self._resolve_backup_dir(memory_config)
        if not os.path.isdir(backup_dir):
            return 0
        max_files = int(memory_config.get('summary_backup_max_files', 20))
        max_age = int(memory_config.get('summary_backup_max_age_seconds', 604800))
        now = time.time()
        backups = []
        for name in os.listdir(backup_dir):
            if not (name.startswith('memory_') and name.endswith('.sqlite3')):
                continue
            path = os.path.join(backup_dir, name)
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                continue
            backups.append((path, mtime))
        backups.sort(key=lambda item: item[1], reverse=True)
        delete_paths = set()
        if max_age > 0:
            for path, mtime in backups:
                if now - mtime > max_age:
                    delete_paths.add(path)
        if max_files > 0:
            for path, _mtime in backups[max_files:]:
                delete_paths.add(path)
        deleted = 0
        for path in delete_paths:
            try:
                os.remove(path)
                deleted += 1
            except Exception as exc:
                logger.warning('Failed to delete summary backup %s: %s', path, exc)
        if deleted:
            logger.info('Summary backup cleanup deleted=%s dir=%s', deleted, backup_dir)
        return deleted

    def _resolve_backup_dir(self, memory_config):
        backup_dir = memory_config.get('summary_backup_dir') or 'data/memory_backups'
        if os.path.isabs(backup_dir):
            return backup_dir
        database_dir = os.path.dirname(os.path.abspath(self._memory_store.database_path))
        return os.path.abspath(os.path.join(database_dir, '..', backup_dir))


    def clear_session(self, session_id):
        self._memory_store.clear_session(session_id)


def _default_summary_prompt():
    return '''请把以下微信聊天记录整理成一份长期上下文摘要。

要求：
1. 保留用户偏好、长期任务、重要事实、已经做过的决定。
2. 删除寒暄、重复内容、无关细节。
3. 如果有待办事项，请单独列出。
4. 如果有代码、配置、账号、模型名、命令等关键信息，要保留。
5. 不要编造。
6. 控制在 1500 字以内。

已有摘要：
{old_summary}

新增聊天记录：
{messages}

请输出新的长期摘要：'''