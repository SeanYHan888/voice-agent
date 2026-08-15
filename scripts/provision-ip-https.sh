#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

set -a
source .env
set +a

: "${PUBLIC_HOST:?Set PUBLIC_HOST to the EC2 public IPv4 address in .env}"
: "${LETSENCRYPT_EMAIL:?Set LETSENCRYPT_EMAIL in .env}"

mkdir -p certbot/conf certbot/www

# Start the HTTP gateway first so Let's Encrypt can reach the webroot challenge.
docker compose up -d --build gateway

docker run --rm \
  -v "$REPO_DIR/certbot/conf:/etc/letsencrypt" \
  -v "$REPO_DIR/certbot/www:/var/www/certbot" \
  certbot/certbot:v5.4.0 certonly \
  --non-interactive \
  --agree-tos \
  --email "$LETSENCRYPT_EMAIL" \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path /var/www/certbot \
  --ip-address "$PUBLIC_HOST"

docker compose -f docker-compose.yml -f docker-compose.https.yml up -d gateway
