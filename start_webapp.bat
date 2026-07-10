@echo off
REM Launch the Dream Machine web app (API + PWA) on port 8000.
REM Reachable from your phone over Tailscale at http://<laptop-tailscale-ip>:8000
cd /d "%~dp0"
".venv\Scripts\python.exe" -m webapp --port 8000
