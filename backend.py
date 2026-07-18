import psycopg2
import psycopg2.extras
import bcrypt
import os
from datetime import date, timedelta
try:
    import streamlit as st
    DATABASE_URL    = st.secrets["DATABASE_URL"]
    GMAIL_SENDER    = st.secrets["GMAIL_SENDER"]
    GMAIL_APP_PASS  = st.secrets["GMAIL_APP_PASS"]
    OTP_EXPIRY_MINS = int(st.secrets.get("OTP_EXPIRY_MINS", 2))
except Exception:
    try:
        from config import DATABASE_URL, GMAIL_SENDER, GMAIL_APP_PASS, OTP_EXPIRY_MINS
    except ImportError:
        DATABASE_URL    = os.environ.get("DATABASE_URL", "")
        GMAIL_SENDER    = os.environ.get("GMAIL_SENDER", "")
        GMAIL_APP_PASS  = os.environ.get("GMAIL_APP_PASS", "")
        OTP_EXPIRY_MINS = 2
# ---------------- DB CONNECTION ---------------- #
# Every function below calls get_conn() then, at the end, calls cur.close();
# conn.close() — that pattern is unchanged from your original Streamlit app.
# The problem: opening a brand-new TCP connection + login to Postgres on
# every single call doesn't scale once 100+ people are hitting the API —
# Postgres only allows ~100 open connections by default, and each new
# connection is slow to establish.
#
# Fix: keep a small pool of already-open connections and hand them out.
# get_conn() returns a lightweight wrapper (_PooledConn) instead of the raw
# psycopg2 connection — every method call (cursor(), commit(), etc.) is
# forwarded straight through to the real connection, EXCEPT close(), which
# returns the connection to the pool instead of really closing it. This
# means every "cur.close(); conn.close()" call already in this file below
# keeps working unchanged.
#
# (An earlier version of this tried to monkeypatch .close directly onto the
# raw psycopg2 connection object. That's unsafe: psycopg2's own pool code
# sometimes calls conn.close() internally to actually discard a connection,
# and a monkeypatched close() would catch that call too and call putconn()
# again, causing infinite recursion. The wrapper class below avoids that
# because it's a separate object — calling wrapper.close() never triggers
# the real connection's own close() through the pool's internal logic.)
from psycopg2.pool import ThreadedConnectionPool

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        # minconn/maxconn: tune these based on your host's connection limit.
        # 20 max is comfortable headroom for 100+ users on a typical
        # small-hostel-scale API without exhausting a free-tier Postgres plan.
        _pool = ThreadedConnectionPool(minconn=2, maxconn=20, dsn=DATABASE_URL)
    return _pool


class _PooledConn:
    """Wraps a pooled psycopg2 connection so existing code's `conn.close()`
    calls return it to the pool instead of actually closing the socket."""

    def __init__(self, real_conn, pool):
        object.__setattr__(self, "_real_conn", real_conn)
        object.__setattr__(self, "_pool", pool)

    def close(self):
        self._pool.putconn(self._real_conn)

    def __getattr__(self, name):
        return getattr(self._real_conn, name)


def get_conn():
    pool = _get_pool()
    return _PooledConn(pool.getconn(), pool)
# ---------------- CONSTANTS ---------------- #
GUEST_LOCATIONS = ["PKR Prime", "Matsaya", "Navalur", "Palavakkam"]
GUEST_GENDERS   = ["Male", "Female", "Other"]
PAYMENT_TYPES   = ["rent", "food", "deposit", "misc"]
PAYMENT_MODES   = ["cash", "UPI", "bank transfer"]
# ---------------- DATE HELPERS ---------------- #
def get_min_allowed_date():
    return date.today() - timedelta(days=7)
def validate_dates(checkin, checkout):
    min_date = get_min_allowed_date()
    if checkin and checkin < min_date:
        return False, f"Check-in cannot be before {min_date.strftime('%d/%m/%Y')}"
    if checkout and checkout < min_date:
        return False, f"Check-out cannot be before {min_date.strftime('%d/%m/%Y')}"
    if checkin and checkout and checkout < checkin:
        return False, "Check-out cannot be before check-in"
    return True, ""
