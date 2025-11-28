import sqlite3
from werkzeug.security import generate_password_hash

DB = "users.db"

conn = sqlite3.connect(DB)
c = conn.cursor()

try:
    c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'Teacher'")
except Exception:
    pass

try:
    c.execute("ALTER TABLE users ADD COLUMN approved INTEGER DEFAULT 0")
except Exception:
    pass

# Ensure commands table exists
try:
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
except Exception:
    pass

# Create an admin if none exists
c.execute("SELECT * FROM users WHERE role='Admin'")
if not c.fetchone():
    pw_hash = generate_password_hash('AdminPass123!')
    c.execute('''
        INSERT INTO users (username, email, password, role, approved)
        VALUES (?, ?, ?, ?, ?)
    ''', ("Admin", "admin@example.com", pw_hash, "Admin", 1))

conn.commit()
conn.close()
print("Database updated successfully!")
