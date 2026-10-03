#!/bin/bash

#═══════════════════════════════════════════════
#   Oneirodex macOS Installer v1.0
#   Homebrew-based install for Apple Silicon and Intel Macs
#═══════════════════════════════════════════════
#
# Deliberately does NOT install Homebrew for you. The official installer is a
# script fetched over the network and run with your privileges; deciding to do
# that is the operator's call, not this script's. If brew is missing you get
# the one-liner and an exit.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/install.log"
PG_FORMULA="postgresql@17"
PYTHON_FORMULA="python@3.12"
DB_NAME="oneirodex"
TEST_DB_NAME="oneirodextest"
DB_USER="$(id -un)"
GAMES_DIR=""
LIBRARY_ROOTS=""
CUSTOM_PORT="5006"
FORCE_INSTALL=false
DEV_MODE=false
SKIP_DB=false
VERBOSE_MODE=false

cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo -e "\n${RED}✗ Installation failed!${NC}"
        echo -e "${YELLOW}Check the log file: $LOG_FILE${NC}"
    fi
}
trap cleanup EXIT

log() { echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" >> "$LOG_FILE"; }
print_step()    { echo -e "${BLUE}[→]${NC} $1"; log "STEP: $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; log "SUCCESS: $1"; }
print_error()   { echo -e "${RED}[✗]${NC} $1"; log "ERROR: $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; log "WARNING: $1"; }
print_info()    { echo -e "${CYAN}[ℹ]${NC} $1"; log "INFO: $1"; }
print_verbose() { if [ "$VERBOSE_MODE" = true ]; then echo -e "${CYAN}[ℹ]${NC} $1"; fi; log "VERBOSE: $1"; }

run_quiet() {
    if [ "$VERBOSE_MODE" = true ]; then
        "$@"
    else
        "$@" >/dev/null
    fi
}

print_header() {
    clear
    echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
    echo -e "${WHITE}    Oneirodex macOS Installer v1.0${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
    echo
}

show_help() {
    echo "Oneirodex macOS Installer"
    echo
    echo "USAGE:"
    echo "  ./install-macos.sh [OPTIONS]"
    echo
    echo "OPTIONS:"
    echo "  --force           Overwrite an existing .env / config.py"
    echo "  --dev             Install development dependencies too"
    echo "  --no-db           Skip PostgreSQL setup (use an existing database)"
    echo "  --verbose, -v     Show detailed output"
    echo "  --quiet, -q       Suppress detailed output (default)"
    echo "  --games-dir PATH  Games directory"
    echo "  --library-roots S Extra scan locations, pipe-separated, optional Label="
    echo "  --port PORT       Custom port (default: 5006)"
    echo "  --help, -h        Show this help message"
    echo
    echo "EXAMPLES:"
    echo "  ./install-macos.sh"
    echo "  ./install-macos.sh --games-dir ~/Games"
    echo "  ./install-macos.sh --library-roots 'NAS ROMs=/Volumes/roms|Archive=/Volumes/archive'"
    echo
    echo "SCAN LOCATIONS:"
    echo "  An SMB/AFP share mounted in Finder lands under /Volumes and is scannable"
    echo "  like any local folder. Finder mounts are per-login-session, so a share"
    echo "  you want available to a background Oneirodex needs autofs instead —"
    echo "  docs/runbooks/remote-scan-locations.md walks through both."
}

parse_arguments() {
    while [ $# -gt 0 ]; do
        case $1 in
            --force)   FORCE_INSTALL=true; shift ;;
            --dev)     DEV_MODE=true; shift ;;
            --no-db)   SKIP_DB=true; shift ;;
            --verbose|-v) VERBOSE_MODE=true; shift ;;
            --quiet|-q)   VERBOSE_MODE=false; shift ;;
            --games-dir)
                if [ $# -lt 2 ]; then print_error "--games-dir requires an argument"; exit 1; fi
                GAMES_DIR="$2"; shift 2 ;;
            --library-roots)
                if [ $# -lt 2 ]; then print_error "--library-roots requires an argument"; exit 1; fi
                LIBRARY_ROOTS="$2"; shift 2 ;;
            --port)
                if [ $# -lt 2 ]; then print_error "--port requires an argument"; exit 1; fi
                CUSTOM_PORT="$2"; shift 2 ;;
            --help|-h) show_help; exit 0 ;;
            *) print_error "Unknown option: $1"; show_help; exit 1 ;;
        esac
    done
}