def _fmt_date(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    s = str(value).strip()
    return None if s.lower() in ("", "nat", "none", "nan") else s
def _parse_date(value):
    import pandas as pd
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(parsed) else parsed.date()
    except Exception:
        return None
# ---------------- OTP ---------------- #
import smtplib
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
_otp_store = {}
def _generate_otp():
    return "".join(random.choices(string.digits, k=6))
def send_otp(email):
    email = email.strip().lower()
    otp   = _generate_otp()
    _otp_store[email] = {
        "otp":     otp,
        "expires": datetime.now() + timedelta(minutes=OTP_EXPIRY_MINS),
    }
    subject = "Your Hostel App OTP"
    body    = f"""
    <div style="font-family:sans-serif;max-width:400px;margin:auto;
                padding:2rem;border-radius:10px;background:#0f172a;color:#f1f5f9;">
        <h2 style="color:#a855f7;">🏠 Hostel Management</h2>
        <p style="color:#94a3b8;">Your one-time password:</p>
        <div style="font-size:2.5rem;font-weight:800;letter-spacing:0.3em;
                    color:#e9d5ff;text-align:center;padding:1rem;
                    background:#1e293b;border-radius:8px;margin-bottom:1.5rem;">
            {otp}
        </div>
        <p style="color:#64748b;font-size:0.85rem;">
            Expires in {OTP_EXPIRY_MINS} minutes.
        </p>
    </div>
    """
    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_SENDER
        msg["To"]      = email
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_SENDER, email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)
def verify_otp(email, otp_input):
    email  = email.strip().lower()
    record = _otp_store.get(email)
    if not record:
        return False, "No OTP sent to this email"
    if datetime.now() > record["expires"]:
        del _otp_store[email]
        return False, "OTP expired. Please request a new one."
    if otp_input.strip() != record["otp"]:
        return False, "Incorrect OTP"
    del _otp_store[email]
    return True, ""
# ---------------- AUTH ---------------- #
def is_email_allowed(email):
    email = email.strip().lower()
    conn  = get_conn()
    cur   = conn.cursor()
    cur.execute("SELECT 1 FROM allowed_users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row is not None
def is_email_registered(email):
    email = email.strip().lower()
    conn  = get_conn()
    cur   = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row is not None
def register_user(user_id, email, password):
    email = email.strip().lower()
    conn  = get_conn()
    cur   = conn.cursor()
    cur.execute("SELECT 1 FROM allowed_users WHERE email=%s", (email,))
    if not cur.fetchone():
        cur.close(); conn.close()
        return "Email not authorized"
    cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
    if cur.fetchone():
        cur.close(); conn.close()
        return "User already registered"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash) VALUES (%s, %s, %s)",
            (user_id, email, hashed.decode()),
        )
        conn.commit()
    except Exception:
        cur.close(); conn.close()
        return "Username already taken"
    cur.close(); conn.close()
    return "Registered successfully"
def login_user(user_id, password):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE user_id=%s", (user_id,))
    result = cur.fetchone()
    cur.close(); conn.close()
    if result:
        stored = result[0]
        if isinstance(stored, str):
            stored = stored.encode()
        if bcrypt.checkpw(password.encode(), stored):
            return True
    return False
def reset_password(user_id, email, new_password, check_only=False):
    email = email.strip().lower()
    conn  = get_conn()
    cur   = conn.cursor()
    cur.execute("SELECT email FROM users WHERE user_id=%s", (user_id,))
    result = cur.fetchone()
    if not result:
        cur.close(); conn.close()
        return "User not found"
    if result[0].strip().lower() != email:
        cur.close(); conn.close()
        return "Email does not match"
    if check_only:
        cur.close(); conn.close()
        return "ok"
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
    cur.execute(
        "UPDATE users SET password_hash=%s WHERE user_id=%s",
        (hashed.decode(), user_id)
    )
    conn.commit()
    cur.close(); conn.close()
    return "Password reset successfully"
