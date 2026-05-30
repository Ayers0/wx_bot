"""Wechat long-polling bot orchestration."""

import json
import logging
import time

from bot_core.config.manager import get_active_ai_config
from bot_core.media.image_data import image_file_to_data_url, is_image_media_type


logger = logging.getLogger(__name__)


class WechatAiBot(object):
    """Connects Weixin SDK message monitoring to the AI client."""

    def __init__(self, config_provider, ai_client, session_manager, image_downloader=None,
                 received_media_cleaner=None, config_manager=None):
        self._config_provider = config_provider
        self._ai_client = ai_client
        self._session_manager = session_manager
        self._image_downloader = image_downloader
        self._received_media_cleaner = received_media_cleaner
        self._config_manager = config_manager
        self._monitor = None
        self._send_service = None
        self._api_client = None

    def start(self):
        from ilinkai_weixin import WeixinApiClient, WeixinApiClientOptions
        from ilinkai_weixin.auth.account_store import AccountStore
        from ilinkai_weixin.messaging.message_monitor_service import MessageMonitorService
        from ilinkai_weixin.messaging.message_send_service import MessageSendService

        config = self._config_provider()
        wechat = config.get('wechat', {})
        account_store = AccountStore()
        account_id = wechat.get('account_id') or _first_account_id(account_store)
        if not account_id:
            raise RuntimeError('No wechat.account_id configured and no saved account found. Run SDK login first.')

        account = account_store.resolve_account(account_id)
        if not account.token:
            raise RuntimeError('No token found for account: %s. Run SDK login first.' % account_id)

        api_client = WeixinApiClient(WeixinApiClientOptions(
            base_url=account.base_url,
            cdn_base_url=account.cdn_base_url,
            token=account.token,
        ))
        self._api_client = api_client
        self._send_service = MessageSendService(api_client, account.cdn_base_url)
        self._monitor = MessageMonitorService(
            base_url=account.base_url,
            cdn_base_url=account.cdn_base_url,
            token=account.token,
            account_id=account.account_id,
            media_dir=wechat.get('media_dir')
        )
        self._monitor.on_message_received = self._on_message
        self._monitor.on_error = self._on_error
        logger.info('Starting bot for account=%s', account.account_id)
        self._monitor.start()

    def stop(self):
        if self._monitor:
            self._monitor.stop()

    def _on_error(self, err):
        logger.error('Monitor error: %s', err)

    def _on_message(self, ctx):
        if self._received_media_cleaner:
            self._received_media_cleaner.cleanup_if_needed()
        config = self._config_provider()
        reply_config = config.get('reply', {})
        text = (ctx.body or '').strip()
        session_id = self._session_manager.get_session_id(ctx)
        logger.info('Message received session=%s from=%s text=%s', session_id, ctx.from_, _short(text, 80))

        if _is_menu_command(text):
            self._send_reply(ctx, self._build_menu_text(reply_config))
            return

        if _is_clear_command(text, reply_config):
            self._session_manager.clear_session(session_id)
            self._send_reply(ctx, '已清空当前会话上下文：最近消息、图片记录和历史摘要都已删除。不会删除模型配置、备份文件或其他会话。')
            return

        if _is_summary_command(text):
            self._handle_summary_command(ctx, session_id, text)
            return

        if _is_add_model_command(text, reply_config):
            self._handle_add_model_command(ctx, text, reply_config)
            return

        if _is_list_model_command(text, reply_config):
            self._handle_list_model_command(ctx)
            return

        if _is_update_model_command(text, reply_config):
            self._handle_update_model_command(ctx, text, reply_config)
            return

        if _is_delete_model_command(text, reply_config):
            self._handle_delete_model_command(ctx, text, reply_config)
            return

        if _is_model_command(text):
            self._handle_model_command(ctx, text)
            return

        if reply_config.get('ignore_empty_text', True) and not text:
            if not self._has_supported_image(ctx, reply_config):
                logger.info('Skip empty message session=%s', session_id)
                return

        if not ctx.context_token:
            logger.warning('Skip message without context_token session=%s', session_id)
            return

        typing_ticket = self._start_typing(ctx, reply_config)
        try:
            messages = self._build_ai_messages(ctx, session_id, text, reply_config)
            self._session_manager.save_user_message(session_id, self._memory_user_content(ctx, text), ctx.message_id)
            if self._has_supported_image(ctx, reply_config):
                self._session_manager.save_user_image(session_id, ctx.media_path, ctx.media_type, ctx.message_id)
            ai_config = get_active_ai_config(config)
            if ai_config.get('stream', False):
                reply = self._chat_stream(ctx, messages, reply_config)
            else:
                reply = self._ai_client.chat(messages)
            reply = (reply or '').strip()
            if not reply:
                reply = '(AI 返回空内容)'
            self._session_manager.save_assistant_message(session_id, reply)
            self._session_manager.summarize_if_needed(session_id, self._ai_client)
            if not ai_config.get('stream', False) or not reply_config.get('stream_send_to_wechat', False):
                if not self._try_send_image_reply(ctx, session_id, reply):
                    self._send_reply(ctx, reply)
        except Exception as exc:
            logger.exception('Failed to handle message: %s', exc)
            try:
                self._send_reply(ctx, '处理消息失败：%s' % exc)
            except Exception:
                logger.exception('Failed to send error reply')
        finally:
            self._stop_typing(ctx, typing_ticket)

    def _build_menu_text(self, reply_config):
        lines = [
            '🤖 微信 AI 助手菜单',
            '',
            '常用命令：',
            '1. /菜单',
            '   查看本菜单。',
            '2. /清理    或 /clear',
            '   清空当前会话上下文：消息、图片记录和历史摘要。',
            '3. /模型列表 或 /list models',
            '   查看模型详情。',
            '4. /模型 模型名 或 /model 模型名',
            '   切换到指定模型。',
            '5. /添加模型 ... 或 /add model ...',
            '   添加模型。末尾加 --activate 可添加后立即切换，建议使用 api_key_env。',
            '6. /修改模型 ... 或 /update model ...',
            '   修改模型字段，支持 JSON 或 key=value。',
            '7. /删除模型 ... 或 /delete model ...',
            '   删除模型。不能删除当前正在使用的模型。',
            '8. /上下文状态 或 /总结上下文',
            '   查看摘要状态，或手动总结当前会话。',
            '',
            '示例：',
            '- /添加模型 demo https://api.example.com/v1/chat/completions your-model sk-xxx --activate',
            '- /添加模型 demo https://api.example.com/v1/chat/completions your-model api_key_env=OPENAI_COMPAT_API_KEY --activate',
            '- /修改模型 kimi model=moonshot-v1-32k max_tokens=2048',
            '- /删除模型 kimi',
            '',
            'JSON 添加模型：',
            '/添加模型 {"name":"kimi","chat_completions_url":"...","model":"...","api_key":"...","activate":true}',
            '',
            '直接发送文字或图片即可和 AI 对话。'
        ]
        return '\n'.join(lines)

    def _handle_summary_command(self, ctx, session_id, text):
        if text in ('/上下文状态', '/context status'):
            status = self._session_manager.get_context_status(session_id)
            summary = status.get('summary') or ''
            lines = [
                '上下文状态：',
                '- 当前保留消息数：%s' % status.get('message_count'),
                '- 摘要更新时间：%s' % (status.get('summary_updated_at') or '无'),
                '- 已总结到消息ID：%s' % (status.get('summarized_until_message_id') or '无'),
                '- 摘要长度：%s 字' % len(summary),
            ]
            if summary:
                lines.append('摘要预览：%s' % _short(summary, 300))
            self._send_reply(ctx, '\n'.join(lines))
            return
        ok = self._session_manager.summarize_now(session_id, self._ai_client)
        if ok:
            self._send_reply(ctx, '已完成当前会话上下文总结，并已备份数据库后压缩历史消息。')
        else:
            self._send_reply(ctx, '当前没有可总结的旧消息，或总结失败。详情请查看日志。')


    def _handle_list_model_command(self, ctx):
        if not self._config_manager:
            self._send_reply(ctx, '当前程序未启用模型配置管理器。')
            return
        self._send_reply(ctx, self._build_model_list_text())

    def _build_model_list_text(self):
        config = self._config_provider()
        models = (config.get('ai', {}).get('models') or {})
        current = self._config_manager.current_ai_model()
        if not models:
            return '暂无模型配置。'
        lines = ['模型列表：']
        for name in sorted(models.keys()):
            profile = models.get(name) or {}
            prefix = '当前' if name == current else '可用'
            lines.append('%s：%s => %s' % (prefix, name, profile.get('model') or ''))
            lines.append('  API：%s' % _mask_url(profile.get('chat_completions_url') or ''))
            lines.append('  视觉：%s' % ('支持' if profile.get('supports_vision') else '不支持'))
        lines.append('')
        lines.append('切换：/模型 模型名')
        lines.append('修改：/修改模型 模型名 字段=新值')
        lines.append('删除：/删除模型 模型名')
        return '\n'.join(lines)

    def _handle_update_model_command(self, ctx, text, reply_config):
        if not self._config_manager:
            self._send_reply(ctx, '当前程序未启用模型配置管理器。')
            return
        try:
            command, payload = _split_command_payload(text, reply_config.get('update_model_commands') or [], ['/修改模型', '/update model'])
            if not payload:
                self._send_reply(ctx, _update_model_usage(command))
                return
            model_name, patch, activate = _parse_update_model_payload(payload)
            self._config_manager.update_ai_model(model_name, patch, activate=activate)
            active_tip = '，并已切换为当前模型' if activate else ''
            self._send_reply(ctx, '已修改模型：%s%s' % (model_name, active_tip))
        except Exception as exc:
            self._send_reply(ctx, '修改模型失败：%s\n%s' % (exc, _update_model_usage('/修改模型')))

    def _handle_delete_model_command(self, ctx, text, reply_config):
        if not self._config_manager:
            self._send_reply(ctx, '当前程序未启用模型配置管理器。')
            return
        try:
            command, payload = _split_command_payload(text, reply_config.get('delete_model_commands') or [], ['/删除模型', '/delete model'])
            model_name = (payload or '').strip().split()[0] if payload else ''
            if not model_name:
                self._send_reply(ctx, _delete_model_usage(command))
                return
            self._config_manager.delete_ai_model(model_name)
            self._send_reply(ctx, '已删除模型：%s' % model_name)
        except Exception as exc:
            self._send_reply(ctx, '删除模型失败：%s\n%s' % (exc, _delete_model_usage('/删除模型')))


    def _handle_add_model_command(self, ctx, text, reply_config):
        if not self._config_manager:
            self._send_reply(ctx, '当前程序未启用模型配置管理器。')
            return
        try:
            command, payload = _split_command_payload(text, reply_config.get('add_model_commands') or [], ['/add model', '/添加模型'])
            if not payload:
                self._send_reply(ctx, _add_model_usage(command))
                return
            model_name, profile, activate = _parse_add_model_payload(payload)
            self._config_manager.add_ai_model(model_name, profile, activate=activate)
            active_tip = '，并已切换为当前模型' if activate else ''
            self._send_reply(ctx, '已添加/更新模型：%s => %s%s' % (model_name, profile.get('model') or '', active_tip))
        except Exception as exc:
            self._send_reply(ctx, '添加模型失败：%s\n%s' % (exc, _add_model_usage('/添加模型')))

    def _handle_model_command(self, ctx, text):
        if not self._config_manager:
            self._send_reply(ctx, '当前程序未启用模型切换管理器。')
            return
        parts = text.split()
        config = self._config_provider()
        model_names = self._config_manager.list_ai_models()
        current = self._config_manager.current_ai_model()
        if len(parts) == 1 or (len(parts) >= 2 and parts[1].lower() == 'list'):
            active_config = get_active_ai_config(config)
            lines = ['当前模型：%s' % (current or active_config.get('model') or '未配置')]
            if model_names:
                lines.append('可切换模型：')
                for name in model_names:
                    prefix = '* ' if name == current else '- '
                    profile = (config.get('ai', {}).get('models') or {}).get(name) or {}
                    lines.append('%s%s => %s' % (prefix, name, profile.get('model') or ''))
                lines.append('用法：/model 模型名 或 /模型 模型名')
            else:
                lines.append('未配置 ai.models，无法通过 /model 或 /模型 切换。')
            self._send_reply(ctx, '\n'.join(lines))
            return
        target = parts[1].strip()
        try:
            self._config_manager.switch_ai_model(target)
            profile = (self._config_provider().get('ai', {}).get('models') or {}).get(target) or {}
            self._send_reply(ctx, '已全局切换模型：%s => %s' % (target, profile.get('model') or ''))
        except Exception as exc:
            available = ', '.join(model_names) if model_names else '无'
            self._send_reply(ctx, '模型切换失败：%s\n可用模型：%s' % (exc, available))

    def _build_ai_messages(self, ctx, session_id, text, reply_config):
        if self._has_supported_image(ctx, reply_config):
            data_url = image_file_to_data_url(ctx.media_path, ctx.media_type)
            return self._session_manager.build_vision_messages(session_id, text, data_url)
        return self._session_manager.build_messages(session_id, text)

    def _has_supported_image(self, ctx, reply_config):
        if not reply_config.get('recognize_images', True):
            return False
        return bool(ctx.media_path and is_image_media_type(ctx.media_type))

    def _memory_user_content(self, ctx, text):
        if ctx.media_path and is_image_media_type(ctx.media_type):
            if text:
                return '[图片] %s' % text
            return '[图片]'
        return text

    def _start_typing(self, ctx, reply_config):
        if not reply_config.get('send_typing', True):
            return None
        if not self._api_client or not self._send_service or not ctx.context_token:
            return None
        try:
            config_resp = self._api_client.get_config(ctx.from_, ctx.context_token)
            typing_ticket = getattr(config_resp, 'typing_ticket', None)
            if not typing_ticket:
                return None
            self._send_service.send_typing(ctx.from_, typing_ticket, True)
            logger.debug('Typing started for=%s', ctx.from_)
            return typing_ticket
        except Exception as exc:
            logger.debug('Failed to start typing: %s', exc)
            return None

    def _stop_typing(self, ctx, typing_ticket):
        if not typing_ticket or not self._send_service:
            return
        try:
            self._send_service.send_typing(ctx.from_, typing_ticket, False)
            logger.debug('Typing stopped for=%s', ctx.from_)
        except Exception as exc:
            logger.debug('Failed to stop typing: %s', exc)

    def _chat_stream(self, ctx, messages, reply_config):
        chunks = []
        send_to_wechat = reply_config.get('stream_send_to_wechat', False)
        chunk_chars = int(reply_config.get('stream_chunk_chars', 120))
        interval = float(reply_config.get('stream_chunk_interval_seconds', 1.5))
        pending = ''
        last_send = 0
        for delta in self._ai_client.chat_stream(messages):
            chunks.append(delta)
            pending += delta
            print(delta, end='', flush=True)
            if send_to_wechat and len(pending) >= chunk_chars and time.time() - last_send >= interval:
                self._send_reply(ctx, pending)
                pending = ''
                last_send = time.time()
        if chunks:
            print('', flush=True)
        if send_to_wechat and pending:
            self._send_reply(ctx, pending)
        return ''.join(chunks)

    def _send_reply(self, ctx, text):
        if not ctx.context_token:
            logger.warning('Cannot send reply without context_token')
            return
        to_user = ctx.from_
        self._send_service.send_text(to_user, text, ctx.context_token)
        logger.info('Reply sent to=%s text=%s', to_user, _short(text, 80))

    def _try_send_image_reply(self, ctx, session_id, reply):
        if not self._image_downloader:
            return False
        config = self._config_provider()
        if not config.get('reply', {}).get('send_ai_images', True):
            return False
        image_url = self._image_downloader.find_image_url(reply)
        if not image_url:
            return False
        image_path = self._image_downloader.download(image_url)
        self._session_manager.save_assistant_image(session_id, image_path, _guess_image_media_type(image_path))
        caption = config.get('reply', {}).get('image_caption') or ''
        self._send_service.send_image(ctx.from_, image_path, ctx.context_token, caption=caption)
        logger.info('Image reply sent as image to=%s file=%s', ctx.from_, image_path)
        return True


