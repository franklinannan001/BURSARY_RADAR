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
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

from application_documents import (
    DocumentProcessingUnavailable,
    InvalidDocument,
    decrypt_document,
    document_cipher,
    encrypt_document,
    inspect_documents,
    sanitize_image,
)
from sms_service import (
    SMSConfigurationError,
    SMSDeliveryError,
    normalize_kenyan_mobile,
    send_infobip_sms,
)
from bursary_model import (
    DB_PATH,
    get_connection,
    get_opportunities,
    get_opportunity_by_id,
    init_db,
    match_opportunities,
)

load_dotenv()

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
                role TEXT NOT NULL DEFAULT 'student',
                phone_number TEXT,
                sms_consent INTEGER NOT NULL DEFAULT 0,
                notification_county TEXT,
                notification_constituency TEXT,
                notification_level TEXT,
                notification_institution_type TEXT,
                notification_institution_name TEXT
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
        user_migrations = {
            "phone_number": "TEXT",
            "sms_consent": "INTEGER NOT NULL DEFAULT 0",
            "notification_county": "TEXT",
            "notification_constituency": "TEXT",
            "notification_level": "TEXT",
            "notification_institution_type": "TEXT",
            "notification_institution_name": "TEXT",
        }
        for column, column_type in user_migrations.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE users ADD COLUMN {column} {column_type}"
                )


init_users_db()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with sqlite3.connect(USERS_DB) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """SELECT id,full_name,enrollment_no,email,course,study_level,role,
                      phone_number,sms_consent
               FROM users WHERE id=?""",
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


def student_session_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return api_error("Authentication required", 401)
        if user["role"] != "student":
            return api_error("Student access required", 403)
        return view(*args, **kwargs)
    return wrapped


def save_notification_preferences(user_id, profile):
    with open(
        os.path.join(os.path.dirname(__file__), "static", "kenya_locations.json"),
        encoding="utf-8",
    ) as locations_file:
        county_map = json.load(locations_file)["counties"]
    county_value = profile.get("county")
    constituency_value = profile.get("constituency")
    if not isinstance(county_value, str) or not isinstance(constituency_value, str):
        return
    county = next(
        (name for name in county_map if name.casefold() == county_value.casefold()),
        None,
    )
    if not county:
        return
    constituency = next(
        (
            name for name in county_map[county]
            if name.casefold() == constituency_value.casefold()
        ),
        None,
    )
    if not constituency:
        return
    with get_connection() as connection:
        connection.execute(
            """UPDATE users
               SET notification_county=?,notification_constituency=?,
                   notification_level=?,notification_institution_type=?,
                   notification_institution_name=?
               WHERE id=? AND role='student' AND sms_consent=1 AND phone_number IS NOT NULL""",
            (
                county,
                constituency,
                profile.get("level"),
                profile.get("institution_type"),
                str(profile.get("institution_name", "")).strip()[:200] or None,
                user_id,
            ),
        )


