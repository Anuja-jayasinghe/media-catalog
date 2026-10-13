"""Clerk session verification at the API boundary."""

from __future__ import annotations

import os

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import HTTPException, Request


def require_clerk_user(request: Request) -> str:
    secret = os.getenv("CLERK_SECRET_KEY")
    jwt_key = os.getenv("CLERK_JWT_KEY")
    parties = [value.strip() for value in os.getenv("CLERK_AUTHORIZED_PARTIES", "").split(",") if value.strip()]
    if not secret or not parties:
        raise HTTPException(status_code=503, detail="Clerk authentication is not configured")
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=secret,
            jwt_key=jwt_key.replace("\\n", "\n") if jwt_key else None,
            authorized_parties=parties,
            accepts_token=["session_token"],
        ),
    )
    if not state.is_signed_in or not state.payload or not state.payload.get("sub"):
        raise HTTPException(status_code=401, detail="Sign in required")
    return str(state.payload["sub"])