# ---------------- CUSTOMERS ---------------- #
def get_all_customers():
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT c.cid, c.first_name, c.last_name, c.phone,
               c.emergency_contact, c.aadhar, c.gender,
               s.location, s.room_number, s.checkin, s.checkout,
               s.sid, s.status, s.rent_amount
        FROM customers c
        LEFT JOIN stays s ON s.sid = (
            SELECT sid FROM stays
            WHERE cid = c.cid
            ORDER BY created_at DESC LIMIT 1
        )
        ORDER BY c.cid ASC
    """, conn)
    conn.close()
    for col in ("checkin", "checkout"):
        if col in df.columns:
            df[col] = df[col].apply(_parse_date)
    return df
def get_customer_by_cid(cid):
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT cid, first_name, last_name, phone,
               aadhar, emergency_contact, gender
        FROM customers WHERE cid=%s
    """, (cid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None
def get_customer_by_phone(phone):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT cid FROM customers WHERE phone=%s", (phone,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else None
def add_customer(first_name, last_name, phone, aadhar, emergency_contact, gender):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO customers
        (first_name, last_name, phone, aadhar, emergency_contact, gender)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING cid
    """, (first_name, last_name, phone, aadhar, emergency_contact, gender))
    cid = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return cid
def update_customer(cid, first_name, last_name, phone, aadhar, emergency_contact, gender):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE customers SET
            first_name=%s, last_name=%s, phone=%s,
            aadhar=%s, emergency_contact=%s, gender=%s
        WHERE cid=%s
    """, (first_name, last_name, phone, aadhar, emergency_contact, gender, cid))
    conn.commit()
    cur.close(); conn.close()
def delete_customer(cid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM payments WHERE cid=%s", (cid,))
    cur.execute("DELETE FROM remarks WHERE cid=%s", (cid,))
    cur.execute("DELETE FROM stays WHERE cid=%s", (cid,))
    cur.execute("DELETE FROM customers WHERE cid=%s", (cid,))
    conn.commit()
    cur.close(); conn.close()
def check_duplicate_customer(first_name, last_name, phone, exclude_cid=None):
    conn = get_conn()
    cur  = conn.cursor()
    if phone:
        q    = "SELECT cid, first_name, last_name FROM customers WHERE phone=%s"
        args = [phone]
        if exclude_cid:
            q += " AND cid!=%s"
            args.append(exclude_cid)
        cur.execute(q, args)
        row = cur.fetchone()
        if row:
            cur.close(); conn.close()
            return f"Phone already exists for: {row[1]} {row[2]} (CID {row[0]})"
    cur.close(); conn.close()
    return None
# ---------------- STAYS ---------------- #
def get_stays_for_customer(cid):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT sid, cid, location, room_number,
               checkin, checkout, status, rent_amount
        FROM stays WHERE cid=%s
        ORDER BY created_at DESC
    """, conn, params=(cid,))
    conn.close()
    for col in ("checkin", "checkout"):
        df[col] = df[col].apply(_parse_date)
    return df
def add_stay(cid, location, room_number, checkin, checkout, status="active", rent_amount=0):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO stays (cid, location, room_number, checkin, checkout, status, rent_amount)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING sid
    """, (cid, location, room_number,
          _fmt_date(checkin), _fmt_date(checkout), status, rent_amount))
    sid = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return sid
def update_stay(sid, location, room_number, checkin, checkout, status, rent_amount=0):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE stays SET
            location=%s, room_number=%s, checkin=%s,
            checkout=%s, status=%s, rent_amount=%s
        WHERE sid=%s
    """, (location, room_number,
          _fmt_date(checkin), _fmt_date(checkout), status, rent_amount, sid))
    conn.commit()
    cur.close(); conn.close()
def delete_stay(sid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM payments WHERE sid=%s", (sid,))
    cur.execute("DELETE FROM stays WHERE sid=%s", (sid,))
    conn.commit()
    cur.close(); conn.close()
# ---------------- ROOM OCCUPANCY ---------------- #
def get_room_occupancy(location):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT c.cid, c.first_name, c.last_name, c.phone,
               s.room_number, s.checkin, s.checkout, s.status
        FROM stays s
        JOIN customers c ON c.cid = s.cid
        WHERE s.location = %s AND s.status = 'active'
    """, conn, params=(location,))
    conn.close()
    df["checkin"]  = df["checkin"].apply(_parse_date)
    df["checkout"] = df["checkout"].apply(_parse_date)
    occupancy = {}
    for _, row in df.iterrows():
        key = str(row["room_number"]).strip()
        if not key:
            continue
        entry = {
            "name":     f"{row['first_name']} {row.get('last_name','') or ''}".strip(),
            "cid":      row["cid"],
            "phone":    row.get("phone", ""),
            "checkin":  row["checkin"],
            "checkout": row["checkout"],
        }
        occupancy.setdefault(key, []).append(entry)
    return occupancy
