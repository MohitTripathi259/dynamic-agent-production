#!/bin/bash
set -e

# Clean up any stale X server lock files
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Create Xauthority file
touch /root/.Xauthority

# Start Xvfb (X Virtual Frame Buffer) with no auth
echo "Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &
export DISPLAY=:99

# Wait for Xvfb to start
sleep 3

# Generate X authentication AFTER Xvfb is running
xauth generate :99 . trusted 2>/dev/null || true

# Start x11vnc for VNC access
echo "Starting x11vnc on port 5900..."
x11vnc -display :99 -forever -nopw -listen 0.0.0.0 -xkb &

# Start fluxbox window manager
echo "Starting fluxbox window manager..."
DISPLAY=:99 fluxbox &

# Wait for window manager to start
sleep 2

# Start the FastAPI server
echo "Starting computer use API server on port 8080..."
cd /app
DISPLAY=:99 python3 -m uvicorn computer_use_server:app --host 0.0.0.0 --port 8080
