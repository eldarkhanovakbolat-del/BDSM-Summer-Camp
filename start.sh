#!/bin/sh
python /app/server/prestart.py
python /app/adapter.py &
python /app/server/app.py &
exec pnpm start -- --hostname 0.0.0.0 --port 3000
