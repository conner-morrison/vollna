#!/bin/sh
# Container start: keep everything the app writes on the volume at $DATA_DIR, so sessions, the relay
# registration and the list of handled jobs survive a redeploy. The app writes these next to its
# code, so each one is linked from there into the volume.
set -e
DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/profiles" "$DATA_DIR/out" "$DATA_DIR/pages"
for item in profiles out pages chrome-profile state.json telegram.json reports.json handled.json logged-out.html; do
    rm -rf "/app/$item"
    ln -s "$DATA_DIR/$item" "/app/$item"
done
exec python3 server.py
