"""Directory cleanup helpers for runtime media files."""

import os
import time


class DirectoryCleaner(object):
    """Periodically removes old or excessive files from a directory."""

    def __init__(self, directory, max_age_seconds, max_files, interval_seconds):
        self._directory = directory
        self._max_age_seconds = int(max_age_seconds)
        self._max_files = int(max_files)
        self._interval_seconds = int(interval_seconds)
        self._last_cleanup_at = 0

    def cleanup_if_needed(self):
        if self._interval_seconds <= 0:
            return
        now = time.time()
        if now - self._last_cleanup_at < self._interval_seconds:
            return
        self._last_cleanup_at = now
        self.cleanup()

    def cleanup(self):
        cleanup_directory(self._directory, self._max_age_seconds, self._max_files)


def cleanup_directory(directory, max_age_seconds, max_files):
    if not directory or not os.path.exists(directory):
        return
    files = []
    now = time.time()
    for root, _dirs, names in os.walk(directory):
        for name in names:
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                continue
            files.append((path, mtime))
            if max_age_seconds > 0 and now - mtime > max_age_seconds:
                _safe_remove(path)
    if max_files <= 0:
        return
    remaining = []
    for path, mtime in files:
        if os.path.exists(path):
            remaining.append((path, mtime))
    remaining.sort(key=lambda item: item[1], reverse=True)
    for path, _mtime in remaining[max_files:]:
        _safe_remove(path)


def _safe_remove(path):
    try:
        os.remove(path)
    except Exception:
        pass
