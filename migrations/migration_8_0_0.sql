
-- Migration 8.0.0

CREATE TABLE IF NOT EXISTS exercises (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT,
 text TEXT,
 type TEXT,
 objective TEXT,
 level INTEGER,
 voice TEXT,
 rate REAL,
 pause_ms INTEGER,
 created_at TEXT,
 updated_at TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 target_type TEXT,
 target_value TEXT,
 plan_id INTEGER,
 active INTEGER DEFAULT 1,
 created_at TEXT
);

ALTER TABLE sessions ADD COLUMN run_id INTEGER;
