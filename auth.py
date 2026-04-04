"""Password hashing and Flask login decorator."""

from functools import wraps

import bcrypt
from flask import g, jsonify, session


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        uid = session.get("user_id")
        if uid is None:
            return jsonify({"error": "Not authenticated"}), 401
        g.user_id = uid
        return f(*args, **kwargs)

    return decorated
