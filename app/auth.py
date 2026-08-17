import os

import jwt
from fastapi import Header, HTTPException


def current_user(authorization: str | None = Header(default=None)) -> str:
    """Validate Supabase JWTs when configured; permit local development otherwise."""
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        return "local-dev"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        return str(payload.get("sub"))
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication token") from exc
