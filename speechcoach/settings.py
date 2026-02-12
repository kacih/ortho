# speechcoach/settings.py
import sqlite3
from typing import Dict, Any, Optional

from speechcoach.config import DEFAULT_DB_PATH

DEFAULT_SETTINGS = {
    "tts_voice": "Microsoft Hortense Desktop",
    "tts_rate": 1.0,     # 0.5 → 1.5
    "tts_volume": 1.0,   # 0.0 → 1.0
}


class SettingsManager:
    """
    Minimal settings persistence using sqlite3 directly.
    This avoids coupling to DataLayer API variations.
    """

    def __init__(self, db_path: str = str(DEFAULT_DB_PATH)):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    tts_voice TEXT,
                    tts_rate REAL,
                    tts_volume REAL
                )
            """)
            # Ensure single row exists (id=1)
            con.execute("INSERT OR IGNORE INTO user_settings (id, tts_voice, tts_rate, tts_volume) VALUES (1, ?, ?, ?)",
                        (DEFAULT_SETTINGS["tts_voice"], DEFAULT_SETTINGS["tts_rate"], DEFAULT_SETTINGS["tts_volume"]))
            con.commit()

    def load(self) -> Dict[str, Any]:
        with self._connect() as con:
            row = con.execute(
                "SELECT tts_voice, tts_rate, tts_volume FROM user_settings WHERE id=1"
            ).fetchone()

        if not row:
            return DEFAULT_SETTINGS.copy()

        return {
            "tts_voice": row["tts_voice"] or DEFAULT_SETTINGS["tts_voice"],
            "tts_rate": float(row["tts_rate"]) if row["tts_rate"] is not None else DEFAULT_SETTINGS["tts_rate"],
            "tts_volume": float(row["tts_volume"]) if row["tts_volume"] is not None else DEFAULT_SETTINGS["tts_volume"],
        }

    def save(self, s: Dict[str, Any]) -> None:
        voice = s.get("tts_voice", DEFAULT_SETTINGS["tts_voice"])
        rate = float(s.get("tts_rate", DEFAULT_SETTINGS["tts_rate"]))
        volume = float(s.get("tts_volume", DEFAULT_SETTINGS["tts_volume"]))

        with self._connect() as con:
            con.execute(
                "UPDATE user_settings SET tts_voice=?, tts_rate=?, tts_volume=? WHERE id=1",
                (voice, rate, volume),
            )
            con.commit()