check_platform() {
    print_step "Checking platform..."
    if [ "$(uname -s)" != "Darwin" ]; then
        print_error "This installer is for macOS. On Linux use ./install-linux.sh"
        exit 1
    fi
    print_success "macOS $(sw_vers -productVersion) on $(uname -m)"
}

check_homebrew() {
    print_step "Checking Homebrew..."
    if ! command -v brew >/dev/null 2>&1; then
        # Apple Silicon puts brew outside the default PATH of a fresh shell.
        for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
            if [ -x "$candidate" ]; then
                eval "$("$candidate" shellenv)"
                break
            fi
        done
    fi

    if ! command -v brew >/dev/null 2>&1; then
        print_error "Homebrew is required and was not found."
        echo
        print_info "Install it yourself (review the script first — it runs as you):"
        print_info '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        print_info "Then re-run ./install-macos.sh"
        exit 1
    fi
    print_success "Homebrew found: $(brew --prefix)"
}

install_prerequisites() {
    print_step "Installing prerequisites (Python, PostgreSQL)..."

    if ! brew list --formula "$PYTHON_FORMULA" >/dev/null 2>&1; then
        print_verbose "Installing $PYTHON_FORMULA..."
        run_quiet brew install "$PYTHON_FORMULA"
    fi
    print_success "Python available"

    if [ "$SKIP_DB" = true ]; then
        print_info "Skipping PostgreSQL install (--no-db)"
        return 0
    fi

    if ! brew list --formula "$PG_FORMULA" >/dev/null 2>&1; then
        print_verbose "Installing $PG_FORMULA..."
        run_quiet brew install "$PG_FORMULA"
    fi
    # Homebrew keeps versioned formulae off PATH; psql/createdb live in its bin.
    PG_BIN="$(brew --prefix "$PG_FORMULA")/bin"
    export PATH="$PG_BIN:$PATH"
    print_success "PostgreSQL 17 available at $PG_BIN"
}

setup_postgresql() {
    if [ "$SKIP_DB" = true ]; then
        print_info "Skipping database setup (--no-db)"
        return 0
    fi

    print_step "Starting PostgreSQL..."
    run_quiet brew services start "$PG_FORMULA" || true

    # brew services returns before the socket is accepting connections.
    local attempts=0
    until pg_isready -q >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 30 ]; then
            print_error "PostgreSQL did not become ready. Check: brew services list"
            return 1
        fi
        sleep 1
    done
    print_success "PostgreSQL is accepting connections"

    print_step "Creating databases..."
    # Homebrew's PostgreSQL trusts the local account, so Oneirodex connects as
    # you over the local socket rather than as a password-protected role.
    for database in "$DB_NAME" "$TEST_DB_NAME"; do
        if psql -lqt 2>/dev/null | cut -d '|' -f 1 | grep -qw "$database"; then
            print_info "Database already exists: $database"
        else
            createdb "$database"
            print_success "Database created: $database"
        fi
    done
}

