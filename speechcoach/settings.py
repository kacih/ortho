# speechcoach/settings.py
import sqlite3
from typing import Dict, Any

from speechcoach.config import DEFAULT_DB_PATH

DEFAULT_SETTINGS = {
    "tts_voice": "Microsoft Hortense Desktop",
    "tts_rate": 1.0,     # 0.5 → 1.5
    "tts_volume": 1.0,   # 0.0 → 1.0
    "tts_backend": "system",  # system | edge
    "edge_voice": "fr-FR-DeniseNeural",
    "last_plan_json": "",
    "last_plan_name": "",
    "last_plan_mode": "",
    "kiosk_mode": 0,
}


class SettingsManager:
    """Minimal settings persistence using sqlite3 directly."""

    def __init__(self, db_path: str = str(DEFAULT_DB_PATH)):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    tts_voice TEXT,
                    tts_rate REAL,
                    tts_volume REAL,
                    tts_backend TEXT,
                    edge_voice TEXT,
                    last_plan_json TEXT,
                    last_plan_name TEXT,
                    last_plan_mode TEXT,
                    kiosk_mode INTEGER DEFAULT 0
                )
                """
            )
            # Migrate older DBs: add column if missing
            try:
                cols = [r[1] for r in con.execute("PRAGMA table_info(user_settings)").fetchall()]
                if "tts_backend" not in cols:
                    con.execute("ALTER TABLE user_settings ADD COLUMN tts_backend TEXT")
                if "edge_voice" not in cols:
                    con.execute("ALTER TABLE user_settings ADD COLUMN edge_voice TEXT")

                if "last_plan_json" not in cols:
                    con.execute("ALTER TABLE user_settings ADD COLUMN last_plan_json TEXT")
                if "last_plan_name" not in cols:
                    con.execute("ALTER TABLE user_settings ADD COLUMN last_plan_name TEXT")
                if "last_plan_mode" not in cols:
                    con.execute("ALTER TABLE user_settings ADD COLUMN last_plan_mode TEXT")
                if "kiosk_mode" not in cols:
                    con.execute("ALTER TABLE user_settings ADD COLUMN kiosk_mode INTEGER DEFAULT 0")
            except Exception:
                pass

            con.execute(
                """INSERT OR IGNORE INTO user_settings
                    (id, tts_voice, tts_rate, tts_volume, tts_backend, edge_voice, last_plan_json, last_plan_name, last_plan_mode, kiosk_mode)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_SETTINGS["tts_voice"],
                    DEFAULT_SETTINGS["tts_rate"],
                    DEFAULT_SETTINGS["tts_volume"],
                    DEFAULT_SETTINGS["tts_backend"],
                    DEFAULT_SETTINGS["edge_voice"],
                    DEFAULT_SETTINGS["last_plan_json"],
                    DEFAULT_SETTINGS["last_plan_name"],
                    DEFAULT_SETTINGS["last_plan_mode"],
                    int(DEFAULT_SETTINGS["kiosk_mode"]),
                ),
            )
            con.commit()

    def load(self) -> Dict[str, Any]:
        with self._connect() as con:
            row = con.execute(
                "SELECT tts_voice, tts_rate, tts_volume, tts_backend, edge_voice, last_plan_json, last_plan_name, last_plan_mode, kiosk_mode FROM user_settings WHERE id=1"
            ).fetchone()

        if not row:
            return DEFAULT_SETTINGS.copy()

        return {
            "tts_voice": row["tts_voice"] or DEFAULT_SETTINGS["tts_voice"],
            "tts_rate": float(row["tts_rate"]) if row["tts_rate"] is not None else DEFAULT_SETTINGS["tts_rate"],
            "tts_volume": float(row["tts_volume"]) if row["tts_volume"] is not None else DEFAULT_SETTINGS["tts_volume"],
            "tts_backend": (row["tts_backend"] or DEFAULT_SETTINGS["tts_backend"]).strip() or DEFAULT_SETTINGS["tts_backend"],
            "last_plan_json": row["last_plan_json"] or DEFAULT_SETTINGS["last_plan_json"],
            "last_plan_name": row["last_plan_name"] or DEFAULT_SETTINGS["last_plan_name"],
            "last_plan_mode": row["last_plan_mode"] or DEFAULT_SETTINGS["last_plan_mode"],
            "kiosk_mode": int(row["kiosk_mode"]) if row["kiosk_mode"] is not None else int(DEFAULT_SETTINGS["kiosk_mode"]),
        }

    def save(self, s: Dict[str, Any]) -> None:
        voice = s.get("tts_voice", DEFAULT_SETTINGS["tts_voice"])
        rate = float(s.get("tts_rate", DEFAULT_SETTINGS["tts_rate"]))
        volume = float(s.get("tts_volume", DEFAULT_SETTINGS["tts_volume"]))
        backend = (s.get("tts_backend", DEFAULT_SETTINGS["tts_backend"]) or "system").strip()
        last_plan_json = s.get("last_plan_json", DEFAULT_SETTINGS["last_plan_json"]) or ""
        last_plan_name = s.get("last_plan_name", DEFAULT_SETTINGS["last_plan_name"]) or ""
        last_plan_mode = s.get("last_plan_mode", DEFAULT_SETTINGS["last_plan_mode"]) or ""
        kiosk_mode = int(s.get("kiosk_mode", DEFAULT_SETTINGS["kiosk_mode"]) or 0)

        with self._connect() as con:
            con.execute(
                """UPDATE user_settings
                   SET tts_voice=?, tts_rate=?, tts_volume=?, tts_backend=?, edge_voice=?, last_plan_json=?, last_plan_name=?, last_plan_mode=?, kiosk_mode=?
                   WHERE id=1""",
                (voice, rate, volume, backend, last_plan_json, last_plan_name, last_plan_mode, kiosk_mode),
            )
            con.commit()
