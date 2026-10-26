import os
import secrets
import time
from contextlib import closing
from threading import Lock, Thread

import psycopg2
import uvicorn
from fastapi import Depends, FastAPI, Form, HTTPException, Response
from pydantic import BaseModel, Field
from microtube_auth import COOKIE_NAME, bearer, check_origin, user_token

TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "3600"))
if TOKEN_TTL <= 0:
    raise ValueError("AUTH_TOKEN_TTL_SECONDS must be positive")
tokens = {}
token_lock = Lock()
app = FastAPI(dependencies=[Depends(check_origin)])
internal = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Credentials(BaseModel):
    login_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    password_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def connect():
    return psycopg2.connect(
        database="users", host="db-users",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"], connect_timeout=5,
    )


def session_user(token):
    if token is None:
        return None
    with token_lock:
        session = tokens.get(token)
        if session is not None and session["expires_at"] > time.monotonic():
            return session["login_hash"]
        tokens.pop(token, None)
    return None


def start_session(login_hash, response):
    token, now = secrets.token_urlsafe(32), time.monotonic()
    with token_lock:
        for key in list(tokens):
            if tokens[key]["expires_at"] <= now:
                del tokens[key]
        tokens[token] = {"login_hash": login_hash, "expires_at": now + TOKEN_TTL}
    response.set_cookie(
        COOKIE_NAME, token, max_age=TOKEN_TTL, httponly=True, samesite="strict",
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "expires_in": TOKEN_TTL}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", status_code=201)
def register(response: Response, data: Credentials = Form()):
    try:
        with closing(connect()) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO users (login_hash, password_hash) VALUES (%s, %s)",
                        (data.login_hash, data.password_hash),
                    )
    except psycopg2.errors.UniqueViolation as error:
        raise HTTPException(409, "Username already exists") from error
    return start_session(data.login_hash, response)


@app.post("/auth/login")
def login(response: Response, data: Credentials = Form()):
    with closing(connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE login_hash = %s", (data.login_hash,))
            row = cursor.fetchone()
    valid = secrets.compare_digest(row[0] if row else "0" * 64, data.password_hash)
    if row is None or not valid:
        raise HTTPException(401, "not logged in", headers={"WWW-Authenticate": "Bearer"})

    return start_session(data.login_hash, response)


@app.get("/auth/me")
def me(token=Depends(user_token)):
    login_hash = session_user(token)
    if login_hash is None:
        raise HTTPException(401, "not logged in", headers={"WWW-Authenticate": "Bearer"})
    return {"login_hash": login_hash}


@app.post("/auth/logout")
def logout(response: Response, token=Depends(user_token)):
    if token is not None:
        with token_lock:
            tokens.pop(token, None)
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict")
    return {"logged_in": False}


@internal.get("/check")
def check(token=Depends(bearer)):
    return session_user(token.credentials if token else None) is not None


if __name__ == "__main__":
    # Both listeners share the same token dictionary in one process.
    Thread(target=uvicorn.run, args=(internal,), kwargs={"host": "0.0.0.0", "port": 3034}, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=3033)
