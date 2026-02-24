#!/bin/bash
set -e

# If no config.ini mounted, copy the example template
if [ ! -f /app/config.ini ]; then
    cp /app/config.example.ini /app/config.ini
fi

exec python main.py "$@"
