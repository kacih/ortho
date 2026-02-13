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

-- Rewards / collections (one row per card owned)
CREATE TABLE IF NOT EXISTS child_cards(
  child_id INTEGER NOT NULL,
  card_name TEXT NOT NULL,
  obtained_at TEXT,
  PRIMARY KEY(child_id, card_name),
  FOREIGN KEY(child_id) REFERENCES children(id)
);

CREATE INDEX IF NOT EXISTS idx_child_cards_child
ON child_cards(child_id);

-- Rewards v2 (catalog + progress) ------------------------------------------
CREATE TABLE IF NOT EXISTS cards_catalog(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  icon_path TEXT,
  rarity TEXT,
  min_level INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS child_progress(
  child_id INTEGER PRIMARY KEY,
  xp INTEGER DEFAULT 0,
  level INTEGER DEFAULT 1,
  total_sessions INTEGER DEFAULT 0,
  last_play_date TEXT,
  streak INTEGER DEFAULT 0,
  FOREIGN KEY(child_id) REFERENCES children(id)
);

CREATE TABLE IF NOT EXISTS child_cards_v2(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  child_id INTEGER NOT NULL,
  card_id TEXT NOT NULL,
  obtained_at TEXT,
  UNIQUE(child_id, card_id),
  FOREIGN KEY(child_id) REFERENCES children(id),
  FOREIGN KEY(card_id) REFERENCES cards_catalog(id)
);

CREATE INDEX IF NOT EXISTS idx_child_cards_v2_child
ON child_cards_v2(child_id);

"""

def _column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def migrate_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(DDL)

    # ---- Seed cards_catalog if empty (best-effort)
    try:
        cur.execute("SELECT COUNT(*) FROM cards_catalog")
        n = int(cur.fetchone()[0] or 0)
        if n == 0:
            # load local catalog.json if present
            try:
                from pathlib import Path
                import json as _json
                from .config import RESOURCES_DIR
                cat_path = Path(RESOURCES_DIR) / "cards" / "catalog.json"
                if cat_path.exists():
                    data = _json.loads(cat_path.read_text(encoding="utf-8"))
                    for r in data:
                        cur.execute(
                            "INSERT OR IGNORE INTO cards_catalog(id,name,icon_path,rarity,min_level) VALUES(?,?,?,?,?)",
                            (str(r.get("id")), str(r.get("name")), str(r.get("icon")), str(r.get("rarity","common")), int(r.get("min_level",1)))
                        )
                    conn.commit()
            except Exception:
                pass
    except Exception:
        pass

    # ---- Migrate old child_cards (v1 names) into v2 when possible
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='child_cards'")
        if cur.fetchone():
            cur.execute("SELECT child_id, card_name, obtained_at FROM child_cards")
            rows = cur.fetchall()
            # map name->id from catalog
            cur.execute("SELECT id, name FROM cards_catalog")
            name_map = {r[1]: r[0] for r in cur.fetchall()}
            for r in rows:
                cid = int(r[0])
                nm = str(r[1])
                dt = r[2]
                card_id = name_map.get(nm)
                if not card_id:
                    # create a minimal catalog entry for unknown names
                    card_id = nm.lower().replace(" ", "_")
                    cur.execute(
                        "INSERT OR IGNORE INTO cards_catalog(id,name,icon_path,rarity,min_level) VALUES(?,?,?,?,?)",
                        (card_id, nm, "", "common", 1)
                    )
                cur.execute(
                    "INSERT OR IGNORE INTO child_cards_v2(child_id, card_id, obtained_at) VALUES(?,?,?)",
                    (cid, card_id, dt or now_iso())
                )
            conn.commit()
    except Exception:
        pass

    add_cols = [
        # Children schema upgrades (older DBs might miss these)
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

    def get_child(self, child_id: int):
        """Return a child row as a dict-like sqlite3.Row, or None."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM children WHERE id=?", (child_id,))
            return cur.fetchone()

    # --- rewards / collections
    def list_child_cards(self, child_id: int) -> List[str]:
        """Return all collected card names for a child."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT card_name FROM child_cards WHERE child_id=? ORDER BY datetime(REPLACE(obtained_at,'T',' ')) DESC",
                (int(child_id),)
            )
            return [r[0] for r in cur.fetchall()]

    def add_child_card(self, child_id: int, card_name: str) -> bool:
        """Insert a card if not already owned. Returns True if inserted."""
        if not card_name:
            return False
        with self.lock:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO child_cards(child_id, card_name, obtained_at) VALUES(?,?,?)",
                    (int(child_id), str(card_name).strip(), now_iso())
                )
                self.conn.commit()
                return cur.rowcount > 0
            except Exception:
                return False




    # --- rewards / collections v2
    def ensure_child_progress(self, child_id: int) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR IGNORE INTO child_progress(child_id) VALUES(?)", (int(child_id),))
            self.conn.commit()

    def get_child_progress(self, child_id: int) -> Optional[sqlite3.Row]:
        self.ensure_child_progress(child_id)
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM child_progress WHERE child_id=?", (int(child_id),))
            return cur.fetchone()

    def list_child_cards_v2(self, child_id: int) -> List[sqlite3.Row]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT cc.id as card_id, cc.name, cc.icon_path, cc.rarity, cc.min_level, c2.obtained_at
                   FROM child_cards_v2 c2
                   JOIN cards_catalog cc ON cc.id = c2.card_id
                   WHERE c2.child_id=?
                   ORDER BY datetime(REPLACE(c2.obtained_at,'T',' ')) DESC""",
                (int(child_id),)
            )
            return cur.fetchall()

    def list_owned_card_ids(self, child_id: int) -> List[str]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT card_id FROM child_cards_v2 WHERE child_id=?", (int(child_id),))
            return [r[0] for r in cur.fetchall()]

    def add_child_card_v2(self, child_id: int, card_id: str) -> bool:
        if not card_id:
            return False
        with self.lock:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO child_cards_v2(child_id, card_id, obtained_at) VALUES(?,?,?)",
                    (int(child_id), str(card_id).strip(), now_iso())
                )
                self.conn.commit()
                return cur.rowcount > 0
            except Exception:
                return False

    def get_card_catalog(self) -> List[sqlite3.Row]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM cards_catalog ORDER BY min_level ASC, rarity ASC, name ASC")
            return cur.fetchall()

    def upsert_progress_after_session(self, child_id: int, final_score: float) -> sqlite3.Row:
        """Update XP/level/streak after a session. Returns updated progress row."""
        from datetime import date
        from .rewards import compute_xp_gain, level_from_xp

        self.ensure_child_progress(child_id)
        today = date.today().isoformat()

        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM child_progress WHERE child_id=?", (int(child_id),))
            p = cur.fetchone()
            last_play = (p["last_play_date"] if p and "last_play_date" in p.keys() else None)

            used_today = (last_play == today)
            gain = compute_xp_gain(final_score=final_score, used_today=used_today)

            xp = int(p["xp"] or 0) + int(gain)
            lvl = int(level_from_xp(xp))
            total = int(p["total_sessions"] or 0) + (0 if used_today else 1)

            # streak: increments only once per day
            streak = int(p["streak"] or 0)
            if not used_today:
                # naive streak: if last_play was yesterday -> +1 else reset to 1
                try:
                    from datetime import datetime, timedelta
                    if last_play:
                        d0 = datetime.fromisoformat(last_play).date()
                        if d0 == (date.today() - timedelta(days=1)):
                            streak += 1
                        else:
                            streak = 1
                    else:
                        streak = 1
                except Exception:
                    streak = 1

            cur.execute(
                """UPDATE child_progress SET xp=?, level=?, total_sessions=?, last_play_date=?, streak=? WHERE child_id=?""",
                (xp, lvl, total, today, streak, int(child_id))
            )
            self.conn.commit()
            cur.execute("SELECT * FROM child_progress WHERE child_id=?", (int(child_id),))
            return cur.fetchone()

    def get_score_series(self, child_id: int, phoneme: str) -> List[tuple]:
        """Return list of (created_at, final_score) for an enfant + phonème."""
        ph = (phoneme or "").strip()
        with self.lock:
            cur = self.conn.cursor()
            if not ph or ph.lower() == "tous":
                cur.execute(
                    """SELECT created_at, final_score FROM sessions
                         WHERE child_id=? AND final_score IS NOT NULL
                         ORDER BY datetime(REPLACE(created_at,'T',' ')) ASC""",
                    (int(child_id),)
                )
            else:
                cur.execute(
                    """SELECT created_at, final_score FROM sessions
                         WHERE child_id=? AND phoneme_target=? AND final_score IS NOT NULL
                         ORDER BY datetime(REPLACE(created_at,'T',' ')) ASC""",
                    (int(child_id), ph)
                )
            return [(r[0], float(r[1])) for r in cur.fetchall() if r[0] and r[1] is not None]

    def list_distinct_phonemes(self, child_id: Optional[int]=None, limit: int=50) -> List[str]:
        """Return distinct phoneme_target values (empty/NULL excluded), optionally filtered by child."""
        with self.lock:
            cur = self.conn.cursor()
            if child_id:
                cur.execute(
                    "SELECT DISTINCT COALESCE(phoneme_target,'') AS p FROM sessions WHERE child_id=? ORDER BY p LIMIT ?",
                    (child_id, limit)
                )
            else:
                cur.execute(
                    "SELECT DISTINCT COALESCE(phoneme_target,'') AS p FROM sessions ORDER BY p LIMIT ?",
                    (limit,)
                )
            return [r[0] for r in cur.fetchall() if r[0] is not None]


    def add_child(self, name: str, age: Optional[int], sex: str, grade: str, avatar_bytes: Optional[bytes]=None) -> int:
        """Create a child profile.

        7.8+: avatars are stored as BLOB in DB.
        7.9: avatar_path is deprecated (kept only for legacy DBs).
        """
        with self.lock:
            cur = self.conn.cursor()
            blob = None
            try:
                if avatar_bytes:
                    blob = bytes(avatar_bytes)
            except Exception:
                blob = None
            cur.execute(
                "INSERT INTO children(name, age, sex, grade, avatar_blob, created_at) VALUES(?,?,?,?,?,?)",
                (name, age, sex, grade, sqlite3.Binary(blob) if blob else None, now_iso())
            )
            self.conn.commit()
            return cur.lastrowid

    def update_child(self, child_id: int, name: str, age: Optional[int], sex: str, grade: str, avatar_bytes: Optional[bytes]=None):
        """Update a child profile. Avatar stored as BLOB."""
        with self.lock:
            cur = self.conn.cursor()
            blob = None
            try:
                if avatar_bytes:
                    blob = bytes(avatar_bytes)
            except Exception:
                blob = None
            cur.execute(
                "UPDATE children SET name=?, age=?, sex=?, grade=?, avatar_blob=? WHERE id=?",
                (name, age, sex, grade, sqlite3.Binary(blob) if blob else None, child_id)
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

    def fetch_sessions_filtered(self, child_id: Optional[int]=None, phoneme_target: Optional[str]=None, limit: int=500):
        with self.lock:
            cur = self.conn.cursor()
            order = "ORDER BY datetime(REPLACE(created_at,'T',' ')) DESC, id DESC"

            clauses = []
            params = []
            if child_id:
                clauses.append("child_id=?")
                params.append(child_id)
            if phoneme_target and phoneme_target != "__ALL__":
                clauses.append("COALESCE(phoneme_target,'')=?")
                params.append(phoneme_target)

            where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
            params.append(limit)
            cur.execute(f"SELECT * FROM sessions {where}{order} LIMIT ?", tuple(params))
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
