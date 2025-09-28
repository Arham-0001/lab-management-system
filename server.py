from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from flask_cors import CORS
import time, os, sqlite3, random, string, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = Flask(__name__)
CORS(app)
app.secret_key = "super-secret-key"

commands = {}
heartbeats = {}
os.makedirs("static/screenshots", exist_ok=True)

DB = "users.db"
CODE_STORE = {}
CODE_EXPIRY = 600

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
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
    conn.commit()
    conn.close()

init_db()

def password_valid(password):
    import re
    pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*]).{8,}$'
    return re.match(pattern, password)

def send_email(to_email, subject, html_content):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = "innovisionorg018@gmail.com"
    smtp_pass = "hplp tkfi qnia dfcx"
    msg = MIMEMultipart('alternative')
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

def send_verification_email(to_email, code):
    html_content = f"""
    <div style="font-family:sans-serif; text-align:center; padding:20px;">
    <h2>SLMMS Verification Code</h2>
    <p>Your verification code is:</p>
    <div style="font-size:32px; font-weight:bold; margin:10px 0;">{code}</div>
    <p>Expires in 10 minutes.</p>
    </div>
    """
    send_email(to_email, "SLMMS Verification Code", html_content)

def send_rejection_email(to_email, reason):
    html_content = f"""
    <div style="font-family:sans-serif; text-align:center; padding:20px;">
    <h2>SLMMS Account Rejected</h2>
    <p>Your account creation request was rejected by admin.</p>
    <p><b>Reason:</b> {reason}</p>
    </div>
    """
    send_email(to_email, "SLMMS Account Rejection", html_content)

# -------- Routes --------

@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
        user = c.fetchone()
        conn.close()
        if user:
            role = user[4]
            approved = user[5]
            if role == "Admin" or approved == 1:
                session['user_email'] = email
                session['role'] = role
                flash("Login successful","success")
                return redirect(url_for("dashboard"))  
            else:
                flash("Account not approved. Contact admin","error")
        else:
            flash("Invalid credentials","error")
    return render_template("login.html")


@app.route("/register", methods=["GET","POST"])
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
        c.execute("INSERT INTO users (username,email,password,role,approved) VALUES (?,?,?,?,?)",
                  (username,email,password,"Teacher",0))
        conn.commit()
        conn.close()
        flash("Account created! Contact admin to approve.","info")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/forgot-password", methods=["GET","POST"])
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
            send_verification_email(email, code)
            flash("Verification code sent","info")
            return redirect(url_for("reset_password", email=email))
        else:
            flash("Email not registered","error")
    return render_template("forgot_password.html")

@app.route("/reset-password/<email>", methods=["GET","POST"])
def reset_password(email):
    if request.method=="POST":
        password = request.form.get("password")
        if not password_valid(password):
            flash("Password invalid","error")
            return redirect(url_for("reset_password",email=email))
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("UPDATE users SET password=? WHERE email=?",(password,email))
        conn.commit()
        conn.close()
        CODE_STORE.pop(email,None)
        flash("Password updated","success")
        return redirect(url_for("login"))
    return render_template("reset_password.html", email=email)

@app.route("/dashboard")
def dashboard():
    if 'user_email' not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Pending approvals for admins
    if session.get('role') == "Admin":
        c.execute("SELECT id, username, email FROM users WHERE approved=0")
        pending_users = c.fetchall()
    else:
        pending_users = []

    # Simulated PC statuses
    pcs = []
    c.execute("SELECT id, username FROM users")
    users = c.fetchall()
    for u in users:
        status = random.choice(["Online","Idle","Offline"])
        pcs.append({"id":u[1], "status":status})

    pcs_total = len(pcs)
    pcs_online = sum(1 for p in pcs if p['status']=="Online")
    pcs_idle = sum(1 for p in pcs if p['status']=="Idle")
    pcs_offline = sum(1 for p in pcs if p['status']=="Offline")

    conn.close()
    return render_template("dashboard.html", pending_users=pending_users,
                           pcs=pcs, pcs_total=pcs_total, pcs_online=pcs_online,
                           pcs_idle=pcs_idle, pcs_offline=pcs_offline,
                           heartbeats=heartbeats)

@app.route("/approve-user/<int:user_id>", methods=["POST"])
def approve_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET approved=1 WHERE id=?",(user_id,))
    c.execute("SELECT email FROM users WHERE id=?",(user_id,))
    email = c.fetchone()[0]
    conn.commit()
    conn.close()
    flash("User approved","success")
    return jsonify({"ok":True})

@app.route("/reject-user/<int:user_id>", methods=["POST"])
def reject_user(user_id):
    reason = request.form.get("reason")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT email FROM users WHERE id=?",(user_id,))
    email = c.fetchone()[0]
    c.execute("DELETE FROM users WHERE id=?",(user_id,))
    conn.commit()
    conn.close()
    send_rejection_email(email, reason)
    flash("User rejected and email sent","error")
    return jsonify({"ok":True})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/heartbeatz/<client_id>", methods=["POST"])
def heartbeat(client_id):
    heartbeats[client_id] = time.time()
    return jsonify({client_id:"alive"})

@app.route("/status/<client_id>")
def status(client_id):
    if client_id not in heartbeats:
        return jsonify({"status":"Unknown"})
    last_seen = time.time() - heartbeats[client_id]
    return jsonify({"status":"Online" if last_seen<60 else "Offline"})

@app.route("/upload/<client_id>", methods=["POST"])
def upload_screenshot(client_id):
    if "screenshot" not in request.files:
        return jsonify({"msg":"No screenshot file"}), 400
    screenshot = request.files["screenshot"]
    path = f"static/screenshots/{client_id}.png"
    screenshot.save(path)
    return jsonify({"msg":"Screenshot uploaded"})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
