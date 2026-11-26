#!/bin/bash
# NML League Manager — start both servers

PYTHON=/Applications/Xcode.app/Contents/Developer/usr/bin/python3
DIR=/Users/j/Desktop/Claude/nmlapp

echo "Starting NML League Manager..."

# Kill any existing instances
pkill -f "python3 app.py" 2>/dev/null
pkill -f "http.server 8080" 2>/dev/null
sleep 1

# Start Flask backend
cd "$DIR/backend" && $PYTHON app.py &
echo "✓ Backend started"

# Start file server
$PYTHON -m http.server 8080 --directory "$DIR" --bind 127.0.0.1 &
echo "✓ File server started"

echo ""
echo "App is running at: http://127.0.0.1:8080/nml-app.html"
echo ""
echo "Press Ctrl+C to stop both servers."

# Keep running and stop both servers on Ctrl+C
trap "pkill -f 'python3 app.py'; pkill -f 'http.server 8080'; echo 'Servers stopped.'" EXIT
wait
