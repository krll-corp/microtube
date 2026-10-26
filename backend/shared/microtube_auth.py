import json
from urllib.parse import urlsplit
from urllib.request import Request as URLRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer

bearer = HTTPBearer(auto_error=False)
COOKIE_NAME = "microtube_token"


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        source = urlsplit(origin)
        if (source.scheme, source.hostname) != (request.url.scheme, request.url.hostname):
            raise HTTPException(403, "Cross-site request rejected")


def user_token(request: Request, authorization=Depends(bearer)):
    if authorization is not None:
        return authorization.credentials
    token = request.cookies.get(COOKIE_NAME)
    if token and request.method not in ("GET", "HEAD", "OPTIONS"):
        if not request.headers.get("origin"):
            raise HTTPException(403, "Origin required for cookie authentication")
        check_origin(request)
    return token


def require_user(token=Depends(user_token)):
    if token is None:
        raise HTTPException(401, "not logged in", headers={"WWW-Authenticate": "Bearer"})
    request = URLRequest(
        "http://backend-auth:3034/check",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=3) as response:
            logged_in = json.load(response)
    except (OSError, ValueError) as error:
        raise HTTPException(503, "Authentication service unavailable") from error
    if logged_in is not True:
        raise HTTPException(401, "not logged in", headers={"WWW-Authenticate": "Bearer"})
    return True
