"""
Bring up a throwaway Oneirodex instance for docs capture, in one command.

Everything `docs/assets/readme/CAPTURE.md` used to ask for by hand — a
`.env.capture.local`, a scratch database, the startup initialisation, an admin
matching `CAPTURE_USER` / `CAPTURE_PASS`, seeded libraries and free-ROM titles,
system-templated covers and a little chat history — happens here, in order,
and then uvicorn serves the result on `CAPTURE_PORT` (default 5006).

    python scripts/serve_capture.py            # bring up (idempotent)
    python scripts/serve_capture.py --reset    # drop the scratch DB first
    python scripts/serve_capture.py --seed-only

Nothing here writes the repo-root `.env` or touches the live database: the
scratch database is always named `oneirodexcapture`, and its env file is
gitignored. A local `DATABASE_URL` may supply the admin credential for the
scratch database; remote URLs are ignored.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.capture.local"
DB_NAME = "oneirodexcapture"


def _default_admin_url() -> str:
    """Reuse a local bootstrap credential without exposing or changing .env."""
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = raw.partition("=")
            if not separator or key.strip() != "DATABASE_URL":
                continue
            database_url = value.strip().strip("\"'")
            parsed = urlsplit(database_url)
            if (
                parsed.scheme in {"postgres", "postgresql"}
                and parsed.username == "postgres"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            ):
                return urlunsplit(parsed._replace(path="/postgres"))
            break
    return "postgresql://postgres:postgres@127.0.0.1:5432/postgres"


def _database_url(admin_url: str, database: str) -> str:
    return urlunsplit(urlsplit(admin_url)._replace(path=f"/{database}"))


DB_ADMIN_URL = os.environ.get("CAPTURE_PG_ADMIN_URL") or _default_admin_url()
DB_URL = _database_url(DB_ADMIN_URL, DB_NAME)

USER = os.environ.get("CAPTURE_USER", "admin")
PASSWORD = os.environ.get("CAPTURE_PASS", "CaptureAdmin1!")
PORT = int(os.environ.get("CAPTURE_PORT", "5006"))

# A second member so presence, DMs and chat history have two names in them.
MEMBER_USER = "mira"
MEMBER_PASS = "CaptureMember1!"


def write_env() -> None:
    if ENV_FILE.exists():
        print("env  :", ENV_FILE, "(kept)")
        return
    games = ROOT / "data" / "games-capture"
    lines = [
        f"SECRET_KEY={secrets.token_urlsafe(48)}",
        f"DATABASE_URL={DB_URL}",
        f"DATA_FOLDER_GAMES={games.as_posix()}",
        f"UPLOAD_FOLDER={(ROOT / 'oneirodex' / 'static' / 'library').as_posix()}",
        f"LIBRARY_HOST_PATH={(ROOT / 'oneirodex' / 'static' / 'library').as_posix()}",
        "BASE_FOLDER_WINDOWS=C:/",
        "BASE_FOLDER_POSIX=/",
        f"PORT={PORT}",
        "UVICORN_WORKERS=1",
        "DEV_MODE=false",
        "SESSION_COOKIE_SECURE=false",
        "REMEMBER_COOKIE_SECURE=false",
        # Keep every outbound integration off: capture never hits the network.
        "ENABLE_FREE_GAMES=false",
        "ENABLE_AI_ARTWORK=false",
        "SCAN_CHECK_FRESHNESS=false",
        "FETCH_WEBRETRO_CORES_ON_BOOT=false",
        "ENABLE_LIVEKIT=false",
        "ENABLE_LOGIN_RATE_LIMIT=false",
        # Stop all pollers so screenshots cannot trigger outbound requests or
        # populate the developer checkout with downloaded cache data.
        "ONEIRODEX_ENABLE_BACKGROUND_WORKERS=false",
        "OIDC_ENABLED=false",
    ]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("env  :", ENV_FILE, "(written)")


def load_env() -> None:
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    # ASGI startup prints an emoji; a cp1252 console would kill uvicorn before
    # it served a request. The env vars above only help child processes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def ensure_db(reset: bool) -> None:
    import psycopg2

    conn = psycopg2.connect(DB_ADMIN_URL)
    conn.autocommit = True
    cur = conn.cursor()
    if reset:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (DB_NAME,)
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}"')
        print("db   : dropped", DB_NAME)
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if cur.fetchone() is None:
        cur.execute(f'CREATE DATABASE "{DB_NAME}"')
        print("db   : created", DB_NAME)
    else:
        print("db   :", DB_NAME, "(exists)")
    conn.close()


def initialise() -> None:
    from oneirodex.init_manager import run_complete_startup_initialization

    if not run_complete_startup_initialization():
        raise SystemExit("startup initialisation failed")


def seed() -> None:
    """Admin + member, finished setup wizard, libraries, games, covers, chat."""
    from uuid import uuid4

    from sqlalchemy import select

    from oneirodex import create_app, db
    from oneirodex.models import Game, GlobalSettings, Library, LibraryPlatform, User, UserPreference
    from oneirodex.utils.setup import get_current_setup_step, mark_setup_complete

    app = create_app()
    with app.app_context():
        # --- accounts -----------------------------------------------------
        for name, email, role, pw in (
            (USER, "capture-admin@example.test", "admin", PASSWORD),
            (MEMBER_USER, "capture-member@example.test", "user", MEMBER_PASS),
        ):
            u = db.session.execute(select(User).filter_by(name=name)).scalars().first()
            if u is None:
                u = User(name=name, email=email, role=role, user_id=str(uuid4()))
                db.session.add(u)
            u.role = role
            u.state = True
            u.is_email_verified = True
            u.set_password(pw)
            # A five-title library at 1920 wide is mostly empty grid at the
            # default 50 % tile; the slider lives in Preferences now, so set
            # it here rather than in every capture script.
            if u.preferences is None:
                u.preferences = UserPreference()
            u.preferences.tile_size = "78"
        db.session.commit()
        print("users:", USER, "(admin) ·", MEMBER_USER, "(member)")

        # --- setup wizard -------------------------------------------------
        gs = db.session.execute(select(GlobalSettings)).scalars().first()
        if gs is None:
            gs = GlobalSettings()
            db.session.add(gs)
            db.session.commit()
        gs.igdb_client_id = (gs.igdb_client_id or "").strip() or "capturelocalclientid0001"
        gs.igdb_client_secret = (gs.igdb_client_secret or "").strip() or "capturelocalsecret00001"
        gs.smtp_enabled = False
        db.session.commit()
        mark_setup_complete()
        print("setup: step", get_current_setup_step())

        try:
            from oneirodex.init_data import (
                initialize_allowed_file_types,
                initialize_default_settings,
                initialize_discovery_sections,
                initialize_library_folders,
                insert_default_scanning_filters,
            )

            initialize_library_folders()
            initialize_discovery_sections()
            insert_default_scanning_filters()
            initialize_default_settings()
            initialize_allowed_file_types()
        except Exception as exc:  # noqa: BLE001
            print("seed helpers skipped:", type(exc).__name__, exc)

        # --- libraries + the five legal sample ROMs -----------------------
        libs = {
            lib.name: lib for lib in db.session.execute(select(Library)).scalars().all()
        }
        wanted = [
            ("Free NES samples", "NES", "NES", "nestest", "nestest"),
            ("Free GB samples", "GB", "GB", "dmg-acid2", "dmg-acid2"),
            ("Free GBA samples", "GBA", "GBA", "CASCADE7", "CASCADE7"),
            ("Free Genesis samples", "SEGA_MD", "Genesis", "genmddj", "genmddj"),
            ("Free Atari 2600 samples", "ATARI_2600", "Atari2600", "paddle-tester", "paddle-tester"),
        ]
        games_root = Path(os.environ["DATA_FOLDER_GAMES"])
        for lib_name, plat, plat_dir, game_dir, game_name in wanted:
            lib = libs.get(lib_name)
            if lib is None:
                lib = Library(
                    name=lib_name,
                    platform=LibraryPlatform[plat],
                    scan_depth=1,
                    image_url="/static/newstyle/default_library.jpg",
                )
                db.session.add(lib)
                db.session.flush()
                libs[lib_name] = lib
            folder = games_root / plat_dir / game_dir
            roms = [
                p for p in folder.iterdir()
                if p.is_file() and not p.name.endswith(".LICENSE.txt")
            ] if folder.is_dir() else []
            if not roms:
                print("missing rom:", folder)
                continue
            if db.session.execute(
                select(Game).filter_by(name=game_name, library_uuid=lib.uuid)
            ).scalars().first():
                continue
            db.session.add(Game(
                uuid=str(uuid4()),
                name=game_name,
                library_uuid=lib.uuid,
                full_disk_path=str(roms[0].resolve()),
                size=roms[0].stat().st_size,
                times_downloaded=0,
            ))
            print("game :", game_name, "->", lib_name)
        db.session.commit()
    return app



class _Browser:
    """One signed-in browser against the served app, in-process.

    Bootstraps a session and CSRF token, signs in through /api/auth/login
    and sends the token on every write, as the SPA does.
    """

    def __init__(self, username: str, password: str):
        import asyncio
        import httpx

        from asgi import asgi_app

        self._loop = asyncio.new_event_loop()
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi_app, client=("127.0.0.1", 50000)),
            base_url=f"http://127.0.0.1:{PORT}",
        )
        self.token = ""
        self._refresh_token()
        r = self.post("/api/auth/login", json={"username": username, "password": password})
        self.status = r.status_code
        self._refresh_token()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _refresh_token(self) -> None:
        # The sign-in screen bootstraps its CSRF token (and session) here.
        response = self._run(self._client.get("/api/auth/runtime-bootstrap"))
        if response.status_code == 200:
            self.token = response.json().get("csrf_token") or self.token

    def get(self, path: str):
        return self._run(self._client.get(path))

    def post(self, path: str, **kwargs):
        headers = {"X-CSRFToken": self.token, **kwargs.pop("headers", {})}
        return self._run(self._client.post(path, headers=headers, **kwargs))

    def close(self) -> None:
        self._run(self._client.aclose())
        self._loop.close()


def seed_via_http(app) -> None:
    """Covers and chat, through the served app's own endpoints."""
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import ChatMessage

    admin = _Browser(USER, PASSWORD)
    print("login:", admin.status)
    r = admin.post("/admin/api/art-studio/batch-generate", json={})
    print("covers:", r.status_code)

    def _channels(browser):
        payload = browser.get("/api/chat/channels").json() or {}
        return (payload.get("data") or payload).get("channels") or []

    def _find(chs, slug):
        return next((c for c in chs if str(c.get("slug") or c.get("name") or "").lstrip("#") == slug), None)

    chans = _channels(admin)
    for name, slug in (("general", "general"), ("looking-for-players", "looking-for-players")):
        if _find(chans, slug) is None:
            r = admin.post("/api/chat/channels", json={"name": name, "slug": slug})
            print("chat : created", name, r.status_code)
    chans = _channels(admin)

    # Two voices, so presence, avatars and reactions have something to show.
    member = _Browser(MEMBER_USER, MEMBER_PASS)
    print("member login:", member.status)

    script = {
        "general": [
            (admin, "Scan finished — the NES and Genesis shelves are up."),
            (member, "Nice. Is dmg-acid2 the one with the smiley test screen?"),
            (admin, "That's the one. Covers are generated now too, check the tiles."),
            (member, "The pixel icon pack looks great on the living-room TV."),
        ],
        "looking-for-players": [
            (member, "Anyone up for a paddle-tester high-score run tonight?"),
            (admin, "In. 9pm, voice room?"),
        ],
    }
    for slug, lines in script.items():
        ch = _find(chans, slug)
        if ch is None:
            print("chat : no channel", slug)
            continue
        with app.app_context():
            # Re-seed only when the history is wrong: a single-author run or
            # nothing at all.
            rows = db.session.execute(
                select(ChatMessage).filter_by(channel_id=ch["id"])
            ).scalars().all()
            if rows and len({m.user_id for m in rows}) > 1:
                continue
            for m in rows:
                db.session.delete(m)
            db.session.commit()
        for who, text in lines:
            who.post(f"/api/chat/channels/{ch['id']}/messages", json={"body": text})
        print("chat : seeded", len(lines), "messages in #" + slug)
    admin.close()
    member.close()


def serve() -> None:
    import uvicorn

    os.environ["ONEIRODEX_MIGRATIONS_COMPLETE"] = "true"
    os.environ["ONEIRODEX_INITIALIZATION_COMPLETE"] = "true"
    print(f"serve: http://127.0.0.1:{PORT}  ({USER} / {PASSWORD})")
    uvicorn.run("asgi:asgi_app", host="127.0.0.1", port=PORT, workers=1, proxy_headers=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate the scratch DB")
    ap.add_argument("--seed-only", action="store_true", help="do not start the server")
    ap.add_argument("--no-seed", action="store_true", help="skip seeding; just serve")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    write_env()
    load_env()
    ensure_db(args.reset)
    if not args.no_seed:
        initialise()
        app = seed()
        seed_via_http(app)
    if not args.seed_only:
        serve()


if __name__ == "__main__":
    main()
