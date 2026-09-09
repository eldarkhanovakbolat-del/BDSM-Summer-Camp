#!/bin/sh
python /app/adapter.py &
python /app/server/app.py &
exec pnpm start -- --hostname 0.0.0.0 --port 3000
