import hmac
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash

from bursary_model import (
    DB_PATH,
    get_connection,
    get_opportunities,
    get_opportunity_by_id,
    init_db,
    match_opportunities,
)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "bursary-radar-local-development-key")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["300 per hour"])
init_db()
USERS_DB = DB_PATH


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
                course TEXT,
                study_level TEXT,
                role TEXT NOT NULL DEFAULT 'student'
            )
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        if "email" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "study_level" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN study_level TEXT")
        if "role" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"
            )


init_users_db()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with sqlite3.connect(USERS_DB) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT id, full_name, enrollment_no, email, course, study_level, role FROM users WHERE id=?",
            (user_id,),
        ).fetchone()


def email_domain(email):
    local, separator, domain = email.rpartition("@")
    if not separator or not local or not domain or not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local
    ):
        return None
    domain = domain.rstrip(".").lower()
    labels = domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        return None
    return domain


def is_go_ke_email(email):
    domain = email_domain(email)
    return domain == "go.ke" or (domain is not None and domain.endswith(".go.ke"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if CORS_ORIGINS:
        origin = request.headers.get("Origin")
        if origin in CORS_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'"
    )
    return response


@app.errorhandler(413)
def request_too_large(error):
    return api_error("Request is too large", 413)


def api_error(message, status=400):
    return jsonify({"error": {"message": message, "status": status}}), status


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user and user["role"] == "admin":
            return view(*args, **kwargs)
        supplied = request.headers.get("X-Admin-Token", "")
        if ADMIN_TOKEN and hmac.compare_digest(supplied, ADMIN_TOKEN):
            return view(*args, **kwargs)
        if user:
            return api_error("Admin access required", 403)
        if not ADMIN_TOKEN:
            return api_error("Admin authentication required", 401)
        else:
            return api_error("Invalid or missing admin token", 401)
    return wrapped


def admin_session_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return api_error("Authentication required", 401)
        if user["role"] != "admin":
            return api_error("Admin access required", 403)
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
@login_required
def index():
    user = current_user()
    return redirect(url_for("admin_page" if user["role"] == "admin" else "dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user()["role"] == "admin":
        return redirect(url_for("admin_page"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        user = current_user()
        return redirect(url_for("admin_page" if user["role"] == "admin" else "dashboard"))
    error = None
    account_type = "student"
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        account_type = request.form.get("account_type", "student")
        if account_type not in ("student", "admin"):
            error = "Select Student or Admin."
        else:
            with sqlite3.connect(USERS_DB) as connection:
                connection.row_factory = sqlite3.Row
                user = connection.execute(
                    "SELECT * FROM users WHERE email=?", (email,)
                ).fetchone()
                if user and check_password_hash(user["password_hash"], password):
                    stored_role = user["role"] or "student"
                    if account_type == "admin" and not is_go_ke_email(user["email"]):
                        error = "Admin access requires an email address ending in .go.ke."
                    else:
                        if account_type == "admin" and stored_role == "student":
                            connection.execute(
                                "UPDATE users SET role='admin' WHERE id=?", (user["id"],)
                            )
                            stored_role = "admin"
                        if account_type != stored_role:
                            error = "This account is registered as a different account type."
                        else:
                            session.clear()
                            session["user_id"] = user["id"]
                            return redirect(
                                url_for("admin_page" if stored_role == "admin" else "dashboard")
                            )
        if error is None:
            error = "Invalid email or password."
    return render_template(
        "auth.html", mode="login", error=error, account_type=account_type
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        user = current_user()
        return redirect(url_for("admin_page" if user["role"] == "admin" else "dashboard"))
    error = None
    account_type = "student"
    if request.method == "POST":
        account_type = request.form.get("account_type", "student")
        full_name = request.form.get("full_name", "").strip()
        enrollment_no = request.form.get("enrollment_no", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        gender = request.form.get("gender", "")
        date_of_birth = request.form.get("date_of_birth", "")
        study_level = request.form.get("study_level", "")
        course = request.form.get("course", "").strip()
        custom_course = request.form.get("custom_course", "").strip()
        valid_levels = {
            "Primary": range(1, 7),
            "Junior Secondary": range(7, 10),
            "Senior Secondary": range(10, 13),
        }
        tertiary_courses = {
            "Computer Science", "Computer Engineering", "Civil Engineering",
            "Electrical Engineering", "Mechanical Engineering", "Information Technology",
            "Education", "Nursing", "Medicine", "Law", "Business Administration",
            "Accounting", "Agriculture", "Other",
        }
        if account_type not in ("student", "admin"):
            error = "Select Student or Admin."
        elif not all((full_name, email, password)):
            error = "Name, email and password are required."
        elif email_domain(email) is None:
            error = "Enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif account_type == "admin" and not is_go_ke_email(email):
            error = "Admin accounts require an email address ending in .go.ke."
        elif account_type == "student" and study_level not in (*valid_levels.keys(), "Tertiary"):
            error = "Select a valid level of study."
        elif account_type == "student" and study_level in valid_levels and course not in {
            f"Grade {grade}" for grade in valid_levels[study_level]
        }:
            error = "Select a grade that belongs to the selected level."
        elif account_type == "student" and study_level == "Tertiary" and course == "Other" and not custom_course:
            error = "Enter your course name."
        elif account_type == "student" and study_level == "Tertiary" and course not in tertiary_courses:
            error = "Select a course or choose Other."
        else:
            if account_type == "student" and study_level == "Tertiary" and course == "Other":
                course = custom_course
            if account_type == "admin":
                study_level = None
                course = None
            try:
                with sqlite3.connect(USERS_DB) as connection:
                    connection.execute(
                        """INSERT INTO users
                        (full_name,enrollment_no,email,password_hash,gender,date_of_birth,course,study_level,role)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (full_name, enrollment_no, email, generate_password_hash(password),
                         gender, date_of_birth, course, study_level, account_type),
                    )
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "An account with that email already exists."
    return render_template(
        "auth.html", mode="signup", error=error, account_type=account_type
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/opportunities")
def opportunities():
    level = request.args.get("level")
    county = request.args.get("county")
    status = request.args.get("status")
    return jsonify(get_opportunities({"level": level, "county": county, "status": status}))


@app.route("/api/opportunities/<opportunity_id>")
def opportunity_detail(opportunity_id):
    opportunity = get_opportunity_by_id(opportunity_id)
    if not opportunity:
        return api_error("Opportunity not found", 404)
    return jsonify(opportunity)


@app.route("/api/match", methods=["POST"])
@limiter.limit("30 per minute")
def public_match():
    profile = request.get_json(silent=True) or {}
    level = profile.get("level")
    year_ranges = {
        "Primary": range(1, 7),
        "Junior Secondary": range(1, 4),
        "Senior Secondary": range(1, 4),
        "Tertiary": range(1, 6),
        "secondary": range(1, 9),
        "tvet": range(1, 9),
        "university": range(1, 9),
    }
    if not isinstance(level, str) or level not in year_ranges:
        return api_error("Select a valid level of study")
    if not str(profile.get("institution_name", "")).strip():
        return api_error("institution_name is required")
    year_value = profile.get("year_of_study")
    try:
        if isinstance(year_value, bool):
            raise ValueError
        year = int(year_value)
    except (TypeError, ValueError):
        return api_error("year_of_study is required and must be a whole number")
    if year not in year_ranges[level]:
        return api_error("year_of_study is outside the selected level's range")
    if not str(profile.get("county", "")).strip():
        return api_error("county is required")
    if not str(profile.get("constituency", "")).strip():
        return api_error("constituency is required")
    institution_type = profile.get("institution_type")
    if institution_type not in (None, "public", "private"):
        return api_error("institution_type must be public or private")
    return jsonify(match_opportunities(profile))


def reminder_text(opportunity, schedule_day, lang):
    name = opportunity["name"]
    if lang == "sw":
        text = f"Bursary Radar: {name} — omba {schedule_day} siku kabla ya tarehe ya mwisho."
    else:
        text = f"Bursary Radar: {name} — apply {schedule_day} days before the deadline."
    if len(text) > 160:
        text = text[:157].rstrip() + "..."
    return text


@app.route("/api/reminders/preview", methods=["POST"])
@limiter.limit("30 per minute")
def reminders_preview():
    data = request.get_json(silent=True) or {}
    ids = data.get("opportunity_ids") or []
    lang = data.get("lang", "en")
    reminders = []
    skipped = []
    today = datetime.now(timezone.utc).date()
    for opportunity_id in ids[:20]:
        opportunity = get_opportunity_by_id(opportunity_id)
        if not opportunity:
            continue
        if not opportunity["deadline"]:
            skipped.append({
                "id": opportunity_id,
                "name": opportunity["name"],
                "reason": "No confirmed deadline",
            })
            continue
        deadline = datetime.strptime(opportunity["deadline"], "%Y-%m-%d").date()
        if deadline < today:
            skipped.append({
                "id": opportunity_id,
                "name": opportunity["name"],
                "reason": "Deadline has passed",
            })
            continue
        schedule = []
        for days in (14, 7, 2):
            date = deadline - timedelta(days=days)
            schedule.append({
                "send_on": date.isoformat(),
                "days_before": days,
                "message": reminder_text(opportunity, days, lang),
            })
        reminders.append({
            "id": opportunity_id,
            "name": opportunity["name"],
            "deadline": deadline.isoformat(),
            "schedule": schedule,
            "documents": opportunity["documents_required"] or [],
        })
    return jsonify({"reminders": reminders, "skipped": skipped})


@app.route("/api/reports", methods=["POST"])
@limiter.limit("10 per minute")
def report():
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    note = str(data.get("note", ""))[:300]
    opportunity_id = data.get("opportunity_id")
    if reason not in ("deadline_wrong", "link_broken", "closed", "other"):
        return api_error("Invalid report reason")
    if not get_opportunity_by_id(opportunity_id):
        return api_error("Opportunity not found", 404)
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO reports (opportunity_id,reason,note,status,created_at) VALUES (?,?,?,?,?)",
            (opportunity_id, reason, note, "new", datetime.now(timezone.utc).isoformat()),
        )
    record_event("report_submitted", opportunity_id)
    return jsonify({"status": "submitted"}), 201


@app.route("/api/feedback", methods=["POST"])
@limiter.limit("10 per minute")
def feedback():
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    comment = str(data.get("comment", ""))[:300]
    if not isinstance(rating, int) or isinstance(rating, bool) or rating not in range(1, 6):
        return api_error("rating must be between 1 and 5")
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO feedback (rating,comment,created_at) VALUES (?,?,?)",
            (rating, comment, datetime.now(timezone.utc).isoformat()),
        )
    record_event("feedback_submitted")
    return jsonify({"status": "submitted"}), 201


def record_event(event_type, value=None):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO events (type,value,created_at) VALUES (?,?,?)",
            (event_type, str(value) if value is not None else None,
             datetime.now(timezone.utc).isoformat()),
        )


@app.route("/api/events", methods=["POST"])
@limiter.limit("60 per minute")
def events():
    data = request.get_json(silent=True) or {}
    allowed = ("profile_completed", "match_viewed", "plan_item_added",
               "reminder_previewed", "report_submitted", "feedback_submitted",
               "poll_vote")
    event_type = data.get("type")
    if event_type not in allowed:
        return api_error("Invalid event type")
    record_event(event_type, data.get("value"))
    return jsonify({"status": "recorded"}), 201


QUESTIONS = {
    "funding_sources": "Do you know every funding source you can apply for?",
    "missed_deadline": "Have you ever missed a funding deadline?",
}


@app.route("/api/poll", methods=["GET", "POST"])
@limiter.limit("60 per minute")
def poll():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        question_key = data.get("question_key")
        answer = data.get("answer")
        if question_key not in QUESTIONS:
            return api_error("Invalid question key")
        if answer not in ("yes", "no"):
            return api_error("answer must be yes or no")
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO poll_votes (question_key,answer,created_at) VALUES (?,?,?)",
                (question_key, answer, datetime.now(timezone.utc).isoformat()),
            )
        record_event("poll_vote", question_key)
        return jsonify(poll_tallies()), 201
    return jsonify(poll_tallies())


def poll_tallies():
    tallies = {}
    with get_connection() as connection:
        for key, question in QUESTIONS.items():
            yes = connection.execute(
                "SELECT COUNT(*) FROM poll_votes WHERE question_key=? AND answer='yes'", (key,)
            ).fetchone()[0]
            no = connection.execute(
                "SELECT COUNT(*) FROM poll_votes WHERE question_key=? AND answer='no'", (key,)
            ).fetchone()[0]
            tallies[key] = {"question": question, "yes": yes, "no": no}
    return tallies


@app.route("/api/admin/opportunities", methods=["GET", "POST"])
@admin_required
def admin_opportunities():
    if request.method == "GET":
        return jsonify(get_opportunities())
    data = request.get_json(silent=True) or {}
    required = ("id", "name", "provider", "provider_type", "source_url", "source_type")
    if any(not data.get(field) for field in required):
        return api_error("Missing required opportunity fields")
    with get_connection() as connection:
        columns = [
            "id", "name", "provider", "provider_type", "description", "levels",
            "institution_types", "institution_name", "counties", "constituencies",
            "eligibility_notes", "need_flags", "gender_restriction",
            "amount_published", "amount_min", "amount_max", "amount_note", "deadline",
            "number_of_bursaries", "disbursement_start", "disbursement_end",
            "window_note", "is_recurring", "status", "documents_required", "how_to_apply",
            "apply_url", "source_url", "source_type", "last_verified_at", "verified_by",
        ]
        values = {}
        for column in columns:
            value = data.get(column)
            if column in ("levels", "institution_types", "counties", "constituencies",
                          "need_flags", "documents_required") and value is not None:
                value = json.dumps(value)
            values[column] = value
        placeholders = ",".join(columns)
        assignments = ",".join(f"{column}=excluded.{column}" for column in columns if column != "id")
        sql = f"""INSERT INTO opportunities ({placeholders},created_at,updated_at)
                  VALUES ({','.join(':' + c for c in columns)},:created_at,:updated_at)
                  ON CONFLICT(id) DO UPDATE SET {assignments},updated_at=excluded.updated_at"""
        values["created_at"] = datetime.now(timezone.utc).isoformat()
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        connection.execute(sql, values)
    return jsonify(get_opportunity_by_id(data["id"])), 201


@app.route("/api/admin/bursaries", methods=["POST"])
@admin_session_required
@limiter.limit("30 per minute")
def upload_bursary():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("A JSON object is required")

    text_fields = (
        "name", "provider", "provider_type", "eligibility_notes",
        "amount_note", "how_to_apply", "source_url", "status",
        "disbursement_start", "disbursement_end",
    )
    for field in text_fields:
        if not isinstance(data.get(field), str) or not data[field].strip():
            return api_error(f"{field} is required")
    text_limits = {
        "name": 200,
        "provider": 200,
        "provider_type": 40,
        "eligibility_notes": 4000,
        "amount_note": 1000,
        "how_to_apply": 4000,
        "source_url": 2048,
        "status": 20,
        "disbursement_start": 10,
        "disbursement_end": 10,
    }
    if any(len(data[field].strip()) > limit for field, limit in text_limits.items()):
        return api_error("One or more text fields exceed their maximum length")

    allowed_provider_types = {
        "national_government", "county_government", "university",
        "tvet", "ngo", "foundation", "other",
    }
    if not isinstance(data["provider_type"], str) or data["provider_type"] not in allowed_provider_types:
        return api_error("Select a valid provider type")

    levels = data.get("levels")
    allowed_levels = {"primary", "secondary", "tvet", "university"}
    if not isinstance(levels, list) or not levels or any(
        not isinstance(level, str) or level not in allowed_levels for level in levels
    ):
        return api_error("Select at least one valid level")

    def valid_string_list(field, allowed=None):
        values = data.get(field, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            return None
        normalized = list(dict.fromkeys(value.strip() for value in values))
        if allowed is not None and any(value not in allowed for value in normalized):
            return None
        return normalized

    institution_types = valid_string_list("institution_types", {"public", "private"})
    need_flags = valid_string_list(
        "need_flags", {"orphan", "disability", "low_income", "single_parent"}
    )
    if institution_types is None or need_flags is None:
        return api_error("Invalid institution types or need indicators")

    counties = valid_string_list("counties")
    constituencies = valid_string_list("constituencies")
    if counties is None or constituencies is None:
        return api_error("County and constituency values must be lists")
    with open(
        os.path.join(os.path.dirname(__file__), "static", "kenya_locations.json"),
        encoding="utf-8",
    ) as locations_file:
        county_map = json.load(locations_file)["counties"]
    if any(county not in county_map for county in counties):
        return api_error("Select valid counties")
    valid_constituencies = {
        constituency
        for county in counties
        for constituency in county_map[county]
    }
    if constituencies and not counties:
        return api_error("Select a county before selecting constituencies")
    if any(constituency not in valid_constituencies for constituency in constituencies):
        return api_error("Constituencies must belong to the selected counties")

    number_of_bursaries = data.get("number_of_bursaries")
    if (
        isinstance(number_of_bursaries, bool)
        or not isinstance(number_of_bursaries, int)
        or number_of_bursaries < 1
    ):
        return api_error("number_of_bursaries must be a positive whole number")

    try:
        disbursement_start = datetime.strptime(data["disbursement_start"], "%Y-%m-%d").date()
        disbursement_end = datetime.strptime(data["disbursement_end"], "%Y-%m-%d").date()
    except ValueError:
        return api_error("Disbursement dates must use YYYY-MM-DD")
    if disbursement_end < disbursement_start:
        return api_error("Disbursement end date must not be before its start date")

    deadline = data.get("deadline") or None
    if deadline is not None and not isinstance(deadline, str):
        return api_error("deadline must use YYYY-MM-DD")
    if deadline:
        try:
            datetime.strptime(deadline, "%Y-%m-%d")
        except (TypeError, ValueError):
            return api_error("deadline must use YYYY-MM-DD")
    window_value = data.get("window_note", "")
    if not isinstance(window_value, str):
        return api_error("window_note must be text")
    window_note = window_value.strip()
    if len(window_note) > 500:
        return api_error("window_note must not exceed 500 characters")
    if not deadline and not window_note:
        return api_error("Provide a deadline or an application window note")

    if not isinstance(data["status"], str) or data["status"] not in {
        "open", "upcoming", "closed", "unknown"
    }:
        return api_error("Select a valid status")
    for boolean_field in ("amount_published", "is_recurring"):
        if not isinstance(data.get(boolean_field), bool):
            return api_error(f"{boolean_field} must be true or false")

    def amount_value(field):
        value = data.get(field)
        if value in (None, ""):
            return None, True
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, False
        return value, True

    amount_min, valid_min = amount_value("amount_min")
    amount_max, valid_max = amount_value("amount_max")
    if not valid_min or not valid_max:
        return api_error("Amounts must be non-negative whole numbers")
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        return api_error("Minimum amount must not exceed maximum amount")
    if not data["amount_published"] and (amount_min is not None or amount_max is not None):
        return api_error("Do not enter amounts when the amount is unpublished")

    documents_required = valid_string_list("documents_required")
    if documents_required is None or not documents_required:
        return api_error("List required documents, or enter 'None stated'")
    if any(len(document) > 500 for document in documents_required):
        return api_error("Document names must not exceed 500 characters")

    source_url = data["source_url"].strip()
    apply_url_value = data.get("apply_url")
    if apply_url_value is not None and not isinstance(apply_url_value, str):
        return api_error("apply_url must be a URL")
    apply_url = apply_url_value.strip() or None if apply_url_value is not None else None
    for field, url in (("source_url", source_url), ("apply_url", apply_url)):
        if url:
            parsed = urlparse(url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return api_error(f"{field} must be an HTTP or HTTPS URL")

    gender_restriction = data.get("gender_restriction") or None
    if gender_restriction not in (None, "Male", "Female"):
        return api_error("Select a valid gender restriction")
    optional_text_fields = {
        "institution_name": 200,
        "description": 4000,
    }
    optional_text = {}
    for field, maximum_length in optional_text_fields.items():
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            return api_error(f"{field} must be text")
        value = value.strip() if value is not None else ""
        if len(value) > maximum_length:
            return api_error(f"{field} must not exceed {maximum_length} characters")
        optional_text[field] = value or None
    institution_name = optional_text["institution_name"]
    description = optional_text["description"]
    amount_note = data["amount_note"].strip()
    id = f"official-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()
    verified_by = current_user()["email"]
    columns = (
        "id", "name", "provider", "provider_type", "description", "levels",
        "institution_types", "institution_name", "counties", "constituencies",
        "eligibility_notes", "need_flags", "gender_restriction", "amount_published",
        "amount_min", "amount_max", "amount_note", "number_of_bursaries",
        "disbursement_start", "disbursement_end", "deadline", "window_note",
        "is_recurring", "status", "documents_required", "how_to_apply", "apply_url",
        "source_url", "source_type", "last_verified_at", "verified_by",
        "created_at", "updated_at",
    )
    values = (
        id, data["name"].strip(), data["provider"].strip(), data["provider_type"],
        description, json.dumps(levels), json.dumps(institution_types),
        institution_name, json.dumps(counties), json.dumps(constituencies),
        data["eligibility_notes"].strip(), json.dumps(need_flags),
        gender_restriction, int(data["amount_published"]), amount_min, amount_max,
        amount_note, number_of_bursaries, disbursement_start.isoformat(),
        disbursement_end.isoformat(), deadline, window_note,
        int(data["is_recurring"]), data["status"], json.dumps(documents_required),
        data["how_to_apply"].strip(), apply_url, source_url, "official", now,
        verified_by, now, now,
    )
    placeholders = ",".join("?" for _ in columns)
    with get_connection() as connection:
        connection.execute(
            f"INSERT INTO opportunities ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
    return jsonify(get_opportunity_by_id(id)), 201


@app.route("/api/admin/opportunities/<opportunity_id>", methods=["PUT", "PATCH", "DELETE"])
@admin_required
def admin_opportunity(opportunity_id):
    if request.method == "DELETE":
        with get_connection() as connection:
            connection.execute("DELETE FROM opportunities WHERE id=?", (opportunity_id,))
        return jsonify({"status": "deleted"})
    data = request.get_json(silent=True) or {}
    if not get_opportunity_by_id(opportunity_id):
        return api_error("Opportunity not found", 404)
    with get_connection() as connection:
        for column, value in data.items():
            if column not in ("id", "confidence", "confidence_reason", "created_at", "updated_at"):
                if isinstance(value, (list, dict)):
                    value = json.dumps(value)
                if isinstance(value, bool):
                    value = int(value)
                connection.execute(
                    f'UPDATE opportunities SET "{column}"=?,updated_at=? WHERE id=?',
                    (value, datetime.now(timezone.utc).isoformat(), opportunity_id),
                )
    return jsonify(get_opportunity_by_id(opportunity_id))


@app.route("/api/admin/opportunities/<opportunity_id>/verify", methods=["POST"])
@admin_required
def verify_opportunity(opportunity_id):
    if not get_opportunity_by_id(opportunity_id):
        return api_error("Opportunity not found", 404)
    data = request.get_json(silent=True) or {}
    user = current_user()
    verified_by = user["email"] if user else str(data.get("verified_by", ""))
    with get_connection() as connection:
        connection.execute(
            "UPDATE opportunities SET last_verified_at=?,verified_by=?,updated_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), verified_by,
             datetime.now(timezone.utc).isoformat(), opportunity_id),
        )
    return jsonify(get_opportunity_by_id(opportunity_id))


@app.route("/api/admin/reports")
@admin_required
def admin_reports():
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/admin/reports/<int:report_id>", methods=["PATCH"])
@admin_required
def review_report(report_id):
    data = request.get_json(silent=True) or {}
    if data.get("status") != "reviewed":
        return api_error("status must be reviewed")
    with get_connection() as connection:
        connection.execute("UPDATE reports SET status='reviewed' WHERE id=?", (report_id,))
    return jsonify({"status": "reviewed"})


@app.route("/api/admin/metrics")
@admin_required
def admin_metrics():
    with get_connection() as connection:
        event_counts = [dict(row) for row in connection.execute(
            "SELECT type,COUNT(*) AS count FROM events GROUP BY type"
        )]
        feedback_row = connection.execute(
            "SELECT AVG(rating) AS average,COUNT(*) AS count FROM feedback"
        ).fetchone()
        report_count = connection.execute(
            "SELECT COUNT(*) FROM reports WHERE status='new'"
        ).fetchone()[0]
    opportunities = get_opportunities()
    confidence = {}
    for label in ("GREEN", "AMBER", "RED"):
        confidence[label] = sum(o["confidence"] == label for o in opportunities)
    return jsonify({
        "events": event_counts,
        "average_feedback": feedback_row["average"],
        "feedback_count": feedback_row["count"],
        "poll": poll_tallies(),
        "confidence": confidence,
        "unreviewed_reports": report_count,
    })


@app.route("/api/admin/export")
@admin_required
def admin_export():
    return jsonify(get_opportunities())


@app.route("/api/admin/drafts")
@admin_required
def admin_drafts():
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM drafts ORDER BY created_at DESC").fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/admin/notices/extract", methods=["POST"])
@admin_required
@limiter.limit("10 per minute")
def notice_extract():
    data = request.get_json(silent=True) or {}
    raw_text = str(data.get("text", ""))[:8000]
    raw_text = re.sub(r"<[^>]*>", " ", raw_text)
    if not raw_text.strip():
        return api_error("Notice text is required")
    if data.get("image"):
        return api_error("Image extraction is not configured; send notice text", 501)
    cleaned = " ".join(raw_text.split())
    extracted = {
        "name": None,
        "provider": None,
        "provider_type": "other",
        "levels": None,
        "institution_types": None,
        "counties": None,
        "constituencies": None,
        "eligibility_notes": None,
        "deadline": None,
        "amount_published": False,
        "amount_note": None,
        "source_url": None,
        "how_to_apply": None,
    }
    evidence = {key: None for key in extracted}
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO drafts
            (raw_text_excerpt,extracted_json,field_evidence,uncertain_fields,status,created_at)
            VALUES (?,?,?,?,?,?)""",
            (cleaned, json.dumps(extracted), json.dumps(evidence),
             json.dumps(list(extracted.keys())), "pending", now),
        )
        draft_id = cursor.lastrowid
    return jsonify({
        "id": draft_id,
        "raw_text_excerpt": cleaned,
        "extracted": extracted,
        "field_evidence": evidence,
        "uncertain_fields": list(extracted.keys()),
        "status": "pending",
    }), 201


@app.route("/api/admin/drafts/<int:draft_id>/approve", methods=["POST"])
@admin_required
def approve_draft(draft_id):
    data = request.get_json(silent=True) or {}
    opportunity = data.get("opportunity")
    if not opportunity:
        return api_error("Edited opportunity fields are required")
    required = ("id", "name", "provider", "provider_type", "source_url", "source_type")
    if any(not opportunity.get(field) for field in required):
        return api_error("Missing required opportunity fields")
    with get_connection() as connection:
        connection.execute("UPDATE drafts SET status='approved',reviewed_at=? WHERE id=?",
                           (datetime.now(timezone.utc).isoformat(), draft_id))
    request_payload = data
    with app.test_request_context(
        "/api/admin/opportunities",
        method="POST",
        json=opportunity,
        headers={"X-Admin-Token": request.headers.get("X-Admin-Token", "")},
    ):
        return admin_opportunities()


@app.route("/api/admin/drafts/<int:draft_id>/reject", methods=["POST"])
@admin_required
def reject_draft(draft_id):
    with get_connection() as connection:
        connection.execute("UPDATE drafts SET status='rejected',reviewed_at=? WHERE id=?",
                           (datetime.now(timezone.utc).isoformat(), draft_id))
    return jsonify({"status": "rejected"})


@app.route("/poll")
def poll_page():
    return render_template("index.html", poll_only=True)


@app.route("/admin")
@login_required
def admin_page():
    user = current_user()
    if user["role"] != "admin":
        return redirect(url_for("dashboard"))
    return render_template("admin.html", user=user)


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
