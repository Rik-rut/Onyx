from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from arr.core.models import DownloadState

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    infohash TEXT PRIMARY KEY,
    media_type TEXT NOT NULL,
    tmdb_id INTEGER,
    title TEXT,
    season INTEGER,
    episode INTEGER,
    indexer TEXT,
    state TEXT NOT NULL,
    download_dir TEXT,
    content_path TEXT,
    destination_path TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    tmdb_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    state TEXT NOT NULL,
    infohash TEXT,
    path TEXT,
    PRIMARY KEY (tmdb_id, season, episode)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    infohash TEXT,
    state TEXT,
    detail TEXT,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS monitored_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id INTEGER UNIQUE NOT NULL,
    imdb_id TEXT,
    title TEXT NOT NULL,
    status TEXT,
    quality TEXT,
    last_checked_at REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_path TEXT NOT NULL,
    language TEXT NOT NULL,
    source TEXT NOT NULL,
    state TEXT NOT NULL,
    subtitle_id INTEGER,
    created_at REAL NOT NULL
);
"""


class DB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(downloads)")}
        for col, typ in (("year", "INTEGER"), ("imdb_id", "TEXT"), ("episode_title", "TEXT")):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE downloads ADD COLUMN {col} {typ}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # downloads
    def add_download(self, infohash: str, **fields) -> bool:
        now = time.time()
        try:
            self._conn.execute(
                "INSERT INTO downloads (infohash, state, created_at, updated_at, media_type, "
                "tmdb_id, title, season, episode, indexer, download_dir, year, imdb_id, "
                "episode_title) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    infohash,
                    fields.get("state", DownloadState.QUEUED.value),
                    now,
                    now,
                    fields.get("media_type"),
                    fields.get("tmdb_id"),
                    fields.get("title"),
                    fields.get("season"),
                    fields.get("episode"),
                    fields.get("indexer"),
                    fields.get("download_dir"),
                    fields.get("year"),
                    fields.get("imdb_id"),
                    fields.get("episode_title"),
                ),
            )
            self._conn.commit()
            self._event(infohash, str(fields.get("state", DownloadState.QUEUED.value)), "added")
            return True
        except sqlite3.IntegrityError:
            return False

    def get_download(self, infohash: str) -> dict | None:
        h = infohash.strip()
        row = self._conn.execute(
            "SELECT * FROM downloads WHERE LOWER(infohash)=LOWER(?)", (h,)
        ).fetchone()
        if not row and len(h) >= 4:
            row = self._conn.execute(
                "SELECT * FROM downloads WHERE LOWER(infohash) LIKE LOWER(?) || '%' LIMIT 1",
                (h,),
            ).fetchone()
        return dict(row) if row else None

    def set_download_state(self, infohash: str, state: DownloadState | str, **fields) -> None:
        s = state.value if isinstance(state, DownloadState) else str(state)
        sets = ["state=?", "updated_at=?"]
        vals: list = [s, time.time()]
        for k, v in fields.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(infohash)
        self._conn.execute(f"UPDATE downloads SET {', '.join(sets)} WHERE infohash=?", vals)
        self._conn.commit()
        self._event(infohash, s, "state change")

    def list_downloads(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM downloads ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_download(self, infohash: str) -> None:
        self._conn.execute("DELETE FROM downloads WHERE infohash=?", (infohash,))
        self._conn.commit()

    def _event(self, infohash, state, detail) -> None:
        self._conn.execute(
            "INSERT INTO events (infohash, state, detail, ts) VALUES (?,?,?,?)",
            (infohash, state, detail, time.time()),
        )
        self._conn.commit()

    # episodes
    def episode_state(self, tmdb_id: int, season: int, episode: int) -> str | None:
        row = self._conn.execute(
            "SELECT state FROM episodes WHERE tmdb_id=? AND season=? AND episode=?",
            (tmdb_id, season, episode),
        ).fetchone()
        return row["state"] if row else None

    def set_episode_state(
        self,
        tmdb_id: int,
        season: int,
        episode: int,
        state: str,
        infohash: str | None = None,
        path: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO episodes (tmdb_id, season, episode, state, infohash, path) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(tmdb_id, season, episode) DO UPDATE SET state=excluded.state, "
            "infohash=excluded.infohash, path=excluded.path",
            (tmdb_id, season, episode, state, infohash, path),
        )
        self._conn.commit()

    def episodes_for_series(self, tmdb_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodes WHERE tmdb_id=? ORDER BY season, episode", (tmdb_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # monitored_series
    def add_monitored(
        self,
        tmdb_id: int,
        title: str,
        imdb_id: str | None,
        status: str,
        quality: str | None,
    ) -> int:
        self._conn.execute(
            "INSERT OR IGNORE INTO monitored_series "
            "(tmdb_id, imdb_id, title, status, quality, created_at) VALUES (?,?,?,?,?,?)",
            (tmdb_id, imdb_id, title, status, quality, time.time()),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM monitored_series WHERE tmdb_id=?", (tmdb_id,)
        ).fetchone()
        return int(row["id"])

    def list_monitored(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM monitored_series ORDER BY title").fetchall()
        return [dict(r) for r in rows]

    def remove_monitored(self, series_id: int) -> None:
        self._conn.execute("DELETE FROM monitored_series WHERE id=?", (series_id,))
        self._conn.commit()

    def set_last_checked(self, series_id: int, ts: float) -> None:
        self._conn.execute(
            "UPDATE monitored_series SET last_checked_at=? WHERE id=?", (ts, series_id)
        )
        self._conn.commit()

    # subtitles
    def add_subtitle(
        self,
        media_path: str,
        language: str,
        source: str,
        state: str,
        subtitle_id: int | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO subtitles (media_path, language, source, state, subtitle_id, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (media_path, language, source, state, subtitle_id, time.time()),
        )
        self._conn.commit()

    def list_subtitles(self, media_path: str | None = None) -> list[dict]:
        if media_path:
            rows = self._conn.execute(
                "SELECT * FROM subtitles WHERE media_path=?", (media_path,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM subtitles ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
