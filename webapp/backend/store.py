"""Where accounts and search records live: MongoDB when MONGODB_URI is set, else local.

Render's free disk is wiped on every restart, so the deployed backend keeps users and
search records in MongoDB (Atlas free tier). Locally and in tests, users stay in the
SQLite file and search records in memory, exactly as before.

    users      {email, name, salt, hash}            email unique, lower-case
    searches   {job_id, user, created, status, ...} one per search, for quotas and polling
"""
import os
import sqlite3
import threading
from pathlib import Path


class DuplicateUser(Exception):
    pass


class SqliteUsers:
    def __init__(self, path):
        self.path = Path(path)

    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE IF NOT EXISTS users (email TEXT PRIMARY KEY, name TEXT, salt BLOB, hash BLOB)")
        return db

    def get(self, email):
        with self._db() as db:
            row = db.execute("SELECT email, name, salt, hash FROM users WHERE email = ?", (email,)).fetchone()
        return dict(zip(("email", "name", "salt", "hash"), row)) if row else None

    def add(self, email, name, salt, hash_):
        try:
            with self._db() as db:
                db.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (email, name, salt, hash_))
        except sqlite3.IntegrityError:
            raise DuplicateUser(email)


class MongoUsers:
    def __init__(self, db):
        self.c = db["users"]
        self.c.create_index("email", unique=True)

    def get(self, email):
        d = self.c.find_one({"email": email}, {"_id": 0})
        return d and {**d, "salt": bytes(d["salt"]), "hash": bytes(d["hash"])}

    def add(self, email, name, salt, hash_):
        from pymongo.errors import DuplicateKeyError
        try:
            self.c.insert_one({"email": email, "name": name, "salt": salt, "hash": hash_})
        except DuplicateKeyError:
            raise DuplicateUser(email)


class MemorySearches:
    """Search records in memory (the single-container Modal app and tests)."""

    def __init__(self, keep=500):
        self.rows, self.keep, self.lock = {}, keep, threading.Lock()

    def add(self, row):
        with self.lock:
            self.rows[row["job_id"]] = dict(row)
            for old in sorted(self.rows, key=lambda k: self.rows[k]["created"])[:-self.keep]:
                del self.rows[old]

    def get(self, job_id):
        with self.lock:
            r = self.rows.get(job_id)
            return dict(r) if r else None

    def update(self, job_id, **kw):
        with self.lock:
            if job_id in self.rows:
                self.rows[job_id].update(kw)

    def active(self):
        with self.lock:
            return [dict(r) for r in self.rows.values() if r["status"] in ("queued", "running")]

    def since(self, user, t):
        with self.lock:
            return [dict(r) for r in self.rows.values() if r["user"] == user and r["created"] >= t]

    def recent(self, user, limit=50):
        """The user's searches, newest first, without their (large) results."""
        with self.lock:
            rows = sorted((r for r in self.rows.values() if r["user"] == user), key=lambda r: -r["created"])
            return [{k: v for k, v in r.items() if k != "result"} for r in rows[:limit]]


class MongoSearches:
    def __init__(self, db):
        self.c = db["searches"]
        self.c.create_index("job_id", unique=True)
        self.c.create_index([("user", 1), ("created", -1)])

    def add(self, row):
        self.c.insert_one(dict(row))

    def get(self, job_id):
        return self.c.find_one({"job_id": job_id}, {"_id": 0})

    def update(self, job_id, **kw):
        self.c.update_one({"job_id": job_id}, {"$set": kw})

    def active(self):
        return list(self.c.find({"status": {"$in": ["queued", "running"]}}, {"_id": 0}))

    def since(self, user, t):
        return list(self.c.find({"user": user, "created": {"$gte": t}}, {"_id": 0, "result": 0}))

    def recent(self, user, limit=50):
        """The user's searches, newest first, without their (large) results."""
        return list(self.c.find({"user": user}, {"_id": 0, "result": 0}).sort("created", -1).limit(limit))


def _mongo_db():
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10_000)
    return client[os.getenv("MONGODB_DB", "darksts")]


def open_stores(users_db_path):
    """(users, searches) for this deployment."""
    if os.getenv("MONGODB_URI"):
        db = _mongo_db()
        return MongoUsers(db), MongoSearches(db)
    return SqliteUsers(users_db_path), MemorySearches()
