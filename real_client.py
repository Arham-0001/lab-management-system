#!/usr/bin/env python3
"""
real_client.py
Real client for lab PCs that:
 - polls server for commands (/poll-commands/<client_id>)
 - uploads screenshots to /upload/<client_id>
 - posts heartbeat to /heartbeatz/<client_id>
 - reports command results back via POST to /poll-commands/<client_id>

Usage:
  SERVER=http://192.168.1.10:5000 CLIENT_ID=labpc1 python3 real_client.py
"""

import os
import time
import json
import threading
import io
import platform
import subprocess
from typing import Optional

import requests

# Try to use mss for fast screenshots; fallback to PIL/pyscreenshot
try:
    import mss
    USE_MSS = True
except Exception:
    from PIL import ImageGrab
    USE_MSS = False

# --- Configuration (can be overridden by env or config.json) ---
SERVER = os.environ.get("SERVER", "http://127.0.0.1:5000")
CLIENT_ID = os.environ.get("CLIENT_ID") or platform.node() or "client-unknown"
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))      # seconds
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "15"))
ENABLE_REMOTE_POWER = os.environ.get("ENABLE_REMOTE_POWER", "false").lower() in ("1","true","yes")
AUTH_TOKEN = os.environ.get("CLIENT_AUTH_TOKEN")  # optional header auth token

# Optional: try to load config.json in cwd
cfg_path = os.path.join(os.getcwd(), "client_config.json")
if os.path.exists(cfg_path):
    try:
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
            SERVER = cfg.get("server", SERVER)
            CLIENT_ID = cfg.get("client_id", CLIENT_ID)
            POLL_INTERVAL = int(cfg.get("poll_interval", POLL_INTERVAL))
            HEARTBEAT_INTERVAL = int(cfg.get("heartbeat_interval", HEARTBEAT_INTERVAL))
            ENABLE_REMOTE_POWER = bool(cfg.get("enable_remote_power", ENABLE_REMOTE_POWER))
    except Exception as e:
        print("Warning: failed to read client_config.json:", e)

HEADERS = {}
if AUTH_TOKEN:
    HEADERS["Authorization"] = f"Bearer {AUTH_TOKEN}"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": f"RealClient/{CLIENT_ID}", **HEADERS})

stop_event = threading.Event()


# --- Screenshot capture ---
def capture_screenshot() -> bytes:
    """Return PNG bytes of the current screen."""
    try:
        if USE_MSS:
            with mss.mss() as s:
                monitor = s.monitors[0]  # full desktop
                img = s.grab(monitor)
                # convert to PNG bytes via PIL
                from PIL import Image
                im = Image.frombytes("RGB", img.size, img.rgb)
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                return buf.getvalue()
        else:
            # Pillow ImageGrab (Windows/macOS) or pyscreenshot on Linux if available
            im = ImageGrab.grab()
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        # As a fallback, return a tiny PNG binary (1x1)
        print("Screenshot failed:", e)
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAn8B9o7sQwAAAABJRU5ErkJggg=="
        )


# --- Command handlers ---
def handle_command(cmd: dict):
    cid = cmd.get("id")
    command = cmd.get("command")
    args = cmd.get("args", "")
    result = f"unknown command {command}"

    try:
        if command == "screenshot":
            png = capture_screenshot()
            files = {"screenshot": ("s.png", io.BytesIO(png), "image/png")}
            try:
                up = SESSION.post(f"{SERVER.rstrip('/')}/upload/{CLIENT_ID}", files=files, timeout=20)
                if up.ok:
                    result = "screenshot uploaded"
                else:
                    result = f"upload failed status={up.status_code}"
            except Exception as e:
                result = f"upload exception: {e}"

        elif command in ("restart", "shutdown"):
            if not ENABLE_REMOTE_POWER:
                result = f"{command} blocked by client config (ENABLE_REMOTE_POWER=False)"
            else:
                # careful: these are destructive operations — only run if explicitly enabled
                result = perform_power_action(command)

        else:
            result = f"unhandled command: {command} args={args}"

    except Exception as e:
        result = f"error executing command: {e}"

    # Report back result
    try:
        SESSION.post(f"{SERVER.rstrip('/')}/poll-commands/{CLIENT_ID}",
                     json={"id": cid, "status": "done", "result": result}, timeout=8)
    except Exception as e:
        print("Failed to report result:", e)


def perform_power_action(action: str) -> str:
    """
    Very careful: only performs OS-level restart/shutdown if enabled.
    Returns a short status string.
    """
    try:
        system = platform.system().lower()
        if action == "restart":
            if system == "windows":
                subprocess.Popen(["shutdown", "/r", "/t", "10"])
            elif system in ("linux", "darwin"):
                # requires privileges; use sudo if needed (lab admin should configure)
                subprocess.Popen(["sudo", "shutdown", "-r", "+0"])
            else:
                return f"restart unsupported on {system}"
            return "restart triggered"
        else:  # shutdown
            if system == "windows":
                subprocess.Popen(["shutdown", "/s", "/t", "10"])
            elif system in ("linux", "darwin"):
                subprocess.Popen(["sudo", "shutdown", "-h", "+0"])
            else:
                return f"shutdown unsupported on {system}"
            return "shutdown triggered"
    except Exception as e:
        return f"power action failed: {e}"


# --- Polling loop ---
def polling_loop():
    backoff = 1
    while not stop_event.is_set():
        try:
            r = SESSION.get(f"{SERVER.rstrip('/')}/poll-commands/{CLIENT_ID}", timeout=12)
            if r.status_code == 200:
                data = r.json()
                for cmd in data.get("commands", []):
                    # handle each command in its own short thread to avoid blocking polling
                    threading.Thread(target=handle_command, args=(cmd,), daemon=True).start()
                backoff = 1
            else:
                print("Poll returned status", r.status_code)
                time.sleep(backoff)
                backoff = min(60, backoff * 2)
                continue
        except Exception as e:
            print("Poll error:", e)
            time.sleep(backoff)
            backoff = min(60, backoff * 2)
            continue

        time.sleep(POLL_INTERVAL)


# --- Heartbeat loop ---
def heartbeat_loop():
    last = 0
    while not stop_event.is_set():
        now = time.time()
        try:
            if now - last >= HEARTBEAT_INTERVAL:
                SESSION.post(f"{SERVER.rstrip('/')}/heartbeatz/{CLIENT_ID}", timeout=6)
                last = now
        except Exception:
            pass
        time.sleep(1)


# --- Main ---
def main():
    print("Real client starting. SERVER=", SERVER, "CLIENT_ID=", CLIENT_ID,
          "ENABLE_REMOTE_POWER=", ENABLE_REMOTE_POWER)
    poll_t = threading.Thread(target=polling_loop, daemon=True)
    hb_t = threading.Thread(target=heartbeat_loop, daemon=True)
    poll_t.start()
    hb_t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping client...")
        stop_event.set()


if __name__ == "__main__":
    main()
