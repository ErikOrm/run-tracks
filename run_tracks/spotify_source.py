from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"


@dataclass(frozen=True)
class Track:
    spotify_id: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int

    @property
    def main_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    def __str__(self) -> str:
        return f"{', '.join(self.artists)} - {self.title}"


def client(token_path: Path) -> spotipy.Spotify:
    # Credentials come from SPOTIPY_* environment variables (see .env).
    cache_handler = CacheFileHandler(cache_path=str(token_path))
    return spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPE, cache_handler=cache_handler))


def _to_track(item: dict | None) -> Track | None:
    # Skip podcast episodes, local files and tracks that are no longer available.
    if not item or item.get("type", "track") != "track" or not item.get("id"):
        return None
    return Track(
        spotify_id=item["id"],
        title=item["name"],
        artists=tuple(a["name"] for a in item.get("artists", [])),
        album=(item.get("album") or {}).get("name", ""),
        duration_ms=item.get("duration_ms", 0),
    )


def _paginate(sp: spotipy.Spotify, page: dict | None) -> Iterator[dict]:
    while page:
        yield from page["items"]
        page = sp.next(page) if page.get("next") else None


def liked_tracks(sp: spotipy.Spotify) -> Iterator[Track]:
    for entry in _paginate(sp, sp.current_user_saved_tracks(limit=50)):
        if track := _to_track(entry.get("track")):
            yield track


def playlist_tracks(sp: spotipy.Spotify, playlist: str) -> Iterator[Track]:
    """`playlist` can be an ID, URI or URL. Since Feb 2026, dev-mode apps can only
    read playlists the user owns or collaborates on."""
    for entry in _paginate(sp, sp.playlist_items(playlist, limit=50)):
        # The Feb 2026 API renamed "track" to "item" in playlist entries.
        if track := _to_track(entry.get("item") or entry.get("track")):
            yield track


def search_tracks(sp: spotipy.Spotify, query: str) -> Iterator[Track]:
    """Search the whole Spotify catalog. Dev-mode apps get at most 10 results per
    request, and Spotify stops paging at offset 1000.

    Pages are often short and `total` is unreliable, so only an empty page means
    the results are exhausted. Pages can also repeat earlier tracks."""
    page_size = 10
    seen = set()
    for offset in range(0, 1000, page_size):
        results = sp.search(q=query, type="track", limit=page_size, offset=offset)
        items = results["tracks"]["items"] if results else []
        if not items:
            break
        for item in items:
            if (track := _to_track(item)) and track.spotify_id not in seen:
                seen.add(track.spotify_id)
                yield track


def my_playlists(sp: spotipy.Spotify) -> Iterator[dict]:
    yield from _paginate(sp, sp.current_user_playlists(limit=50))