def send_user_sms(
    user_id,
    phone_number,
    sms_consent,
    event_type,
    dedupe_key,
    message,
    opportunity_id=None,
    application_id=None,
):
    notification_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    initial_status = "pending" if sms_consent and phone_number else "skipped"
    initial_error = None
    if not sms_consent:
        initial_error = "Student has not consented to SMS notifications."
    elif not phone_number:
        initial_error = "No mobile number is registered."
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT status FROM sms_notifications WHERE dedupe_key=?",
            (dedupe_key,),
        ).fetchone()
        if existing:
            return {"status": existing["status"]}
        connection.execute(
            """INSERT INTO sms_notifications
               (id,dedupe_key,user_id,event_type,opportunity_id,application_id,
                status,error,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                notification_id,
                dedupe_key,
                user_id,
                event_type,
                opportunity_id,
                application_id,
                initial_status,
                initial_error,
                created_at,
            ),
        )
    if initial_status == "skipped":
        return {"status": "skipped"}

    try:
        provider_message_id = send_infobip_sms(phone_number, message)
    except SMSConfigurationError as error:
        status = "not_configured"
        detail = str(error)
        app.logger.error("SMS notification %s was not sent: %s", notification_id, detail)
    except SMSDeliveryError as error:
        status = "failed"
        detail = str(error)
        app.logger.warning("SMS notification %s failed: %s", notification_id, detail)
    else:
        status = "accepted"
        detail = None
    with get_connection() as connection:
        connection.execute(
            """UPDATE sms_notifications
               SET status=?,provider_message_id=?,error=? WHERE id=?""",
            (
                status,
                provider_message_id if status == "accepted" else None,
                detail,
                notification_id,
            ),
        )
    return {"status": status}


def opportunity_matches_notification_profile(opportunity, student):
    county = student["notification_county"]
    constituency = student["notification_constituency"]
    if not county or not constituency:
        return False
    if opportunity["counties"] and county.casefold() not in {
        value.casefold() for value in opportunity["counties"]
    }:
        return False
    if opportunity["constituencies"] and constituency.casefold() not in {
        value.casefold() for value in opportunity["constituencies"]
    }:
        return False
    level_aliases = {
        "Primary": {"primary"},
        "Junior Secondary": {"secondary"},
        "Senior Secondary": {"secondary"},
        "Tertiary": {"university", "tvet", "tertiary"},
    }
    if opportunity["levels"] and not level_aliases.get(
        student["notification_level"], set()
    ).intersection(opportunity["levels"]):
        return False
    if opportunity["institution_types"] and student["notification_institution_type"] not in opportunity["institution_types"]:
        return False
    required_institution = opportunity["institution_name"]
    if required_institution and (
        not student["notification_institution_name"]
        or student["notification_institution_name"].casefold()
        != required_institution.casefold()
    ):
        return False
    return True


def notify_students_about_bursary(opportunity):
    if opportunity["status"] not in {"open", "upcoming"}:
        return
    with get_connection() as connection:
        students = connection.execute(
            """SELECT id,phone_number,sms_consent,notification_county,
                      notification_constituency,notification_level,
                      notification_institution_type,notification_institution_name
               FROM users
               WHERE role='student' AND sms_consent=1 AND phone_number IS NOT NULL
                 AND notification_county IS NOT NULL
               ORDER BY id"""
        ).fetchall()
    location = ", ".join(
        value
        for value in (", ".join(opportunity["counties"] or []),
                      ", ".join(opportunity["constituencies"] or []))
        if value
    ) or "all areas"
    deadline = opportunity["deadline"] or opportunity["window_note"] or "not confirmed"
    bursary_type = opportunity["provider_type"].replace("_", " ")
    award_count = opportunity["number_of_bursaries"]
    awards = f" {award_count} bursaries." if award_count else ""
    message = (
        f"Bursary Radar: {opportunity['name']} ({bursary_type}) "
        f"from {opportunity['provider']}.{awards} Area: {location}. Deadline: {deadline}. "
        f"Details: {opportunity['source_url']}"
    )
    for student in students:
        if not opportunity_matches_notification_profile(opportunity, student):
            continue
        send_user_sms(
            student["id"],
            student["phone_number"],
            bool(student["sms_consent"]),
            "bursary_alert",
            f"bursary:{opportunity['id']}:student:{student['id']}",
            message,
            opportunity_id=opportunity["id"],
        )


@app.route("/")
@login_required
def index():
    user = current_user()
    return redirect(url_for("admin_page" if user["role"] == "admin" else "dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin_page"))
    return render_template("index.html", user=user)


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
        phone_number = None
        sms_consent = False
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
        elif account_type == "student" and not normalize_kenyan_mobile(
            request.form.get("phone_number", "")
        ):
            error = "Enter a valid Kenyan mobile number, such as +254 7XX XXX XXX."
        elif account_type == "student" and request.form.get("sms_consent") != "yes":
            error = "Consent to SMS updates is required to create a student account."
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
            if account_type == "student":
                phone_number = normalize_kenyan_mobile(request.form.get("phone_number", ""))
                sms_consent = True
            if account_type == "student" and study_level == "Tertiary" and course == "Other":
                course = custom_course
            if account_type == "admin":
                study_level = None
                course = None
            try:
                with sqlite3.connect(USERS_DB) as connection:
                    connection.execute(
                        """INSERT INTO users
                        (full_name,enrollment_no,email,password_hash,gender,date_of_birth,
                         course,study_level,role,phone_number,sms_consent)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (full_name, enrollment_no, email, generate_password_hash(password),
                         gender, date_of_birth, course, study_level, account_type,
                         phone_number, int(sms_consent)),
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
    result = match_opportunities(profile)
    user = current_user()
    if user and user["role"] == "student" and user["sms_consent"]:
        save_notification_preferences(user["id"], profile)
    return jsonify(result)


@app.route("/api/applications", methods=["POST"])
@student_session_required
@limiter.limit("5 per minute")
def submit_application():
    request.max_content_length = 10 * 1024 * 1024
    try:
        profile = json.loads(request.form.get("profile", ""))
    except json.JSONDecodeError:
        return api_error("A valid matched student profile is required")
    if not isinstance(profile, dict):
        return api_error("A valid matched student profile is required")
    if request.form.get("residence_confirmed") != "yes":
        return api_error("Confirm that the listed county and constituency are current")

    level_ranges = {
        "Primary": range(1, 7),
        "Junior Secondary": range(1, 4),
        "Senior Secondary": range(1, 4),
        "Tertiary": range(1, 6),
    }
    level = profile.get("level")
    if not isinstance(level, str) or level not in level_ranges:
        return api_error("Select a valid level of study")
    year_value = profile.get("year_of_study")
    if isinstance(year_value, bool) or not isinstance(year_value, (int, str)):
        return api_error("A valid year of study is required")
    try:
        year = int(year_value)
    except ValueError:
        return api_error("A valid year of study is required")
    if year not in level_ranges[level]:
        return api_error("Year of study is outside the selected level's range")

    institution_name = profile.get("institution_name")
    if not isinstance(institution_name, str) or not institution_name.strip():
        return api_error("Institution name is required")
    if len(institution_name.strip()) > 200:
        return api_error("Institution name must not exceed 200 characters")
    institution_type = profile.get("institution_type")
    if institution_type not in (None, "", "public", "private"):
        return api_error("Institution type must be public or private")
    need_flags = profile.get("need_flags", [])
    valid_need_flags = {"orphan", "disability", "low_income", "single_parent"}
    if not isinstance(need_flags, list) or any(
        not isinstance(flag, str) or flag not in valid_need_flags for flag in need_flags
    ):
        return api_error("Need indicators are invalid")

    with open(
        os.path.join(os.path.dirname(__file__), "static", "kenya_locations.json"),
        encoding="utf-8",
    ) as locations_file:
        location_map = json.load(locations_file)["counties"]
    county_value = profile.get("county")
    constituency_value = profile.get("constituency")
    if not isinstance(county_value, str) or not isinstance(constituency_value, str):
        return api_error("A current county and constituency are required")
    county = next(
        (name for name in location_map if name.casefold() == county_value.casefold()),
        None,
    )
    if not county:
        return api_error("Select a valid county")
    constituency = next(
        (
            name for name in location_map[county]
            if name.casefold() == constituency_value.casefold()
        ),
        None,
    )
    if not constituency:
        return api_error("Select a constituency within the selected county")

    opportunity_id = request.form.get("opportunity_id", "").strip()
    opportunity = get_opportunity_by_id(opportunity_id)
    if not opportunity:
        return api_error("Opportunity not found", 404)
    if opportunity["status"] == "closed":
        return api_error("Applications are closed for this opportunity", 409)

    profile.update({
        "institution_name": institution_name.strip(),
        "institution_type": institution_type or None,
        "year_of_study": year,
        "county": county,
        "constituency": constituency,
        "need_flags": need_flags,
    })
    matched_ids = {
        item["opportunity"]["id"]
        for group in match_opportunities(profile).values()
        for item in group
    }
    if opportunity_id not in matched_ids:
        return api_error(
            "This opportunity no longer matches the submitted profile. "
            "Update your profile and find matches again.",
            409,
        )

    identity_upload = request.files.get("identity_document")
    if not identity_upload or not identity_upload.filename:
        return api_error("A national ID or birth certificate image is required")
    identity_document_type = request.form.get("identity_document_type")
    if identity_document_type not in {"national_id", "birth_certificate"}:
        return api_error("Choose a national ID or birth certificate")
    passport_upload = request.files.get("passport_document")
    if passport_upload and not passport_upload.filename:
        passport_upload = None

    existing = get_connection()
    try:
        already_applied = existing.execute(
            "SELECT 1 FROM applications WHERE user_id=? AND opportunity_id=?",
            (current_user()["id"], opportunity_id),
        ).fetchone()
    finally:
        existing.close()
    if already_applied:
        return api_error("You have already applied for this opportunity", 409)

    try:
        cipher = document_cipher()
        identity_image, identity_mime = sanitize_image(identity_upload)
        passport_image = None
        passport_mime = None
        if passport_upload:
            passport_image, passport_mime = sanitize_image(passport_upload)
        document_checks = inspect_documents(
            identity_image,
            passport_image,
            current_user()["full_name"],
        )
    except InvalidDocument as error:
        return api_error(str(error))
    except DocumentProcessingUnavailable as error:
        app.logger.error("Application document processing is unavailable: %s", error)
        return api_error(str(error), 503)

    application_id = uuid.uuid4().hex
    residence_status = (
        "self_declared_match"
        if opportunity["counties"] or opportunity["constituencies"]
        else "unrestricted"
    )
    try:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO applications (
                    id,user_id,applicant_name,applicant_email,opportunity_id,opportunity_name,
                    level,institution_type,institution_name,
                    year_of_study,county,constituency,residence_status,
                    identity_document_type,identity_document,identity_mime_type,
                    passport_document,passport_mime_type,identity_ocr_status,
                    identity_name_status,mrz_status,mrz_name_status,status,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    application_id,
                    current_user()["id"],
                    current_user()["full_name"],
                    current_user()["email"],
                    opportunity_id,
                    opportunity["name"],
                    level,
                    institution_type or None,
                    institution_name.strip(),
                    year,
                    county,
                    constituency,
                    residence_status,
                    identity_document_type,
                    encrypt_document(cipher, identity_image),
                    identity_mime,
                    encrypt_document(cipher, passport_image) if passport_image else None,
                    passport_mime,
                    document_checks["identity_ocr_status"],
                    document_checks["identity_name_status"],
                    document_checks["mrz_status"],
                    document_checks["mrz_name_status"],
                    "submitted",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except sqlite3.IntegrityError:
        return api_error("You have already applied for this opportunity", 409)

    user = current_user()
    sms_result = send_user_sms(
        user["id"],
        user["phone_number"],
        bool(user["sms_consent"]),
        "application_confirmation",
        f"application:{application_id}",
        (
            f"Bursary Radar: Your application for {opportunity['name']} "
            f"was received successfully. Reference: {application_id[:8]}."
        ),
        opportunity_id=opportunity_id,
        application_id=application_id,
    )
    return jsonify({
        "application_id": application_id,
        "status": "submitted",
        "residence_status": residence_status,
        "document_checks": document_checks,
        "notification": sms_result,
    }), 201


@app.route("/api/admin/applications")
@admin_session_required
def admin_applications():
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT a.id,a.opportunity_id,
                      COALESCE(o.name,a.opportunity_name) AS opportunity_name,
                      a.applicant_name AS full_name,a.applicant_email AS email,
                      a.level,a.institution_name,a.year_of_study,
                      a.county,a.constituency,a.residence_status,
                      a.identity_document_type,a.passport_document IS NOT NULL AS has_passport,
                      a.identity_ocr_status,a.identity_name_status,a.mrz_status,
                      a.mrz_name_status,a.status,a.created_at
               FROM applications a
               LEFT JOIN opportunities o ON o.id=a.opportunity_id
               ORDER BY a.created_at DESC"""
        ).fetchall()
    results = [dict(row) for row in rows]
    for application in results:
        if not application["opportunity_name"]:
            application["opportunity_name"] = "Opportunity no longer in directory"
    return jsonify(results)


@app.route("/api/admin/applications/<application_id>/documents/<document_type>")
@admin_session_required
def admin_application_document(application_id, document_type):
    if document_type not in {"identity", "passport"}:
        return api_error("Document type not found", 404)
    column = (
        "identity_document,identity_mime_type"
        if document_type == "identity"
        else "passport_document,passport_mime_type"
    )
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {column} FROM applications WHERE id=?",
            (application_id,),
        ).fetchone()
    if not row or not row[0]:
        return api_error("Document not found", 404)
    try:
        content = decrypt_document(document_cipher(), row[0])
    except DocumentProcessingUnavailable as error:
        app.logger.error("Application document is unavailable: %s", error)
        return api_error(str(error), 503)
    response = app.response_class(content, mimetype=row[1])
    response.headers["Content-Disposition"] = (
        f'inline; filename="{document_type}-document.jpg"'
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/admin/applications/<application_id>/status", methods=["POST"])
@admin_session_required
def update_application_status(application_id):
    data = request.get_json(silent=True)
    allowed_statuses = {"under_review", "approved", "rejected"}
    status = data.get("status") if isinstance(data, dict) else None
    if not isinstance(status, str) or status not in allowed_statuses:
        return api_error("Choose under_review, approved, or rejected")
    with get_connection() as connection:
        result = connection.execute(
            "UPDATE applications SET status=? WHERE id=?",
            (status, application_id),
        )
    if not result.rowcount:
        return api_error("Application not found", 404)
    return jsonify({"id": application_id, "status": status})


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
    opportunity = get_opportunity_by_id(id)
    notify_students_about_bursary(opportunity)
    return jsonify(opportunity), 201


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
