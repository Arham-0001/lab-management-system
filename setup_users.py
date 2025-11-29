import sqlite3
from werkzeug.security import generate_password_hash

DB = "users.db"

ADMIN_USERNAME = "Admin"
ADMIN_EMAIL = "arhamrehman278@gmail.com"
ADMIN_PASSWORD = "Arham277!"
ADMIN_ROLE = "Admin"

conn = sqlite3.connect(DB)
c = conn.cursor()

# ensure users table exists (compatible with server.init_db)
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL,
    approved INTEGER DEFAULT 1
)
''')

c.execute("SELECT * FROM users WHERE role='Admin'")
if not c.fetchone():
    pw_hash = generate_password_hash(ADMIN_PASSWORD)
    c.execute(
        "INSERT INTO users (username, email, password, role, approved) VALUES (?, ?, ?, ?, ?)",
        (ADMIN_USERNAME, ADMIN_EMAIL, pw_hash, ADMIN_ROLE, 1)
    )
    print("Admin account created.")
else:
    pw_hash = generate_password_hash(ADMIN_PASSWORD)
    c.execute(
        "UPDATE users SET email=?, password=? WHERE role='Admin'",
        (ADMIN_EMAIL, pw_hash)
    )
    print("Admin account updated.")

conn.commit()
conn.close()
print("Setup completed.")
