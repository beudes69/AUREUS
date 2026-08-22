#!/usr/bin/env bash
# Lance AUREUS en dry-run via Docker (aucune clé API requise).
set -euo pipefail
cd "$(dirname "$0")"
docker compose up --build aureus-dryrun
