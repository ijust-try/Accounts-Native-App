"""
Small helper queries that don't exist in your original backend.py because
Streamlit's session_state used to keep track of "who is logged in" for us.
The mobile API has no session_state, so every request needs to look the
user's role/cid up fresh from the token's user_id.
"""
from backend import get_conn


def get_user_auth_record(user_id):
    """Returns {'user_id', 'email', 'role', 'cid'} or None if not found."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, email, role, cid FROM users WHERE user_id=%s",
        (user_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "email": row[1], "role": row[2], "cid": row[3]}


def set_user_role_and_cid(user_id, role, cid=None):
    """Used when creating a guest account, or promoting a user to staff."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET role=%s, cid=%s WHERE user_id=%s",
        (role, cid, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()