import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from bursary_model import calculate_fee_gap, init_db, match_opportunities


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "bursary-radar-local-development-key")
init_db()
USERS_DB = Path(__file__).resolve().parent / "bursary_radar.db"


def init_users_db():
    with sqlite3.connect(USERS_DB) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                enrollment_no TEXT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                gender TEXT,
                date_of_birth TEXT,
                course TEXT
            )
        """)


init_users_db()


def current_user():
    if not session.get("user_id"):
        return None
    with sqlite3.connect(USERS_DB) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT id, full_name, enrollment_no, email, course FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
@login_required
def index():
    return render_template("index.html", user=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with sqlite3.connect(USERS_DB) as connection:
            connection.row_factory = sqlite3.Row
            user = connection.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        error = "Invalid email or password."

    return render_template("auth.html", mode="login", error=error)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        enrollment_no = request.form.get("enrollment_no", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        gender = request.form.get("gender", "")
        date_of_birth = request.form.get("date_of_birth", "")
        course = request.form.get("course", "").strip()

        if not all([full_name, email, password]):
            error = "Name, email and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            try:
                with sqlite3.connect(USERS_DB) as connection:
                    connection.execute(
                        """INSERT INTO users
                        (full_name, enrollment_no, email, password_hash, gender,
                         date_of_birth, course)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            full_name,
                            enrollment_no,
                            email,
                            generate_password_hash(password),
                            gender,
                            date_of_birth,
                            course,
                        ),
                    )
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "An account with that email already exists."

    return render_template("auth.html", mode="signup", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/matches", methods=["POST"])
def matches():
    profile = request.get_json(silent=True) or {}
    clean_profile = {
        "level": profile.get("level", "University"),
        "institution_type": profile.get("institution_type", "Public"),
        "county": profile.get("county", "Machakos"),
        "constituency": profile.get("constituency", "Machakos Town"),
        "need_flag": bool(profile.get("need_flag")),
        "disability": bool(profile.get("disability")),
    }
    return jsonify(match_opportunities(clean_profile))


@app.route("/api/fee-gap", methods=["POST"])
def fee_gap():
    data = request.get_json(silent=True) or {}
    try:
        gap = calculate_fee_gap(
            data.get("fees", 0),
            data.get("scholarship", 0),
            data.get("helb", 0),
        )
    except (TypeError, ValueError):
        return jsonify({"error": "Enter valid numbers"}), 400
    return jsonify({"gap": gap})


@app.route("/api/simulate-sms", methods=["POST"])
def simulate_sms():
    data = request.get_json(silent=True) or {}
    opportunity = str(data.get("opportunity", "your bursary opportunity"))
    return jsonify({
        "message": (
            f"Bursary Radar: Apply for {opportunity}. "
            "Check the deadline and prepare your documents. Never pay to apply."
        )
    })


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