# ---------------- PAYMENTS ---------------- #
def get_payments_for_customer(cid):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT p.payment_id, p.sid, p.amount, p.payment_type,
               p.payment_date, p.payment_mode, p.notes,
               s.location, s.room_number
        FROM payments p
        JOIN stays s ON s.sid = p.sid
        WHERE p.cid=%s
        ORDER BY p.payment_date DESC
    """, conn, params=(cid,))
    conn.close()
    return df
def get_payments_for_stay(sid):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT payment_id, amount, payment_type,
               payment_date, payment_mode, notes
        FROM payments WHERE sid=%s
        ORDER BY payment_date DESC
    """, conn, params=(sid,))
    conn.close()
    return df
def add_payment(cid, sid, amount, payment_type, payment_date, payment_mode, notes=""):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO payments
        (cid, sid, amount, payment_type, payment_date, payment_mode, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (cid, sid, amount, payment_type,
          _fmt_date(payment_date), payment_mode, notes))
    conn.commit()
    cur.close(); conn.close()
def get_total_paid_by_customer(cid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE cid=%s", (cid,))
    total = cur.fetchone()[0]
    cur.close(); conn.close()
    return total
def get_total_paid_for_stay(sid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE sid=%s", (sid,))
    total = cur.fetchone()[0]
    cur.close(); conn.close()
    return total
# ---------------- PAYMENTS SUMMARY ---------------- #
def get_all_payment_summaries(payment_mode_filter=None):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT
            c.cid, c.first_name, c.last_name, c.phone,
            s.sid, s.location, s.room_number,
            s.checkin, s.checkout, s.status, s.rent_amount,
            COALESCE((SELECT SUM(amount) FROM payments p
                WHERE p.cid=c.cid AND p.sid=s.sid AND p.payment_type='deposit'),0) AS deposit_paid,
            COALESCE((SELECT SUM(amount) FROM payments p
                WHERE p.cid=c.cid AND p.sid=s.sid AND p.payment_type='rent'),0) AS rent_paid,
            COALESCE((SELECT SUM(amount) FROM payments p
                WHERE p.cid=c.cid AND p.sid=s.sid AND p.payment_type='food'),0) AS food_paid,
            (SELECT MAX(payment_date) FROM payments p
                WHERE p.cid=c.cid AND p.sid=s.sid) AS last_payment_date,
            COALESCE((SELECT STRING_AGG(DISTINCT payment_mode,',') FROM payments p
                WHERE p.cid=c.cid AND p.sid=s.sid),'') AS payment_modes_used
        FROM customers c
        JOIN stays s ON s.cid=c.cid
        WHERE s.status='active'
        ORDER BY s.checkin ASC
    """, conn)
    conn.close()
    df["checkin"]  = df["checkin"].apply(_parse_date)
    df["checkout"] = df["checkout"].apply(_parse_date)
    if payment_mode_filter and payment_mode_filter != "All":
        df = df[df["payment_modes_used"].str.contains(payment_mode_filter, na=False)]
    today = date.today()
    df["rent_due"]     = df["rent_amount"].fillna(0)
    df["rent_balance"] = (df["rent_due"] - df["rent_paid"]).clip(lower=0)
    def alert_status(row):
        checkin = row["checkin"]
        days    = (today - checkin).days if checkin else 0
        if row["deposit_paid"] == 0 and days >= 5:
            return "red"
        if row["deposit_paid"] == 0 or row["rent_balance"] > 0:
            return "red"
        return "green"
    alert_values = []
    for _, row in df.iterrows():
        alert_values.append(alert_status(row))
    df["alert"] = alert_values
    df["days_since_checkin"] = df["checkin"].apply(
        lambda d: (today - d).days if d else 0
    )
    df["deposit_overdue"] = (
        (df["deposit_paid"] == 0) & (df["days_since_checkin"] >= 5)
    )
    return df
# ---------------- REMARKS ---------------- #
def get_remarks_for_customer(cid):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT rid, note, created_at FROM remarks
        WHERE cid=%s ORDER BY created_at DESC
    """, conn, params=(cid,))
    conn.close()
    return df
def add_remark(cid, note):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("INSERT INTO remarks (cid, note) VALUES (%s, %s)", (cid, note))
    conn.commit()
    cur.close(); conn.close()
def delete_remark(rid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM remarks WHERE rid=%s", (rid,))
    conn.commit()
    cur.close(); conn.close()
# ---------------- EMPLOYEES ---------------- #
EMPLOYEE_PROPERTIES = ["PKR Prime", "Matsaya", "Navalur", "Palavakkam", "All Properties"]
EMPLOYEE_PAY_TYPES  = ["salary", "advance", "bonus", "misc"]
def get_all_employees():
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT e.eid, e.name, e.phone, e.aadhar, e.address,
               e.property, e.base_salary,
               COALESCE((SELECT SUM(amount) FROM employee_payments
                         WHERE eid=e.eid AND pay_type='salary'),0) AS salary_paid,
               COALESCE((SELECT SUM(amount) FROM employee_payments
                         WHERE eid=e.eid AND pay_type='advance'),0) AS advance_paid,
               COALESCE((SELECT SUM(amount) FROM employee_payments
                         WHERE eid=e.eid AND pay_type='bonus'),0) AS bonus_paid,
               COALESCE((SELECT SUM(amount) FROM employee_payments
                         WHERE eid=e.eid AND pay_type='misc'),0) AS misc_paid,
               COALESCE((SELECT COUNT(*) FROM employee_leaves
                         WHERE eid=e.eid),0) AS total_leaves
        FROM employees e ORDER BY e.name ASC
    """, conn)
    conn.close()
    return df
def get_employee_by_eid(eid):
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM employees WHERE eid=%s", (eid,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None
def add_employee(name, phone, aadhar, address, property_, base_salary):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO employees (name, phone, aadhar, address, property, base_salary)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING eid
    """, (name, phone, aadhar, address, property_, base_salary))
    eid = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return eid
def update_employee(eid, name, phone, aadhar, address, property_, base_salary):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE employees SET
            name=%s, phone=%s, aadhar=%s, address=%s,
            property=%s, base_salary=%s
        WHERE eid=%s
    """, (name, phone, aadhar, address, property_, base_salary, eid))
    conn.commit()
    cur.close(); conn.close()
def delete_employee(eid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM employee_payments WHERE eid=%s", (eid,))
    cur.execute("DELETE FROM employee_leaves WHERE eid=%s", (eid,))
    cur.execute("DELETE FROM employees WHERE eid=%s", (eid,))
    conn.commit()
    cur.close(); conn.close()
def get_payments_for_employee(eid):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT epid, pay_type, amount, pay_date, notes
        FROM employee_payments WHERE eid=%s
        ORDER BY pay_date DESC
    """, conn, params=(eid,))
    conn.close()
    return df
