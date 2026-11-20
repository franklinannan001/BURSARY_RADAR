# Bursary Radar

Bursary Radar is a mobile-first, low-data funding discovery tool for Kenyan students.

> Bursary Radar is an independent student project. It is not affiliated with HELB, the Universities Fund, NG-CDF, county governments or any funder. Always confirm details at the official source. Never pay money to apply for a bursary.

## Screens

Screenshots can be placed here:

- Landing and sample profile
- Five-step profile wizard
- Matched opportunity cards
- My Plan and SMS preview
- `/poll` and `/admin`

## Architecture

```mermaid
flowchart LR
  Student[Student browser] --> Flask[Flask/Jinja frontend]
  Flask --> API["Public /api endpoints"]
  API --> SQLite[(SQLite / admin-managed listings)]
  Admin[Government official] -->|Account role and login session| Flask
  Admin -->|Optional X-Admin-Token| API
  API --> Draft[Notice Reader draft]
  Draft -->|Approval| SQLite
```

The Flask/Jinja frontend serves the student and admin pages. Matching for anonymous visitors is stateless: nothing from the profile is stored. If a signed-in student who has given SMS consent searches, their county, constituency, study level and relevant institution details are saved so matching bursary alerts can be targeted; optional need indicators are never stored. Applications store the submitted details and documents (see below). My Plan is stored only in the browser's `localStorage`.

## Run locally

Windows (PowerShell):

```powershell
cd BURSARY_RADAR
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python app.py
```

macOS / Linux:

