#!/bin/bash
# Daedalus Assistant Launch Script

# Navigate to the workspace
cd "/home/dan/Desktop/DAEDALUS"

# Check if the server is already running, if not, start it
if ! lsof -i:8000 > /dev/null; then
    echo "Starting Daedalus Assistant Server..."
    python3 assistant_server.py &
    sleep 2
fi

# Open the dashboard in the default browser
xdg-open http://localhost:8012 &
