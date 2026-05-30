"""Download generated images for sending through Wechat."""

import os
import re
import uuid
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bot_core.config.manager import get_ai_api_key
from bot_core.media.cleanup import DirectoryCleaner


_IMAGE_URL_RE = re.compile(r'https?://[^\s\)\]\}"\']+/v1/files/image\?id=[^\s\)\]\}"\']+')
_CONTENT_TYPE_EXTENSIONS = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
}


class ImageDownloader(object):
    """Finds AI image URLs and saves them as local files."""

    def __init__(self, config_provider, output_dir):
        self._config_provider = config_provider
        self._output_dir = output_dir
        config = config_provider()
        reply_config = config.get('reply', {}) if config else {}
        self._cleaner = DirectoryCleaner(
            output_dir,
            reply_config.get('generated_image_max_age_seconds', 86400),
            reply_config.get('generated_image_max_files', 200),
            reply_config.get('generated_image_cleanup_interval_seconds', 3600),
        )

    def find_image_url(self, text):
        if not text:
            return ''
        match = _IMAGE_URL_RE.search(text)
        if match:
            return match.group(0)
        return ''

    def download(self, image_url):
        if not os.path.exists(self._output_dir):
            os.makedirs(self._output_dir)
        self.cleanup_if_needed()
        config = self._config_provider()
        req = Request(image_url)
        api_key = get_ai_api_key(config)
        if api_key:
            req.add_header('Authorization', 'Bearer %s' % api_key)
        with urlopen(req, timeout=120) as resp:
            content_type = (resp.headers.get('content-type') or '').split(';')[0].strip().lower()
            data = resp.read()
        ext = _CONTENT_TYPE_EXTENSIONS.get(content_type) or _extension_from_url(image_url) or '.jpg'
        file_name = 'ai_image_%s%s' % (uuid.uuid4().hex, ext)
        file_path = os.path.join(self._output_dir, file_name)
        with open(file_path, 'wb') as f:
            f.write(data)
        return file_path

    def cleanup_if_needed(self):
        self._cleaner.cleanup_if_needed()

    def cleanup(self):
        self._cleaner.cleanup()


def _extension_from_url(url):
    path = urlparse(url).path.lower()
    for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        if path.endswith(ext):
            return '.jpg' if ext == '.jpeg' else ext
    return ''