```bash
cd BURSARY_RADAR
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

## Environment

Variables the application reads:

- `SECRET_KEY`: signs login sessions. **Required in production.** If it is not set, the app falls back to a public development key, which would let anyone forge a session, including an admin session
- `ADMIN_TOKEN`: optional token for direct admin API clients; web admins sign in with an admin account
- `APPLICATION_DOCUMENT_KEY`: required Fernet key for encrypting retained application document images; keep it backed up and unchanged
- `TESSERACT_CMD`: optional path to the Tesseract OCR executable when it is not on `PATH`
- `INFOBIP_BASE_URL`, `INFOBIP_API_KEY`: Infobip HTTPS base host and API key; configure in ignored local `.env` or deployment secrets, never in source control
- `INFOBIP_SENDER_ID`: Infobip-approved SMS sender ID; the example value is only a placeholder. SMS is sent only when all three Infobip variables are set
- `CORS_ORIGINS`: comma-separated allowed browser origins
- `HOST`, `PORT`, `FLASK_DEBUG`: used when running `python app.py` locally (debug is on unless `FLASK_DEBUG=0`)

Reserved placeholders (listed in `.env.example` but **not read by the code yet**): `APP_ENV`, `DATABASE_URL`, `LLM_PROVIDER`, `LLM_API_KEY`, `ENABLE_SMS`, `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID`. Setting them has no effect: the Notice Reader is always the offline mock, and SMS is controlled only by the Infobip variables.

## Pages and API overview

Pages: `/` (home), `/signup`, `/login`, `/dashboard`, `/poll`, `/admin`.

Public and student endpoints:

- `GET /healthz`
- `GET /api/opportunities`
- `GET /api/opportunities/{id}`
- `POST /api/match`
- `POST /api/reminders/preview`
- `POST /api/reports`
- `POST /api/feedback`
- `POST /api/events`
- `GET|POST /api/poll`
- `POST /api/applications`: submits a matched bursary application for a signed-in student

Admin endpoints (admin login session or, where supported, the `X-Admin-Token` header):

- `POST /api/admin/bursaries`: creates a validated bursary; requires an authenticated admin session
- `GET|POST /api/admin/opportunities`
- `PUT|PATCH|DELETE /api/admin/opportunities/{id}`
- `POST /api/admin/opportunities/{id}/verify`
- `GET /api/admin/applications`, `GET /api/admin/applications/{id}/documents/{type}`, `POST /api/admin/applications/{id}/status`: admin-session-only application listing, document viewing and status updates
- `GET /api/admin/reports`, `PATCH /api/admin/reports/{id}`
- `GET /api/admin/metrics`
- `GET /api/admin/export`
- `GET /api/admin/drafts`, `POST /api/admin/notices/extract`, `POST /api/admin/drafts/{id}/approve`, `POST /api/admin/drafts/{id}/reject`: Notice Reader draft review

Infobip sends an SMS confirmation after an application is stored, and alerts opted-in students when an admin publishes an open or upcoming bursary matching their saved area and study profile.

Admin accounts are selected during signup and login and require an email ending in `.go.ke`. This checks the address domain only; it does not verify control of the mailbox or government employment. The admin dashboard is at `/admin`.

No Swagger UI is enabled.

## Tests

```bash
python -m pytest -q
```

The tests cover confidence, public/private matching, county and constituency restrictions, reminder schedules, removed features, role-based admin access, bursary validation and admin authentication.

### Student applications and document processing

Students can apply from personalized results. The application confirms the current county and constituency from the matching profile and checks those values against the bursary's county/constituency restrictions. This is a self-declared location match, not proof of residence. Kenyan ID and birth-certificate images are OCR-screened and retained encrypted in SQLite for admin review; an optional passport image is OCR-scanned for ICAO TD3 MRZ checks. OCR/MRZ results are advisory and require human review. ID cards and birth certificates generally do not have an MRZ, and an MRZ cannot establish current residence.

Student signup requires a valid Kenyan mobile number and SMS consent. The number is normalized to E.164. When an opted-in student searches, their county, constituency, study level and relevant institution details are saved to target matching bursary alerts; optional need indicators are not stored. SMS is outbound only; inbound replies are not configured. If Infobip is unavailable, the application remains saved and the UI clearly reports that its confirmation SMS was not accepted. The admin bursary upload is also preserved if an alert send fails.

Set `INFOBIP_BASE_URL` to the HTTPS Infobip API host, `INFOBIP_API_KEY` to a secret, and `INFOBIP_SENDER_ID` to a sender approved for your account/route. The example sender is a placeholder and may not be accepted by Infobip. Provider acceptance is not a guarantee of handset delivery. Never commit `.env`; rotate any API key pasted into chats or otherwise exposed before production use.

Install Tesseract OCR on local hosts (and put its executable on `PATH`, or set `TESSERACT_CMD`). Render installs the Tesseract system package during build. Generate an application-document key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set that value as `APPLICATION_DOCUMENT_KEY` in `.env` and in the deployment environment. Back it up securely: losing or changing the key makes retained application images unreadable. Only authenticated admin sessions can list applications or view the retained documents.

## Deploy on Render

1. Push the project to a Git repository.
2. Create a Python Web Service from the repository.
3. Render will read `render.yaml`.
4. In the Render dashboard, set `SECRET_KEY` (a long random value), `APPLICATION_DOCUMENT_KEY` and `CORS_ORIGINS`, plus `INFOBIP_API_KEY`. Set `ADMIN_TOKEN` only if direct API-token access is required. Do not rely on `APP_ENV`; the code does not read it.
5. Use `gunicorn app:app --bind 0.0.0.0:$PORT` as the start command.

## SQLite and redeployment

Render's default disk is ephemeral. SQLite edits, applications, retained documents and verification dates may disappear on redeploy.
Export reviewed data with `GET /api/admin/export` as a backup, or configure a persistent PostgreSQL database. The application no longer seeds opportunity records on startup.

## Seed and verification

The code does not seed any opportunity listings, and no real or sample opportunities are bundled in the repository. Government officials can sign in at `/admin` and submit bursaries with their official source, eligibility, number of awards, application window, disbursement dates and application details. Any demonstration bursary or admin account created for a presentation must be clearly labelled "DEMO ONLY". Do not commit `*.db` files: they can contain accounts and applications.

See [DATA_VERIFICATION.md](docs/DATA_VERIFICATION.md), [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) and [ROADMAP.md](docs/ROADMAP.md).

## Limitations

- Award amounts and application windows may change.
- The database is local unless migrated to a hosted database.
- SMS reminder scheduling is preview-only. Application confirmations and new matching bursary alerts use Infobip when configured.
- Mock Notice Reader output requires human review and is not an extraction engine.
- Anonymous matching profiles are not stored. Profiles of signed-in, SMS-consenting students are saved to target alerts, and application details are stored when an application is submitted.
- Rate limits use in-memory storage, which resets on restart and is not shared across workers.
