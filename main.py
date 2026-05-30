"""Single entry point for the Wechat AI memory bot."""

import argparse
import logging
import os
import sys

from bot_core.ai.client import AiClient
from bot_core.config.manager import ConfigManager, resolve_path
from bot_core.media.cleanup import DirectoryCleaner
from bot_core.media.image_downloader import ImageDownloader
from bot_core.memory.store import MemoryStore
from bot_core.session.manager import SessionManager
from bot_core.wechat.bot import WechatAiBot


def main():
    """Starts the long-running bot process."""
    parser = argparse.ArgumentParser(description='Wechat AI Memory Bot')
    parser.add_argument('--config', default='config.json', help='config file path')
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    config_manager = ConfigManager(config_path)
    config = config_manager.load()
    _setup_logging(config, os.path.dirname(config_path))
    _setup_sdk_path(config, os.path.dirname(config_path))
    config_manager.start_hot_reload()

    memory_path = resolve_path(os.path.dirname(config_path), config.get('memory', {}).get('database_path'))
    memory_store = MemoryStore(memory_path)
    ai_client = AiClient(config_manager.get)
    session_manager = SessionManager(config_manager.get, memory_store)
    generated_image_dir = resolve_path(os.path.dirname(config_path), config.get('reply', {}).get('generated_image_dir'))
    image_downloader = ImageDownloader(config_manager.get, generated_image_dir)
    media_dir = resolve_path(os.path.dirname(config_path), config.get('wechat', {}).get('media_dir'))
    received_media_cleaner = DirectoryCleaner(
        media_dir,
        config.get('wechat', {}).get('media_max_age_seconds', 86400),
        config.get('wechat', {}).get('media_max_files', 500),
        config.get('wechat', {}).get('media_cleanup_interval_seconds', 3600),
    )
    bot = WechatAiBot(config_manager.get, ai_client, session_manager, image_downloader, received_media_cleaner, config_manager)

    try:
        bot.start()
    except KeyboardInterrupt:
        logging.info('Stopping bot by keyboard interrupt')
    finally:
        bot.stop()
        memory_store.close()
        config_manager.stop()
    return 0


def _setup_sdk_path(config, base_dir):
    sdk_path = config.get('wechat', {}).get('sdk_path')
    if not sdk_path:
        return
    sdk_path = resolve_path(base_dir, sdk_path)
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)


def _setup_logging(config, base_dir):
    log_config = config.get('logging', {})
    level_name = (log_config.get('level') or 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = log_config.get('file')
    handlers = [logging.StreamHandler()]
    if log_file:
        log_path = resolve_path(base_dir, log_file)
        log_dir = os.path.dirname(log_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        handlers.append(logging.FileHandler(log_path, encoding='utf-8'))
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=handlers,
    )


if __name__ == '__main__':
    sys.exit(main())
