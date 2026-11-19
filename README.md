# Bursary Radar

Every bursary you qualify for. Every deadline. Before it closes.

This is a hackathon MVP built with Python and Flask. It provides:

- a two-minute student profile and rule-based opportunity matching;
- a fee-gap calculator;
- deadline confidence and source metadata;
- document checklists;
- a simulated SMS reminder preview;
- a human-reviewed notice-reader demo.

> Demo data is illustrative and must be reverified against official sources before launch.
> Bursary Radar is independent and is not affiliated with HELB, the Government of Kenya,
> county governments or NG-CDF offices.

## Run locally

1. Install Python 3.11 or newer.
2. Open a terminal in this project folder.
3. Create and activate an environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

4. Initialize and start the app:

   ```powershell
   python app.py
   ```

5. Open `http://127.0.0.1:5000`.

The first visit opens the student login page. Create an account with the **Create an
account** link; account details are stored locally in `bursary_radar.db`. Set a strong
`SECRET_KEY` environment variable before deploying the app.

### Open from another device

The app listens on all network interfaces by default. Start it with:

```powershell
python app.py
```

Find the host computer's IPv4 address with `ipconfig`, then open
`http://<host-ipv4-address>:5000` on another device connected to the same network.
For example: `http://192.168.1.25:5000`.

Allow Python/Flask through Windows Defender Firewall for private networks if Windows
prompts. Internet users who are not on the same network require hosting with port
forwarding or a cloud tunnel/deployment service.

## Project structure

```text
app.py                 Flask routes and demo endpoints
bursary_model.py       SQLite setup and matching/fee-gap logic
templates/index.html   Main application UI
static/styles.css      Responsive interface
static/app.js          Profile, planner and UI interactions
tests/test_app.py      Focused Flask and matching tests
```

## Data integration

Opportunities are seeded into `bursary_radar.db` on the first run. Replace
`SEED_OPPORTUNITIES` in `bursary_model.py` with verified office data before a pilot.
Each record should include:

- name and provider;
- level and institution type;
- county and optional constituency;
- need criteria;
- amount;
- deadline;
- source URL and last-verified date;
- confidence;
- required documents.

## SMS integration

The current reminder panel is a demo. To enable live SMS:

1. Create an Africa's Talking account and obtain a sandbox/API key.
2. Add `AFRICAS_TALKING_USERNAME` and `AFRICAS_TALKING_API_KEY` environment variables.
3. Implement `send_sms()` in `app.py` using the Africa's Talking SDK.
4. Schedule deadline checks (14, 7 and 2 days) through a cron job or cloud task.
5. Store only the phone number and reminder consent needed for delivery.

No phone number or uploaded document is stored by this demo.