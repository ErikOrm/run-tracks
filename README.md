# run-tracks

Look up the tempo (BPM) of the tracks in your Spotify Liked Songs or playlists,
or of any track you find by searching Spotify.

Spotify no longer exposes audio features such as tempo to new apps, so this tool
reads your tracks from Spotify and looks each one up in third-party BPM databases
([GetSongBPM](https://getsongbpm.com) and [Deezer](https://www.deezer.com)).
Tracks are matched by fuzzy title and artist, with duration as a tie-breaker.
Results are cached locally, so re-runs only query new tracks.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A Spotify account and a Spotify developer app
- Optional: a free [GetSongBPM API key](https://getsongbpm.com/api)

## Setup

1. Install the `run-tracks` command from a clone of this repo:

   ```sh
   uv tool install --editable .
   ```

   This puts `run-tracks` in `~/.local/bin` (run `uv tool update-shell` if that
   isn't on your `PATH`). With `--editable`, code changes take effect without
   reinstalling. To remove it again: `uv tool uninstall run-tracks`.

2. Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   and add `http://127.0.0.1:8888/callback` as a Redirect URI.

3. Run the setup, which asks for your Spotify client ID and secret and an optional
   GetSongBPM API key, saves them, and logs you in to Spotify in the browser:

   ```sh
   run-tracks setup
   ```

   Run it again at any time to change a value; pressing Enter keeps the current one.
   The settings are saved to `~/.config/run-tracks/.env`:

   | Variable                | Description                                              |
   |-------------------------|----------------------------------------------------------|
   | `SPOTIPY_CLIENT_ID`     | Client ID of your Spotify app                            |
   | `SPOTIPY_CLIENT_SECRET` | Client secret of your Spotify app                        |
   | `SPOTIPY_REDIRECT_URI`  | Must match the Redirect URI set on your Spotify app      |
   | `GETSONGBPM_API_KEY`    | Optional. Without it, only Deezer is queried             |

   You can also write that file by hand, starting from `.env.example`. A `.env` in
   the current directory, or real environment variables, take precedence over it.

`run-tracks` keeps its files in fixed locations, so it works from any directory:

| File                                           | Contents                    |
|------------------------------------------------|-----------------------------|
| `~/.config/run-tracks/.env`                   | Credentials and API keys    |
| `~/.local/share/run-tracks/spotify_token.json`| Spotify login token         |
| `~/.local/share/run-tracks/bpm_cache.db`      | Cached tracks and BPMs      |

`$XDG_CONFIG_HOME` and `$XDG_DATA_HOME` are respected if set.

## Usage

```sh
# Look up BPMs for your Liked Songs
run-tracks liked

# List your playlists (ID and name)
run-tracks playlists

# Look up BPMs for a playlist (ID, URI, URL or the name of one of your playlists)
run-tracks playlist 37i9dQZF1DXcBWIGoYBM5M
run-tracks playlist "Movits"

# Search the whole Spotify catalog (first 5 results by default)
run-tracks search "daft punk one more time"
run-tracks search "track:one more time artist:daft punk" --limit 10

# Print the cached results as a table, or as CSV
run-tracks show
run-tracks show --csv > bpms.csv

# Only show cached tracks within a BPM range (either bound can be left out)
run-tracks show --min-bpm 120 --max-bpm 130

# Also match tracks reported at half or double that tempo
run-tracks show --min-bpm 90 --max-bpm 95 --half-double
```

`show` filters on the GetSongBPM value when there is one, and on the Deezer value
otherwise. Tracks with no BPM are hidden when a filter is set.

BPM databases often report a track at double or half its felt tempo (a 93 BPM
track listed as 186). With `--half-double`, a track also matches if half or
double its BPM is in range. The table then shows the matching tempo after the
title, e.g. `(as 93.115)`, and `--csv` adds a `matched_bpm` column.

The `liked`, `playlist` and `search` commands accept these options:

| Option            | Description                                                     |
|-------------------|-----------------------------------------------------------------|
| `--limit N`       | Only process the first N tracks (`search` defaults to 5, `0` for no limit) |
| `--retry-misses`  | Re-query sources that previously returned no BPM                |
| `--all-sources`   | Query every source instead of stopping at the first BPM found   |

Sources are tried in order: GetSongBPM first (if a key is set), then Deezer.
Network errors are not cached, so a failed lookup is retried on the next run.

### Limitations

- Since February 2026, Spotify apps in development mode can only read playlists
  you own or collaborate on.
- Matching is fuzzy, so an occasional track may be matched to a different
  version (live, remix, ...). Use `--all-sources` to compare values across sources.
- Deezer often reports a BPM of 0 (unknown), which is treated as no result.

## Data sources and attribution

BPM data is provided by:

- **[GetSongBPM](https://getsongbpm.com)**: tempo data from the
  [GetSongBPM API](https://getsongbpm.com/api).
- **[Deezer](https://www.deezer.com)**: track metadata and tempo data from the
  [Deezer API](https://developers.deezer.com).

Track and playlist data comes from the [Spotify Web API](https://developer.spotify.com/documentation/web-api).
This project is not affiliated with or endorsed by GetSongBPM, Deezer or Spotify.
