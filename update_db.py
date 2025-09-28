import sqlite3

DB = "users.db"

conn = sqlite3.connect(DB)
c = conn.cursor()

try:
    c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'Teacher'")
except:
    pass

try:
    c.execute("ALTER TABLE users ADD COLUMN approved INTEGER DEFAULT 0")
except:
    pass

c.execute("SELECT * FROM users WHERE role='Admin'")
if not c.fetchone():
    c.execute("""
        INSERT INTO users (username, email, password, role, approved)
        VALUES (?, ?, ?, ?, ?)
    """, ("Admin", "admin@example.com", "AdminPass123!", "Admin", 1))

conn.commit()
conn.close()
print("Database updated successfully!")
