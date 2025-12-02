from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_cors import CORS
import time, os, sqlite3, random, string, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash 
# import module

app = Flask(__name__)
CORS(app)

# Secure secret key
app.secret_key = os.environ.get("FLASK_SECRET") or os.urandom(24)

# Read debug value from env (default off)
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"


commands = {}   # store commands per client
heartbeats = {} # store last heartbeat times
os.makedirs("static/screenshots", exist_ok=True)

DB = "users.db"   # SQLite DB file
CODE_STORE = {}   # email: {code, time}
CODE_EXPIRY = 600 # code valid for 10 minutes

def init_db(): # initialize DB and tables if not exist
    conn = sqlite3.connect(DB, timeout=30)
    c = conn.cursor()
# Better concurrency
    c.execute("PRAGMA journal_mode=WAL;")

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'Teacher',
            approved INTEGER DEFAULT 0
        )
    ''')
    # Commands table for server-client actions
    c.execute('''
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT,
            command TEXT,
            args TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at REAL,
            updated_at REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db() # ensure DB initialized


def _log_smtp_config():
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = os.environ.get('SMTP_PORT', '587')
    smtp_user = os.environ.get('SMTP_USER')
    smtp_use_tls = os.environ.get('SMTP_USE_TLS', '1')
    print(f"SMTP config: server={smtp_server} port={smtp_port} user={'set' if smtp_user else 'NOT SET'} use_tls={smtp_use_tls}")

_log_smtp_config()

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user_email' not in session or session.get('role','').lower() != 'admin':
            return jsonify({'error':'admin required'}), 403
        return fn(*args, **kwargs)
    return wrapper

def password_valid(password):
    import re
    pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*]).{8,}$'
    return re.match(pattern, password)

def send_email(to_email, subject, html_content): # send HTML email
    # Load SMTP config from environment variables for security
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASS')
    # Allow disabling STARTTLS for local debug servers
    smtp_use_tls = os.environ.get('SMTP_USE_TLS', '1') in ('1', 'true', 'yes')
    if not smtp_user or not smtp_pass:
        # If no credentials are configured, we will attempt to send without auth
        # (useful for local debug SMTP servers on localhost).
        # If you want to force skipping emails entirely, set SMTP_USER and SMTP_PASS.
        if smtp_server not in ('localhost', '127.0.0.1'):
            print('SMTP credentials missing and server is not localhost; skipping email to', to_email)
            return False
    msg = MIMEMultipart('alternative')
    from_addr = smtp_user or f"no-reply@{smtp_server}"
    msg['From'] = from_addr
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            # If TLS is requested/available, try to upgrade
            if smtp_use_tls:
                try:
                    server.starttls()
                except Exception:
                    # ignore starttls failures for local debug servers
                    pass

            # If credentials provided, attempt to login
            if smtp_user and smtp_pass:
                try:
                    server.login(smtp_user, smtp_pass)
                except Exception as e:
                    print('SMTP login failed:', e)
                    # proceed only if server allows sending without login
            server.send_message(msg)
        return True
    except Exception as e:
        print('SMTP send failed for', to_email, e)
        return False

def send_verification_email(to_email, code): # send code email
    html_content = f"""
    <div style="font-family:sans-serif; text-align:center; padding:20px;">
    <h2>SLMMS Verification Code</h2>
    <p>Your verification code is:</p>
    <div style="font-size:32px; font-weight:bold; margin:10px 0;">{code}</div>
    <p>Expires in 10 minutes.</p>
    </div>
    """
    # Return whether we actually attempted / succeeded in sending the email.
    # send_email returns True on success, False on failure/skip.
    try:
        return send_email(to_email, "SLMMS Verification Code", html_content)
    except Exception:
        return False

def send_rejection_email(to_email, reason): # send rejection email
    html_content = f"""
    <div style="font-family:sans-serif; text-align:center; padding:20px;">
    <h2>SLMMS Account Rejected</h2>
    <p>Your account creation request was rejected by admin.</p>
    <p><b>Reason:</b> {reason}</p>
    </div>
    """
    try:
        return send_email(to_email, "SLMMS Account Rejection", html_content)
    except Exception:
        return False

