#!/usr/bin/env bash
set -euo pipefail

# Deploy script for Crypto OI Dashboard
# Usage: run on the server after cloning the repo

APP_DIR="/opt/coinglass_"
REPO_URL="${REPO_URL:-https://github.com/mmdzzh/coinglass_look.git}"
DOMAIN="${DOMAIN:-}"
ACME_EMAIL="${ACME_EMAIL:-}"

if [[ -z "$REPO_URL" ]]; then
    echo "Usage: REPO_URL=<git-repo-url> DOMAIN=<your-domain> [ACME_EMAIL=<email>] ./deploy.sh"
    exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
    echo "Please run as root or with sudo"
    exit 1
fi

# Install dependencies
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi

if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null; then
    echo "Installing Docker Compose plugin..."
    apt-get update
    apt-get install -y docker-compose-plugin
fi

# Clone or update code
if [[ -d "$APP_DIR/.git" ]]; then
    echo "Updating existing repo..."
    cd "$APP_DIR"
    git pull origin main
else
    echo "Cloning repo..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# Create .env if not exists
if [[ ! -f .env ]]; then
    echo "Creating .env from example..."
    cp .env.example .env
    # Generate random DB password
    DB_PASS=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql+psycopg2://coinglass:${DB_PASS}@db:5432/coinglass|" .env
    sed -i "s|POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASS}|" .env 2>/dev/null || true
fi

# Set domain and email
if [[ -n "$DOMAIN" ]]; then
    sed -i "s|^DOMAIN=.*|DOMAIN=${DOMAIN}|" .env
fi
if [[ -n "$ACME_EMAIL" ]]; then
    sed -i "s|^ACME_EMAIL=.*|ACME_EMAIL=${ACME_EMAIL}|" .env 2>/dev/null || echo "ACME_EMAIL=${ACME_EMAIL}" >> .env
fi

# Pull and build images
export COMPOSE_FILE=docker-compose.prod.yml
docker compose pull
docker compose build

# Run database migrations / init
docker compose up -d db
sleep 5
docker compose run --rm web python -c "from database import init_db; init_db()"

# Start all services
docker compose up -d

echo "Deployment complete. App should be available at https://${DOMAIN:-localhost}"