setup_python_environment() {
    print_step "Setting up Python virtual environment..."
    local python_bin
    python_bin="$(brew --prefix "$PYTHON_FORMULA")/bin/python3"
    [ -x "$python_bin" ] || python_bin="python3"

    if [ ! -d "$SCRIPT_DIR/venv" ]; then
        "$python_bin" -m venv "$SCRIPT_DIR/venv"
        print_success "Virtual environment created"
    else
        print_info "Using existing virtual environment"
    fi

    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/venv/bin/activate"
    run_quiet python3 -m pip install --upgrade pip
    print_verbose "Installing Python dependencies..."
    if run_quiet python3 -m pip install -r "$SCRIPT_DIR/requirements.txt"; then
        print_success "Python dependencies installed"
    else
        print_error "Failed to install Python dependencies"
        return 1
    fi

    if [ "$DEV_MODE" = true ] && [ -f "$SCRIPT_DIR/requirements-dev.txt" ]; then
        run_quiet python3 -m pip install -r "$SCRIPT_DIR/requirements-dev.txt"
    fi
}

check_scan_locations() {
    # Warn, never fail: an autofs mount can legitimately be absent until first
    # access, and a share that is down today should not block the install.
    [ -n "$LIBRARY_ROOTS" ] || return 0
    local old_ifs="$IFS"
    IFS='|'
    for entry in $LIBRARY_ROOTS; do
        local root_path="${entry#*=}"
        root_path="$(echo "$root_path" | sed 's/^ *//; s/ *$//')"
        if [ -z "$root_path" ]; then
            continue
        elif [ -d "$root_path" ]; then
            print_success "Scan location found: $root_path"
        else
            print_warning "Scan location not mounted yet: $root_path"
        fi
    done
    IFS="$old_ifs"
}

configure_application() {
    print_step "Configuring Oneirodex..."

    if [ -f "$SCRIPT_DIR/.env" ]; then
        cp "$SCRIPT_DIR/.env" "$SCRIPT_DIR/.env.backup.$(date +%Y%m%d-%H%M%S)"
        print_success "Existing .env backed up"
    fi

    local secret_key
    secret_key=""
    if [ -f "$SCRIPT_DIR/.env" ]; then
        secret_key="$(sed -n 's/^SECRET_KEY=//p' "$SCRIPT_DIR/.env" | head -n 1)"
    fi
    if [ -z "$secret_key" ]; then
        secret_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
    fi

    if [ -z "$GAMES_DIR" ]; then
        echo
        print_info "Which folder holds your games?"
        read -r -p "Games directory path [$HOME/Games]: " input_dir
        GAMES_DIR="${input_dir:-$HOME/Games}"
    fi

    if [ ! -d "$GAMES_DIR" ]; then
        print_warning "Games directory does not exist: $GAMES_DIR"
        read -r -p "Create this directory? [Y/n]: " create_dir
        case "${create_dir:-Y}" in
            [Yy]|[Yy][Ee][Ss]) mkdir -p "$GAMES_DIR"; print_success "Created $GAMES_DIR" ;;
            *) print_warning "Update DATA_FOLDER_GAMES in .env before your first scan" ;;
        esac
    else
        print_success "Games directory exists: $GAMES_DIR"
    fi

    # Extra scan locations. On macOS a mounted share shows up under /Volumes,
    # so pointing Oneirodex at a NAS is a matter of naming the mount point.
    if [ -z "$LIBRARY_ROOTS" ]; then
        echo
        print_info "Extra scan locations beyond $GAMES_DIR (optional)."
        print_info "Mounted shares live under /Volumes — e.g. 'NAS ROMs=/Volumes/roms'"
        print_info "Separate several with a pipe character."
        read -r -p "Extra scan locations [none]: " input_roots
        LIBRARY_ROOTS="${input_roots:-}"
    fi
    check_scan_locations

    local db_url="postgresql://$DB_USER@localhost:5432/$DB_NAME"
    local test_db_url="postgresql://$DB_USER@localhost:5432/$TEST_DB_NAME"

    cat > "$SCRIPT_DIR/.env" <<EOF
# Oneirodex Configuration - Generated by install-macos.sh $(date)

# Database connection (Homebrew PostgreSQL trusts the local account)
DATABASE_URL=$db_url
TEST_DATABASE_URL=$test_db_url

# Game files directory
DATA_FOLDER_GAMES=$GAMES_DIR

