import sqlite3

DB = "users.db"

ADMIN_USERNAME = "Admin"
ADMIN_EMAIL = "aryanrwt018@gmail.com"
ADMIN_PASSWORD = "AdminNewPass123!"
ADMIN_ROLE = "Admin"

conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL,
    approved INTEGER DEFAULT 1
)
""")

c.execute("SELECT * FROM users WHERE role='Admin'")
if not c.fetchone():
    c.execute(
        "INSERT INTO users (username, email, password, role, approved) VALUES (?, ?, ?, ?, ?)",
        (ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_ROLE, 1)
    )
    print("Admin account created.")
else:
    c.execute(
        "UPDATE users SET email=?, password=? WHERE role='Admin'",
        (ADMIN_EMAIL, ADMIN_PASSWORD)
    )
    print("Admin account updated.")

conn.commit()
conn.close()
print("Setup completed.")
