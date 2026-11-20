import json
import os
import subprocess
from functools import cache
from hashlib import sha256
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "microtube-ci-" + uuid4().hex[:8]
CLIP = """
import io, sys, av

buffer = io.BytesIO()
with av.open(buffer, "w", format=sys.argv[2]) as media:
    stream = media.add_stream(sys.argv[3], rate=12)
    stream.width = stream.height = 64
    stream.pix_fmt = "yuv420p"
    for _ in range(12 * int(sys.argv[1])):
        frame = av.VideoFrame(64, 64, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes([128]) * plane.buffer_size)
        media.mux(stream.encode(frame))
    media.mux(stream.encode())
sys.stdout.buffer.write(buffer.getvalue())
"""


def child_environment():
    keys = ("AI_UI_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY",
            "COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
    return {key: value for key, value in os.environ.items() if key not in keys}


def compose(*args, check=True, **kwargs):
    env = dict(child_environment(), POSTGRES_USER="ci", POSTGRES_PASSWORD="microtube-ci", AUTH_COOKIE_SECURE="false")
    return subprocess.run(
        ["docker", "compose", "--env-file", ".env.example", "-p", PROJECT,
         "-f", "compose.yaml", "-f", "tests/compose.test.yaml", *args],
        cwd=ROOT, env=env, check=check, **kwargs,
    )


@cache
def address(service):
    return "http://" + compose("port", f"frontend-{service}", "80", capture_output=True, text=True).stdout.strip()


@cache
def make_clip(seconds, format_name="mp4", codec="libx264"):
    return compose(
        "exec", "-T", "backend-upload", "python", "-c", CLIP, str(seconds), format_name, codec, capture_output=True,
    ).stdout


def client():
    return build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))


def request(opener, service, path, *, data=None, headers=None, status=200, method=None):
    base = address(service)
    req = Request(base + path, data=data, headers={"Origin": base, **(headers or {})}, method=method)
    try:
        response = opener.open(req, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        if response.status != status:
            raise AssertionError(f"{req.get_method()} {path}: expected {status}, got {response.status}")
        return response.read(), response.headers


def account_credentials(username=None, password="ci-password"):
    login = uuid4().bytes if username is None else username.encode()
    return {
        "login_hash": sha256(sha256(login).digest()).hexdigest(),
        "password_hash": sha256(sha256(password.encode()).digest()).hexdigest(),
    }


def account(username=None, password="ci-password"):
    opener = client()
    credentials = urlencode(account_credentials(username, password)).encode()
    request(opener, "auth", "/api/auth/register", data=credentials, status=201)
    return opener


def upload(opener, title, clip, *, tags="", key=None):
    boundary = uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\n{title}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="tags"\r\n\r\n{tags}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.mp4"\r\n'
        "Content-Type: video/mp4\r\n\r\n"
    ).encode() + clip + f"\r\n--{boundary}--\r\n".encode()
    response, _ = request(opener, "upload", "/api/upload/upload", data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}", "Idempotency-Key": key or uuid4().hex,
    })
    return json.loads(response)