# -------- Routes --------

@app.route("/") # main page
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"]) # login page
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()
        if user:
            # user schema: id, username, email, password, role, approved
            stored_hash = user[3]
            role = user[4]
            approved = user[5]
            # Support legacy plaintext passwords: if stored value isn't a werkzeug hash,
            # allow direct match and re-hash the password for future logins.
            valid = False
            try:
                valid = check_password_hash(stored_hash, password)
            except Exception:
                valid = False
            if not valid:
                # fallback: stored_hash may actually be plaintext password from old DB
                if stored_hash == password:
                    # migrate: re-hash and update DB
                    try:
                        new_hash = generate_password_hash(password)
                        conn2 = sqlite3.connect(DB)
                        c2 = conn2.cursor()
                        c2.execute("UPDATE users SET password=? WHERE email=?", (new_hash, email))
                        conn2.commit()
                        conn2.close()
                        valid = True
                    except Exception as e:
                        print('Failed to migrate plaintext password for', email, e)
                else:
                    flash("Invalid credentials","error")
                    return render_template("login.html")
            if (role and str(role).lower() == "admin") or approved == 1:
                session['user_email'] = email
                session['role'] = role
                flash("Login successful","success")
                return redirect(url_for("dashboard"))
            else:
                flash("Account not approved. Contact admin","error")
        else:
            flash("Invalid credentials","error")
    return render_template("login.html")


@app.route("/register", methods=["GET","POST"]) # registration page
def register():
    if request.method=="POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        if not username or not email or not password:
            flash("All fields required","error")
            return redirect(url_for("register"))
        if not password_valid(password):
            flash("Password must include upper, lower, number, special char & min 8 chars","error")
            return redirect(url_for("register"))
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        if c.fetchone():
            flash("Email already registered","error")
            conn.close()
            return redirect(url_for("register"))
        pw_hash = generate_password_hash(password)
        c.execute("INSERT INTO users (username,email,password,role,approved) VALUES (?,?,?,?,?)",
                  (username,email,pw_hash,"Teacher",0))
        conn.commit()
        conn.close()
        flash("Account created! Contact admin to approve.","info")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/forgot-password", methods=["GET","POST"]) # forgot password
def forgot_password():
    if request.method=="POST":
        email = request.form.get("email")
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()
        if user:
            code = ''.join(random.choices(string.digits,k=6))
            CODE_STORE[email] = {"code": code, "time": time.time()}
            sent = send_verification_email(email, code)
            # If email send failed (or skipped), show the code in UI for development convenience.
            if not sent:
                flash(f"Verification code (dev): {code}", "info")
            flash("Verification code sent","info")
            return redirect(url_for("reset_password", email=email))
        else:
            flash("Email not registered","error")
    return render_template("forgot_password.html")

@app.route("/reset-password/<email>", methods=["GET","POST"]) # reset password
def reset_password(email):
    if request.method=="POST":
        code = request.form.get('code')
        password = request.form.get("password")
        entry = CODE_STORE.get(email)
        if not entry or entry.get('code') != code or (time.time() - entry.get('time',0))>CODE_EXPIRY:
            flash('Invalid or expired code','error')
            return redirect(url_for('forgot_password'))
        if not password_valid(password):
            flash("Password invalid","error")
            return redirect(url_for("reset_password",email=email))
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        pw_hash = generate_password_hash(password)
        c.execute("UPDATE users SET password=? WHERE email=?",(pw_hash,email))
        conn.commit()
        conn.close()
        CODE_STORE.pop(email,None)
        flash("Password updated","success")
        return redirect(url_for("login"))
    return render_template("reset_password.html", email=email)

