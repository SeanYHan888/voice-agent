#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

docker run --rm \
  -v "$REPO_DIR/certbot/conf:/etc/letsencrypt" \
  -v "$REPO_DIR/certbot/www:/var/www/certbot" \
  certbot/certbot:v5.4.0 renew --quiet

docker compose -f docker-compose.yml -f docker-compose.https.yml exec -T gateway nginx -s reload
