import os
import json
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, UnidentifiedImageError
from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_security_keys():
    secret_key = os.getenv("SECRET_KEY")
    totp_key = os.getenv("TOTP_ENCRYPTION_KEY")
    if secret_key and totp_key:
        return secret_key, totp_key
    if os.getenv("APP_ENV") == "production":
        raise RuntimeError("SECRET_KEY and TOTP_ENCRYPTION_KEY are required in production")
    key_file = INSTANCE_DIR / "local-secrets.json"
    if key_file.exists():
        values = json.loads(key_file.read_text(encoding="utf-8"))
    else:
        values = {"secret_key": secrets.token_urlsafe(64), "totp_key": Fernet.generate_key().decode("ascii")}
        key_file.write_text(json.dumps(values), encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    return secret_key or values["secret_key"], totp_key or values["totp_key"]


SECRET_KEY, TOTP_ENCRYPTION_KEY = load_security_keys()
TOTP_CIPHER = Fernet(TOTP_ENCRYPTION_KEY.encode("ascii"))
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))
SECURE_COOKIES = os.getenv(
    "COOKIE_SECURE", "1" if os.getenv("APP_ENV") == "production" else "0"
) == "1"
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MOODS = {"좋음", "설렘", "평온", "그리움", "속상함"}
Image.MAX_IMAGE_PIXELS = 20_000_000
app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    DATABASE=os.getenv("DATABASE_PATH", str(BASE_DIR / "miniroom.db")),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SECURE_COOKIES,
    SESSION_COOKIE_NAME="__Host-miniroom" if SECURE_COOKIES else "miniroom_session",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    WTF_CSRF_TIME_LIMIT=7200,
    MAX_FORM_MEMORY_SIZE=2 * 1024 * 1024,
    MAX_FORM_PARTS=50,
)
csrf = CSRFProtect(app)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def encrypt_totp(secret):
    return TOTP_CIPHER.encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_totp(encrypted):
    try:
        return TOTP_CIPHER.decrypt(encrypted.encode("ascii")).decode("ascii")
    except InvalidToken as error:
        raise RuntimeError("OTP encryption key is invalid or has changed") from error


def save_avatar(upload, user_id):
    image = Image.open(upload.stream)
    if image.format not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("unsupported image format")
    image.verify()
    upload.stream.seek(0)
    image = Image.open(upload.stream)
    if image.format not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("unsupported image format")
    image = image.convert("RGB")
    width, height = image.size
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((640, 640), Image.Resampling.LANCZOS)
    filename = f"avatar-{user_id}-{secrets.token_hex(12)}.webp"
    image.save(UPLOAD_DIR / filename, "WEBP", quality=88, method=6)
    return filename


