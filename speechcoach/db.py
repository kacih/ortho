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

  -- Sprint 1: session plan metadata
  plan_id TEXT,
  plan_name TEXT,
  plan_mode TEXT,
  plan_json TEXT,

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
  card_name TEXT,
  rarity TEXT,
  icon_blob BLOB,
  obtained_at TEXT,
  UNIQUE(child_id, card_id),
  FOREIGN KEY(child_id) REFERENCES children(id)
);

CREATE INDEX IF NOT EXISTS idx_child_cards_v2_child
ON child_cards_v2(child_id);


-- Sprint 2: user session plans (presets) ------------------------------------
CREATE TABLE IF NOT EXISTS session_plans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_plans_name ON session_plans(name);

-- Sprint 2: session run summary (session-level metadata) --------------------
CREATE TABLE IF NOT EXISTS session_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  child_id INTEGER NOT NULL,
  plan_json TEXT NOT NULL,
  planned_items INTEGER,
  completed_items INTEGER,
  ended_early INTEGER DEFAULT 0,
  early_end_reason TEXT DEFAULT '',
  FOREIGN KEY(child_id) REFERENCES children(id)
);
CREATE INDEX IF NOT EXISTS idx_session_runs_child_created
ON session_runs(child_id, created_at);
"""

def _column_exists(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def migrate_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(DDL)

    


    # ---- Ensure sessions plan columns exist (Sprint 1)
    try:
        if not _column_exists(cur, "sessions", "plan_id"):
            cur.execute("ALTER TABLE sessions ADD COLUMN plan_id TEXT")
        if not _column_exists(cur, "sessions", "plan_name"):
            cur.execute("ALTER TABLE sessions ADD COLUMN plan_name TEXT")
        if not _column_exists(cur, "sessions", "plan_mode"):
            cur.execute("ALTER TABLE sessions ADD COLUMN plan_mode TEXT")
        if not _column_exists(cur, "sessions", "plan_json"):
            cur.execute("ALTER TABLE sessions ADD COLUMN plan_json TEXT")
    except Exception:
        pass

    # ---- Ensure child_cards_v2 snapshot columns exist (tolerant migrations)
    try:
        if not _column_exists(cur, "child_cards_v2", "card_name"):
            cur.execute("ALTER TABLE child_cards_v2 ADD COLUMN card_name TEXT")
        if not _column_exists(cur, "child_cards_v2", "rarity"):
            cur.execute("ALTER TABLE child_cards_v2 ADD COLUMN rarity TEXT")
        if not _column_exists(cur, "child_cards_v2", "icon_blob"):
            cur.execute("ALTER TABLE child_cards_v2 ADD COLUMN icon_blob BLOB")
    except Exception:
        pass

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
        # Re-entrant lock: some public methods call other methods that also
        # take the DB lock (e.g. get_child_session_summary -> get_child_progress
        # -> ensure_child_progress). A plain Lock would deadlock.
        self.lock = threading.RLock()
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
                """SELECT card_id, card_name, icon_blob, rarity, obtained_at
                   FROM child_cards_v2
                   WHERE child_id=?
                   ORDER BY datetime(REPLACE(obtained_at,'T',' ')) DESC""",
                (int(child_id),)
            )
            return cur.fetchall()

    def list_owned_card_ids(self, child_id: int) -> List[str]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT card_id FROM child_cards_v2 WHERE child_id=?", (int(child_id),))
            return [r[0] for r in cur.fetchall()]

    def add_child_card_v2(self, child_id: int, card) -> bool:
        card_id = getattr(card, 'id', None) or (card.get('id') if isinstance(card, dict) else None)
        if not card_id:
            return False
        card_name = getattr(card, 'name', None) or (card.get('name') if isinstance(card, dict) else None)
        rarity = getattr(card, 'rarity', None) or (card.get('rarity') if isinstance(card, dict) else None)
        icon_blob = getattr(card, 'icon_bytes', None) or (card.get('icon_bytes') if isinstance(card, dict) else None) or b""
        with self.lock:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO child_cards_v2(child_id, card_id, card_name, rarity, icon_blob, obtained_at) VALUES(?,?,?,?,?,?)",
                    (int(child_id), str(card_id).strip(), card_name, rarity, sqlite3.Binary(icon_blob), now_iso())
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


    # --- Sprint 6: progress dashboard helpers ---------------------------------
    def get_child_session_summary(self, child_id: int) -> Dict[str, Any]:
        """Return a quick, human-facing summary for the progress dashboard."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT
                       COUNT(*) AS n,
                       COALESCE(SUM(duration_sec), 0.0) AS total_dur,
                       COALESCE(AVG(final_score), 0.0) AS avg_score
                   FROM sessions
                   WHERE child_id=? AND final_score IS NOT NULL""",
                (int(child_id),)
            )
            r = cur.fetchone()
            n = int(r["n"] or 0) if r else 0
            total_dur = float(r["total_dur"] or 0.0) if r else 0.0
            avg_score = float(r["avg_score"] or 0.0) if r else 0.0

            # Use child_progress for streak/level/xp (best effort)
            p = self.get_child_progress(child_id)
            out: Dict[str, Any] = {
                "total_sessions": n,
                "total_duration_sec": total_dur,
                "avg_score": avg_score,
                "xp": int(p["xp"] or 0) if p else 0,
                "level": int(p["level"] or 1) if p else 1,
                "streak": int(p["streak"] or 0) if p else 0,
                "last_play_date": (p["last_play_date"] if p else None),
            }
            return out

    def get_child_recent_scores(self, child_id: int, limit: int = 20) -> List[tuple]:
        """Return list of (created_at, final_score) for the last N sessions."""
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT created_at, final_score FROM sessions
                     WHERE child_id=? AND final_score IS NOT NULL
                     ORDER BY datetime(REPLACE(created_at,'T',' ')) DESC
                     LIMIT ?""",
                (int(child_id), int(limit)),
            )
            rows = cur.fetchall()
            # Return chronological order for plotting
            out = [(r[0], float(r[1])) for r in rows if r[0] and r[1] is not None]
            out.reverse()
            return out

    def get_phoneme_insights(self, child_id: int, min_count: int = 3) -> Dict[str, Any]:
        """Compute simple 'weakest' and 'improving' phoneme insights.

        - Weakest: lowest avg score across all time (min_count sessions)
        - Improving: compare last 10 vs previous 10 for the same phoneme
        """
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT phoneme_target AS p,
                          COUNT(*) AS n,
                          AVG(final_score) AS avg
                   FROM sessions
                   WHERE child_id=? AND final_score IS NOT NULL
                     AND COALESCE(phoneme_target,'') <> ''
                   GROUP BY phoneme_target
                   HAVING COUNT(*) >= ?
                   ORDER BY avg ASC""",
                (int(child_id), int(min_count)),
            )
            agg = [(str(r["p"]), int(r["n"]), float(r["avg"] or 0.0)) for r in cur.fetchall()]

            weakest = agg[:3]

            # Improving: per phoneme, fetch last 20 scores and compare windows
            improving: List[tuple] = []  # (p, delta, recent_avg, prev_avg, n)
            for p, n, _avg in agg:
                cur.execute(
                    """SELECT final_score FROM sessions
                         WHERE child_id=? AND phoneme_target=? AND final_score IS NOT NULL
                         ORDER BY datetime(REPLACE(created_at,'T',' ')) DESC
                         LIMIT 20""",
                    (int(child_id), p),
                )
                vals = [float(x[0]) for x in cur.fetchall() if x[0] is not None]
                if len(vals) < 10:
                    continue
                recent = vals[:10]
                prev = vals[10:20] if len(vals) >= 20 else vals[10:]
                if len(prev) < 5:
                    continue
                recent_avg = sum(recent) / len(recent)
                prev_avg = sum(prev) / len(prev)
                delta = recent_avg - prev_avg
                improving.append((p, delta, recent_avg, prev_avg, n))

            improving.sort(key=lambda x: x[1], reverse=True)
            improving = [t for t in improving if t[1] > 0.01][:3]

            return {
                "weakest": weakest,
                "improving": improving,
            }

    def export_child_sessions_csv(self, child_id: int, out_path: str, limit: int = 500) -> str:
        """Export latest sessions for a child as CSV. Returns written path."""
        import csv
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT created_at, duration_sec, final_score, phoneme_target,
                          plan_name, story_title, expected_text, recognized_text
                   FROM sessions
                   WHERE child_id=?
                   ORDER BY datetime(REPLACE(created_at,'T',' ')) DESC
                   LIMIT ?""",
                (int(child_id), int(limit)),
            )
            rows = cur.fetchall()

        # Write in chronological order
        rows = list(reversed(rows))

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([
                "date",
                "duration_sec",
                "final_score",
                "phoneme_target",
                "plan",
                "story_title",
                "expected_text",
                "recognized_text",
            ])
            for r in rows:
                w.writerow([
                    r[0] or "",
                    ("{:.2f}".format(float(r[1] or 0.0))),
                    ("{:.3f}".format(float(r[2] or 0.0))) if r[2] is not None else "",
                    r[3] or "",
                    r[4] or "",
                    r[5] or "",
                    (r[6] or "").replace("\n", " ").strip(),
                    (r[7] or "").replace("\n", " ").strip(),
                ])
        return out_path


    def get_class_overview(self, limit_per_child: int = 20) -> List[Dict[str, Any]]:
        """Return per-child overview for a class/group screen.

        Trend is computed from the last up to 20 sessions:
        - recent_avg = avg(last 10)
        - prev_avg   = avg(previous 10)
        - delta      = recent_avg - prev_avg
        Status:
          ▲ if delta >= +0.05
          ▼ if delta <= -0.05
          ■ otherwise
        """
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT id, name, age, grade FROM children ORDER BY name COLLATE NOCASE")
            children = cur.fetchall()

            out: List[Dict[str, Any]] = []
            for c in children:
                child_id = int(c["id"])
                cur.execute(
                    """SELECT final_score, duration_sec, created_at
                       FROM sessions
                       WHERE child_id=? AND final_score IS NOT NULL
                       ORDER BY datetime(REPLACE(created_at,'T',' ')) DESC
                       LIMIT ?""",
                    (child_id, int(limit_per_child)),
                )
                rows = cur.fetchall()
                scores = [float(r[0]) for r in rows if r[0] is not None]
                total_sessions = len(scores)
                avg = (sum(scores) / total_sessions) if total_sessions else None

                recent = scores[:10]
                prev = scores[10:20]
                recent_avg = (sum(recent) / len(recent)) if len(recent) >= 3 else None
                prev_avg = (sum(prev) / len(prev)) if len(prev) >= 3 else None
                delta = (recent_avg - prev_avg) if (recent_avg is not None and prev_avg is not None) else None

                status = "■"
                if delta is not None:
                    if delta >= 0.05:
                        status = "▲"
                    elif delta <= -0.05:
                        status = "▼"

                out.append({
                    "child_id": child_id,
                    "name": c["name"],
                    "age": c["age"],
                    "grade": c["grade"],
                    "sessions": total_sessions,
                    "avg_score": avg,
                    "recent_avg": recent_avg,
                    "prev_avg": prev_avg,
                    "delta": delta,
                    "status": status,
                })

        return out


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
            "phoneme_confidence","focus_start_sec","focus_end_sec",
            "plan_id","plan_name","plan_mode","plan_json"
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

    

    
    # --- session plans (Sprint 2)
    def list_session_plans(self) -> List[sqlite3.Row]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, name, plan_json, created_at, updated_at FROM session_plans ORDER BY datetime(REPLACE(updated_at,'T',' ')) DESC, id DESC"
            )
            return cur.fetchall()

    def save_session_plan(self, name: str, plan: Dict[str, Any]) -> int:
        """Insert a user preset plan. Returns plan id."""
        nm = (name or "").strip()
        if not nm:
            raise ValueError("Plan name is required")
        pj = json.dumps(plan, ensure_ascii=False)
        ts = now_iso()
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO session_plans(name, plan_json, created_at, updated_at) VALUES(?,?,?,?)",
                (nm, pj, ts, ts)
            )
            self.conn.commit()
            return cur.lastrowid

    def delete_session_plan(self, plan_id: int) -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM session_plans WHERE id=?", (int(plan_id),))
            self.conn.commit()

    def get_session_plan(self, plan_id: int) -> Optional[Dict[str, Any]]:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("SELECT plan_json FROM session_plans WHERE id=?", (int(plan_id),))
            row = cur.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except Exception:
                return None

    # --- session run summary (Sprint 2)
    def create_session_run(self, child_id: int, plan: Dict[str, Any], planned_items: int) -> int:
        pj = json.dumps(plan, ensure_ascii=False)
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO session_runs(created_at, child_id, plan_json, planned_items, completed_items, ended_early, early_end_reason) VALUES(?,?,?,?,?,?,?)",
                (now_iso(), int(child_id), pj, int(planned_items), 0, 0, "")
            )
            self.conn.commit()
            return cur.lastrowid

    def finish_session_run(self, run_id: int, completed_items: int, ended_early: bool, reason: str = "") -> None:
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE session_runs SET completed_items=?, ended_early=?, early_end_reason=? WHERE id=?",
                (int(completed_items), 1 if ended_early else 0, (reason or ""), int(run_id))
            )
            self.conn.commit()

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
