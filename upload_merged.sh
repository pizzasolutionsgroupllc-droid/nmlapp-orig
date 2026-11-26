#!/bin/bash
# Upload merged ratings DB to Railway production
# Usage: bash upload_merged.sh
# Run after: python3 scripts/push_ratings_to_prod.py ...

RAILWAY_URL="https://nmlapp-production.up.railway.app"
UPLOAD_TOKEN="nml2026upload"
DB_PATH="data/nml-merged.db"

if [ ! -f "$DB_PATH" ]; then
  echo "ERROR: $DB_PATH not found. Run push_ratings_to_prod.py first."
  exit 1
fi

echo "Uploading $DB_PATH to $RAILWAY_URL..."
curl -X POST "$RAILWAY_URL/admin/upload-db" \
  -H "X-Upload-Token: $UPLOAD_TOKEN" \
  -F "db=@$DB_PATH" \
  -w "\nHTTP status: %{http_code}\n"
