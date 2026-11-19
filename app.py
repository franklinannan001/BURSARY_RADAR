import os
from flask import Flask, jsonify, render_template, request

from bursary_model import calculate_fee_gap, init_db, match_opportunities


app = Flask(__name__)
init_db()


@app.route("/")
def index():
    return render_template("index.html")


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
