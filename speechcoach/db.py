import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from .utils_text import now_iso

DDL = """
CREATE TABLE IF NOT EXISTS children(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  age INTEGER,
  sex TEXT,
  grade TEXT,
  avatar_path TEXT,
  avatar_blob BLOB,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT,
  child_id INTEGER,
  story_id TEXT,
  story_title TEXT,
  goal TEXT,
  sentence_index INTEGER,
  expected_text TEXT,
  recognized_text TEXT,
  wer REAL,
  audio_path TEXT,
  duration_sec REAL,
  phoneme_target TEXT,
  spectral_centroid_hz REAL,
  phoneme_quality REAL,

  features_json TEXT,
  acoustic_score REAL,
  acoustic_contrast REAL,
  final_score REAL,
  phoneme_confidence REAL,
  focus_start_sec REAL,
  focus_end_sec REAL,

  FOREIGN KEY(child_id) REFERENCES children(id)
);

CREATE TABLE IF NOT EXISTS reference_profiles(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  child_id INTEGER,
  phoneme TEXT,
  label TEXT,
  features_json TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reference_profiles_child_phoneme
ON reference_profiles(child_id, phoneme);

CREATE INDEX IF NOT EXISTS idx_sessions_child_created
ON sessions(child_id, created_at);
"""

def _column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def migrate_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(DDL)

    add_cols = [
        # Children schema upgrades (older DBs might miss these)
        ("children", "avatar_path", "TEXT"),
        ("children", "avatar_blob", "BLOB"),
        ("children", "created_at", "TEXT"),
        ("sessions", "features_json", "TEXT"),
        ("sessions", "acoustic_score", "REAL"),
        ("sessions", "acoustic_contrast", "REAL"),
        ("sessions", "final_score", "REAL"),
        ("sessions", "phoneme_confidence", "REAL"),
        ("sessions", "focus_start_sec", "REAL"),
        ("sessions", "focus_end_sec", "REAL"),
    ]
    for table, col, typ in add_cols:
        if not _column_exists(cur, table, col):
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    conn.commit()

    # Best-effort backfill: if avatar_blob is empty but avatar_path points to an existing file,
    # store the binary in DB to avoid runtime dependency on filesystem paths.
    try:
        if _column_exists(cur, "children", "avatar_blob") and _column_exists(cur, "children", "avatar_path"):
            cur.execute("SELECT id, avatar_path, avatar_blob FROM children")
            rows = cur.fetchall()
            for r in rows:
                try:
                    if r[2] is not None:
                        continue
                    p = (r[1] or "").strip()
                    if not p or not os.path.exists(p):
                        continue
                    with open(p, "rb") as f:
                        blob = f.read()
                    if blob:
                        cur.execute("UPDATE children SET avatar_blob=? WHERE id=?", (sqlite3.Binary(blob), r[0]))
                except Exception:
                    continue
            conn.commit()
    except Exception:
        # Never fail migration because of avatar backfill
        pass

class DataLayer:
    """Repository SQLite (thread-safe)."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        migrate_db(self.conn)
    def get_audio_path_by_session_id(self, session_id: int) -> str | None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT audio_path FROM sessions WHERE id = ?",
                (session_id,)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # --- children
    def list_children(self):
        with self.lock:
            cur = self.conn.cursor()
            # Older DBs may not have created_at yet; be defensive.
            if _column_exists(cur, "children", "created_at"):
                cur.execute("SELECT * FROM children ORDER BY created_at DESC")
            else:
                cur.execute("SELECT * FROM children ORDER BY id DESC")
            return cur.fetchall()

    def add_child(self, name: str, age: Optional[int], sex: str, grade: str, avatar_path: str) -> int:
        with self.lock:
            cur = self.conn.cursor()
            blob = None
            try:
                p = (avatar_path or "").strip()
                if p and os.path.exists(p):
                    with open(p, "rb") as f:
                        blob = f.read()
            except Exception:
                blob = None
            cur.execute(
                "INSERT INTO children(name, age, sex, grade, avatar_path, avatar_blob, created_at) VALUES(?,?,?,?,?,?,?)",
                (name, age, sex, grade, avatar_path, sqlite3.Binary(blob) if blob else None, now_iso())
            )
            self.conn.commit()
            return cur.lastrowid

    def update_child(self, child_id: int, name: str, age: Optional[int], sex: str, grade: str, avatar_path: str):
        with self.lock:
            cur = self.conn.cursor()
            blob = None
            try:
                p = (avatar_path or "").strip()
                if p and os.path.exists(p):
                    with open(p, "rb") as f:
                        blob = f.read()
            except Exception:
                blob = None
            cur.execute(
                "UPDATE children SET name=?, age=?, sex=?, grade=?, avatar_path=?, avatar_blob=? WHERE id=?",
                (name, age, sex, grade, avatar_path, sqlite3.Binary(blob) if blob else None, child_id)
            )
            self.conn.commit()

    def delete_child(self, child_id: int):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM children WHERE id=?", (child_id,))
            self.conn.commit()

    # --- sessions
    def save_session(self, s: Dict[str, Any]) -> int:
        cols = [
            "created_at","child_id","story_id","story_title","goal","sentence_index",
            "expected_text","recognized_text","wer","audio_path","duration_sec",
            "phoneme_target","spectral_centroid_hz","phoneme_quality",
            "features_json","acoustic_score","acoustic_contrast","final_score",
            "phoneme_confidence","focus_start_sec","focus_end_sec"
        ]
        values = [s.get(c) for c in cols]
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                f"INSERT INTO sessions({','.join(cols)}) VALUES({','.join(['?']*len(cols))})",
                values
            )
            self.conn.commit()
            return cur.lastrowid

    def fetch_sessions_filtered(self, child_id: Optional[int]=None, limit: int=500):
        with self.lock:
            cur = self.conn.cursor()
            order = "ORDER BY datetime(REPLACE(created_at,'T',' ')) DESC, id DESC"
            if child_id:
                cur.execute(
                    f"SELECT * FROM sessions WHERE child_id=? {order} LIMIT ?",
                    (child_id, limit)
                )
            else:
                cur.execute(f"SELECT * FROM sessions {order} LIMIT ?", (limit,))
            return cur.fetchall()


    def delete_sessions_by_ids(self, ids: List[int]):
        if not ids:
            return
        with self.lock:
            cur = self.conn.cursor()
            cur.executemany("DELETE FROM sessions WHERE id=?", [(i,) for i in ids])
            self.conn.commit()

    # --- reference profiles
    def save_reference_profile(self, child_id: Optional[int], phoneme: str, label: str, features: Dict[str, Any]):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO reference_profiles(child_id, phoneme, label, features_json, created_at) VALUES(?,?,?,?,?)",
                (child_id, phoneme, label, json.dumps(features, ensure_ascii=False), now_iso())
            )
            self.conn.commit()

    def load_reference_profile(self, child_id: Optional[int], phoneme: str, label: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            cur = self.conn.cursor()
            if child_id is None:
                cur.execute(
                    "SELECT * FROM reference_profiles WHERE child_id IS NULL AND phoneme=? AND label=? ORDER BY created_at DESC LIMIT 1",
                    (phoneme, label)
                )
            else:
                cur.execute(
                    "SELECT * FROM reference_profiles WHERE child_id=? AND phoneme=? AND label=? ORDER BY created_at DESC LIMIT 1",
                    (child_id, phoneme, label)
                )
            row = cur.fetchone()
            if not row:
                return None
            try:
                return json.loads(row["features_json"])
            except Exception:
                return None
