import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "bursary_radar.db"
SEED_PATH = Path(__file__).resolve().parent / "data" / "opportunities.seed.json"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        table_info = connection.execute("PRAGMA table_info(opportunities)").fetchall()
        id_column = next((row for row in table_info if row[1] == "id"), None)
        if id_column and str(id_column[2]).upper() != "TEXT":
            connection.execute("DROP TABLE opportunities")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
                provider_type TEXT NOT NULL, description TEXT, levels TEXT,
                institution_types TEXT, institution_name TEXT, counties TEXT,
                constituencies TEXT, eligibility_notes TEXT, need_flags TEXT,
                gender_restriction TEXT, amount_published INTEGER DEFAULT 0,
                amount_min INTEGER, amount_max INTEGER, amount_note TEXT,
                deadline TEXT, window_note TEXT, is_recurring INTEGER DEFAULT 0,
                status TEXT, documents_required TEXT, how_to_apply TEXT,
                apply_url TEXT, source_url TEXT NOT NULL, source_type TEXT NOT NULL,
                last_verified_at TEXT, verified_by TEXT,
                created_at TEXT, updated_at TEXT
            )
        """)
        existing = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(opportunities)").fetchall()
        }
        migrations = {
            "provider_type": "TEXT",
            "description": "TEXT",
            "levels": "TEXT",
            "institution_types": "TEXT",
            "institution_name": "TEXT",
            "counties": "TEXT",
            "constituencies": "TEXT",
            "eligibility_notes": "TEXT",
            "need_flags": "TEXT",
            "gender_restriction": "TEXT",
            "amount_published": "INTEGER DEFAULT 0",
            "amount_min": "INTEGER",
            "amount_max": "INTEGER",
            "amount_note": "TEXT",
            "deadline": "TEXT",
            "window_note": "TEXT",
            "is_recurring": "INTEGER DEFAULT 0",
            "status": "TEXT",
            "documents_required": "TEXT",
            "how_to_apply": "TEXT",
            "apply_url": "TEXT",
            "source_type": "TEXT",
            "last_verified_at": "TEXT",
            "verified_by": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }
        for column, column_type in migrations.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE opportunities ADD COLUMN {column} {column_type}"
                )
        connection.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id TEXT,
                reason TEXT, note TEXT, status TEXT DEFAULT 'new', created_at TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT, rating INTEGER,
                comment TEXT, created_at TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT,
                value TEXT, created_at TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, raw_text_excerpt TEXT,
                extracted_json TEXT, field_evidence TEXT, uncertain_fields TEXT,
                status TEXT DEFAULT 'pending', created_at TEXT, reviewed_at TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS poll_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question_key TEXT,
                answer TEXT, created_at TEXT
            )
        """)
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        for item in seed:
            columns = [
                "levels", "institution_types", "counties", "constituencies",
                "need_flags", "documents_required",
            ]
            row = dict(item)
            for column in columns:
                value = row.get(column)
                row[column] = json.dumps(value) if value is not None else None
            row["amount_published"] = int(row.get("amount_published", False))
            row["is_recurring"] = int(row.get("is_recurring", False))
            row["created_at"] = now
            row["updated_at"] = now
            if not row.get("deadline"):
                row["deadline"] = None
            connection.execute(
                """INSERT INTO opportunities (
                id,name,provider,provider_type,description,levels,institution_types,
                institution_name,counties,constituencies,eligibility_notes,need_flags,
                gender_restriction,amount_published,amount_min,amount_max,amount_note,
                deadline,window_note,is_recurring,status,documents_required,how_to_apply,
                apply_url,source_url,source_type,last_verified_at,verified_by,created_at,updated_at
                ) VALUES (
                :id,:name,:provider,:provider_type,:description,:levels,:institution_types,
                :institution_name,:counties,:constituencies,:eligibility_notes,:need_flags,
                :gender_restriction,:amount_published,:amount_min,:amount_max,:amount_note,
                :deadline,:window_note,:is_recurring,:status,:documents_required,:how_to_apply,
                :apply_url,:source_url,:source_type,:last_verified_at,:verified_by,:created_at,:updated_at
                ) ON CONFLICT(id) DO NOTHING""",
                row,
            )


