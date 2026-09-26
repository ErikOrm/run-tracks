"""Interactive `run-tracks setup`: ask for credentials and write them to the config .env."""

import os
from getpass import getpass
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

from . import spotify_source

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


def _mask(value: str) -> str:
    return f"****{value[-4:]}" if len(value) > 4 else "****"


def _ask(label: str, current: str | None, secret: bool = False, default: str | None = None) -> str:
    """Prompt for a value. Pressing Enter keeps the current value (or the default)."""
    fallback = current or default or ""
    shown = (_mask(fallback) if secret else fallback) if fallback else ""
    prompt = f"{label} [{shown}]: " if shown else f"{label}: "
    answer = (getpass(prompt) if secret else input(prompt)).strip()
    return answer or fallback


def _write_env(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Written by `run-tracks setup`. Spotify app: https://developer.spotify.com/dashboard",
        f"SPOTIPY_CLIENT_ID={values.pop('SPOTIPY_CLIENT_ID')}",
        f"SPOTIPY_CLIENT_SECRET={values.pop('SPOTIPY_CLIENT_SECRET')}",
        f"SPOTIPY_REDIRECT_URI={values.pop('SPOTIPY_REDIRECT_URI')}",
        "",
        "# Optional: free key from https://getsongbpm.com/api",
        f"GETSONGBPM_API_KEY={values.pop('GETSONGBPM_API_KEY')}",
    ]
    if values:  # keep anything else that was already in the file
        lines += ["", *(f"{k}={v}" for k, v in values.items())]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with owner-only permissions, since the file holds secrets.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def run(env_path: Path, token_path: Path) -> None:
    existing = {k: v or "" for k, v in dotenv_values(env_path).items()} if env_path.exists() else {}
    print(f"Configuring run-tracks. Settings are saved to {env_path}")
    print("Press Enter to keep the value in [brackets].\n")

    print("1. Spotify: create an app at https://developer.spotify.com/dashboard")
    redirect_uri = existing.get("SPOTIPY_REDIRECT_URI") or DEFAULT_REDIRECT_URI
    print(f"   and add this Redirect URI to it: {redirect_uri}")
    values = dict(existing)
    values["SPOTIPY_CLIENT_ID"] = _ask("   Client ID", existing.get("SPOTIPY_CLIENT_ID"))
    values["SPOTIPY_CLIENT_SECRET"] = _ask(
        "   Client secret", existing.get("SPOTIPY_CLIENT_SECRET"), secret=True)
    values["SPOTIPY_REDIRECT_URI"] = _ask(
        "   Redirect URI", existing.get("SPOTIPY_REDIRECT_URI"), default=DEFAULT_REDIRECT_URI)

    print("\n2. GetSongBPM (optional, leave empty to use Deezer only):")
    print("   free key at https://getsongbpm.com/api, requires a backlink to getsongbpm.com")
    values["GETSONGBPM_API_KEY"] = _ask(
        "   API key", existing.get("GETSONGBPM_API_KEY"), secret=True)

    if not values["SPOTIPY_CLIENT_ID"] or not values["SPOTIPY_CLIENT_SECRET"]:
        raise SystemExit("\nSpotify client ID and secret are required. Nothing was saved.")

    spotify_changed = any(values[k] != existing.get(k) for k in
                          ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI"))
    for key in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI", "GETSONGBPM_API_KEY"):
        os.environ[key] = values[key]
    _write_env(env_path, values)
    print(f"\nSaved to {env_path}")

    if spotify_changed and token_path.exists():
        # The cached login belongs to the old Spotify app settings.
        token_path.unlink()

    if (local_env := find_dotenv(usecwd=True)) and Path(local_env).resolve() != env_path.resolve():
        print(f"Note: {local_env} takes precedence over these settings when you run "
              "run-tracks from that directory.")

    if input("\nLog in to Spotify now to check the credentials? [Y/n]: ").strip().lower() in ("", "y", "yes"):
        try:
            user = spotify_source.client(token_path).current_user() or {}
        except Exception as e:
            raise SystemExit(f"Spotify login failed: {e}\nRun `run-tracks setup` again to fix the settings.")
        print(f"Logged in to Spotify as {user.get('display_name') or user.get('id')}. You're all set.")
