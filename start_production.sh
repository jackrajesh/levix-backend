#!/bin/bash
# ==============================================================================
# LEVIX PRODUCTION SERVER BOOT ENGINE
# Domain Target: https://levixapp.in
# Author: Senior Publisher Developer
# ==============================================================================

# Exit immediately if a command exits with a non-zero status
set -e

echo "===================================================================="
echo "          L E V I X   T E C H N O L O G I E S   L A U N C H E R     "
echo "===================================================================="

# 1. Load Environment Variables safely
if [ -f "config/.env" ]; then
    echo "[LAUNCH] Loading configurations from config/.env..."
    export $(grep -v '^#' config/.env | xargs)
elif [ -f ".env" ]; then
    echo "[LAUNCH] Loading configurations from root .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "[LAUNCH] No local environment file found. Relying on platform injected environment variables."
fi

# 2. Setup Production Defaults
export PORT=${PORT:-8000}
export HOST=${HOST:-0.0.0.0}

# Derive core count or fallback to 3 worker threads
CPU_CORES=$(python -c "import os; print(os.cpu_count() or 1)")
export WORKERS=${WORKERS:-$((CPU_CORES * 2 + 1))}

# Cap workers at 4 to manage memory limits efficiently on standard containers
if [ "$WORKERS" -gt 4 ]; then
    export WORKERS=4
fi

echo "[LAUNCH] Target domain: https://levixapp.in"
echo "[LAUNCH] Active worker processes: $WORKERS"
echo "[LAUNCH] Binding to network interface: http://$HOST:$PORT"

# 3. Pre-flight database socket availability validation
echo "[LAUNCH] Initializing database pre-flight checks..."
python -c "
import os, sys, time, socket
from urllib.parse import urlparse

db_url = os.getenv('DATABASE_URL')
if not db_url:
    print('[LAUNCH] DATABASE_URL not detected. Falling back to local SQLite DB.')
    sys.exit(0)

if db_url.startswith('postgres'):
    print('[LAUNCH] PostgreSQL connection detected. Verifying database socket...')
    try:
        # Compatibility override for SQLAlchemy
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        
        parsed = urlparse(db_url)
        host = parsed.hostname
        port = parsed.port or 5432
        
        start_time = time.time()
        connected = False
        while time.time() - start_time < 15:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((host, port))
                s.close()
                print('[LAUNCH] Database connection verified successfully!')
                connected = True
                break
            except Exception:
                print('[LAUNCH] Database socket is not ready yet... retrying in 2 seconds.')
                time.sleep(2)
        if not connected:
            print('[LAUNCH WARNING] Database socket timeout! Server will attempt boot, but migrations might crash.')
    except Exception as e:
        print(f'[LAUNCH ERROR] Pre-flight failed: {e}. Attempting normal boot.')
"

# 4. Launch Production Server with secure proxy flags
# --proxy-headers: critical for HTTPS resolution behind cloud proxies (Render, Cloudflare, AWS)
# --forwarded-allow-ips: allow proxy forward headers from intermediate routing layers
# --no-access-log: disable standard verbose logging to maximize CPU throughput
echo "[LAUNCH] Starting server workers in high-performance uvloop state..."
exec uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --no-access-log \
    --log-level info