# ----- Command queue endpoints -----
@app.route('/enqueue-command', methods=['POST'])      # add command for client
def enqueue_command():
    # expected json: {client_id, command, args}
    data = request.get_json() or {}
    client_id = data.get('client_id')
    command = data.get('command')
    args = data.get('args', '')
    if not client_id or not command:
        return jsonify({'error':'client_id and command required'}), 400
    now = time.time()
    # For safety, prevent duplicate pending 'screenshot' commands for the same client
    if command == 'screenshot':
        conn_check = sqlite3.connect(DB)
        c_check = conn_check.cursor()
        c_check.execute("SELECT id FROM commands WHERE client_id=? AND command=? AND status='pending'", (client_id, command))
        if c_check.fetchone():
            conn_check.close()
            return jsonify({'ok': False, 'message': 'screenshot already pending'}), 409
        conn_check.close()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('INSERT INTO commands (client_id,command,args,created_at,updated_at) VALUES (?,?,?,?,?)',
              (client_id, command, str(args), now, now))
    conn.commit()
    conn.close()
    return jsonify({'ok':True})

@app.route('/poll-commands/<client_id>', methods=['GET','POST'])  # get or post command results
def poll_commands(client_id):
    # Clients call to get pending commands. If POST with result, will update status.
    if request.method=='POST':
        data = request.get_json() or {}
        cmd_id = data.get('id')
        status = data.get('status')
        result = data.get('result')
        if not cmd_id:
            return jsonify({'error':'id required'}), 400
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute('UPDATE commands SET status=?, result=?, updated_at=? WHERE id=?', (status or 'done', str(result), time.time(), cmd_id))
        conn.commit()
        conn.close()
        return jsonify({'ok':True})
    # GET: return pending commands
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, command, args, status, created_at FROM commands WHERE client_id=? AND status='pending'", (client_id,))
    rows = c.fetchall()
    conn.close()
    items = [{'id':r[0],'command':r[1],'args':r[2],'status':r[3],'created_at':r[4]} for r in rows]
    return jsonify({'commands':items})

@app.route("/dashboard") # dashboard page
def dashboard():
    if 'user_email' not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Pending approvals for admins
    if session.get('role','').lower() == "admin":
        c.execute("SELECT id, username, email FROM users WHERE approved=0")
        pending_users = c.fetchall()
    else:
        pending_users = []

    # Determine PC list from registered users (excluding simulator accounts) and heartbeat entries
    pcs = []
    c.execute("SELECT id, username FROM users")
    users = c.fetchall()
    real_usernames = []
    for u in users:
        uname = u[1]
        if not uname:
            continue
        # Exclude simulator accounts created by tests (start with 'sim')
        if uname.lower().startswith('sim'):
            continue
        real_usernames.append(uname)

    # Build set of clients to show: registered real usernames + heartbeat-known clients
    client_ids = set(real_usernames) | set(heartbeats.keys())
    now_time = time.time()
    for cid in sorted(client_ids):
        hb_time = heartbeats.get(cid)
        if hb_time:
            age = now_time - hb_time
            if age < 60:
                status = "Online"
            elif age < 300:
                status = "Idle"
            else:
                status = "Offline"
        else:
            status = "Offline"
        pcs.append({"id": cid, "status": status})

    pcs_total = len(pcs)
    pcs_online = sum(1 for p in pcs if p['status']=="Online")
    pcs_idle = sum(1 for p in pcs if p['status']=="Idle")
    pcs_offline = sum(1 for p in pcs if p['status']=="Offline")

    conn.close()
    now_ts = int(time.time())
    return render_template("dashboard.html", pending_users=pending_users,
                           pcs=pcs, pcs_total=pcs_total, pcs_online=pcs_online,
                           pcs_idle=pcs_idle, pcs_offline=pcs_offline,
                           heartbeats=heartbeats, now=now_ts)

