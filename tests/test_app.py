from app import app
from bursary_model import calculate_fee_gap, match_opportunities


def test_fee_gap_calculation():
    assert calculate_fee_gap(100000, 40000, 30000) == 30000
    assert calculate_fee_gap(50000, 40000, 30000) == 0


def test_matching_filters_constituency():
    profile = {
        "level": "University",
        "institution_type": "Public",
        "county": "Machakos",
        "constituency": "Machakos Town",
        "need_flag": True,
        "disability": False,
    }
    matches = match_opportunities(profile)
    names = {match["name"] for match in matches}
    assert "Machakos Town NG-CDF Bursary" in names
    assert "Masinga NG-CDF Bursary" not in names
    assert "Machakos University Need-Based Bursary" in names


def test_fee_gap_api():
    client = app.test_client()
    response = client.post(
        "/api/fee-gap",
        json={"fees": 100000, "scholarship": 40000, "helb": 30000},
    )
    assert response.status_code == 200
    assert response.get_json()["gap"] == 30000


def test_login_page_and_signup_flow():
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    response = client.get("/login")
    assert response.status_code == 200
    assert b"Student Login" in response.data

    response = client.post(
        "/signup",
        data={
            "full_name": "Test Student",
            "enrollment_no": "TEST-001",
            "email": "test.student@example.com",
            "password": "secure123",
            "gender": "Other",
            "course": "Computer Engineering",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    response = client.post(
        "/login",
        data={
            "email": "test.student@example.com",
            "password": "secure123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    response = client.get("/")
    assert response.status_code == 200
    assert b"Test Student" in response.data
