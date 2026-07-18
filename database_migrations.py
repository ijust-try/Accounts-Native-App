"""
Run this file ONCE to add the new columns/tables the mobile app needs,
on top of your existing schema. It never drops or rewrites existing data —
everything here is additive (ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS).

How to run:
    python database_migrations.py

Safe to run more than once — it will just skip anything that already exists.
"""
from backend import get_conn


def run_migrations():
    conn = get_conn()
    cur = conn.cursor()

    # 1. Role on the users table: owner / staff / guest.
    #    Existing rows default to 'owner' since your current app only has
    #    owner/staff logins today — update specific rows to 'guest' as needed
    #    once guest signup exists.
    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'owner'
    """)

    # 2. Link a login to a guest's customer record (nullable — only guests
    #    have this set; owner/staff logins leave it NULL).
    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS cid INTEGER REFERENCES customers(cid)
    """)

    # 3. Government ID / document uploads, tied to a customer.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            did          SERIAL PRIMARY KEY,
            cid          INTEGER NOT NULL REFERENCES customers(cid),
            doc_type     TEXT NOT NULL,
            file_url     TEXT NOT NULL,
            verified     BOOLEAN DEFAULT FALSE,
            uploaded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. Guest-submitted requests to change their stay dates. Guests never
    #    edit `stays` directly from the app — they submit a request here,
    #    and the owner approves/rejects it from the owner app.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stay_update_requests (
            rid            SERIAL PRIMARY KEY,
            sid            INTEGER NOT NULL REFERENCES stays(sid),
            cid            INTEGER NOT NULL REFERENCES customers(cid),
            requested_checkin  DATE,
            requested_checkout DATE,
            reason         TEXT,
            status         TEXT NOT NULL DEFAULT 'pending',
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at    TIMESTAMP
        )
    """)

    # 5. Indexes on the foreign-key columns that get filtered on constantly
    #    (every "payments for this guest", "leaves for this employee", etc.
    #    query). Without these, Postgres has to scan the whole table once
    #    you have real data volume and concurrent users.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stays_cid ON stays(cid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_cid ON payments(cid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_sid ON payments(sid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_remarks_cid ON remarks(cid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_employee_payments_eid ON employee_payments(eid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_employee_leaves_eid ON employee_leaves(eid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_category_property ON expenses(category, property)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_cid ON documents(cid)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_stay_update_requests_cid ON stay_update_requests(cid)")

    conn.commit()
    cur.close()
    conn.close()
    print("Migrations applied successfully.")


def check_money_columns():
    """
    Informational only — does not change anything automatically.

    rent_amount and payment/expense amounts are currently stored as REAL
    (floating point), which can introduce small rounding errors on money
    over time. The correct type for currency is NUMERIC(10,2). Converting
    existing REAL columns to NUMERIC is safe and non-destructive, but
    touches live financial data, so it's deliberately not automated here —
    ask me to run it as its own reviewed step when you're ready:

        ALTER TABLE stays              ALTER COLUMN rent_amount TYPE NUMERIC(10,2);
        ALTER TABLE payments            ALTER COLUMN amount      TYPE NUMERIC(10,2);
        ALTER TABLE employees           ALTER COLUMN base_salary TYPE NUMERIC(10,2);
        ALTER TABLE employee_payments   ALTER COLUMN amount      TYPE NUMERIC(10,2);
        ALTER TABLE expenses            ALTER COLUMN amount      TYPE NUMERIC(10,2);
    """
    print("See the docstring in check_money_columns() for the recommended (manual) next step.")


if __name__ == "__main__":
    run_migrations()