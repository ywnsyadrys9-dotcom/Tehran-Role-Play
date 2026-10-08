import sqlite3, os
from flask import Flask, request, redirect, url_for, session, jsonify, render_template, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB = os.path.join(os.path.dirname(__file__), "tehran_rp.db")

FORMS = {
    "admin": "فرم درخواست ادمینی",
    "gang": "فرم لیدری گتو",
    "helper": "فرم درخواست هلپری",
    "government": "فرم لیدری دولت"
}

def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    return c

def init():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      game_name TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'user',
      verified INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS forms(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      form_type TEXT NOT NULL,
      game_name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      form_id INTEGER NOT NULL,
      sender_name TEXT NOT NULL,
      sender_role TEXT NOT NULL DEFAULT 'user',
      message TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(form_id) REFERENCES forms(id)
    );
    """)
    # Owner account: owner / owner12345
    if not c.execute("SELECT 1 FROM users WHERE game_name='owner'").fetchone():
        c.execute("INSERT INTO users(game_name,password_hash,role,verified) VALUES(?,?,?,1)",
                  ("owner", generate_password_hash("owner12345"), "owner"))
    c.commit(); c.close()

@app.context_processor
def common():
    return {"forms": FORMS}

@app.route("/")
def home():
    if session.get("user"):
        return render_template("home.html", user=session["user"])
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    name=request.form.get("game_name","").strip()
    pw=request.form.get("password","")
    c=db(); u=c.execute("SELECT * FROM users WHERE game_name=?", (name,)).fetchone(); c.close()
    if not u or not check_password_hash(u["password_hash"], pw):
        return render_template("login.html", error="نام گیم یا رمز عبور اشتباه است.")
    session["user"]={"id":u["id"],"game_name":u["game_name"],"role":u["role"]}
    return redirect(url_for("home"))

@app.route("/register", methods=["POST"])
def register():
    name=request.form.get("game_name","").strip()
    pw=request.form.get("password","")
    if len(name)<2 or len(pw)<4:
        return render_template("login.html", error="نام گیم حداقل ۲ کاراکتر و رمز حداقل ۴ کاراکتر باشد.")
    c=db()
    try:
        c.execute("INSERT INTO users(game_name,password_hash) VALUES(?,?)",(name,generate_password_hash(pw)))
        c.commit()
    except sqlite3.IntegrityError:
        c.close()
        return render_template("login.html", error="این نام گیم قبلاً ثبت شده است.")
    c.close()
    return redirect(url_for("login_page"))

@app.route("/login")
def login_page():
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login_page"))

@app.route("/form/<form_type>")
def form_page(form_type):
    if not session.get("user"): return redirect(url_for("login_page"))
    if form_type not in FORMS: abort(404)
    c=db()
    f=c.execute("SELECT * FROM forms WHERE form_type=? AND game_name=? ORDER BY id DESC LIMIT 1",
                (form_type,session["user"]["game_name"])).fetchone()
    if not f:
        c.execute("INSERT INTO forms(form_type,game_name) VALUES(?,?)",
                  (form_type,session["user"]["game_name"]))
        c.commit()
        f=c.execute("SELECT * FROM forms WHERE id=last_insert_rowid()").fetchone()
    msgs=c.execute("SELECT * FROM messages WHERE form_id=? ORDER BY id",(f["id"],)).fetchall()
    c.close()
    return render_template("chat.html", form=f, messages=msgs, title=FORMS[form_type])

@app.route("/form/<int:form_id>/send", methods=["POST"])
def send_message(form_id):
    if not session.get("user"): return jsonify(ok=False,error="login"),401
    msg=request.form.get("message","").strip()
    if not msg: return redirect(request.referrer or url_for("home"))
    c=db(); f=c.execute("SELECT * FROM forms WHERE id=?",(form_id,)).fetchone()
    if not f: c.close(); abort(404)
    is_manager=session["user"]["role"] in ("owner","admin")
    if f["status"]!="open" and not is_manager:
        c.close(); return redirect(url_for("form_page",form_type=f["form_type"]))
    c.execute("INSERT INTO messages(form_id,sender_name,sender_role,message) VALUES(?,?,?,?)",
              (form_id,session["user"]["game_name"],session["user"]["role"],msg))
    c.execute("UPDATE forms SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(form_id,))
    c.commit(); c.close()
    return redirect(url_for("form_page",form_type=f["form_type"]))

def manager():
    return session.get("user") and session["user"]["role"] in ("owner","admin")

@app.route("/panel")
def panel():
    if not manager(): return redirect(url_for("login_page"))
    c=db()
    fs=c.execute("SELECT * FROM forms ORDER BY updated_at DESC").fetchall()
    us=c.execute("SELECT id,game_name,role,verified FROM users ORDER BY id DESC").fetchall()
    c.close()
    return render_template("panel.html", forms_list=fs, users=us)

@app.route("/panel/form/<int:form_id>/toggle", methods=["POST"])
def toggle_form(form_id):
    if not manager(): abort(403)
    c=db(); f=c.execute("SELECT status FROM forms WHERE id=?",(form_id,)).fetchone()
    if not f: c.close(); abort(404)
    new="closed" if f["status"]=="open" else "open"
    c.execute("UPDATE forms SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(new,form_id))
    c.commit(); c.close()
    return redirect(url_for("panel"))

@app.route("/panel/form/<int:form_id>")
def panel_chat(form_id):
    if not manager(): return redirect(url_for("login_page"))
    c=db(); f=c.execute("SELECT * FROM forms WHERE id=?",(form_id,)).fetchone()
    msgs=c.execute("SELECT * FROM messages WHERE form_id=? ORDER BY id",(form_id,)).fetchall()
    c.close()
    if not f: abort(404)
    return render_template("manager_chat.html",form=f,messages=msgs,title=FORMS[f["form_type"]])

@app.route("/panel/form/<int:form_id>/send",methods=["POST"])
def manager_send(form_id):
    if not manager(): abort(403)
    msg=request.form.get("message","").strip()
    if msg:
        c=db()
        u=session["user"]
        c.execute("INSERT INTO messages(form_id,sender_name,sender_role,message) VALUES(?,?,?,?)",
                  (form_id,u["game_name"],u["role"],msg))
        c.execute("UPDATE forms SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(form_id,))
        c.commit(); c.close()
    return redirect(url_for("panel_chat",form_id=form_id))

@app.route("/panel/user/<int:user_id>/role",methods=["POST"])
def set_role(user_id):
    if session.get("user",{}).get("role")!="owner": abort(403)
    role=request.form.get("role","user")
    if role not in ("user","admin","owner"): abort(400)
    c=db(); c.execute("UPDATE users SET role=? WHERE id=?",(role,user_id)); c.commit(); c.close()
    return redirect(url_for("panel"))

if __name__=="__main__":
    init()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