@app.route("/approve-user/<int:user_id>", methods=["POST"])
@admin_required
def approve_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT email, username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error':'user not found'}), 404
    email, username = row[0], row[1]
    c.execute("UPDATE users SET approved=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    # notify user by email (best-effort)
    try:
        html = f"""
        <div style='font-family:sans-serif; text-align:center; padding:20px;'>
        <h2>SLMMS Account Approved</h2>
        <p>Hello {username or ''},</p>
        <p>Your account has been approved by the administrator. You can now log in.</p>
        </div>
        """
        sent = send_email(email, "SLMMS Account Approved", html)
    except Exception as e:
        print('Approval email send failed', e)
        sent = False

    flash("User approved","success")
    return jsonify({"ok":True, 'email_sent': bool(sent)})

@app.route("/reject-user/<int:user_id>", methods=["POST"])
@admin_required
def reject_user(user_id):
    reason = request.form.get("reason") or "No reason provided"
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT email, username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error':'user not found'}), 404
    email, username = row[0], row[1]
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    try:
        sent = send_rejection_email(email, reason)
    except Exception as e:
        print('Rejection email send failed', e)
        sent = False
    flash("User rejected and email sent","error")
    return jsonify({"ok":True, 'email_sent': bool(sent)})

@app.route("/logout") # logout
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/heartbeatz/<client_id>", methods=["POST"])     # heartbeat
def heartbeat(client_id):
    heartbeats[client_id] = time.time()
    return jsonify({client_id:"alive"})

@app.route("/status/<client_id>") # client status
def status(client_id):
    if client_id not in heartbeats:
        return jsonify({"status":"Unknown"})
    last_seen = time.time() - heartbeats[client_id]
    return jsonify({"status":"Online" if last_seen<60 else "Offline"})

@app.route("/upload/<client_id>", methods=["POST"]) # upload screenshot
def upload_screenshot(client_id):
    if "screenshot" not in request.files:
        return jsonify({"msg":"No screenshot file"}), 400
    screenshot = request.files["screenshot"]
    path = f"static/screenshots/{client_id}.png"
    screenshot.save(path)
    return jsonify({"msg":"Screenshot uploaded"})


@app.route('/screenshot/<client_id>', methods=['GET']) # get screenshot info
def screenshot_info(client_id):
    # Provide info about a screenshot: exists, mtime and a url with cache-busting mtime
    path = os.path.join('static', 'screenshots', f"{client_id}.png")
    exists = os.path.exists(path)
    mtime = int(os.path.getmtime(path)) if exists else 0
    url = url_for('static', filename=f'screenshots/{client_id}.png')
    if exists:
        url = f"{url}?t={mtime}"
    return jsonify({"exists": exists, "mtime": mtime, "url": url})


@app.route('/clients-status', methods=['GET']) # get all clients status
def clients_status():
    # Returns current set of clients with status and screenshot info
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, username FROM users")
    users = c.fetchall()
    real_usernames = []
    for u in users:
        uname = u[1]
        if not uname:
            continue
        # Exclude simulator accounts created by tests (start with 'sim')
        if uname.lower().startswith('sim'):
            continue
        real_usernames.append(uname)
    conn.close()

    now_time = time.time()
    client_ids = set(real_usernames) | set(heartbeats.keys())

    clients = []
    pcs_online = pcs_idle = pcs_offline = 0
    for cid in sorted(client_ids):
        hb_time = heartbeats.get(cid)
        if hb_time:
            age = now_time - hb_time
            if age < 60:
                status = 'Online'
                pcs_online += 1
            elif age < 300:
                status = 'Idle'
                pcs_idle += 1
            else:
                status = 'Offline'
                pcs_offline += 1
        else:
            status = 'Offline'
            pcs_offline += 1

        # Screenshot metadata
        path = os.path.join('static', 'screenshots', f"{cid}.png")
        exists = os.path.exists(path)
        mtime = int(os.path.getmtime(path)) if exists else 0
        url = url_for('static', filename=f'screenshots/{cid}.png')
        if exists:
            url = f"{url}?t={mtime}"

        clients.append({
            'id': cid,
            'status': status,
            'screenshot_exists': exists,
            'screenshot_mtime': mtime,
            'screenshot_url': url
        })

    # Compute pending approvals (exclude simulator accounts starting with 'sim')
    try:
        conn2 = sqlite3.connect(DB)
        c2 = conn2.cursor()
        c2.execute("SELECT COUNT(*) FROM users WHERE approved=0 AND username IS NOT NULL AND LOWER(username) NOT LIKE 'sim%'")
        pending_count = c2.fetchone()[0] or 0
        conn2.close()
    except Exception:
        pending_count = 0

    return jsonify({
        'clients': clients,
        'counts': {'total': len(clients), 'online': pcs_online, 'idle': pcs_idle, 'offline': pcs_offline},
        'pending_approvals': pending_count
    })

if __name__=="__main__": # run server
    app.run(host="0.0.0.0", port=5000, debug=DEBUG) # debug mode if set
