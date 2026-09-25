#!/bin/sh
# Container start-up: bind Apache to Render's $PORT and tell the browser apps where the model API lives.
set -e

PORT="${PORT:-10000}"
sed -i "s/Listen 80/Listen ${PORT}/" /etc/apache2/ports.conf
sed -i "s/<VirtualHost \*:80>/<VirtualHost *:${PORT}>/" /etc/apache2/sites-available/000-default.conf

# API_URL is set by the operator in the Render dashboard; escape quotes/backslashes before writing JS.
SAFE_API_URL=$(printf '%s' "${API_URL:-}" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf 'window.SMARTDETECTOR_API_URL = "%s";\n' "$SAFE_API_URL" > /var/www/html/app/runtime-config.js

exec "$@"