def db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      display_name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT '오늘도 행복한 하루 :)',
      bio TEXT NOT NULL DEFAULT '나만의 작은 미니홈피입니다.',
      totp_secret TEXT NOT NULL,
      totp_enabled INTEGER NOT NULL DEFAULT 0,
      last_totp_step INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS visits (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      home_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      visitor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
      visited_on TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS posts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      mood TEXT NOT NULL DEFAULT '좋음',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS comments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS guestbook (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      home_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      body TEXT NOT NULL,
      is_secret INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS friendships (
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      friend_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id, friend_id),
      CHECK(user_id <> friend_id)
    );
    CREATE TABLE IF NOT EXISTS auth_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action TEXT NOT NULL,
      identity TEXT NOT NULL,
      attempted_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup
      ON auth_attempts(action, identity, attempted_at);
    CREATE TABLE IF NOT EXISTS recovery_codes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      code_hash TEXT NOT NULL,
      used_at TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_id, code_hash)
    );
    """)
    visits_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='visits'").fetchone()
    if visits_sql and "UNIQUE(home_user_id, visitor_id, visited_on)" in visits_sql[0].replace("\n", " "):
        conn.executescript("""
        ALTER TABLE visits RENAME TO visits_daily_unique;
        CREATE TABLE visits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          home_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          visitor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          visited_on TEXT NOT NULL
        );
        INSERT INTO visits(id,home_user_id,visitor_id,visited_on)
          SELECT id,home_user_id,visitor_id,visited_on FROM visits_daily_unique;
        DROP TABLE visits_daily_unique;
        """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "avatar_filename" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_filename TEXT")
    if "totp_enabled" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 1")
    if "last_totp_step" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_totp_step INTEGER")
    if "session_version" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1")
    for user_id, stored_secret in conn.execute("SELECT id,totp_secret FROM users").fetchall():
        if not stored_secret.startswith("gAAAA"):
            conn.execute("UPDATE users SET totp_secret=? WHERE id=?", (encrypt_totp(stored_secret), user_id))
    conn.commit()
    conn.close()


init_db()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def rate_limit(action, identity, limit, window_seconds):
    cutoff = int(time.time()) - window_seconds
    conn = db()
    conn.execute("DELETE FROM auth_attempts WHERE attempted_at<?", (int(time.time()) - 86400,))
    count = conn.execute(
        "SELECT COUNT(*) FROM auth_attempts WHERE action=? AND identity=? AND attempted_at>=?",
        (action, identity, cutoff),
    ).fetchone()[0]
    if count >= limit:
        abort(429)


def record_attempt(action, identity):
    db().execute("INSERT INTO auth_attempts(action,identity,attempted_at) VALUES(?,?,?)", (action, identity, int(time.time())))
    db().commit()


def clear_attempts(action, identity):
    db().execute("DELETE FROM auth_attempts WHERE action=? AND identity=?", (action, identity))
    db().commit()


def verify_totp_once(user, code):
    secret = decrypt_totp(user["totp_secret"])
    totp = pyotp.TOTP(secret)
    current_step = int(time.time()) // totp.interval
    matched_step = next(
        (step for step in range(current_step - 1, current_step + 2) if secrets.compare_digest(totp.at(step * totp.interval), code)),
        None,
    )
    if matched_step is None or (user["last_totp_step"] is not None and matched_step <= user["last_totp_step"]):
        return False
    db().execute("UPDATE users SET last_totp_step=? WHERE id=?", (matched_step, user["id"]))
    db().commit()
    return True


def recovery_digest(code):
    normalized = code.replace("-", "").strip().upper()
    return hmac.new(SECRET_KEY.encode("utf-8"), normalized.encode("ascii", "ignore"), hashlib.sha256).hexdigest()


def generate_recovery_codes(user_id):
    codes = []
    conn = db()
    conn.execute("DELETE FROM recovery_codes WHERE user_id=?", (user_id,))
    for _ in range(8):
        raw = secrets.token_hex(8).upper()
        code = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
        codes.append(code)
        conn.execute("INSERT INTO recovery_codes(user_id,code_hash) VALUES(?,?)", (user_id, recovery_digest(code)))
    conn.commit()
    return codes


@app.before_request
def load_user():
    session.permanent = True
    g.user = None
    if session.get("user_id"):
        g.user = db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if g.user is None or session.get("session_version") != g.user["session_version"]:
            session.clear()
            g.user = None


@app.after_request
def security_headers(response):
    if response.mimetype and response.mimetype.startswith("text/"):
        response.headers["Content-Type"] = f"{response.mimetype}; charset=utf-8"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if g.get("user"):
        response.headers["Cache-Control"] = "no-store"
    if SECURE_COOKIES:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response


@app.errorhandler(CSRFError)
def csrf_error(_error):
    return render_template("error.html", code=400, message="요청이 만료되었거나 올바르지 않습니다. 페이지를 새로고침해 주세요."), 400


@app.context_processor
def common():
    return {"now": datetime.now()}


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("mini_home", username=g.user["username"]))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        rate_limit("register", request.remote_addr or "unknown", 10, 3600)
        if not re.fullmatch(r"[a-z0-9_]{3,20}", username):
            flash("아이디는 영문·숫자·밑줄 3~20자로 입력해 주세요.", "error")
        elif not (2 <= len(name) <= 30) or len(password) < 12 or len(password) > 128:
            flash("이름은 2~30자, 비밀번호는 12~128자로 입력해 주세요.", "error")
        else:
            existing = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if existing:
                if not existing["totp_enabled"] and check_password_hash(existing["password_hash"], password):
                    session.clear()
                    session["setup_user_id"] = existing["id"]
                    flash("이미 생성된 계정입니다. OTP 설정을 이어서 완료해 주세요.", "success")
                    return redirect(url_for("otp_setup"))
                record_attempt("register", request.remote_addr or "unknown")
                flash("이미 사용 중인 아이디입니다.", "error")
                return render_template("auth.html", mode="register")
            try:
                raw_totp = pyotp.random_base32()
                cur = db().execute(
                    "INSERT INTO users(username,password_hash,display_name,totp_secret) VALUES(?,?,?,?)",
                    (username, generate_password_hash(password), name, encrypt_totp(raw_totp)),
                )
                db().commit()
                session.clear()
                session["setup_user_id"] = cur.lastrowid
                return redirect(url_for("otp_setup"))
            except sqlite3.IntegrityError as error:
                app.logger.warning("Registration integrity error: %s", error)
                flash("계정을 저장하지 못했습니다. 입력 내용을 확인해 다시 시도해 주세요.", "error")
    return render_template("auth.html", mode="register")


@app.route("/otp/setup", methods=["GET", "POST"])
def otp_setup():
    uid = session.get("setup_user_id")
    user = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not user:
        return redirect(url_for("register"))
    raw_secret = decrypt_totp(user["totp_secret"])
    uri = pyotp.TOTP(raw_secret).provisioning_uri(name=user["username"], issuer_name="Miniroom")
    if request.method == "POST":
        identity = f"setup:{user['id']}:{request.remote_addr or 'unknown'}"
        rate_limit("otp", identity, 5, 300)
        if verify_totp_once(user, request.form.get("code", "")):
            db().execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user["id"],)); db().commit()
            clear_attempts("otp", identity)
            codes = generate_recovery_codes(user["id"])
            refreshed = db().execute("SELECT session_version FROM users WHERE id=?", (user["id"],)).fetchone()
            session.clear(); session["user_id"] = user["id"]; session["session_version"] = refreshed["session_version"]; session["new_recovery_codes"] = codes; session.permanent = True
            flash("회원가입과 2차 인증 설정이 완료되었습니다.", "success")
            return redirect(url_for("recovery_codes"))
        record_attempt("otp", identity)
        flash("인증번호가 올바르지 않습니다.", "error")
    return render_template("otp.html", secret=raw_secret)


@app.get("/otp/qr")
def otp_qr():
    uid = session.get("setup_user_id")
    user = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not user:
        abort(403)
    uri = pyotp.TOTP(decrypt_totp(user["totp_secret"])).provisioning_uri(name=user["username"], issuer_name="Miniroom")
    buffer = BytesIO()
    qrcode.make(uri).save(buffer, format="PNG")
    buffer.seek(0)
    response = send_file(buffer, mimetype="image/png", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        identity = f"{request.remote_addr or 'unknown'}:{username}"
        rate_limit("login", identity, 5, 900)
        user = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        password_ok = len(password) <= 128 and check_password_hash(user["password_hash"] if user else DUMMY_PASSWORD_HASH, password)
        if user and password_ok:
            clear_attempts("login", identity)
            session.clear()
            if not user["totp_enabled"]:
                session["setup_user_id"] = user["id"]
                return redirect(url_for("otp_setup"))
            session["pending_user_id"] = user["id"]
            return redirect(url_for("otp_verify"))
        record_attempt("login", identity)
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template("auth.html", mode="login")


@app.route("/otp", methods=["GET", "POST"])
def otp_verify():
    uid = session.get("pending_user_id")
    user = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        identity = f"login:{user['id']}:{request.remote_addr or 'unknown'}"
        rate_limit("otp", identity, 5, 300)
        if verify_totp_once(user, request.form.get("code", "")):
            clear_attempts("otp", identity)
            session.clear(); session["user_id"] = user["id"]; session["session_version"] = user["session_version"]; session.permanent = True
            return redirect(url_for("mini_home", username=user["username"]))
        record_attempt("otp", identity)
        flash("인증번호가 올바르지 않습니다.", "error")
    return render_template("otp.html", verify=True)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    response = redirect(url_for("index"))
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    return response


@app.route("/security", methods=["GET", "POST"])
@login_required
def account_security():
    if request.method == "POST":
        action = request.form.get("action", "")
        current_password = request.form.get("current_password", "")
        otp_code = request.form.get("otp_code", "")
        identity = f"security:{g.user['id']}:{request.remote_addr or 'unknown'}"
        rate_limit("security", identity, 5, 600)
        if not check_password_hash(g.user["password_hash"], current_password) or not verify_totp_once(g.user, otp_code):
            record_attempt("security", identity)
            flash("현재 비밀번호 또는 OTP가 올바르지 않습니다.", "error")
            return render_template("security.html"), 400
        clear_attempts("security", identity)
        if action == "change_password":
            new_password = request.form.get("new_password", "")
            confirmation = request.form.get("new_password_confirm", "")
            if not (12 <= len(new_password) <= 128) or new_password != confirmation or check_password_hash(g.user["password_hash"], new_password):
                flash("새 비밀번호는 기존과 달라야 하며 12~128자로 동일하게 입력해야 합니다.", "error")
                return render_template("security.html"), 400
            db().execute("UPDATE users SET password_hash=?,session_version=session_version+1 WHERE id=?", (generate_password_hash(new_password), g.user["id"]))
            db().commit()
            version = db().execute("SELECT session_version FROM users WHERE id=?", (g.user["id"],)).fetchone()[0]
            session["session_version"] = version
            flash("비밀번호를 변경하고 다른 로그인 세션을 종료했습니다.", "success")
            return redirect(url_for("account_security"))
        if action == "recovery_codes":
            session["new_recovery_codes"] = generate_recovery_codes(g.user["id"])
            return redirect(url_for("recovery_codes"))
        abort(400)
    remaining = db().execute("SELECT COUNT(*) FROM recovery_codes WHERE user_id=? AND used_at IS NULL", (g.user["id"],)).fetchone()[0]
    return render_template("security.html", remaining=remaining)


@app.get("/recovery-codes")
@login_required
def recovery_codes():
    codes = session.pop("new_recovery_codes", None)
    if not codes:
        return redirect(url_for("account_security"))
    return render_template("recovery_codes.html", codes=codes)


@app.route("/password/forgot", methods=["GET", "POST"])
def password_forgot():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        code = request.form.get("recovery_code", "")
        new_password = request.form.get("new_password", "")
        confirmation = request.form.get("new_password_confirm", "")
        identity = f"{request.remote_addr or 'unknown'}:{username}"
        rate_limit("recovery", identity, 5, 3600)
        user = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        code_row = None
        if user:
            code_row = db().execute(
                "SELECT id FROM recovery_codes WHERE user_id=? AND code_hash=? AND used_at IS NULL",
                (user["id"], recovery_digest(code)),
            ).fetchone()
        if not user or not code_row or not (12 <= len(new_password) <= 128) or new_password != confirmation:
            record_attempt("recovery", identity)
            flash("계정 정보 또는 복구 코드가 올바르지 않습니다.", "error")
            return render_template("forgot_password.html"), 400
        db().execute("UPDATE recovery_codes SET used_at=CURRENT_TIMESTAMP WHERE id=?", (code_row["id"],))
        db().execute("UPDATE users SET password_hash=?,session_version=session_version+1 WHERE id=?", (generate_password_hash(new_password), user["id"]))
        db().commit()
        clear_attempts("recovery", identity)
        session.clear()
        flash("비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요.", "success")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


@app.get("/search")
@login_required
def user_search():
    query = request.args.get("q", "").strip()
    users = []
    if query:
        pattern = f"%{query[:50]}%"
        users = db().execute(
            """SELECT u.id,u.username,u.display_name,u.status,u.bio,u.avatar_filename,
                      EXISTS(SELECT 1 FROM friendships f WHERE f.user_id=? AND f.friend_id=u.id) AS is_friend
               FROM users u
               WHERE u.id<>? AND (u.username LIKE ? OR u.display_name LIKE ?)
               ORDER BY CASE WHEN u.username=? THEN 0 ELSE 1 END, u.display_name
               LIMIT 30""",
            (g.user["id"], g.user["id"], pattern, pattern, query.lower()),
        ).fetchall()
    return render_template("search.html", query=query, users=users)


@app.route("/home/<username>")
@login_required
def mini_home(username):
    owner = db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not owner: abort(404)
    today = datetime.now().strftime("%Y-%m-%d")
    if owner["id"] != g.user["id"]:
        db().execute("INSERT INTO visits(home_user_id,visitor_id,visited_on) VALUES(?,?,?)", (owner["id"], g.user["id"], today)); db().commit()
    total = db().execute("SELECT COUNT(*) FROM visits WHERE home_user_id=?", (owner["id"],)).fetchone()[0]
    today_count = db().execute("SELECT COUNT(*) FROM visits WHERE home_user_id=? AND visited_on=?", (owner["id"], today)).fetchone()[0]
    posts = db().execute("SELECT p.*,u.display_name FROM posts p JOIN users u ON u.id=p.user_id WHERE p.user_id=? ORDER BY p.id DESC LIMIT 6", (owner["id"],)).fetchall()
    guests = db().execute("SELECT g.*,u.display_name,u.username FROM guestbook g JOIN users u ON u.id=g.author_id WHERE g.home_user_id=? ORDER BY g.id DESC LIMIT 5", (owner["id"],)).fetchall()
    friends = db().execute(
        """SELECT u.username,u.display_name,u.status,u.avatar_filename
           FROM friendships f JOIN users u ON u.id=f.friend_id
           WHERE f.user_id=? ORDER BY f.created_at DESC LIMIT 8""",
        (owner["id"],),
    ).fetchall()
    suggestions = []
    if owner["id"] == g.user["id"]:
        suggestions = db().execute(
            """SELECT u.username,u.display_name,u.status,u.avatar_filename,
                      COUNT(mutual.friend_id) AS mutual_count
               FROM users u
               LEFT JOIN friendships mutual
                 ON mutual.user_id=u.id
                AND mutual.friend_id IN (SELECT friend_id FROM friendships WHERE user_id=?)
               WHERE u.id<>?
                 AND NOT EXISTS (SELECT 1 FROM friendships f WHERE f.user_id=? AND f.friend_id=u.id)
               GROUP BY u.id
               ORDER BY mutual_count DESC, u.created_at DESC
               LIMIT 5""",
            (g.user["id"], g.user["id"], g.user["id"]),
        ).fetchall()
    is_friend = False
    if owner["id"] != g.user["id"]:
        is_friend = db().execute("SELECT 1 FROM friendships WHERE user_id=? AND friend_id=?", (g.user["id"], owner["id"])).fetchone() is not None
    return render_template("home.html", owner=owner, posts=posts, guests=guests, friends=friends, suggestions=suggestions, is_friend=is_friend, total=total, today_count=today_count)


@app.post("/friends/<username>/add")
@login_required
def friend_add(username):
    friend = db().execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not friend: abort(404)
    if friend["id"] == g.user["id"]:
        flash("자기 자신은 이웃으로 추가할 수 없습니다.", "error")
    else:
        db().execute("INSERT OR IGNORE INTO friendships(user_id,friend_id) VALUES(?,?)", (g.user["id"], friend["id"]))
        db().commit()
        flash("이웃으로 추가했습니다.", "success")
    return redirect(url_for("mini_home", username=username))


@app.post("/friends/<username>/remove")
@login_required
def friend_remove(username):
    friend = db().execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not friend: abort(404)
    db().execute("DELETE FROM friendships WHERE user_id=? AND friend_id=?", (g.user["id"], friend["id"]))
    db().commit()
    flash("이웃에서 삭제했습니다.", "success")
    return redirect(url_for("mini_home", username=username))


@app.post("/profile")
@login_required
def profile():
    display_name = request.form.get("display_name", "").strip()
    status = request.form.get("status", "").strip()
    bio = request.form.get("bio", "").strip()
    if not (2 <= len(display_name) <= 30) or len(status) > 80 or len(bio) > 300:
        flash("프로필 입력 길이를 확인해 주세요.", "error")
        return redirect(url_for("mini_home", username=g.user["username"]))
    avatar_filename = g.user["avatar_filename"]
    upload = request.files.get("avatar")
    if upload and upload.filename:
        try:
            avatar_filename = save_avatar(upload, g.user["id"])
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
            flash("PNG, JPG 또는 WEBP 이미지 파일을 선택해 주세요.", "error")
            return redirect(url_for("mini_home", username=g.user["username"]))
    db().execute("UPDATE users SET display_name=?,status=?,bio=?,avatar_filename=? WHERE id=?", (
        display_name, status, bio, avatar_filename, g.user["id"]))
    db().commit(); flash("프로필을 저장했습니다.", "success")
    return redirect(url_for("mini_home", username=g.user["username"]))


@app.post("/profile/avatar")
@login_required
def profile_avatar():
    upload = request.files.get("avatar")
    if not upload or not upload.filename:
        flash("업로드할 사진을 선택해 주세요.", "error")
        return redirect(url_for("mini_home", username=g.user["username"]))
    try:
        avatar_filename = save_avatar(upload, g.user["id"])
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        flash("PNG, JPG 또는 WEBP 이미지 파일을 선택해 주세요.", "error")
        return redirect(url_for("mini_home", username=g.user["username"]))
    db().execute("UPDATE users SET avatar_filename=? WHERE id=?", (avatar_filename, g.user["id"]))
    db().commit()
    flash("프로필 사진을 변경했습니다.", "success")
    return redirect(url_for("mini_home", username=g.user["username"]))


@app.route("/post/new", methods=["GET", "POST"])
@login_required
def post_new():
    if request.method == "POST":
        title, body = request.form.get("title", "").strip(), request.form.get("body", "").strip()
        mood = request.form.get("mood", "좋음")
        if not title or not body or len(title) > 100 or len(body) > 5000 or mood not in MOODS: flash("게시글 입력 내용을 확인해 주세요.", "error")
        else:
            db().execute("INSERT INTO posts(user_id,title,body,mood) VALUES(?,?,?,?)", (g.user["id"], title, body, mood)); db().commit()
            return redirect(url_for("mini_home", username=g.user["username"]))
    return render_template("post_form.html", post=None)


@app.route("/post/<int:post_id>", methods=["GET", "POST"])
@login_required
def post_detail(post_id):
    post = db().execute("SELECT p.*,u.display_name,u.username FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?", (post_id,)).fetchone()
    if not post: abort(404)
    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if 1 <= len(body) <= 500:
            db().execute("INSERT INTO comments(post_id,user_id,body) VALUES(?,?,?)", (post_id,g.user["id"],body)); db().commit()
            return redirect(url_for("post_detail",post_id=post_id))
        flash("댓글은 1~500자로 입력해 주세요.", "error")
    comments = db().execute("SELECT c.*,u.display_name FROM comments c JOIN users u ON u.id=c.user_id WHERE c.post_id=? ORDER BY c.id", (post_id,)).fetchall()
    return render_template("post.html", post=post, comments=comments)


@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def post_edit(post_id):
    post = db().execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post or post["user_id"] != g.user["id"]: abort(403)
    if request.method == "POST":
        title, body, mood = request.form.get("title", "").strip(), request.form.get("body", "").strip(), request.form.get("mood", "")
        if not title or not body or len(title) > 100 or len(body) > 5000 or mood not in MOODS:
            flash("게시글 입력 내용을 확인해 주세요.", "error")
            return render_template("post_form.html", post=post), 400
        db().execute("UPDATE posts SET title=?,body=?,mood=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title,body,mood,post_id)); db().commit()
        return redirect(url_for("post_detail",post_id=post_id))
    return render_template("post_form.html", post=post)


@app.post("/post/<int:post_id>/delete")
@login_required
def post_delete(post_id):
    db().execute("DELETE FROM posts WHERE id=? AND user_id=?", (post_id,g.user["id"])); db().commit()
    return redirect(url_for("mini_home",username=g.user["username"]))


@app.post("/guestbook/<username>")
@login_required
def guestbook_add(username):
    owner = db().execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not owner: abort(404)
    body = request.form.get("body", "").strip()
    if 1 <= len(body) <= 500:
        db().execute("INSERT INTO guestbook(home_user_id,author_id,body,is_secret) VALUES(?,?,?,?)", (owner["id"],g.user["id"],body,1 if request.form.get("secret") else 0)); db().commit()
    else:
        flash("방명록은 1~500자로 입력해 주세요.", "error")
    return redirect(url_for("mini_home",username=username)+"#guestbook")


@app.errorhandler(404)
def not_found(_e): return render_template("error.html", code=404, message="페이지를 찾을 수 없어요."), 404

@app.errorhandler(403)
def forbidden(_e): return render_template("error.html", code=403, message="이 공간에 들어갈 권한이 없어요."), 403

@app.errorhandler(413)
def too_large(_e): return render_template("error.html", code=413, message="업로드 파일은 2MB 이하여야 합니다."), 413

@app.errorhandler(429)
def too_many(_e): return render_template("error.html", code=429, message="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."), 429


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
