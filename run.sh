#!/bin/bash

# Fail on first error
set -e

# Default values
WORKERS=${WORKERS:-4}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-3000}
APP_MODULE=${APP_MODULE:-wsgi:app}

echo "Starting Gunicorn with $WORKERS workers on $HOST:$PORT serving $APP_MODULE"

# Run gunicorn
exec gunicorn -w "$WORKERS" -b "$HOST:$PORT" "$APP_MODULE"
