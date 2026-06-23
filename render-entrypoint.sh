#!/bin/sh
set -e

# Render PostgreSQL provides a standard postgres:// URL.
# SQLAlchemy with psycopg2 accepts both postgres:// and postgresql+psycopg2://.
export DATABASE_URL="${DATABASE_URL/postgres:\/\//postgresql+psycopg2:\/\/}"

# Initialize DB tables on startup
python -c "from database import init_db; init_db()"

# Start the FastAPI app
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