def _first_account_id(account_store):
    accounts = account_store.list_account_ids()
    if accounts:
        return accounts[0]
    return ''


def _is_clear_command(text, reply_config):
    commands = _command_aliases(reply_config.get('clear_commands') or [], ['/clear', '/清理', '清空记忆'])
    return text in commands


def _is_menu_command(text):
    return text == '/菜单'


def _is_add_model_command(text, reply_config):
    command, payload = _split_command_payload(text, reply_config.get('add_model_commands') or [], ['/add model', '/添加模型'])
    return bool(command) and (payload or text == command)


def _is_list_model_command(text, reply_config):
    command, payload = _split_command_payload(text, reply_config.get('list_model_commands') or [], ['/模型列表', '/list models'])
    return bool(command) and not payload


def _is_update_model_command(text, reply_config):
    command, payload = _split_command_payload(text, reply_config.get('update_model_commands') or [], ['/修改模型', '/update model'])
    return bool(command) and (payload or text == command)

def _is_summary_command(text):
    return text in ('/总结上下文', '/summarize context', '/上下文状态', '/context status')


def _is_delete_model_command(text, reply_config):
    command, payload = _split_command_payload(text, reply_config.get('delete_model_commands') or [], ['/删除模型', '/delete model'])
    return bool(command) and (payload or text == command)


