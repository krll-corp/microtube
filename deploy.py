import asyncio
import importlib.util
import json
import logging
import os
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
import secrets
import subprocess
import sys

import modal

ROOT = Path(__file__).resolve().parent if modal.is_local() else Path("/app")
app = modal.App("microtube")
credentials = modal.Secret.from_name("microtube", required_keys=["POSTGRES_PASSWORD", "MICROTUBE_SERVICE_TOKEN"])
media = modal.Volume.from_name("microtube-videos", create_if_missing=True, version=2)
postgres = modal.Volume.from_name("microtube-postgres", create_if_missing=True, version=2)
models = modal.Volume.from_name("microtube-models", create_if_missing=True, version=2)
runtime = (
    modal.Image.debian_slim(python_version="3.13")
    .pip_install("fastapi", "uvicorn", "python-multipart", "psycopg2-binary", "requests", "httpx", "av")
    .env({"PYTHONPATH": "/app/backend/shared", "POSTGRES_USER": "admin", "AUTH_COOKIE_SECURE": "true",
          "MICROTUBE_MODAL_APP": app.name, "VIDEO_STORAGE_DIR": "/videos"})
)
image = (
    runtime.add_local_dir(ROOT / "backend", "/app/backend", copy=True)
    .add_local_dir(ROOT / "frontend", "/app/frontend", copy=True)
    .add_local_dir(ROOT / "assets", "/app/assets", copy=True)
)

def cache_model():
    from huggingface_hub import snapshot_download
    snapshot_download("google/embeddinggemma-2")
    models.commit()


gpu_image = (
    runtime.pip_install("torch", "torchvision", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install("transformers", "accelerate", "pillow")
    .run_function(cache_model, volumes={"/root/.cache/huggingface": models})
    .env({"HF_HUB_OFFLINE": "1"})
    .add_local_dir(ROOT / "backend", "/app/backend", copy=True)
)
pg_image = modal.Image.from_registry("pgvector/pgvector:pg16", add_python="3.13").entrypoint([]).add_local_dir(
    ROOT / "db", "/app/db", copy=True,
)
cpu = dict(image=image, secrets=[credentials], cpu=0.125, memory=256,
           min_containers=0, max_containers=4, scaledown_window=600, timeout=3600)
gpu = dict(image=gpu_image, secrets=[credentials], gpu=os.getenv("MICROTUBE_GPU", "T4"),
           cpu=0.25, memory=4096, min_containers=0, max_containers=2, timeout=600, startup_timeout=1200,
           scaledown_window=60, volumes={"/videos": media.with_mount_options(read_only=True),
                                        "/root/.cache/huggingface": models.with_mount_options(read_only=True)})


@app.cls(image=pg_image, secrets=[credentials], volumes={"/data": postgres},
         cpu=0.125, memory=256, max_containers=1, scaledown_window=60)
class Database:
    name: str = modal.parameter()

    @modal.enter()
    def start(self):
        if self.name not in ("videos", "users"):
            raise ValueError("Unknown database")
        self.directory = Path("/data") / self.name
        self.directory.mkdir(exist_ok=True)
        subprocess.run(["chown", "postgres:postgres", str(self.directory)], check=True)
        self.pg = ["runuser", "-u", "postgres", "--"]
        if not (self.directory / "PG_VERSION").exists():
            password = Path("/tmp/postgres-password")
            password.write_text(os.environ["POSTGRES_PASSWORD"])
            password.chmod(0o600)
            subprocess.run(["chown", "postgres:postgres", str(password)], check=True)
            try:
                subprocess.run([*self.pg, "initdb", "-D", str(self.directory), "-U", "admin",
                                "--auth-local=trust", "--auth-host=scram-sha-256", f"--pwfile={password}"], check=True)
            finally:
                password.unlink(missing_ok=True)
        self.forwarding = modal.forward(5432, unencrypted=True)
        tunnel = self.forwarding.__enter__()
        self.host, self.port = tunnel.tcp_socket
        key, certificate = "/tmp/server.key", "/tmp/server.crt"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key,
                        "-out", certificate, "-days", "365", "-subj", "/CN=" + self.host],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["chown", "postgres:postgres", key, certificate], check=True)
        Path(key).chmod(0o600)
        (self.directory / "pg_hba.conf").write_text(
            "local all all trust\nhostssl all all all scram-sha-256\nhostnossl all all all reject\n"
        )
        subprocess.run([*self.pg, "pg_ctl", "-D", str(self.directory), "-l", "/tmp/postgres.log", "-w", "start",
                        "-o", f"-c listen_addresses='*' -c shared_buffers=32MB -c max_connections=40 "
                              f"-c ssl=on -c ssl_cert_file={certificate} -c ssl_key_file={key}"], check=True)
        exists = subprocess.run([*self.pg, "psql", "-U", "admin", "-At", "-v", f"name={self.name}",
                                 "-v", "ON_ERROR_STOP=1", "postgres"],
                                input="SELECT 1 FROM pg_database WHERE datname = :'name';",
                                check=True, capture_output=True, text=True).stdout.strip()
        if not exists:
            subprocess.run([*self.pg, "createdb", "-U", "admin", self.name], check=True)
        for schema in sorted((Path("/app/db") / self.name).glob("*.sql")):
            subprocess.run([*self.pg, "psql", "-U", "admin", "-d", self.name,
                            "-v", "ON_ERROR_STOP=1", "-f", str(schema)], check=True)
        postgres.commit()
        modal.Cls.from_name(app.name, "Database")(name=self.name).ready.autoscaler.update(min_containers=0)

    @modal.method()
    def ready(self):
        return {"host": self.host, "port": self.port, "certificate": Path("/tmp/server.crt").read_text()}

    @modal.method()
    def flush(self):
        postgres.commit()

    @modal.exit()
    def stop(self):
        subprocess.run([*self.pg, "pg_ctl", "-D", str(self.directory), "-m", "fast", "-w", "stop"], check=True)
        postgres.commit()
        self.forwarding.__exit__(None, None, None)