# Extra scan locations: mounted shares (/Volumes/...), second disks, anything
# else this Mac can open. Pipe-separated, optional "Label=" prefix.
# See docs/runbooks/remote-scan-locations.md
ONEIRODEX_LIBRARY_ROOTS=$LIBRARY_ROOTS

# Base folders for path resolution
BASE_FOLDER_POSIX=/

# Flask secret key (keep this secure!)
SECRET_KEY=$secret_key

# Upload directory for cover images and zips
UPLOAD_FOLDER=$SCRIPT_DIR/oneirodex/static/library

PORT=$CUSTOM_PORT
DEV_MODE=$DEV_MODE

# Local HTTP — set both true once you put Oneirodex behind HTTPS
SESSION_COOKIE_SECURE=false
REMEMBER_COOKIE_SECURE=false
EOF

    chmod 600 "$SCRIPT_DIR/.env"
    print_success "Environment configuration created"

    chmod +x "$SCRIPT_DIR"/*.sh
    print_success "Shell script permissions set"
}

validate_installation() {
    print_step "Validating installation..."
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/venv/bin/activate"

    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a

    if python3 -c "from oneirodex import create_app; create_app()" >/dev/null 2>&1; then
        print_success "Flask application setup validated"
    else
        print_error "Flask application validation failed — see $LOG_FILE"
        return 1
    fi

    for file in ".env" "config.py" "startweb.sh" "requirements.txt"; do
        if [ ! -f "$SCRIPT_DIR/$file" ]; then
            print_error "Missing required file: $file"
            return 1
        fi
    done
    print_success "Required files present"
}

show_summary() {
    echo
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "${WHITE}    Installation Completed Successfully!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
    echo
    echo -e "${CYAN}📌 Access URL:${NC} http://localhost:$CUSTOM_PORT"
    echo -e "${CYAN}📌 Games Directory:${NC} $GAMES_DIR"
    if [ -n "$LIBRARY_ROOTS" ]; then
        echo -e "${CYAN}📌 Extra Scan Locations:${NC} $LIBRARY_ROOTS"
    fi
    if [ "$SKIP_DB" != true ]; then
        echo -e "${CYAN}📌 Database:${NC} $DB_NAME (local socket, user $DB_USER)"
    fi
    echo -e "${CYAN}📌 Start Command:${NC} ./startweb.sh"
    echo -e "${CYAN}📌 Stop:${NC} Press Ctrl+C"
    echo -e "${CYAN}📌 Reset Database:${NC} ./startweb.sh --force-setup"
    echo -e "${CYAN}📌 Run at login:${NC} docs/runbooks/install-native.md (macOS launchd)"
    echo -e "${CYAN}📌 Log File:${NC} $LOG_FILE"
    echo

    read -r -p "Start Oneirodex now? [Y/n]: " start_now
    case "${start_now:-Y}" in
        [Yy]|[Yy][Ee][Ss])
            echo
            print_info "Starting Oneirodex — open http://localhost:$CUSTOM_PORT"
            print_info "Press Ctrl+C to stop"
            echo
            export PORT="$CUSTOM_PORT"
            exec ./startweb.sh
            ;;
        *)
            echo
            print_info "To start Oneirodex later, run: ./startweb.sh"
            print_info "Then open: http://localhost:$CUSTOM_PORT"
            ;;
    esac
}

main() {
    echo "Oneirodex macOS Installer - $(date)" > "$LOG_FILE"
    print_header
    parse_arguments "$@"

    print_info "This installer will:"
    print_info "  • Install Python and PostgreSQL 17 via Homebrew"
    print_info "  • Create the oneirodex databases"
    print_info "  • Set up a Python virtual environment"
    print_info "  • Write .env (games folder, scan locations, secret key)"
    echo
    print_info "Press any key to continue or Ctrl+C to quit..."
    read -n 1 -s -r
    echo

    check_platform
    check_homebrew
    install_prerequisites
    setup_postgresql
    setup_python_environment
    configure_application
    validate_installation
    show_summary
}

main "$@"
