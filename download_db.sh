#!/bin/bash
# Download production nml.db from Railway
# Usage: bash download_db.sh
# Saves timestamped backup to: data/backups/

RAILWAY_URL="https://nmlapp-production.up.railway.app"
UPLOAD_TOKEN="nml2026upload"
OUTPUT="data/backups/nml-backup-$(date +%Y%m%d-%H%M%S).db"

mkdir -p data/backups

echo "Downloading production database..."
HTTP_STATUS=$(curl -s -X GET "$RAILWAY_URL/admin/download-db" \
  -H "X-Upload-Token: $UPLOAD_TOKEN" \
  -o "$OUTPUT" \
  -w "%{http_code}")

echo "HTTP status: $HTTP_STATUS"

if [ "$HTTP_STATUS" = "200" ] && [ -s "$OUTPUT" ]; then
  echo "✓ Saved to: $OUTPUT"
else
  echo "✗ Download failed"
  rm -f "$OUTPUT"
fi
