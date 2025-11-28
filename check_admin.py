import sqlite3

conn = sqlite3.connect("users.db")
c = conn.cursor()
c.execute("SELECT id, username, email, role FROM users WHERE role='Admin'")
admins = c.fetchall()
conn.close()

for a in admins:
    print(f"ID: {a[0]}, Username: {a[1]}, Email: {a[2]}")
