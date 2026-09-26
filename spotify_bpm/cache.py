import sqlite3
from pathlib import Path

from .bpm_lookup import LookupResult
from .spotify_source import Track

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    spotify_id  TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    artists     TEXT NOT NULL,  -- '; '-separated
    album       TEXT,
    duration_ms INTEGER
);

-- One row per (track, source). bpm IS NULL means the source was checked and had nothing,
-- so misses are cached too (use --retry-misses to try them again).
CREATE TABLE IF NOT EXISTS bpm_lookups (
    spotify_id     TEXT NOT NULL REFERENCES tracks(spotify_id),
    source         TEXT NOT NULL,
    bpm            REAL,
    matched_title  TEXT,
    matched_artist TEXT,
    external_id    TEXT,
    fetched_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (spotify_id, source)
);
"""


class Cache:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def upsert_track(self, track: Track) -> None:
        self.db.execute(
            """INSERT INTO tracks (spotify_id, title, artists, album, duration_ms)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (spotify_id) DO UPDATE SET
                 title = excluded.title, artists = excluded.artists,
                 album = excluded.album, duration_ms = excluded.duration_ms""",
            (track.spotify_id, track.title, "; ".join(track.artists), track.album, track.duration_ms),
        )
        self.db.commit()

    def get_lookup(self, spotify_id: str, source: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM bpm_lookups WHERE spotify_id = ? AND source = ?", (spotify_id, source)
        ).fetchone()

    def save_lookup(self, spotify_id: str, result: LookupResult) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO bpm_lookups
               (spotify_id, source, bpm, matched_title, matched_artist, external_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (spotify_id, result.source, result.bpm, result.matched_title,
             result.matched_artist, result.external_id),
        )
        self.db.commit()

    def summary(self) -> list[sqlite3.Row]:
        """Every cached track with the BPM from each source side by side."""
        return self.db.execute(
            """SELECT t.spotify_id, t.artists, t.title,
                      MAX(CASE WHEN l.source = 'getsongbpm' THEN l.bpm END) AS getsongbpm,
                      MAX(CASE WHEN l.source = 'deezer' THEN l.bpm END) AS deezer
               FROM tracks t LEFT JOIN bpm_lookups l USING (spotify_id)
               GROUP BY t.spotify_id
               ORDER BY t.artists, t.title"""
        ).fetchall()
