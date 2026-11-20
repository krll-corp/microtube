import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

import modal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import app

FUNCTIONS = (
    "frontend", "backend-auth", "backend-upload", "backend-video", "backend-text",
    "backend-indexing", "backend-ai-video", "backend-ai-text",
)


def check_modal():
    modal.App.lookup(app.name)
    for name in FUNCTIONS:
        function = modal.Function.from_name(app.name, name)
        minimum = function.autoscaler.settings().min_containers or 0
        if function.get_current_stats().num_total_runners < minimum:
            raise RuntimeError(f"{name} is still starting")
    for name in ("users", "videos"):
        connection = modal.Cls.from_name(app.name, "Database")(name=name).ready.remote()
        if not connection.get("host") or not connection.get("port"):
            raise RuntimeError(f"Database {name} is not ready")
    url = modal.Function.from_name(app.name, "frontend").get_web_url()
    if not url or not url.startswith("https://"):
        raise RuntimeError("Modal did not return a public HTTPS URL")
    return url.rstrip("/")


def get(url, content_type):
    request = Request(url, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=20) as response:
        if response.status != 200 or response.headers.get_content_type() != content_type:
            raise RuntimeError(f"Unexpected response from {url}")
        return response.read()


def check_http(url):
    for path in ("/", "/auth/", "/upload/", "/monitor/"):
        if b"microtube" not in get(url + path, "text/html").lower():
            raise RuntimeError(f"Unexpected HTML at {path}")
    get(url + "/shared/base.css", "text/css")
    script = get(url + "/app.js", "text/javascript")
    if sha256(script).digest() != sha256((ROOT / "frontend/main/app/app.js").read_bytes()).digest():
        raise RuntimeError("The frontend is serving a different app.js")
    catalog = json.loads(get(url + "/api/video/catalog?limit=1", "application/json"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        raise RuntimeError("The catalog returned an invalid response")
    for name in ("auth-api", "video-api", "text-api"):
        result = json.loads(get(url + "/checks/" + name, "application/json"))
        if result.get("status") != "ok":
            raise RuntimeError(f"{name} is not healthy")
    get(url + "/checks/upload-api", "text/html")


def wait_for(check, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return check()
        except Exception as error:
            if time.monotonic() >= deadline:
                raise
            print(f"Waiting for deployment: {error}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=240)
    arguments = parser.parse_args()
    url = wait_for(check_modal, arguments.timeout)
    print(f"Modal services are ready at {url}", flush=True)
    wait_for(lambda: check_http(url), arguments.timeout)
    print("HTTP deployment checks passed", flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write(f"Deployment checks passed. [Open MicroTube]({url}).\n")
