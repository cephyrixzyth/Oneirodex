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

Nothing here touches the repo-root `.env` or the live database: the scratch
database is always named `oneirodexcapture`, and the env file is gitignored.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.capture.local"
DB_NAME = "oneirodexcapture"
DB_ADMIN_URL = os.environ.get("CAPTURE_PG_ADMIN_URL", "postgresql://postgres:postgres@127.0.0.1:5432/postgres")
DB_URL = DB_ADMIN_URL.rsplit("/", 1)[0] + f"/{DB_NAME}"

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



def seed_via_http(app) -> None:
    """Covers and chat, through the product's own endpoints.

    Deliberately **outside** any `app.app_context()`: Flask-Login caches the
    signed-in user on `g`, which is app-context scoped, so two test clients
    driven inside one long-lived context both act as whoever logged in first
    — the member's lines were being posted as the admin. Each request here
    gets its own context and therefore its own identity.
    """
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import ChatMessage

    # --- covers + chat, through the product's own endpoints -----------
    # In-process test clients, so the form and header CSRF tokens are
    # noise here — the running server keeps CSRF on.
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    r = client.post("/login", data={"username": USER, "password": PASSWORD}, follow_redirects=False)
    print("login:", r.status_code, r.headers.get("Location"))
    headers: dict[str, str] = {}

    r = client.post("/admin/api/art-studio/batch-generate", json={}, headers=headers)
    print("covers:", r.status_code, (r.get_json() or {}).get("data", r.get_json()))

    def _channels(c):
        payload = c.get("/api/chat/channels").get_json() or {}
        return (payload.get("data") or payload).get("channels") or []

    def _find(chs, slug):
        return next((c for c in chs if str(c.get("slug") or c.get("name") or "").lstrip("#") == slug), None)

    chans = _channels(client)
    for name, slug in (("general", "general"), ("looking-for-players", "looking-for-players")):
        if _find(chans, slug) is None:
            r = client.post("/api/chat/channels", json={"name": name, "slug": slug}, headers=headers)
            print("chat : created", name, r.status_code)
    chans = _channels(client)

    # Two voices, so presence, avatars and reactions have something to show.
    member = app.test_client()
    member.post("/login", data={"username": MEMBER_USER, "password": MEMBER_PASS}, follow_redirects=False)
    mheaders: dict[str, str] = {}

    script = {
        "general": [
            (client, headers, "Scan finished — the NES and Genesis shelves are up."),
            (member, mheaders, "Nice. Is dmg-acid2 the one with the smiley test screen?"),
            (client, headers, "That's the one. Covers are generated now too, check the tiles."),
            (member, mheaders, "The pixel icon pack looks great on the living-room TV."),
        ],
        "looking-for-players": [
            (member, mheaders, "Anyone up for a paddle-tester high-score run tonight?"),
            (client, headers, "In. 9pm, voice room?"),
        ],
    }
    for slug, lines in script.items():
        ch = _find(chans, slug)
        if ch is None:
            print("chat : no channel", slug)
            continue
        with app.app_context():
            # Re-seed only when the history is wrong: a single-author run of
            # this script (the bug above) or nothing at all.
            rows = db.session.execute(
                select(ChatMessage).filter_by(channel_id=ch["id"])
            ).scalars().all()
            if rows and len({m.user_id for m in rows}) > 1:
                continue
            for m in rows:
                db.session.delete(m)
            db.session.commit()
        for who, hdrs, text in lines:
            who.post(f"/api/chat/channels/{ch['id']}/messages", json={"body": text}, headers=hdrs)
        print("chat : seeded", len(lines), "messages in #" + slug)


def serve() -> None:
    import uvicorn

    os.environ["ONEIRODEX_MIGRATIONS_COMPLETE"] = "true"
    os.environ["ONEIRODEX_INITIALIZATION_COMPLETE"] = "true"
    print(f"serve: http://127.0.0.1:{PORT}  ({USER} / {PASSWORD})")
    uvicorn.run("asgi:asgi_app", host="127.0.0.1", port=PORT, workers=1)


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