def _is_model_command(text):
    if not text:
        return False
    return text in ('/model', '/模型') or text.startswith('/model ') or text.startswith('/模型 ')


def _command_aliases(configured, defaults):
    commands = []
    for command in list(configured) + list(defaults):
        command = (command or '').strip()
        if command and command not in commands:
            commands.append(command)
    return commands


def _split_command_payload(text, configured, defaults):
    text = (text or '').strip()
    commands = _command_aliases(configured, defaults)
    commands.sort(key=len, reverse=True)
    for command in commands:
        if text == command:
            return command, ''
        prefix = command + ' '
        if text.startswith(prefix):
            return command, text[len(prefix):].strip()
    return '', ''


def _parse_add_model_payload(payload):
    payload = (payload or '').strip()
    if payload.startswith('{'):
        data = json.loads(payload)
        model_name = (data.pop('name', '') or '').strip()
        activate = bool(data.pop('activate', False))
        return model_name, data, activate
    parts = payload.split()
    if len(parts) < 3:
        raise ValueError('参数不足')
    model_name = parts[0]
    profile = {
        'chat_completions_url': parts[1],
        'model': parts[2],
    }
    option_start = 3
    if len(parts) >= 4 and '=' not in parts[3] and not parts[3].startswith('--'):
        profile['api_key'] = parts[3]
        option_start = 4
    activate = False
    for option in parts[option_start:]:
        if option in ('--activate', '--active', 'activate=true'):
            activate = True
        elif option.startswith('provider='):
            profile['provider'] = option.split('=', 1)[1]
        elif option.startswith('api_key_env='):
            profile['api_key_env'] = option.split('=', 1)[1]
        elif option.startswith('supports_vision='):
            profile['supports_vision'] = option.split('=', 1)[1].lower() in ('1', 'true', 'yes', '是')
    return model_name, profile, activate


