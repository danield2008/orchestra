from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "moodle_clone.db"
UPLOAD_FOLDER = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {"pdf"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_: Any) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','student'))
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );
        """
    )

    admin_exists = db.execute(
        "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
    ).fetchone()
    if not admin_exists:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            ("admin", generate_password_hash("admin123")),
        )
        db.commit()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if session.get("role") != "admin":
            flash("Necesitas permisos de administrador.", "error")
            return redirect(url_for("dashboard"))
        return view(**kwargs)

    return wrapped_view


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.before_request
def startup() -> None:
    UPLOAD_FOLDER.mkdir(exist_ok=True)
    init_db()


@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash("Inicio de sesión exitoso.", "success")
            return redirect(url_for("dashboard"))

        flash("Usuario o contraseña inválidos.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    if session.get("role") == "admin":
        users = db.execute(
            "SELECT id, username, role FROM users ORDER BY role DESC, username"
        ).fetchall()
        courses = db.execute("SELECT id, name, description FROM courses ORDER BY name").fetchall()
        enrollments = db.execute(
            """
            SELECT e.user_id, u.username, e.course_id, c.name AS course_name
            FROM enrollments e
            JOIN users u ON u.id = e.user_id
            JOIN courses c ON c.id = e.course_id
            ORDER BY u.username, c.name
            """
        ).fetchall()
        return render_template(
            "admin_dashboard.html", users=users, courses=courses, enrollments=enrollments
        )

    courses = db.execute(
        """
        SELECT c.id, c.name, c.description
        FROM courses c
        JOIN enrollments e ON e.course_id = c.id
        WHERE e.user_id = ?
        ORDER BY c.name
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template("student_dashboard.html", courses=courses)


@app.route("/course/<int:course_id>")
@login_required
def course_detail(course_id: int):
    db = get_db()
    course = db.execute(
        "SELECT id, name, description FROM courses WHERE id = ?", (course_id,)
    ).fetchone()
    if not course:
        flash("Curso no encontrado.", "error")
        return redirect(url_for("dashboard"))

    if session.get("role") != "admin":
        enrollment = db.execute(
            "SELECT 1 FROM enrollments WHERE user_id = ? AND course_id = ?",
            (session["user_id"], course_id),
        ).fetchone()
        if not enrollment:
            flash("No tienes acceso a este curso.", "error")
            return redirect(url_for("dashboard"))

    materials = db.execute(
        """
        SELECT id, title, filename, uploaded_at
        FROM materials
        WHERE course_id = ?
        ORDER BY uploaded_at DESC
        """,
        (course_id,),
    ).fetchall()
    return render_template("course_detail.html", course=course, materials=materials)


@app.route("/admin/users", methods=["POST"])
@login_required
@admin_required
def create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "student")

    if not username or not password or role not in {"admin", "student"}:
        flash("Datos de usuario inválidos.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
        db.commit()
        flash("Usuario creado correctamente.", "success")
    except sqlite3.IntegrityError:
        flash("Ese nombre de usuario ya existe.", "error")

    return redirect(url_for("dashboard"))


@app.route("/admin/courses", methods=["POST"])
@login_required
@admin_required
def create_course():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()

    if not name:
        flash("El nombre del curso es obligatorio.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute(
        "INSERT INTO courses (name, description) VALUES (?, ?)", (name, description)
    )
    db.commit()
    flash("Curso creado correctamente.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/enroll", methods=["POST"])
@login_required
@admin_required
def enroll_user():
    user_id = request.form.get("user_id", type=int)
    course_id = request.form.get("course_id", type=int)

    if not user_id or not course_id:
        flash("Selecciona usuario y curso.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)",
            (user_id, course_id),
        )
        db.commit()
        flash("Inscripción realizada.", "success")
    except sqlite3.IntegrityError:
        flash("La inscripción ya existía o es inválida.", "error")

    return redirect(url_for("dashboard"))


@app.route("/admin/materials", methods=["POST"])
@login_required
@admin_required
def upload_material():
    course_id = request.form.get("course_id", type=int)
    title = request.form.get("title", "").strip()
    file = request.files.get("file")

    if not course_id or not title or not file or not file.filename:
        flash("Completa todos los campos para subir material.", "error")
        return redirect(url_for("dashboard"))

    if not allowed_file(file.filename):
        flash("Solo se permiten archivos PDF.", "error")
        return redirect(url_for("dashboard"))

    filename = secure_filename(file.filename)
    final_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
    file.save(UPLOAD_FOLDER / final_name)

    db = get_db()
    db.execute(
        "INSERT INTO materials (course_id, title, filename, uploaded_at) VALUES (?, ?, ?, ?)",
        (course_id, title, final_name, datetime.utcnow().isoformat(timespec="seconds")),
    )
    db.commit()
    flash("Material subido correctamente.", "success")
    return redirect(url_for("course_detail", course_id=course_id))


@app.route("/materials/<path:filename>")
@login_required
def serve_material(filename: str):
    db = get_db()
    material = db.execute(
        "SELECT id, course_id FROM materials WHERE filename = ?", (filename,)
    ).fetchone()
    if not material:
        flash("Archivo no encontrado.", "error")
        return redirect(url_for("dashboard"))

    if session.get("role") != "admin":
        enrollment = db.execute(
            "SELECT 1 FROM enrollments WHERE user_id = ? AND course_id = ?",
            (session["user_id"], material["course_id"]),
        ).fetchone()
        if not enrollment:
            flash("No tienes acceso a este archivo.", "error")
            return redirect(url_for("dashboard"))

    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