def load_service(name):
    directory = Path("/app/backend") / name / "app"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location("microtube_backend_" + name.replace("/", "_"), directory / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def upload_failed(call_id):
    try:
        modal.FunctionCall.from_id(call_id).get(timeout=0)
    except (modal.exception.FunctionTimeoutError, modal.exception.OutputExpiredError):
        return True
    except (modal.exception.TimeoutError, modal.exception.ConnectionError, modal.exception.ServiceError):
        return False
    except Exception:
        logging.exception("Upload processing failed on Modal")
        return True
    return False


def serve(name):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    module = load_service(name)
    if name in ("auth", "video"):
        Database(name="users" if name == "auth" else "videos").ready.remote()
    if name == "auth":
        module.app.mount("/", module.internal)
    if name == "upload":
        module.app.state.submit_upload = backend_upload_process.spawn
        module.app.state.upload_failed = upload_failed

    @module.app.middleware("http")
    async def internal_request(request: Request, call_next):
        if not secrets.compare_digest(request.headers.get("X-Microtube-Service", ""), os.environ["MICROTUBE_SERVICE_TOKEN"]):
            return JSONResponse({"detail": "Internal service"}, status_code=403)
        request.scope["scheme"] = "https"
        host = request.headers.get("X-Microtube-Host")
        if host:
            request.scope["headers"] = [(key, value) for key, value in request.scope["headers"] if key != b"host"]
            request.scope["headers"].append((b"host", host.encode("ascii")))
        if name in ("video", "ai/video") or (name == "upload" and request.url.path == "/upload"):
            await media.reload.aio()
        response = await call_next(request)
        if name == "video":
            await media.commit.aio()
        if response.status_code < 400 and (request.method == "POST" or request.url.path == "/feed"):
            if name == "upload" and (request.url.path != "/upload" or response.status_code != 200):
                return response
            database = "users" if name == "auth" else "videos"
            await Database(name=database).flush.remote.aio()
            if name == "upload":
                await backend_indexing.spawn.aio()
        return response

    return module.app


@app.function(**{**cpu, "max_containers": 1, "memory": 128}, name="backend-auth")
@modal.asgi_app()
def backend_auth():
    return serve("auth")


@app.function(**cpu, name="backend-video", volumes={"/videos": media})
@modal.asgi_app()
def backend_video():
    return serve("video")


@app.function(**{**cpu, "max_containers": 1, "memory": 512}, name="backend-upload", volumes={"/videos": media})
@modal.asgi_app()
def backend_upload():
    return serve("upload")


@app.function(**{**cpu, "image": image.apt_install("ffmpeg"), "cpu": 2, "memory": 4096,
                 "max_containers": 1, "timeout": 86400, "scaledown_window": 60},
              name="backend-upload-process", volumes={"/videos": media}, retries=3)
def backend_upload_process(owner_hash, key):
    def published():
        Database(name="videos").flush.remote()
        backend_indexing.spawn()

    load_service("upload").process_upload(owner_hash, key, after_publish=published)


@app.function(**cpu, name="backend-text")
@modal.asgi_app()
def backend_text():
    return serve("text")


@app.function(**gpu, name="backend-ai-video")
@modal.asgi_app()
def backend_ai_video():
    return serve("ai/video")


@app.function(**gpu, name="backend-ai-text")
@modal.asgi_app()
def backend_ai_text():
    return serve("ai/text")


@app.function(**{**cpu, "max_containers": 1}, name="backend-indexing",
              retries=modal.Retries(max_retries=3, initial_delay=10))
def backend_indexing():
    worker = load_service("indexing")
    failed = False
    try:
        for video in worker.watcher():
            try:
                worker.run(video)
            except Exception:
                logging.exception("Indexing failed for %s", video["hash"])
                failed = True
    finally:
        Database(name="videos").flush.remote()
    if failed:
        raise RuntimeError("Some videos could not be indexed")


@app.function(**cpu, name="frontend")
@modal.asgi_app()
def frontend():
    import httpx
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.background import BackgroundTask
    from microtube_services import service_headers, service_url

    web = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    # Forward cookies from the current browser request only.
    client = httpx.AsyncClient(timeout=1200, follow_redirects=True,
                               cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=())))
    routes = {"8080": "/", "8081": "/monitor/", "8082": "/upload/", "8083": "/auth/"}
    headers_to_skip = {b"connection", b"transfer-encoding", b"keep-alive", b"upgrade"}

    async def upstream(request, service, path):
        target = await asyncio.to_thread(service_url, service, "") + path
        headers = {key: value for key, value in request.headers.items() if not key.lower().startswith("modal-")}
        headers.update(service_headers())
        headers.pop("connection", None)
        headers["X-Microtube-Host"] = headers.pop("host")
        try:
            return await client.send(client.build_request(
                request.method, target, params=request.query_params,
                headers=headers, content=None if request.method in ("GET", "HEAD") else request.stream(),
            ), stream=True)
        except httpx.HTTPError as error:
            raise HTTPException(502, "Service unavailable") from error

    async def proxy(request, service, path):
        response = await upstream(request, service, path)
        result = StreamingResponse(response.aiter_raw(), status_code=response.status_code,
                                   background=BackgroundTask(response.aclose))
        result.raw_headers = [(key, value) for key, value in response.headers.raw
                              if key.lower() not in headers_to_skip and not key.lower().startswith(b"modal-")]
        return result

    @web.api_route("/api/{service}/{path:path}", methods=["GET", "HEAD", "POST"])
    async def api(request: Request, service: str, path: str):
        if service not in ("auth", "upload", "video"):
            raise HTTPException(404)
        if service == "auth" and path not in ("register", "login", "logout", "me"):
            raise HTTPException(404)
        return await proxy(request, "backend-" + service, ("/auth/" if service == "auth" else "/") + path)

    @web.get("/api/search")
    async def search(request: Request):
        return await proxy(request, "backend-text", "/search")

    @web.get("/checks/{name}")
    async def check(request: Request, name: str):
        if name in ("main", "auth-ui", "upload-ui", "monitor"):
            return {"status": "ok"}
        checks = {"auth-api": ("backend-auth", "/health"), "video-api": ("backend-video", "/videos"),
                  "upload-api": ("backend-upload", "/docs"), "text-api": ("backend-text", "/health")}
        if name in ("ai-video", "ai-text"):
            await asyncio.to_thread(service_url, "backend-" + name, "")
            return {"status": "deployed"}
        if name not in checks:
            raise HTTPException(404)
        return await proxy(request, *checks[name])

    web.mount("/shared", StaticFiles(directory="/app/frontend/shared"))
    web.mount("/assets", StaticFiles(directory="/app/assets"))

    @web.get("/app.js")
    def script():
        return FileResponse("/app/frontend/main/app/app.js", media_type="text/javascript")

    @web.get("/")
    @web.get("/{page}/")
    async def page(request: Request, page: str = "main"):
        if page not in ("main", "auth", "upload", "monitor"):
            raise HTTPException(404)
        headers = {"Cache-Control": "no-cache"}
        if page == "upload":
            session = await upstream(request, "backend-auth", "/auth/me")
            await session.aclose()
            headers["Cache-Control"] = "private, no-store"
            if session.status_code == 401:
                return RedirectResponse(routes["8083"], status_code=302, headers=headers)
            if session.status_code != 200:
                raise HTTPException(503, "Authentication service unavailable")
        html = (Path("/app/frontend") / page / "app/index.html").read_text()
        config = "<script>window.MICROTUBE_URLS=" + json.dumps(routes) + ";</script>"
        return HTMLResponse(html.replace("<head>", "<head>" + config, 1), headers=headers)

    return web


if __name__ == "__main__":
    try:
        credentials.hydrate()
    except modal.exception.NotFoundError:
        modal.Secret.objects.create("microtube", {"POSTGRES_PASSWORD": secrets.token_urlsafe(32),
                                                  "MICROTUBE_SERVICE_TOKEN": secrets.token_urlsafe(32)})
    subprocess.run([sys.executable, "-m", "modal", "deploy", "--strategy", "rolling",
                    str(Path(__file__).resolve())], check=True)
    modal.Function.from_name(app.name, "backend-indexing").spawn()
    print(modal.Function.from_name(app.name, "frontend").get_web_url())