def _json_list(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def get_opportunity_by_id(opportunity_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
    if not row:
        return None
    return deserialize_opportunity(row)


def deserialize_opportunity(row):
    opportunity = dict(row)
    for column in ("levels", "institution_types", "counties", "constituencies",
                   "need_flags", "documents_required"):
        opportunity[column] = _json_list(opportunity.get(column))
    opportunity["amount_published"] = bool(opportunity["amount_published"])
    opportunity["is_recurring"] = bool(opportunity["is_recurring"])
    opportunity.update(compute_confidence(opportunity))
    return opportunity


def get_opportunities(filters=None):
    filters = filters or {}
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM opportunities").fetchall()
    opportunities = [deserialize_opportunity(row) for row in rows]
    level = filters.get("level")
    county = filters.get("county")
    status = filters.get("status")
    if level:
        opportunities = [o for o in opportunities if o["levels"] is None or level in o["levels"]]
    if county:
        opportunities = [o for o in opportunities if o["counties"] is None or county in o["counties"]]
    if status:
        opportunities = [o for o in opportunities if o["status"] == status]
    return opportunities


def compute_confidence(opportunity):
    source_type = opportunity.get("source_type")
    last_verified = opportunity.get("last_verified_at")
    deadline = opportunity.get("deadline")
    status = opportunity.get("status")
    if last_verified:
        parsed = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - parsed).total_seconds() / 86400
    else:
        age_days = None

    if source_type in ("aggregator", "other") or last_verified is None:
        if source_type in ("official", "university") and last_verified is None:
            label = "RED"
            reason = "Never verified"
        elif source_type in ("aggregator", "other"):
            label = "RED"
            reason = "Source is aggregator or other"
        else:
            label = "RED"
            reason = "Never verified"
    elif source_type in ("official", "university") and age_days is not None and age_days <= 14.001 and (deadline or status == "closed"):
        label = "GREEN"
        reason = "Official or university source, last checked within 14 days"
    elif source_type in ("official", "university") and age_days is not None and age_days <= 14:
        label = "AMBER"
        reason = "Credible source, last checked within 14 days"
    elif source_type in ("official", "university") and age_days is not None:
        label = "AMBER"
        reason = "Official or university source, but last checked more than 14 days ago"
    else:
        label = "AMBER"
        reason = "Secondary or credible source"
    return {"confidence": label, "confidence_reason": reason}


def match_opportunities(profile):
    likely = []
    check_eligibility = []
    level = profile.get("level")
    institution_type = profile.get("institution_type")
    institution_name = profile.get("institution_name")
    county = profile.get("county")
    constituency = profile.get("constituency")
    need_flags = set(profile.get("need_flags") or [])
    gender = profile.get("gender")

    for opportunity in get_opportunities():
        reasons = []
        unknown = False
        levels = opportunity["levels"]
        if levels is not None:
            if level not in levels:
                continue
            reasons.append("Matched because: level is included")
        else:
            unknown = True

        types = opportunity["institution_types"]
        if types is not None:
            if institution_type not in types:
                continue
            reasons.append("Matched because: institution type is included")
        else:
            unknown = True

        required_name = opportunity["institution_name"]
        if required_name:
            if not institution_name or institution_name.lower() != required_name.lower():
                continue
            reasons.append("Matched because: institution name matches")

        counties = opportunity["counties"]
        if counties is not None:
            if county not in counties:
                continue
            reasons.append("Matched because: county matches")

        constituencies = opportunity["constituencies"]
        if constituencies is not None:
            if not constituency or constituency not in constituencies:
                continue
            reasons.append("Matched because: constituency matches")

        restrictions = opportunity["need_flags"]
        if restrictions:
            matches = need_flags.intersection(restrictions)
            if matches:
                reasons.append("Matched because: " + ", ".join(sorted(matches)) + " support applies")

        if opportunity["gender_restriction"] and gender:
            if gender == opportunity["gender_restriction"]:
                reasons.append("Matched because: gender matches")

        if unknown:
            check_eligibility.append({"opportunity": opportunity, "reasons": reasons or [
                "Check eligibility at the source"
            ]})
        else:
            likely.append({"opportunity": opportunity, "reasons": reasons or [
                "Matches the profile supplied"
            ]})

    def deadline_sort(match):
        deadline = match["opportunity"]["deadline"]
        return (deadline is None, deadline or "9999-12-31")

    likely.sort(key=deadline_sort)
    check_eligibility.sort(key=deadline_sort)
    return {"likely": likely, "check_eligibility": check_eligibility}


def calculate_fee_gap(annual_fees, scholarship=0, loan=0, other_aid=0):
    try:
        fees = float(annual_fees)
        aid = float(scholarship) + float(loan) + float(other_aid)
    except (TypeError, ValueError):
        raise ValueError("Enter valid numbers")
    if fees < 0 or aid < 0:
        raise ValueError("Amounts cannot be negative")
    gap = max(0, fees - aid)
    percent_covered = 100.0 if fees == 0 else min(100.0, (aid / fees) * 100)
    surplus = max(0, aid - fees)
    return {
        "gap": round(gap, 2),
        "percent_covered": round(percent_covered, 2),
        "surplus": round(surplus, 2),
    }