def get_employee_salary_this_month(eid, month=None, year=None):
    if month is None: month = date.today().month
    if year  is None: year  = date.today().year
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(amount),0)
        FROM employee_payments
        WHERE eid=%s AND pay_type='salary'
          AND EXTRACT(MONTH FROM pay_date)=%s
          AND EXTRACT(YEAR  FROM pay_date)=%s
    """, (eid, month, year))
    total = cur.fetchone()[0]
    cur.close(); conn.close()
    return float(total)
def add_employee_payment(eid, amount, pay_type, pay_date, notes=""):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO employee_payments (eid, amount, pay_type, pay_date, notes)
        VALUES (%s, %s, %s, %s, %s) RETURNING epid
    """, (eid, amount, pay_type, _fmt_date(pay_date), notes))
    epid = cur.fetchone()[0]
    if pay_type in ("salary", "advance", "bonus"):
        cur.execute("SELECT name, property FROM employees WHERE eid=%s", (eid,))
        emp_row  = cur.fetchone()
        emp_name = emp_row[0] if emp_row else f"EID {eid}"
        emp_prop = emp_row[1] if emp_row else "All Properties"
        exp_note = f"{emp_name} ({notes})" if notes else emp_name
        cur.execute("""
            INSERT INTO expenses
                (category, sub_category, property, amount, expense_date, notes, source_id, source_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, ("Employee Salary", pay_type.capitalize(), emp_prop,
              amount, _fmt_date(pay_date), exp_note, epid, "employee_payment"))
    conn.commit()
    cur.close(); conn.close()
def delete_employee_payment(epid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "DELETE FROM expenses WHERE source_id=%s AND source_type='employee_payment'",
        (epid,)
    )
    cur.execute("DELETE FROM employee_payments WHERE epid=%s", (epid,))
    conn.commit()
    cur.close(); conn.close()
def get_leaves_for_employee(eid):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql("""
        SELECT elid, leave_date, reason
        FROM employee_leaves WHERE eid=%s
        ORDER BY leave_date DESC
    """, conn, params=(eid,))
    conn.close()
    return df
def add_employee_leave(eid, leave_date, reason=""):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO employee_leaves (eid, leave_date, reason)
        VALUES (%s, %s, %s)
    """, (eid, _fmt_date(leave_date), reason))
    conn.commit()
    cur.close(); conn.close()
