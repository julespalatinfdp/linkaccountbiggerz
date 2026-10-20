import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path, environment):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA secure_delete=ON')
        # New tables preserve the legacy email table without trusting its records.
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS api_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS verified_links (
          discord_id TEXT PRIMARY KEY, biggerz_user_id TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS pending_links (
          discord_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, expires_at TEXT NOT NULL);
        ''')
        row = self.db.execute("SELECT value FROM api_meta WHERE key='environment'").fetchone()
        if row and row[0] != environment:
            raise RuntimeError('Use a separate DATABASE_PATH for each BiggerZ environment.')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO api_meta VALUES ('environment', ?)", (environment,))

    def pending(self):
        return self.db.execute('SELECT discord_id, request_id, expires_at FROM pending_links').fetchall()

    def put_pending(self, discord_id, request_id, expires_at):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO pending_links VALUES (?,?,?)', (discord_id, request_id, expires_at))

    def end_pending(self, discord_id, request_id):
        with self.db:
            self.db.execute('DELETE FROM pending_links WHERE discord_id=? AND request_id=?', (discord_id, request_id))

    def cursor(self):
        row = self.db.execute("SELECT value FROM api_meta WHERE key='cursor'").fetchone()
        return row[0] if row else None

    def apply_page(self, page):
        # Apply the whole page and advance its cursor in the same transaction.
        with self.db:
            for event in page['events']:
                kind = event.get('type')
                if kind not in ('link.created', 'link.removed'):
                    continue
                discord_id, biggerz_id = event['discord_id'], event['biggerz_user_id']
                if not isinstance(discord_id, str) or not isinstance(biggerz_id, str):
                    raise ValueError('Invalid event IDs')
                if kind == 'link.created':
                    self.db.execute('DELETE FROM verified_links WHERE discord_id=? OR biggerz_user_id=?', (discord_id, biggerz_id))
                    self.db.execute('INSERT INTO verified_links VALUES (?,?)', (discord_id, biggerz_id))
                else:
                    self.db.execute('DELETE FROM verified_links WHERE discord_id=? AND biggerz_user_id=?', (discord_id, biggerz_id))
            if page.get('next_cursor'):
                self.db.execute("INSERT OR REPLACE INTO api_meta VALUES ('cursor',?)", (page['next_cursor'],))

    def close(self):
        self.db.close()
