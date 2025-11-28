"""
Simple client agent to poll server for commands and act on them.
Safe by default: restart/shutdown are simulated unless --exec flag given or SAFE=0.

Usage:
  set SERVER=http://127.0.0.1:5000
  set CLIENT_ID=client1
  python client_agent.py

Environment variables:
  SERVER (default http://127.0.0.1:5000)
  CLIENT_ID (default client1)
  POLL_INTERVAL (seconds, default 10)
  SAFE (1 default: do not execute destructive commands; set 0 to allow)
"""
import os
import time
import requests
import io
import json
import argparse
try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except Exception:
    ImageGrab = None
    PIL_AVAILABLE = False

SERVER = os.environ.get('SERVER', 'http://127.0.0.1:5000')
CLIENT_ID = os.environ.get('CLIENT_ID', 'client1')
POLL = int(os.environ.get('POLL_INTERVAL', '10'))
SAFE = os.environ.get('SAFE', '1') != '0'

parser = argparse.ArgumentParser()
parser.add_argument('--server', help='Server URL')
parser.add_argument('--client', help='Client ID')
parser.add_argument('--poll', type=int, help='Poll interval seconds')
parser.add_argument('--exec', action='store_true', help='Allow destructive commands (restart/shutdown)')
args = parser.parse_args()
if args.server:
    SERVER = args.server
if args.client:
    CLIENT_ID = args.client
if args.poll:
    POLL = args.poll
if args.exec:
    SAFE = False

print(f"Client agent starting. SERVER={SERVER}, CLIENT_ID={CLIENT_ID}, POLL={POLL}, SAFE={SAFE}")

session = requests.Session()

def poll_once():
    try:
        r = session.get(f"{SERVER}/poll-commands/{CLIENT_ID}", timeout=10)
        r.raise_for_status()
        data = r.json()
        cmds = data.get('commands', [])
        for cmd in cmds:
            cid = cmd.get('id')
            command = cmd.get('command')
            args = cmd.get('args')
            print('Got command', cid, command, args)
            result = ''
            status = 'done'
            if command == 'screenshot':
                try:
                    if not PIL_AVAILABLE:
                        raise RuntimeError('Pillow (PIL) not available')
                    img = ImageGrab.grab()
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    buf.seek(0)
                    files = {'screenshot': ('screenshot.png', buf, 'image/png')}
                    up = session.post(f"{SERVER}/upload/{CLIENT_ID}", files=files, timeout=20)
                    if up.ok:
                        result = 'screenshot uploaded'
                    else:
                        result = f'upload failed: {up.status_code}'
                except Exception as e:
                    result = f'screenshot error: {e} (install Pillow: pip install Pillow)'
            elif command in ('restart', 'shutdown'):
                if SAFE:
                    result = f'simulated {command}'
                else:
                    try:
                        if os.name == 'nt':
                            if command == 'restart':
                                os.system('shutdown /r /t 0')
                            else:
                                os.system('shutdown /s /t 0')
                        else:
                            if command == 'restart':
                                os.system('sudo reboot')
                            else:
                                os.system('sudo shutdown -h now')
                        result = f'executed {command}'
                    except Exception as e:
                        result = f'execute error: {e}'
            else:
                result = f'unknown command: {command}'

            # Post back result
            try:
                session.post(f"{SERVER}/poll-commands/{CLIENT_ID}", json={'id':cid,'status':status,'result':result}, timeout=10)
            except Exception as e:
                print('Failed to post result', e)
    except Exception as e:
        print('Poll error', e)

if __name__ == '__main__':
    while True:
        poll_once()
        time.sleep(POLL)
