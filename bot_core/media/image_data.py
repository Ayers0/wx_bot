"""Local image helpers for OpenAI-compatible vision messages."""

import base64
import os


_EXTENSION_TO_MIME = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
}


def image_file_to_data_url(file_path, media_type=None):
    """Converts a local image file to a data URL for vision-capable models."""
    mime = _normalize_mime(file_path, media_type)
    with open(file_path, 'rb') as f:
        encoded = base64.b64encode(f.read()).decode('ascii')
    return 'data:%s;base64,%s' % (mime, encoded)


def is_image_media_type(media_type):
    return bool(media_type and media_type.startswith('image/'))


def _guess_mime(file_path):
    mime = _guess_mime_from_header(file_path)
    if mime:
        return mime
    _root, ext = os.path.splitext(file_path.lower())
    return _EXTENSION_TO_MIME.get(ext, 'image/jpeg')


def _normalize_mime(file_path, media_type):
    if media_type and media_type != 'image/*':
        return media_type
    return _guess_mime(file_path)


def _guess_mime_from_header(file_path):
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)
    except Exception:
        return ''
    if header.startswith(b'\xff\xd8'):
        return 'image/jpeg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image/webp'
    if header.startswith(b'BM'):
        return 'image/bmp'
    return ''
