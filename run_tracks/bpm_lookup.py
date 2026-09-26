import os
import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import requests

from .spotify_source import Track

USER_AGENT = "run-tracks/0.1 (personal project)"


@dataclass
class LookupResult:
    source: str
    bpm: float | None  # None means "looked, found nothing"
    matched_title: str | None = None
    matched_artist: str | None = None
    external_id: str | None = None


def normalize(text: str) -> str:
    """Lowercase, strip accents and drop version noise like
    '(feat. X)', '- 2011 Remaster', '[Radio Edit]'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"\s[-–]\s.*$", "", text)  # " - Remastered 2011"
    text = re.sub(r"[(\[].*?[)\]]", "", text)  # "(feat. X)", "[Live]"
    text = re.sub(r"\b(feat|ft|featuring)\b.*$", "", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(text.split())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def match_score(track: Track, title: str, artist: str, duration_s: float | None = None) -> float:
    """0..1, higher is better. Title and artist must both look right."""
    title_sim = similarity(track.title, title)
    artist_sim = max(similarity(a, artist) for a in track.artists) if track.artists else 0.0
    score = 0.6 * title_sim + 0.4 * artist_sim
    if duration_s:
        diff = abs(track.duration_ms / 1000 - duration_s)
        if diff > 10:
            score -= 0.3  # probably a different version (live, extended mix, ...)
    return score


MIN_SCORE = 0.8


class RateLimiter:
    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self.min_interval_s - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


class GetSongBPM:
    """https://getsongbpm.com/api — free key, requires a backlink to getsongbpm.com
    wherever the data is shown. Limit is 3000 requests/hour."""

    name = "getsongbpm"
    BASE = "https://api.getsong.co"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.limiter = RateLimiter(1.2)

    @classmethod
    def from_env(cls) -> "GetSongBPM | None":
        key = os.environ.get("GETSONGBPM_API_KEY")
        return cls(key) if key else None

    def lookup(self, track: Track) -> LookupResult:
        self.limiter.wait()
        resp = self.session.get(
            f"{self.BASE}/search/",
            params={
                "api_key": self.api_key,
                "type": "both",
                "lookup": f"song:{normalize(track.title)} artist:{normalize(track.main_artist)}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("search")
        # No hits come back as {"search": {"error": "no result"}} rather than a list.
        if not isinstance(results, list):
            return LookupResult(self.name, None)

        best, best_score = None, 0.0
        for r in results:
            score = match_score(track, r.get("title", ""), (r.get("artist") or {}).get("name", ""))
            if score > best_score:
                best, best_score = r, score
        if best is None or best_score < MIN_SCORE:
            return LookupResult(self.name, None)

        try:
            bpm = float(best.get("tempo") or 0) or None
        except ValueError:
            bpm = None
        return LookupResult(
            self.name,
            bpm,
            matched_title=best.get("title"),
            matched_artist=(best.get("artist") or {}).get("name"),
            external_id=best.get("id"),
        )


class Deezer:
    """Public API, no auth. The `bpm` field only exists on /track/{id} and is often 0.
    Limit is 50 requests per 5 seconds."""

    name = "deezer"
    BASE = "https://api.deezer.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.limiter = RateLimiter(0.11)  # just under 10 req/s

    def _get(self, path: str, **params) -> dict:
        self.limiter.wait()
        resp = self.session.get(f"{self.BASE}{path}", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Deezer error: {data['error']}")
        return data

    def lookup(self, track: Track) -> LookupResult:
        # Deezer's advanced syntax (artist:"..." track:"...") often returns nothing,
        # so do a plain search and pick the best match ourselves.
        hits = self._get(
            "/search", q=f"{normalize(track.main_artist)} {normalize(track.title)}", limit=10
        )["data"]

        scored = sorted(
            ((match_score(track, h["title"], h["artist"]["name"], h.get("duration")), h) for h in hits),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best = next((h for score, h in scored if score >= MIN_SCORE), None)
        if best is None:
            return LookupResult(self.name, None)

        details = self._get(f"/track/{best['id']}")
        return LookupResult(
            self.name,
            float(details.get("bpm") or 0) or None,
            matched_title=best["title"],
            matched_artist=best["artist"]["name"],
            external_id=str(best["id"]),
        )
