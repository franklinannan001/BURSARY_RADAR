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
