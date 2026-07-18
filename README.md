# Accounts-Native-App
FastAPI backend for a multi-property hostel/PG management system — guest, employee, expense, and revenue tracking, built to power a future React Native mobile app with owner and guest portals.
# Hostel Management API

A FastAPI backend for a multi-property hostel/PG management system — guest records, stays, payments, employee salaries/leaves, expense tracking, and revenue reporting. Built to sit behind the existing accounting logic and power a future React Native mobile app with separate owner and guest portals.

## Status

This is an early, working shell — not the full app yet.

**Built so far:**
- Auth: register, login, OTP-based email verification, password reset (JWT-based sessions for mobile)
- Reports: monthly/period/yearly revenue, expenses, profit & loss, food revenue vs. kitchen cost, defaulters list
- A connection pool for Postgres (so the API can handle many simultaneous users without exhausting database connections)
- Schema migrations adding user roles (owner/staff/guest), a documents table, and guest stay-change requests

**Not built yet (planned next):**
- Guests, Employees, Expenses, and Payments endpoints
- Guest-facing endpoints (`/me/...`) for stay info, ledger, dues, document upload
- Vacancy/room-occupancy reporting (currently only in the original Streamlit app)
- The mobile app itself (React Native / Expo)

## Tech stack

- **API:** FastAPI (Python)
- **Database:** PostgreSQL (hosted, e.g. Supabase/Neon/Railway)
- **Auth:** bcrypt password hashing + email OTP + JWT sessions
- **Planned mobile client:** React Native (Expo)

## Project structure

```
hostel-backend/
├── main.py                  # App entry point — run this with uvicorn
├── config.py                # Loads settings from .env
├── backend.py                # Core business logic (DB queries, auth, OTP)
├── db_helpers.py             # Auth-record lookups used by the API layer
├── security.py                # JWT creation/verification, role checks
├── models.py                  # Request/response schemas
├── auth_routes.py             # /auth/* endpoints
├── report_routes.py           # /reports/* endpoints
├── database_migrations.py     # One-time schema updates (safe to re-run)
├── requirements.txt
├── .env.example                # Template for secrets — copy to .env, fill in real values
└── .gitignore
```

## Setup

1. Clone the repo and open it in your editor.
2. Copy `.env.example` to `.env` and fill in your real `DATABASE_URL`, `GMAIL_SENDER`, `GMAIL_APP_PASS`, and a generated `JWT_SECRET`.
3. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\activate        # Windows
   pip install -r requirements.txt
   ```
4. Apply the one-time database migration:
   ```
   python database_migrations.py
   ```
5. Run the API:
   ```
   uvicorn main:app --reload
   ```
6. Open `http://127.0.0.1:8000/docs` for the interactive API docs.
