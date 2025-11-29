"""
simulate_many_clients.py

Creates test users in the local `users.db` (if missing) and runs N simulated clients
on the same machine. Each client polls the server for commands and handles:
 - screenshot: uploads a small placeholder PNG
 - restart/shutdown: replies with simulated result

Usage:
  python simulate_many_clients.py --num 5 --base sim

Environment:
  SERVER (default http://127.0.0.1:5000)
"""
import argparse
import threading
import time
import io
import base64
import sqlite3
import os
import requests

try:
    from werkzeug.security import generate_password_hash
except Exception:
    def generate_password_hash(p):
        return p


PLACEHOLDER_PNG_B64 = (
    # 1x1 transparent PNG
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAn8B9o7sQwAAAABJRU5ErkJggg=="
)


def ensure_users(clients, db_path='users.db'):
    if not os.path.exists(db_path):
        print('DB not found at', db_path)
        return
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for cl in clients:
        c.execute('SELECT id FROM users WHERE username=?', (cl,))
        if not c.fetchone():
            email = f"{cl}@example.com"
            pw = generate_password_hash('SimPass123!')
            try:
                c.execute('INSERT INTO users (username,email,password,role,approved) VALUES (?,?,?,?,?)',
                          (cl, email, pw, 'Teacher', 1))
                print('Inserted user', cl)
            except Exception as e:
                print('Insert user failed', cl, e)
    conn.commit()
    conn.close()


def generate_screenshot_bytes(client_id):
    # Attempt to generate a small image using Pillow if available, else fallback to placeholder.
    try:
        from PIL import Image, ImageDraw, ImageFont
        w, h = 640, 360
        img = Image.new('RGB', (w, h), color=(70, 130, 180))
        d = ImageDraw.Draw(img)
        # Load default font and write client id and timestamp
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        text = f"{client_id} - {time.strftime('%Y-%m-%d %H:%M:%S')}"
        # center text
        tw, th = d.textsize(text, font=font)
        d.text(((w-tw)/2, (h-th)/2), text, fill=(255,255,255), font=font)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        return base64.b64decode(PLACEHOLDER_PNG_B64)


def heartbeat_loop(server, client_id, interval=15, session=None, stop_event=None):
    if session is None:
        session = requests.Session()
    while not (stop_event and stop_event.is_set()):
        try:
            session.post(f"{server}/heartbeatz/{client_id}", timeout=8)
        except Exception as e:
            print(f"[{client_id}] Heartbeat failed: {e}")
        time.sleep(interval)


def client_thread_loop(server, client_id, poll_interval=5, heartbeat_interval=15, stop_event=None):
    session = requests.Session()
    session.headers.update({'User-Agent': f'Simulator/{client_id}'})
    png_bytes = generate_screenshot_bytes(client_id)
    # Start heartbeat in this thread's context if configured
    hb_last = 0
    while not (stop_event and stop_event.is_set()):
        try:
            # poll for commands
            r = session.get(f"{server}/poll-commands/{client_id}", timeout=10)
            if r.status_code != 200:
                # server might be down
                time.sleep(poll_interval)
                continue
            data = r.json()
            for cmd in data.get('commands', []):
                cid = cmd.get('id')
                command = cmd.get('command')
                args = cmd.get('args')
                print(f"[{client_id}] Got command {cid} {command} {args}")
                result = ''
                if command == 'screenshot':
                    # regenerate screenshot bytes to make each image unique
                    png_bytes = generate_screenshot_bytes(client_id)
                    files = {'screenshot': ('s.png', io.BytesIO(png_bytes), 'image/png')}
                    try:
                        up = session.post(f"{server}/upload/{client_id}", files=files, timeout=15)
                        if up.ok:
                            result = 'screenshot uploaded (placeholder)'
                        else:
                            result = f'upload failed {up.status_code}'
                    except Exception as e:
                        result = f'upload error: {e}'
                elif command in ('restart','shutdown'):
                    # Simulate a brief downtime for restart/shutdown
                    print(f"[{client_id}] Simulating {command}...")
                    time.sleep(2)
                    result = f'simulated {command} successfully'
                else:
                    result = f'unknown command {command}'
                # report back
                try:
                    session.post(f"{server}/poll-commands/{client_id}", json={'id':cid,'status':'done','result':result}, timeout=8)
                except Exception as e:
                    print(f"[{client_id}] Failed to report result: {e}")
        except Exception as e:
            print(f"[{client_id}] Poll error: {e}")

        # send heartbeat periodically (if configured)
        try:
            now = time.time()
            if now - hb_last > heartbeat_interval:
                session.post(f"{server}/heartbeatz/{client_id}", timeout=6)
                hb_last = now
        except Exception:
            pass
        time.sleep(poll_interval)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--num', type=int, default=5, help='Number of simulated clients')
    p.add_argument('--base', type=str, default='sim', help='Base name for client ids')
    p.add_argument('--server', type=str, default=os.environ.get('SERVER','http://127.0.0.1:5000'))
    p.add_argument('--poll', type=int, default=5, help='Poll interval seconds')
    p.add_argument('--heartbeat', type=int, default=15, help='Heartbeat interval seconds')
    args = p.parse_args()

    clients = [f"{args.base}{i}" for i in range(1, args.num+1)]
    ensure_users(clients)

    threads = []
    stop_events = []
    for cl in clients:
        stop_ev = threading.Event()
        stop_events.append(stop_ev)
        t = threading.Thread(target=client_thread_loop, args=(args.server, cl, args.poll, args.heartbeat, stop_ev), daemon=True)
        t.start()
        threads.append(t)
    print('Started simulated clients:', clients)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('Stopping simulators')
        for ev in stop_events: ev.set()


if __name__ == '__main__':
    main()
