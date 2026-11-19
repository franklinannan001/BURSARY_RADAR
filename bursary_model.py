import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "bursary_radar.db"


SEED_OPPORTUNITIES = [
    {
        "name": "Universities Fund Scholarship",
        "provider": "Universities Fund",
        "level": "University",
        "institution_type": "Public",
        "county": "All",
        "constituency": "",
        "need_flag": "Any",
        "amount": "Government scholarship award",
        "deadline": "2027-01-31",
        "documents": "Placement letter, admission letter, ID or birth certificate",
        "source_url": "https://www.universitiesfund.go.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Amber",
    },
    {
        "name": "HELB Undergraduate Loan",
        "provider": "Higher Education Loans Board",
        "level": "University",
        "institution_type": "All",
        "county": "All",
        "constituency": "",
        "need_flag": "Any",
        "amount": "Loan award",
        "deadline": "2027-01-31",
        "documents": "Admission letter, ID, parent/guardian ID, bank details",
        "source_url": "https://www.helb.co.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Amber",
    },
    {
        "name": "TVET HELB Loan",
        "provider": "Higher Education Loans Board",
        "level": "TVET",
        "institution_type": "All",
        "county": "All",
        "constituency": "",
        "need_flag": "Any",
        "amount": "Loan award",
        "deadline": "2027-01-31",
        "documents": "Admission letter, ID, parent/guardian ID, bank details",
        "source_url": "https://www.helb.co.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Amber",
    },
]


CONSTITUENCIES = [
    "Machakos Town", "Masinga", "Yatta", "Kangundo", "Matungulu",
    "Kathiani", "Mavoko", "Mwala", "Athi River", "Kalama",
]


for constituency in CONSTITUENCIES:
    SEED_OPPORTUNITIES.append({
        "name": f"{constituency} NG-CDF Bursary",
        "provider": f"{constituency} Constituency",
        "level": "All",
        "institution_type": "All",
        "county": "Machakos",
        "constituency": constituency,
        "need_flag": "Any",
        "amount": "Amount published by the constituency",
        "deadline": "TBC",
        "documents": "Admission letter, fee structure, ID/birth certificate, chief's letter",
        "source_url": "https://ngcdf.go.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    })


SEED_OPPORTUNITIES.extend([
    {
        "name": "Machakos County Education Bursary",
        "provider": "Machakos County Government",
        "level": "All",
        "institution_type": "All",
        "county": "Machakos",
        "constituency": "",
        "need_flag": "Any",
        "amount": "County-awarded amount",
        "deadline": "TBC",
        "documents": "Admission letter, fee structure, chief's letter, birth certificate",
        "source_url": "https://machakos.go.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    },
    {
        "name": "Kenya Private Schools Association Bursary",
        "provider": "KPSA",
        "level": "All",
        "institution_type": "Private",
        "county": "All",
        "constituency": "",
        "need_flag": "Any",
        "amount": "Varies",
        "deadline": "TBC",
        "documents": "Admission letter, fee structure, household statement",
        "source_url": "https://www.privateschools.co.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    },
    {
        "name": "Machakos University Need-Based Bursary",
        "provider": "Machakos University",
        "level": "University",
        "institution_type": "Public",
        "county": "All",
        "constituency": "",
        "need_flag": "Need",
        "amount": "Institution-awarded amount",
        "deadline": "TBC",
        "documents": "University ID, fee statement, household need declaration",
        "source_url": "https://www.mksu.ac.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    },
    {
        "name": "University Fee Waiver",
        "provider": "University financial aid office",
        "level": "University",
        "institution_type": "All",
        "county": "All",
        "constituency": "",
        "need_flag": "Need",
        "amount": "Institution-awarded amount",
        "deadline": "TBC",
        "documents": "Fee statement, admission record, household need declaration",
        "source_url": "https://www.helb.co.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    },
    {
        "name": "TVET Institutional Bursary",
        "provider": "TVET institution",
        "level": "TVET",
        "institution_type": "All",
        "county": "All",
        "constituency": "",
        "need_flag": "Need",
        "amount": "Institution-awarded amount",
        "deadline": "TBC",
        "documents": "Admission letter, fee statement, household need declaration",
        "source_url": "https://www.tveta.go.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    },
    {
        "name": "Persons with Disabilities Education Support",
        "provider": "Government or county education office",
        "level": "All",
        "institution_type": "All",
        "county": "All",
        "constituency": "",
        "need_flag": "Disability",
        "amount": "Support award",
        "deadline": "TBC",
        "documents": "Disability registration, admission letter, fee structure",
        "source_url": "https://ncpwd.go.ke/",
        "last_verified": "2026-11-19",
        "confidence": "Red",
    },
])


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                level TEXT NOT NULL,
                institution_type TEXT NOT NULL,
                county TEXT NOT NULL,
                constituency TEXT NOT NULL,
                need_flag TEXT NOT NULL,
                amount TEXT NOT NULL,
                deadline TEXT NOT NULL,
                documents TEXT NOT NULL,
                source_url TEXT NOT NULL,
                last_verified TEXT NOT NULL,
                confidence TEXT NOT NULL
            )
        """)
        count = connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        if count == 0:
            connection.executemany(
                """INSERT INTO opportunities (
                    name, provider, level, institution_type, county, constituency,
                    need_flag, amount, deadline, documents, source_url,
                    last_verified, confidence
                ) VALUES (
                    :name, :provider, :level, :institution_type, :county,
                    :constituency, :need_flag, :amount, :deadline, :documents,
                    :source_url, :last_verified, :confidence
                )""",
                SEED_OPPORTUNITIES,
            )


def get_opportunities():
    with get_connection() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM opportunities ORDER BY confidence DESC, name"
        )]


def match_opportunities(profile):
    matches = []
    for opportunity in get_opportunities():
        if opportunity["level"] not in ("All", profile["level"]):
            continue
        if opportunity["institution_type"] not in ("All", profile["institution_type"]):
            continue
        if opportunity["county"] not in ("All", profile["county"]):
            continue
        if opportunity["constituency"] and opportunity["constituency"] != profile["constituency"]:
            continue
        if opportunity["need_flag"] == "Need" and not profile["need_flag"]:
            continue
        if opportunity["need_flag"] == "Disability" and not profile["disability"]:
            continue
        matches.append(opportunity)
    return matches


def calculate_fee_gap(annual_fees, scholarship, helb):
    gap = max(0, float(annual_fees) - float(scholarship) - float(helb))
    return round(gap, 2)