def _parse_update_model_payload(payload):
    payload = (payload or '').strip()
    if payload.startswith('{'):
        data = json.loads(payload)
        model_name = (data.pop('name', '') or '').strip()
        activate = bool(data.pop('activate', False))
        return model_name, data, activate
    parts = payload.split()
    if len(parts) < 2:
        raise ValueError('参数不足')
    model_name = parts[0]
    patch = {}
    activate = False
    for item in parts[1:]:
        if item in ('--activate', '--active', 'activate=true'):
            activate = True
            continue
        if '=' not in item:
            raise ValueError('修改项必须是 key=value：%s' % item)
        key, value = item.split('=', 1)
        key = key.strip()
        value = value.strip()
        if key in ('stream', 'supports_vision', 'ignore_reasoning_content'):
            patch[key] = value.lower() in ('1', 'true', 'yes', '是')
        elif key in ('timeout_seconds', 'max_tokens'):
            patch[key] = int(value)
        elif key == 'temperature':
            patch[key] = float(value)
        else:
            patch[key] = value
    return model_name, patch, activate


def _update_model_usage(command):
    return '\n'.join([
        '用法1：%s 模型名 字段=新值 [字段=新值] [--activate]' % command,
        '示例：%s demo model=your-model-name max_tokens=2048' % command,
        '可改字段：chat_completions_url、model、api_key、api_key_env、supports_vision、max_tokens、temperature 等',
        '用法2：%s {"name":"kimi","model":"moonshot-v1-32k","activate":true}' % command
    ])


