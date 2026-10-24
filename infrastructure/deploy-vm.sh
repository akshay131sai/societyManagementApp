#!/usr/bin/env bash
# One-shot NestFlow setup on Ubuntu (run as root). Re-runnable.
set -euo pipefail

APP=/opt/nestflow
API=$APP/apps/api

id nestflow >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin nestflow
mkdir -p "$APP"
tar -xzf /home/cloudgoo/nestflow.tgz -C "$APP"
mkdir -p "$API/var/uploads"

# --- Database -----------------------------------------------------------------
if [ ! -f "$APP/.dbpass" ]; then
  openssl rand -hex 24 > "$APP/.dbpass"; chmod 600 "$APP/.dbpass"
fi
DBPASS=$(cat "$APP/.dbpass")
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='nestflow') THEN
    CREATE ROLE nestflow LOGIN CREATEDB PASSWORD '$DBPASS';
  ELSE
    ALTER ROLE nestflow LOGIN CREATEDB PASSWORD '$DBPASS';
  END IF;
END \$\$;
SQL
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='nestflow_platform'" | grep -q 1 \
  || sudo -u postgres createdb -O nestflow nestflow_platform
sudo -u postgres psql -q -c "ALTER SYSTEM SET max_connections = 200" -c "ALTER SYSTEM SET shared_buffers = '512MB'"
systemctl restart postgresql

# --- Backend env ----------------------------------------------------------------
PUBLIC_ORIGIN=${PUBLIC_ORIGIN:-http://103.146.174.34}
cat > "$API/.env" <<ENV
ENVIRONMENT=staging
DEBUG=false
HOST=127.0.0.1
PORT=8001
CENTRAL_DATABASE_URL=postgresql+psycopg://nestflow:$DBPASS@127.0.0.1:5432/nestflow_platform
TENANT_DB_HOST=127.0.0.1
TENANT_DB_PORT=5432
TENANT_DB_USER=nestflow
TENANT_DB_PASSWORD=$DBPASS
TENANT_DB_MAINTENANCE_DB=postgres
TENANT_ENGINE_CACHE_SIZE=15
AUTH_PROVIDER=dev
CORS_ORIGINS=$PUBLIC_ORIGIN,http://172.16.1.62
RATE_LIMIT_ENABLED=true
STORAGE_PROVIDER=local
STORAGE_LOCAL_PATH=$API/var/uploads
STORAGE_PUBLIC_BASE_URL=/static/uploads
SCHEDULER_ENABLED=true
LOG_LEVEL=INFO
LOG_JSON=true
DEFAULT_TIMEZONE=Asia/Kolkata
DEFAULT_LOCALE=en-IN
DEFAULT_CURRENCY=INR
ENV
chmod 600 "$API/.env"

# --- Python ----------------------------------------------------------------------
[ -d "$API/.venv" ] || python3 -m venv "$API/.venv"
"$API/.venv/bin/pip" install -q --timeout 30 -r "$API/requirements.txt"
chown -R nestflow:nestflow "$APP"

cd "$API"
sudo -u nestflow .venv/bin/python -m alembic -c alembic.central.ini upgrade head

# --- systemd -----------------------------------------------------------------
cat > /etc/systemd/system/nestflow-api.service <<UNIT
[Unit]
Description=NestFlow API
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=nestflow
WorkingDirectory=$API
ExecStart=$API/.venv/bin/python run.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q nestflow-api
systemctl restart nestflow-api

sudo -u nestflow .venv/bin/python -m app.cli migrate-tenants || true

# --- nginx ---------------------------------------------------------------------
cat > /etc/nginx/sites-available/nestflow <<'NGINX'
map $http_upgrade $connection_upgrade { default upgrade; '' close; }

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 20m;

    root /opt/nestflow/apps/web/dist;
    index index.html;

    # Marketing page
    location = /site { return 301 /site/; }
    location /site/ { alias /opt/nestflow/apps/marketing/dist/; try_files $uri $uri/ /site/index.html; }

    location /static/uploads/ { alias /opt/nestflow/apps/api/var/uploads/; }

    # WebSocket: token travels in the query string, so keep it out of access logs.
    location /api/v1/ws {
        access_log off;
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    location ~ ^/(api|health|docs|redoc|openapi\.json) {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /assets/ { expires 1y; add_header Cache-Control "public, immutable"; }

    location / { try_files $uri /index.html; }
}
NGINX
ln -sf /etc/nginx/sites-available/nestflow /etc/nginx/sites-enabled/nestflow
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

sleep 3
systemctl is-active nestflow-api
curl -fsS http://127.0.0.1/health/ready && echo