def delete_employee_leave(elid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM employee_leaves WHERE elid=%s", (elid,))
    conn.commit()
    cur.close(); conn.close()
# ---------------- EXPENSES ---------------- #
EXPENSE_CATEGORIES = [
    "Employee Salary","Electricity","Water","Sewage",
    "Maintenance","Kitchen","Rent","Miscellaneous",
]
EXPENSE_SUB_CATEGORIES = {
    "Employee Salary":  ["Salary","Advance","Bonus"],
    "Electricity":      ["Electricity"],
    "Water":            ["Water"],
    "Sewage":           ["Sewage"],
    "Maintenance":      ["AC","WiFi","Elevator","Electrical","Plumbing"],
    "Kitchen":          ["Local Vegetables","Supermarket Grocery","Gas"],
    "Rent":             ["Rent"],
    "Miscellaneous":    ["Miscellaneous"],
}
EXPENSE_PROPERTIES = ["PKR Prime","Matsaya","Navalur","Palavakkam","All Properties"]
def add_expense(category, sub_category, property_, amount, expense_date, notes=""):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO expenses (category, sub_category, property, amount, expense_date, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (category, sub_category, property_, amount, _fmt_date(expense_date), notes))
    conn.commit()
    cur.close(); conn.close()
def delete_expense(xid):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT source_id, source_type FROM expenses WHERE xid=%s", (xid,))
    row = cur.fetchone()
    if row and row[1] == "employee_payment" and row[0]:
        cur.execute("DELETE FROM employee_payments WHERE epid=%s", (row[0],))
    cur.execute("DELETE FROM expenses WHERE xid=%s", (xid,))
    conn.commit()
    cur.close(); conn.close()
def get_expenses(month=None, year=None, category=None, property_=None):
    import pandas as pd
    conn   = get_conn()
    query  = "SELECT * FROM expenses WHERE 1=1"
    params = []
    if month and year:
        query += " AND EXTRACT(MONTH FROM expense_date)=%s AND EXTRACT(YEAR FROM expense_date)=%s"
        params += [month, year]
    if category and category != "All":
        query += " AND category=%s"
        params.append(category)
    if property_ and property_ != "All":
        query += " AND (property=%s OR property='All Properties')"
        params.append(property_)
    query += " ORDER BY expense_date DESC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df
def get_expense_summary_by_category(month, year, property_=None):
    import pandas as pd
    conn   = get_conn()
    query  = """
        SELECT category, SUM(amount) as total FROM expenses
        WHERE EXTRACT(MONTH FROM expense_date)=%s
          AND EXTRACT(YEAR  FROM expense_date)=%s
    """
    params = [month, year]
    if property_ and property_ != "All":
        query += " AND (property=%s OR property='All Properties')"
        params.append(property_)
    query += " GROUP BY category ORDER BY total DESC"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df
def get_food_revenue_vs_cost(month, year):
    import pandas as pd
    conn = get_conn()
    rev_df = pd.read_sql("""
        SELECT s.location, SUM(p.amount) as food_revenue
        FROM payments p JOIN stays s ON s.sid=p.sid
        WHERE p.payment_type='food'
          AND EXTRACT(MONTH FROM p.payment_date)=%s
          AND EXTRACT(YEAR  FROM p.payment_date)=%s
          AND s.location IN ('PKR Prime','Matsaya')
        GROUP BY s.location
    """, conn, params=[month, year])
    cost_df = pd.read_sql("""
        SELECT SUM(amount) as kitchen_cost FROM expenses
        WHERE category='Kitchen'
          AND EXTRACT(MONTH FROM expense_date)=%s
          AND EXTRACT(YEAR  FROM expense_date)=%s
    """, conn, params=[month, year])
    conn.close()
    total_revenue = rev_df["food_revenue"].sum() if not rev_df.empty else 0
    kitchen_cost  = 0
    if not cost_df.empty and cost_df["kitchen_cost"].iloc[0] is not None:
        kitchen_cost = float(cost_df["kitchen_cost"].iloc[0])
    return {
        "revenue_by_property": rev_df,
        "total_food_revenue":  total_revenue,
        "kitchen_cost":        kitchen_cost,
        "food_profit":         total_revenue - kitchen_cost,
    }
def get_monthly_revenue(month, year, property_=None):
    import pandas as pd
    conn   = get_conn()
    query  = """
        SELECT s.location, p.payment_type, SUM(p.amount) as amount
        FROM payments p JOIN stays s ON s.sid=p.sid
        WHERE EXTRACT(MONTH FROM p.payment_date)=%s
          AND EXTRACT(YEAR  FROM p.payment_date)=%s
    """
    params = [month, year]
    if property_ and property_ != "All":
        query += " AND s.location=%s"
        params.append(property_)
    query += " GROUP BY s.location, p.payment_type"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df
def get_monthly_expenses_total(month, year, property_=None):
    conn   = get_conn()
    cur    = conn.cursor()
    query  = """
        SELECT SUM(amount) FROM expenses
        WHERE EXTRACT(MONTH FROM expense_date)=%s
          AND EXTRACT(YEAR  FROM expense_date)=%s
    """
    params = [month, year]
    if property_ and property_ != "All":
        query += " AND (property=%s OR property='All Properties')"
        params.append(property_)
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close(); conn.close()
    return float(row[0]) if row and row[0] else 0.0
# ---------------- MULTI-PERIOD REPORTS ---------------- #
def get_period_summary(months_back=6, property_=None):
    results = []
    today   = date.today()
    for i in range(months_back - 1, -1, -1):
        m = today.month - i
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        rev_df   = get_monthly_revenue(m, y, property_=property_)
        revenue  = rev_df["amount"].sum() if not rev_df.empty else 0
        expenses = get_monthly_expenses_total(m, y, property_=property_)
        results.append({
            "month": m, "year": y,
            "label": date(y, m, 1).strftime("%b %Y"),
            "revenue":  float(revenue),
            "expenses": float(expenses),
            "profit":   float(revenue - expenses),
        })
    return results
def get_yearly_summary(year, property_=None):
    results = []
    for m in range(1, 13):
        rev_df   = get_monthly_revenue(m, year, property_=property_)
        revenue  = rev_df["amount"].sum() if not rev_df.empty else 0
        expenses = get_monthly_expenses_total(m, year, property_=property_)
        results.append({
            "month": m, "year": year,
            "label": date(year, m, 1).strftime("%b"),
            "revenue":  float(revenue),
            "expenses": float(expenses),
            "profit":   float(revenue - expenses),
        })
    return results