def _delete_model_usage(command):
    return '用法：%s 模型名\n示例：%s kimi' % (command, command)


def _mask_url(url):
    if not url:
        return ''
    if len(url) <= 80:
        return url
    return url[:77] + '...'


def _add_model_usage(command):
    return '\n'.join([
        '用法1：%s 模型名 chat_completions_url model api_key [api_key_env=ENV_NAME] [--activate]' % command,
        '示例1：%s demo https://api.example.com/v1/chat/completions your-model sk-xxx --activate' % command,
        '示例2：%s demo https://api.example.com/v1/chat/completions your-model api_key_env=OPENAI_COMPAT_API_KEY --activate' % command,
        '用法2：%s {"name":"demo","chat_completions_url":"https://api.example.com/v1/chat/completions","model":"your-model","api_key_env":"OPENAI_COMPAT_API_KEY","activate":true}' % command
    ])


def _guess_image_media_type(path):
    lower = (path or '').lower()
    if lower.endswith('.png'):
        return 'image/png'
    if lower.endswith('.gif'):
        return 'image/gif'
    if lower.endswith('.webp'):
        return 'image/webp'
    return 'image/jpeg'


def _short(text, limit):
    if text is None:
        return ''
    if len(text) <= limit:
        return text
    return text[:limit] + '...'
