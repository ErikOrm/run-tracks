import argparse
import csv
import os
import sys
from pathlib import Path

import requests
from dotenv import find_dotenv, load_dotenv

from . import configure, spotify_source
from .bpm_lookup import Deezer, GetSongBPM, LookupResult
from .cache import Cache

# Fixed locations, so the command works the same from any directory.
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "spotify-bpm"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "spotify-bpm"
ENV_PATH = CONFIG_DIR / ".env"
CACHE_PATH = DATA_DIR / "bpm_cache.db"
TOKEN_PATH = DATA_DIR / "spotify_token.json"


def lookup_bpm(track, sources, cache: Cache, retry_misses: bool, all_sources: bool) -> float | None:
    """Try each source in order, using cached results where present.
    Stops at the first BPM found unless all_sources is set."""
    found = None
    for source in sources:
        cached = cache.get_lookup(track.spotify_id, source.name)
        if cached and (cached["bpm"] is not None or not retry_misses):
            result = LookupResult(source.name, cached["bpm"])
        else:
            try:
                result = source.lookup(track)
            except (requests.RequestException, RuntimeError, ValueError) as e:
                # Don't cache failures, so they're retried on the next run.
                print(f"    {source.name}: error: {e}", file=sys.stderr)
                continue
            cache.save_lookup(track.spotify_id, result)

        if result.bpm is not None:
            found = found or result.bpm
            print(f"    {source.name}: {result.bpm:g}")
            if not all_sources:
                break
        else:
            print(f"    {source.name}: -")
    return found


def run_lookups(tracks, args) -> None:
    cache = Cache(CACHE_PATH)
    sources = []
    if gsb := GetSongBPM.from_env():
        sources.append(gsb)
    else:
        print("GETSONGBPM_API_KEY not set, skipping GetSongBPM (Deezer only).", file=sys.stderr)
    sources.append(Deezer())

    total = hits = 0
    for track in tracks:
        if args.limit and total >= args.limit:
            break
        total += 1
        print(f"[{total}] {track}")
        cache.upsert_track(track)
        if lookup_bpm(track, sources, cache, args.retry_misses, args.all_sources) is not None:
            hits += 1
    print(f"\nFound a BPM for {hits}/{total} tracks. Cached in {CACHE_PATH}.")


def preferred_bpm(row) -> float | None:
    """The BPM lookups would have picked: GetSongBPM first, then Deezer."""
    return row["getsongbpm"] if row["getsongbpm"] is not None else row["deezer"]


def matching_bpm(bpm: float, min_bpm: float | None, max_bpm: float | None,
                 half_double: bool) -> float | None:
    """Return the tempo that falls in range: the BPM itself or, with half_double,
    half or double it (BPM sources often report double- or half-time)."""
    candidates = (bpm, bpm / 2, bpm * 2) if half_double else (bpm,)
    return next((c for c in candidates
                 if (min_bpm is None or c >= min_bpm) and (max_bpm is None or c <= max_bpm)), None)


def show(args) -> None:
    filtering = args.min_bpm is not None or args.max_bpm is not None
    rows = []  # (row, tempo that matched the filter)
    for r in Cache(CACHE_PATH).summary():
        bpm = preferred_bpm(r)
        if not filtering:
            rows.append((r, bpm))
        elif bpm is not None:
            if (matched := matching_bpm(bpm, args.min_bpm, args.max_bpm, args.half_double)) is not None:
                rows.append((r, matched))

    if args.csv:
        writer = csv.writer(sys.stdout)
        extra = ["matched_bpm"] if args.half_double else []
        writer.writerow(list(rows[0][0].keys()) + extra if rows else [])
        writer.writerows(tuple(r) + ((m,) if args.half_double else ()) for r, m in rows)
        return
    fmt = lambda v: f"{v:6.1f}" if v is not None else "     -"
    print(f"{'getsongbpm':>10} {'deezer':>7}  track")
    for r, matched in rows:
        note = f"  (as {matched:g})" if matched != preferred_bpm(r) else ""
        print(f"{fmt(r['getsongbpm']):>10} {fmt(r['deezer']):>7}  {r['artists']} - {r['title']}{note}")


def main():
    # Real environment variables win, then a .env in the current directory, then the config dir.
    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(ENV_PATH)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(
        prog="run-tracks",
        description="Look up BPMs for your Spotify tracks.",
        epilog=f"Config: {ENV_PATH}  Cache: {CACHE_PATH}",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="enter your Spotify and GetSongBPM credentials")

    lookup_opts = argparse.ArgumentParser(add_help=False)
    lookup_opts.add_argument("--limit", type=int, help="only process the first N tracks")
    lookup_opts.add_argument("--retry-misses", action="store_true",
                             help="re-query sources that previously had no BPM")
    lookup_opts.add_argument("--all-sources", action="store_true",
                             help="query every source instead of stopping at the first hit")

    sub.add_parser("liked", parents=[lookup_opts], help="look up BPMs for your Liked Songs")
    p = sub.add_parser("playlist", parents=[lookup_opts], help="look up BPMs for a playlist")
    p.add_argument("playlist", help="playlist ID, URI or URL")
    p = sub.add_parser("search", parents=[lookup_opts],
                       help="look up BPMs for tracks found by searching Spotify")
    p.add_argument("query", help='search terms, e.g. "daft punk one more time" or '
                                 '"track:one more time artist:daft punk"')
    p.set_defaults(limit=5)
    sub.add_parser("playlists", help="list your playlists")
    p = sub.add_parser("show", help="print cached BPMs")
    p.add_argument("--csv", action="store_true")
    p.add_argument("--min-bpm", type=float, help="only show tracks with at least this BPM")
    p.add_argument("--max-bpm", type=float, help="only show tracks with at most this BPM")
    p.add_argument("--half-double", action="store_true",
                   help="also match tracks whose BPM is half or double the range")

    args = parser.parse_args()

    if args.command == "setup":
        configure.run(ENV_PATH, TOKEN_PATH)
        return
    if args.command == "show":
        show(args)
        return

    if not os.environ.get("SPOTIPY_CLIENT_ID") or not os.environ.get("SPOTIPY_CLIENT_SECRET"):
        sys.exit("Spotify credentials are missing. Run `run-tracks setup` first.")
    sp = spotify_source.client(TOKEN_PATH)
    if args.command == "playlists":
        for pl in spotify_source.my_playlists(sp):
            print(f"{pl['id']}  {pl['name']}")
    elif args.command == "liked":
        run_lookups(spotify_source.liked_tracks(sp), args)
    elif args.command == "playlist":
        run_lookups(spotify_source.playlist_tracks(sp, args.playlist), args)
    elif args.command == "search":
        run_lookups(spotify_source.search_tracks(sp, args.query), args)


if __name__ == "__main__":
    main()
