#!/usr/bin/env bash
# Shared helpers for CLIPNOVA scripts.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/data/run"
LOG_DIR="$ROOT/data/logs"
VENV="$ROOT/.venv"

if [[ -t 1 ]]; then C_V=$'\e[35m'; C_C=$'\e[36m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_0=$'\e[0m'; else C_V= C_C= C_G= C_Y= C_R= C_0=; fi
info() { echo "${C_C}›${C_0} $*"; }
ok()   { echo "${C_G}✔${C_0} $*"; }
warn() { echo "${C_Y}!${C_0} $*"; }
err()  { echo "${C_R}✖${C_0} $*" >&2; }
banner() { echo "${C_V}━━━ CLIPNOVA ━━━${C_0} $*"; }

# Load .env (only CLIPNOVA_* keys) without executing arbitrary code
load_env() {
  [[ -f "$ROOT/.env" ]] || return 0
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^CLIPNOVA_[A-Z_]+$ ]] || continue
    value="${value%\"}"; value="${value#\"}"
    export "$key=$value"
  done < <(grep -E '^[[:space:]]*CLIPNOVA_[A-Z_]+=' "$ROOT/.env" | sed 's/^[[:space:]]*//')
}

pid_alive() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }
