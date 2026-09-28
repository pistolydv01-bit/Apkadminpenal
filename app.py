import os, sqlite3
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, jsonify, request, session, redirect, render_template

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-secret")
DB = os.environ.get("DB_PATH", "admin.db")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-now")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT UNIQUE NOT NULL,
      name TEXT DEFAULT '',
      tokens INTEGER DEFAULT 0,
      subscription_until TEXT,
      blocked INTEGER DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS plans(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      days INTEGER NOT NULL,
      price REAL NOT NULL
    );
    """)
    defaults = {
      "demo_tokens":"1",
      "group_link":"",
      "announcement":"",
      "maintenance":"0"
    }
    for k,v in defaults.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    if con.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0:
        con.executemany("INSERT INTO plans(name,days,price) VALUES(?,?,?)",[
            ("1 Day",1,0),("7 Days",7,0),("30 Days",30,0)
        ])
    con.commit(); con.close()

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect("/login")
        return fn(*a, **kw)
    return wrapper

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("username")==ADMIN_USERNAME and request.form.get("password")==ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/")
        return render_template("login.html", error="Invalid login")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear(); return redirect("/login")

@app.get("/")
@admin_required
def dashboard():
    con=db()
    stats={
      "users": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
      "blocked": con.execute("SELECT COUNT(*) FROM users WHERE blocked=1").fetchone()[0],
      "premium": con.execute("SELECT COUNT(*) FROM users WHERE subscription_until IS NOT NULL AND subscription_until > ?",(datetime.now(timezone.utc).isoformat(),)).fetchone()[0]
    }
    users=con.execute("SELECT * FROM users ORDER BY id DESC LIMIT 100").fetchall()
    settings=dict(con.execute("SELECT key,value FROM settings").fetchall())
    plans=con.execute("SELECT * FROM plans ORDER BY days").fetchall()
    con.close()
    return render_template("dashboard.html",stats=stats,users=users,settings=settings,plans=plans)

@app.post("/admin/user")
@admin_required
def user():
    data=request.form
    con=db()
    con.execute("""INSERT INTO users(external_id,name,tokens,created_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(external_id) DO UPDATE SET name=excluded.name,tokens=excluded.tokens""",
                (data["external_id"],data.get("name",""),int(data.get("tokens",0)),datetime.now(timezone.utc).isoformat()))
    con.commit(); con.close()
    return redirect("/")

@app.post("/admin/user/<int:uid>/toggle")
@admin_required
def toggle(uid):
    con=db()
    con.execute("UPDATE users SET blocked=1-blocked WHERE id=?",(uid,))
    con.commit(); con.close(); return redirect("/")

@app.post("/admin/settings")
@admin_required
def settings():
    con=db()
    for k in ["demo_tokens","group_link","announcement","maintenance"]:
        con.execute("UPDATE settings SET value=? WHERE key=?",(request.form.get(k,""),k))
    con.commit(); con.close(); return redirect("/")

@app.post("/admin/plan/<int:pid>")
@admin_required
def plan(pid):
    con=db()
    con.execute("UPDATE plans SET name=?,days=?,price=? WHERE id=?",
                (request.form["name"],int(request.form["days"]),float(request.form["price"]),pid))
    con.commit(); con.close(); return redirect("/")

# App-facing read-only API. Add real authentication/rate limiting before production use.
@app.get("/api/config")
def api_config():
    con=db()
    settings=dict(con.execute("SELECT key,value FROM settings").fetchall())
    plans=[dict(x) for x in con.execute("SELECT id,name,days,price FROM plans ORDER BY days")]
    con.close()
    return jsonify({"settings":settings,"plans":plans})

@app.post("/api/register")
def api_register():
    data=request.get_json(silent=True) or {}
    external_id=str(data.get("external_id","")).strip()
    if not external_id: return jsonify(error="external_id required"),400
    con=db()
    con.execute("""INSERT OR IGNORE INTO users(external_id,name,tokens,created_at)
                   VALUES(?,?,?,?)""",
                (external_id,data.get("name",""),0,datetime.now(timezone.utc).isoformat()))
    con.commit(); con.close()
    return jsonify(ok=True)

@app.get("/api/user/<external_id>")
def api_user(external_id):
    con=db()
    row=con.execute("SELECT external_id,name,tokens,subscription_until,blocked FROM users WHERE external_id=?",(external_id,)).fetchone()
    con.close()
    if not row: return jsonify(error="not found"),404
    return jsonify(dict(row))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
