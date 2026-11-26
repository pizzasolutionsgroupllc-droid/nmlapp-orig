#!/bin/bash
# Upload local nml.db to Railway production
# Usage: bash upload_db.sh

RAILWAY_URL="https://nmlapp-production.up.railway.app"
UPLOAD_TOKEN="nml2026upload"
DB_PATH="data/nml.db"

echo "Uploading $DB_PATH to $RAILWAY_URL..."
curl -X POST "$RAILWAY_URL/admin/upload-db" \
  -H "X-Upload-Token: $UPLOAD_TOKEN" \
  -F "db=@$DB_PATH" \
  -w "\nHTTP status: %{http_code}\n"
