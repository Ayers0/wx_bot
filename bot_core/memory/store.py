"""SQLite-backed conversation memory store."""

import os
import sqlite3
from datetime import datetime


class MemoryStore(object):
    """Persists conversation messages by session id."""

    def __init__(self, database_path):
        self.database_path = database_path
        directory = os.path.dirname(os.path.abspath(database_path))
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        self._conn = sqlite3.connect(database_path, check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._init_schema()

    def add_message(self, session_id, role, content, message_id=None):
        if not content:
            return
        self._conn.execute(
            'INSERT INTO messages(session_id, role, content, message_id, created_at) VALUES (?, ?, ?, ?, ?)',
            (session_id, role, content, message_id, datetime.utcnow().isoformat())
        )
        self._conn.commit()

    def get_recent_messages(self, session_id, limit):
        cursor = self._conn.execute(
            'SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?',
            (session_id, int(limit))
        )
        rows = cursor.fetchall()
        rows.reverse()
        return [{'role': row[0], 'content': row[1]} for row in rows]

    def get_message_count(self, session_id):
        cursor = self._conn.execute('SELECT COUNT(*) FROM messages WHERE session_id = ?', (session_id,))
        row = cursor.fetchone()
        return int(row[0] or 0)

    def get_old_messages_for_summary(self, session_id, keep_recent):
        cursor = self._conn.execute(
            '''
            SELECT id, role, content, created_at FROM messages
            WHERE session_id = ?
              AND id NOT IN (
                SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
              )
            ORDER BY id ASC
            ''',
            (session_id, session_id, int(keep_recent))
        )
        return [
            {'id': row[0], 'role': row[1], 'content': row[2], 'created_at': row[3]}
            for row in cursor.fetchall()
        ]

    def get_session_summary(self, session_id):
        cursor = self._conn.execute(
            'SELECT summary, summarized_until_message_id, updated_at FROM session_summaries WHERE session_id = ?',
            (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {'summary': row[0], 'summarized_until_message_id': row[1], 'updated_at': row[2]}

    def upsert_session_summary(self, session_id, summary, summarized_until_message_id):
        self._conn.execute(
            '''
            INSERT INTO session_summaries(session_id, summary, summarized_until_message_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              summary = excluded.summary,
              summarized_until_message_id = excluded.summarized_until_message_id,
              updated_at = excluded.updated_at
            ''',
            (session_id, summary, summarized_until_message_id, datetime.utcnow().isoformat())
        )
        self._conn.commit()

    def compact_session_messages(self, session_id, keep_recent):
        self._conn.execute(
            '''
            DELETE FROM messages
            WHERE session_id = ?
              AND id NOT IN (
                SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
              )
            ''',
            (session_id, session_id, int(keep_recent))
        )
        self._conn.commit()

    def backup_database(self, backup_path):
        directory = os.path.dirname(os.path.abspath(backup_path))
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        backup_conn = sqlite3.connect(backup_path)
        try:
            self._conn.backup(backup_conn)
        finally:
            backup_conn.close()

    def add_image(self, session_id, source, media_path, media_type=None, message_id=None):
        if not session_id or not media_path:
            return
        self._conn.execute(
            'INSERT INTO images(session_id, source, media_path, media_type, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (session_id, source or '', media_path, media_type or '', message_id, datetime.utcnow().isoformat())
        )
        self._conn.commit()

    def get_recent_images(self, session_id, limit, max_age_seconds=None, include_sources=None):
        params = [session_id]
        where = ['session_id = ?']
        if include_sources:
            placeholders = ','.join(['?'] * len(include_sources))
            where.append('source IN (%s)' % placeholders)
            params.extend(include_sources)
        if max_age_seconds:
            try:
                cutoff_ts = datetime.utcnow().timestamp() - float(max_age_seconds)
                cutoff = datetime.utcfromtimestamp(cutoff_ts).isoformat()
                where.append('created_at >= ?')
                params.append(cutoff)
            except Exception:
                pass
        params.append(int(limit))
        cursor = self._conn.execute(
            'SELECT source, media_path, media_type, message_id, created_at FROM images WHERE %s ORDER BY id DESC LIMIT ?' % ' AND '.join(where),
            tuple(params)
        )
        rows = cursor.fetchall()
        rows.reverse()
        return [
            {
                'source': row[0],
                'media_path': row[1],
                'media_type': row[2],
                'message_id': row[3],
                'created_at': row[4],
            }
            for row in rows
        ]

    def clear_session(self, session_id):
        self._conn.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
        self._conn.execute('DELETE FROM images WHERE session_id = ?', (session_id,))
        self._conn.execute('DELETE FROM session_summaries WHERE session_id = ?', (session_id,))
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def _init_schema(self):
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                message_id TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        self._conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
            ON messages(session_id, id)
        ''')
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                source TEXT NOT NULL,
                media_path TEXT NOT NULL,
                media_type TEXT,
                message_id TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        self._conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_images_session_id_id
            ON images(session_id, id)
        ''')
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                summarized_until_message_id INTEGER,
                updated_at TEXT NOT NULL
            )
        ''')

        self._conn.commit()
