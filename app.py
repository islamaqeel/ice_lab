import os
import sqlite3
from datetime import datetime, timezone

from flask import (
    Flask,
    flash,
    jsonify,
    session,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


APP_NAME = "ICE LIBRARY"
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), ".data")
DATA_DIR = os.environ.get("ICE_LIBRARY_DATA_DIR", DEFAULT_DATA_DIR)
DB_PATH = os.environ.get("ICE_LIBRARY_DB_PATH", os.path.join(DATA_DIR, "ice_library.db"))
UPLOAD_DIR = os.environ.get("ICE_LIBRARY_UPLOAD_DIR", os.path.join(DATA_DIR, "uploads"))

CATEGORIES = [
    "matlab",
    "math",
    "autocad",
    "programming",
    "logic",
    "english",
    "arabic",
]

ALLOWED_EXTENSIONS = {
    "pdf",
    "txt",
    "md",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "csv",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("ICE_LIBRARY_SECRET_KEY", "dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()
    ensure_default_admin()

    def common_template_args():
        return {
            "app_name": APP_NAME,
            "is_admin": is_admin_session(),
        }

    @app.get("/")
    def home():
        announcements = list_announcements(limit=5)
        return render_template("home.html", announcements=announcements, **common_template_args())

    @app.get("/library")
    def library_page():
        category = (request.args.get("cat") or "").strip().lower()
        if category and category not in CATEGORIES:
            category = ""
        items = list_items(category=category or None)
        return render_template(
            "library.html",
            items=items,
            categories=CATEGORIES,
            selected_category=category,
            **common_template_args(),
        )

    @app.get("/tabligat-public")
    def public_announcements_page():
        announcements = list_announcements(limit=200)
        return render_template(
            "public_announcements.html",
            announcements=announcements,
            **common_template_args(),
        )

    @app.get("/resources")
    def resources_page():
        return render_template("resources.html", **common_template_args())

    @app.get("/chat")
    def chat_page():
        messages = list_chat_messages(limit=80)
        return render_template("chat.html", messages=messages, **common_template_args())

    @app.get("/api/chat/messages")
    def chat_messages_api():
        after_id_raw = (request.args.get("after_id") or "0").strip()
        try:
            after_id = int(after_id_raw)
        except ValueError:
            after_id = 0
        messages = list_chat_messages(after_id=after_id, limit=200)
        return jsonify({"messages": messages})

    @app.post("/api/chat/send")
    def chat_send_api():
        name = (request.form.get("name") or "").strip()
        message = (request.form.get("message") or "").strip()

        if not name:
            return jsonify({"ok": False, "error": "name_required"}), 400
        if not message:
            return jsonify({"ok": False, "error": "message_required"}), 400
        if len(name) > 60:
            return jsonify({"ok": False, "error": "name_too_long"}), 400
        if len(message) > 1000:
            return jsonify({"ok": False, "error": "message_too_long"}), 400

        add_chat_message(name=name, message=message)
        return jsonify({"ok": True})

    @app.get("/about")
    def about_page():
        return render_template("about.html", **common_template_args())

    @app.get("/contact")
    def contact_page():
        return render_template("contact.html", **common_template_args())

    @app.get("/login")
    def login_page():
        if is_admin_session():
            return redirect(url_for("announcements_page"))
        return render_template("login.html", **common_template_args())

    @app.post("/login")
    def login_submit():
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = get_user_by_username(username)
        if not user or not user.get("is_admin"):
            flash("Invalid username or password.", "error")
            return redirect(url_for("login_page"))

        if not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
            return redirect(url_for("login_page"))

        session["admin_user_id"] = user["id"]
        session["admin_username"] = user["username"]
        flash("Logged in.", "success")
        return redirect(url_for("announcements_page"))

    @app.post("/logout")
    def logout():
        session.pop("admin_user_id", None)
        session.pop("admin_username", None)
        flash("Logged out.", "success")
        return redirect(url_for("home"))

    @app.get("/index-legacy")
    def index_legacy():
        # Backward-compat in case someone bookmarked the old homepage template.
        return redirect(url_for("home"))

    @app.post("/upload")
    def upload():
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip().lower()
        file = request.files.get("file")

        if not title:
            flash("Please enter a name/title for the upload.", "error")
            return redirect(url_for("library_page"))

        if category not in CATEGORIES:
            flash("Please choose a valid subject group.", "error")
            return redirect(url_for("library_page"))

        if not file or not file.filename:
            flash("Please choose a file to upload.", "error")
            return redirect(url_for("library_page"))

        original_name = file.filename
        filename = secure_filename(original_name)
        if not filename:
            flash("That file name is not allowed.", "error")
            return redirect(url_for("library_page"))

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            flash(f"File type '.{ext}' is not allowed.", "error")
            return redirect(url_for("library_page"))

        unique_name = f"{int(datetime.now(tz=timezone.utc).timestamp())}_{filename}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)

        try:
            file.save(save_path)
        except Exception:
            flash("Upload failed while saving the file.", "error")
            return redirect(url_for("library_page"))

        mime = file.mimetype or ""
        add_file_item(
            title=title,
            category=category,
            stored_name=unique_name,
            original_name=original_name,
            mime=mime,
        )
        flash("Uploaded successfully.", "success")
        return redirect(url_for("library_page", cat=category))

    @app.post("/add-url")
    def add_url():
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip().lower()
        url = (request.form.get("url") or "").strip()

        if not title:
            flash("Please enter a name/title for the URL.", "error")
            return redirect(url_for("library_page"))

        if category not in CATEGORIES:
            flash("Please choose a valid subject group.", "error")
            return redirect(url_for("library_page"))

        if not (url.startswith("http://") or url.startswith("https://")):
            flash("Please enter a valid URL starting with http:// or https://", "error")
            return redirect(url_for("library_page"))

        add_url_item(title=title, category=category, url=url)
        flash("URL added successfully.", "success")
        return redirect(url_for("library_page", cat=category))

    @app.get("/download/<int:item_id>")
    def download(item_id: int):
        item = get_item(item_id)
        if not item or item["kind"] != "file":
            flash("That file does not exist.", "error")
            return redirect(url_for("library_page"))

        return send_from_directory(
            UPLOAD_DIR,
            item["stored_name"],
            as_attachment=True,
            download_name=item["original_name"] or item["stored_name"],
        )

    @app.get("/tabligat")
    def announcements_page():
        if not is_admin_session():
            return redirect(url_for("login_page"))

        announcements = list_announcements(limit=200)
        return render_template(
            "announcements.html",
            announcements=announcements,
            admin_username=session.get("admin_username") or "admin",
            **common_template_args(),
        )

    @app.post("/tabligat")
    def announcements_submit():
        if not is_admin_session():
            return redirect(url_for("login_page"))

        message = (request.form.get("message") or "").strip()
        if not message:
            flash("Please write a message.", "error")
            return redirect(url_for("announcements_page"))

        if len(message) > 2000:
            flash("Message is too long (max 2000 characters).", "error")
            return redirect(url_for("announcements_page"))

        add_announcement(message=message, created_by=session.get("admin_username") or "admin")
        flash("Announcement posted.", "success")
        return redirect(url_for("announcements_page"))

    return app


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL CHECK (kind IN ('file','url')),
              title TEXT NOT NULL,
              category TEXT,
              stored_name TEXT,
              original_name TEXT,
              mime TEXT,
              url TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        ensure_items_category_column(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_created_at ON items(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              message TEXT NOT NULL,
              created_by TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_announcements_created_at ON announcements(created_at DESC);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              message TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at DESC);")


def is_admin_session() -> bool:
    return bool(session.get("admin_user_id"))


def ensure_items_category_column(conn: sqlite3.Connection) -> None:
    cols = conn.execute("PRAGMA table_info(items);").fetchall()
    col_names = {c[1] for c in cols}  # (cid, name, type, notnull, dflt_value, pk)
    if "category" in col_names:
        return
    conn.execute("ALTER TABLE items ADD COLUMN category TEXT;")
    conn.execute("UPDATE items SET category = 'programming' WHERE category IS NULL;")


def ensure_default_admin() -> None:
    username = os.environ.get("ICE_LIBRARY_ADMIN_USER", "admin").strip() or "admin"
    password = os.environ.get("ICE_LIBRARY_ADMIN_PASS", "admin123")

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            return

        conn.execute(
            """
            INSERT INTO users(username, password_hash, is_admin, created_at)
            VALUES(?, ?, 1, ?)
            """,
            (username, generate_password_hash(password), now_iso()),
        )


def get_user_by_username(username: str):
    if not username:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None


def add_file_item(title: str, category: str, stored_name: str, original_name: str, mime: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO items(kind, title, category, stored_name, original_name, mime, url, created_at)
            VALUES(?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            ("file", title, category, stored_name, original_name, mime, now_iso()),
        )


def add_url_item(title: str, category: str, url: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO items(kind, title, category, stored_name, original_name, mime, url, created_at)
            VALUES(?, ?, ?, NULL, NULL, NULL, ?, ?)
            """,
            ("url", title, category, url, now_iso()),
        )


def list_items(category: str | None = None):
    with get_db() as conn:
        if category:
            rows = conn.execute(
                """
                SELECT id, kind, title, category, stored_name, original_name, mime, url, created_at
                FROM items
                WHERE category = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 500
                """,
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, kind, title, category, stored_name, original_name, mime, url, created_at
                FROM items
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 500
                """
            ).fetchall()
        return [dict(r) for r in rows]


def get_item(item_id: int):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, kind, title, category, stored_name, original_name, mime, url, created_at
            FROM items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
        return dict(row) if row else None


def add_announcement(message: str, created_by: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO announcements(message, created_by, created_at)
            VALUES(?, ?, ?)
            """,
            (message, created_by, now_iso()),
        )


def list_announcements(limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, message, created_by, created_at
            FROM announcements
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def add_chat_message(name: str, message: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages(name, message, created_at)
            VALUES(?, ?, ?)
            """,
            (name, message, now_iso()),
        )


def list_chat_messages(after_id: int = 0, limit: int = 200):
    with get_db() as conn:
        if after_id and after_id > 0:
            rows = conn.execute(
                """
                SELECT id, name, message, created_at
                FROM chat_messages
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (int(after_id), int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, name, message, created_at
                FROM chat_messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            rows = list(reversed(rows))
        return [dict(r) for r in rows]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Render/Gunicorn entrypoint
app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)

