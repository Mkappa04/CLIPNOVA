#!/usr/bin/env bash
# Backup of CLIPNOVA state (NOT the videos): database, credentials key, .env, consent evidence, custom lexicon.
# Usage: scripts/backup.sh [destination_dir]   (default: ./backups)
# Restore: stop CLIPNOVA, extract the archive in the project folder, start again.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
dest="${1:-$ROOT/backups}"
mkdir -p "$dest"
stamp="$(date +%Y%m%d-%H%M%S)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/data"
# consistent copy of SQLite even while the server is running
"$VENV/bin/python" - "$ROOT/data/clipnova.db" "$tmp/data/clipnova.db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close(); dst.close()
PY
for item in data/secret.key data/evidence data/config .env; do
  [[ -e "$ROOT/$item" ]] && cp -a "$ROOT/$item" "$tmp/$item"
done
archive="$dest/clipnova-backup-$stamp.tar.gz"
tar -C "$tmp" -czf "$archive" .
chmod 600 "$archive"
ok "Backup: $archive ($(du -h "$archive" | cut -f1))"
warn "Contains data/secret.key (decrypts your platform tokens): keep it private."
