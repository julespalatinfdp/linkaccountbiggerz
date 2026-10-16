import re
import sqlite3
from pathlib import Path


def normalize_email(value):
    value = value.strip()
    if len(value) > 254 or not value.isascii() or value.count('@') != 1:
        raise ValueError('Adresse e-mail invalide.')
    local, domain = value.rsplit('@', 1)
    if (len(local) > 64 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or local.startswith('.') or local.endswith('.') or '..' in local):
        raise ValueError('Adresse e-mail invalide.')
    labels = domain.split('.')
    if len(labels) < 2 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in labels):
        raise ValueError('Adresse e-mail invalide.')
    return local + '@' + domain.lower()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('''CREATE TABLE IF NOT EXISTS links (
            guild_id TEXT NOT NULL, user_id TEXT NOT NULL, email TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, user_id))''')
        self.db.commit()

    def save(self, guild_id, user_id, email):
        email = normalize_email(email)
        with self.db:
            self.db.execute('''INSERT INTO links (guild_id,user_id,email) VALUES (?,?,?)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET email=excluded.email,
                updated_at=CURRENT_TIMESTAMP''', (str(guild_id), str(user_id), email))
        return email

    def get(self, guild_id, user_id):
        return self.db.execute('SELECT email, updated_at FROM links WHERE guild_id=? AND user_id=?',
                               (str(guild_id), str(user_id))).fetchone()

    def delete(self, guild_id, user_id):
        with self.db:
            self.db.execute('DELETE FROM links WHERE guild_id=? AND user_id=?',
                            (str(guild_id), str(user_id)))

    def close(self):
        self.db.close()
