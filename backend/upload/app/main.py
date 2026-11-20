import json
import logging
import os
import secrets
import shutil
import time
from contextlib import ExitStack, closing, contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Annotated, Literal
import av
import psycopg2
from fastapi import BackgroundTasks, Depends, FastAPI, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from psycopg2.extras import Json
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from microtube_auth import require_user
from microtube_media import encode_thumbnail, first_video_frame, video_duration_seconds, video_stream
from microtube_storage import VIDEO_STORAGE_DIR, find_video, save_thumbnail, save_video, thumbnail_path, video_path
from microtube_tags import get_tag_ids
from microtube_services import commit_media, database_options, reload_media
from playback import prepare_playback
from transcode import inspect_upload, transcode_video

app = FastAPI()
MAX_PART_BYTES = 8 * 1024 * 1024
UPLOAD_IDLE_TTL = 24 * 60 * 60
UploadKey = Annotated[str, Header(pattern=r"^[a-f0-9]{32}$")]

def remux_mp4(container, target):
    video = video_stream(container)
    if video is None:
        raise ValueError("Missing video track")
    streams = [video, *container.streams.audio]
    with av.open(target, mode="w", format="mp4") as output:
        mapping = {}
        for stream in streams:
            destination = output.add_stream_from_template(stream)
            if stream.codec_context.codec_tag == "hvc1":
                destination.codec_context.codec_tag = "hvc1"
            mapping[stream.index] = destination
        for packet in container.demux(streams):
            if packet.size:
                packet.stream = mapping[packet.stream.index]
                output.mux(packet)


@contextmanager
def prepare_upload(file, mode):
    with ExitStack() as files:
        source = file.file
        try:
            if mode == "remux":
                source = files.enter_context(TemporaryFile())
                with av.open(file.file, mode="r") as container:
                    remux_mp4(container, source)
                source.seek(0)
            with av.open(source, mode="r", format="mp4") as container:
                frame, duration = first_video_frame(container), video_duration_seconds(container)
        except (av.FFmpegError, ValueError) as error:
            raise HTTPException(415, "Expected a supported file with a readable video track") from error
        finally:
            file.file.seek(0)
        source.seek(0)
        yield source, frame, duration

def uploaded_thumbnail(file):
    source = file.file
    header = source.read(12)
    source.seek(0)
    try:
        if header.startswith(b"\xff\xd8"):
            codec = "mjpeg"
        elif header.startswith(b"\x89PNG\r\n\x1a\n"):
            codec = "png"
        elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            codec = "webp"
        else:
            raise ValueError("Unknown image format")
        decoder = av.CodecContext.create(codec, "r")
        decoder.options = {"max_pixels": "16000000"}
        while True:
            chunk = source.read(64 * 1024)
            for packet in decoder.parse(chunk):
                frames = decoder.decode(packet)
                if frames:
                    return encode_thumbnail(frames[0])
            if not chunk:
                break
        frames = decoder.decode()
        if not frames:
            raise ValueError("Missing thumbnail frame")
        return encode_thumbnail(frames[0])
    except (av.FFmpegError, ValueError) as error:
        raise HTTPException(415, "Expected a JPEG, PNG or WebP thumbnail up to 16 megapixels") from error


def connect():
    return psycopg2.connect(
        database="videos", user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"], **database_options("videos"),
        connect_timeout=5,
    )


def previous_upload(cursor, owner_hash, key, *, lock=True):
    if lock:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                       ("microtube:upload:" + owner_hash + ":" + key,))
    cursor.execute(
        "SELECT metadata FROM videos WHERE metadata->>'owner_hash' = %s AND metadata->>'upload_key' = %s",
        (owner_hash, key),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    metadata = row[0]
    cursor.execute("SELECT tag_id, tag FROM tags WHERE tag_id = ANY(%s)", (metadata["tag_ids"],))
    names = dict(cursor.fetchall())
    return metadata, [names[id] for id in metadata["tag_ids"] if id in names]


@contextmanager
def staged_upload(owner_hash, key):
    owner = sha256(owner_hash.encode()).hexdigest()
    directory = VIDEO_STORAGE_DIR / ".uploads" / owner / key
    with closing(connect()) as connection, connection, connection.cursor() as cursor:
        # Serialize writes and cleanup for this owner across container restarts.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                       ("microtube:upload-parts:" + owner,))
        reload_media()
        yield directory, cursor


def store_part(owner_hash, key, kind, offset, body):
    with staged_upload(owner_hash, key) as (directory, _):
        path = directory / kind
        stored = path.stat().st_size if path.exists() else 0
        if offset != stored or (directory / "job.json").exists():
            return {"offset": stored}
        if not directory.exists():
            directory.mkdir(parents=True)
            deadline = time.time() - UPLOAD_IDLE_TTL
            for attempt in directory.parent.iterdir():
                if attempt != directory and attempt.is_dir() and attempt.stat().st_mtime < deadline:
                    shutil.rmtree(attempt)
        with path.open("ab") as output:
            output.write(body)
        os.utime(directory, None)
        commit_media()
        return {"offset": stored + len(body)}


@app.post("/part")
async def upload_part(
    request: Request,
    idempotency_key: UploadKey,
    offset: Annotated[int, Query(ge=0)],
    kind: Literal["video", "thumbnail"],
    owner_hash: str = Depends(require_user),
):
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_PART_BYTES:
                raise HTTPException(413, "Upload part exceeds 8 MiB")
            body.extend(chunk)
    except ClientDisconnect as error:
        raise HTTPException(408, "Upload part was interrupted") from error
    if not body:
        raise HTTPException(400, "Upload part is empty")
    return await run_in_threadpool(store_part, owner_hash, idempotency_key, kind, offset, body)


def queue_playback(background, result):
    submit = getattr(app.state, "submit_playback", None)
    if submit is None:
        background.add_task(prepare_playback, result["id"])
    else:
        try:
            submit(result["id"])
        except Exception:
            logging.exception("Could not queue playback for %s", result["id"])
    return result


@app.post("/upload")
def run(
    background: BackgroundTasks,
    file: UploadFile | None = None,
    owner_hash: str = Depends(require_user),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    thumbnail: UploadFile | None = None,
    idempotency_key: Annotated[str | None, Header(pattern=r"^[a-f0-9]{32}$")] = None,
    filename: str = Form(""),
    size: int | None = Form(None, gt=0),
    thumbnail_size: int = Form(0, ge=0),
):
    if file is not None:
        media = inspect_upload(file.file)
        if media["mode"] != "transcode":
            result = store_upload(file, thumbnail, owner_hash, title, description, tags, idempotency_key,
                                  mode=media["mode"])
            return queue_playback(background, result)
        filename = file.filename or "video"
        idempotency_key = idempotency_key or secrets.token_hex(16)
    elif not idempotency_key or not filename or size is None:
        raise HTTPException(422, "A file or completed upload parts are required")

    submit = getattr(app.state, "submit_upload", None)
    with staged_upload(owner_hash, idempotency_key) as (directory, cursor):
        previous = previous_upload(cursor, owner_hash, idempotency_key, lock=False)
        if previous is not None:
            if not (directory / "job.json").exists():
                clear_job(directory)
            return queue_playback(background, upload_response(*previous))
        job = read_job(directory)
        if job is None:
            video = directory / "video"
            image = directory / "thumbnail"
            if file is None:
                if not video.is_file() or video.stat().st_size != size:
                    raise HTTPException(409, "Video parts are incomplete. Retry the upload.")
                if thumbnail_size and (not image.is_file() or image.stat().st_size != thumbnail_size):
                    raise HTTPException(409, "Thumbnail parts are incomplete. Retry the upload.")
                has_thumbnail = bool(thumbnail_size)
                with video.open("rb") as source:
                    media = inspect_upload(source)
            else:
                directory.mkdir(parents=True, exist_ok=True)
                with video.open("wb") as output:
                    shutil.copyfileobj(file.file, output)
                has_thumbnail = bool(thumbnail and thumbnail.filename)
                if has_thumbnail:
                    with image.open("wb") as output:
                        shutil.copyfileobj(thumbnail.file, output)
            job = dict(**media, filename=filename, title=title, description=description, tags=tags,
                       has_thumbnail=has_thumbnail, progress=0 if media["duration"] else None)
            if job["mode"] == "direct":
                result = publish_job(directory, owner_hash, idempotency_key, job)
                clear_job(directory)
                return queue_playback(background, result)
        elif "error" in job:
            del job["error"]
            job["progress"] = 0 if job["duration"] else None
        elif not submit or job.get("call_id"):
            if not submit:
                background.add_task(process_upload, owner_hash, idempotency_key)
            return pending_upload(job, idempotency_key)
        if submit:
            job["call_id"] = submit(owner_hash, idempotency_key).object_id
        write_job(directory, job)
    if not submit:
        background.add_task(process_upload, owner_hash, idempotency_key)
    return pending_upload(job, idempotency_key)


def read_job(directory):
    try:
        return json.loads((directory / "job.json").read_text())
    except FileNotFoundError:
        return None


def write_job(directory, job):
    path = directory / "job.tmp"
    path.write_text(json.dumps(job))
    path.replace(directory / "job.json")
    commit_media()


def clear_job(directory):
    if directory.exists():
        shutil.rmtree(directory)
        commit_media()


def pending_upload(job, key):
    result = {"processing": True, "idempotency_key": key}
    if job["mode"] == "transcode":
        result["progress"] = job["progress"]
    return JSONResponse(result, status_code=202, headers={"Cache-Control": "no-store"})


def try_job_lock(cursor, owner_hash, key):
    cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                   ("microtube:upload-job:" + owner_hash + ":" + key,))
    return cursor.fetchone()[0]


@app.get("/status")
def upload_status(background: BackgroundTasks, idempotency_key: UploadKey, owner_hash: str = Depends(require_user)):
    with staged_upload(owner_hash, idempotency_key) as (directory, cursor):
        previous = previous_upload(cursor, owner_hash, idempotency_key, lock=False)
        if previous is not None:
            return JSONResponse(upload_response(*previous), headers={"Cache-Control": "no-store"})
        job = read_job(directory)
        if job is None:
            raise HTTPException(404, "Upload not found")
        if "error" in job:
            raise HTTPException(*job["error"])
        call_id = job.get("call_id")
        if call_id and time.time() - (directory / "job.json").stat().st_mtime > 60:
            if app.state.upload_failed(call_id):
                job["error"] = [500, "Video processing stopped. Click Upload video to retry."]
                write_job(directory, job)
                raise HTTPException(*job["error"])
        if not getattr(app.state, "submit_upload", None) and try_job_lock(cursor, owner_hash, idempotency_key):
            background.add_task(process_upload, owner_hash, idempotency_key)
        return pending_upload(job, idempotency_key)


def publish_job(directory, owner_hash, key, job, processed=None):
    with ExitStack() as files:
        video = UploadFile(files.enter_context((processed or directory / "video").open("rb")), filename=job["filename"])
        thumbnail = None
        if job["has_thumbnail"]:
            thumbnail = UploadFile(files.enter_context((directory / "thumbnail").open("rb")), filename="thumbnail")
        return store_upload(video, thumbnail, owner_hash, job["title"], job["description"], job["tags"], key,
                            mode="direct" if processed else job["mode"])


def process_upload(owner_hash, key, after_publish=None):
    with ExitStack() as locks:
        # Modal already runs one worker and its database can sleep while encoding.
        if after_publish is None:
            connection = locks.enter_context(closing(connect()))
            locks.enter_context(connection)
            if not try_job_lock(locks.enter_context(connection.cursor()), owner_hash, key):
                return
        with staged_upload(owner_hash, key) as (directory, cursor):
            previous = previous_upload(cursor, owner_hash, key, lock=False)
            job = read_job(directory)
        result = upload_response(*previous) if previous else None
        if previous is None:
            if job is None or "error" in job:
                return

            def update(percent):
                job["progress"] = percent
                write_job(directory, job)

            try:
                if job["mode"] == "transcode":
                    update(0 if job["duration"] else None)
                    with TemporaryDirectory() as work:
                        output = Path(work) / "transcoded.mp4"
                        transcode_video(directory / "video", output, job, update)
                        result = publish_job(directory, owner_hash, key, job, output)
                else:
                    result = publish_job(directory, owner_hash, key, job)
            except HTTPException as error:
                job["error"] = [error.status_code, error.detail]
                write_job(directory, job)
                return
            except Exception:
                logging.exception("Upload processing failed")
                job["error"] = [500, "Video processing failed. Click Upload video to retry."]
                write_job(directory, job)
                return
        if after_publish:
            after_publish()
        with staged_upload(owner_hash, key):
            clear_job(directory)

    if after_publish:
        return result["id"]
    prepare_playback(result["id"])


def store_upload(file, thumbnail, owner_hash, title, description, tags, idempotency_key, *, mode):
    with prepare_upload(file, mode) as (source, frame, duration_seconds):
        jpeg = uploaded_thumbnail(thumbnail) if thumbnail and thumbnail.filename else encode_thumbnail(frame)
        del frame
        while True:
            id = secrets.token_urlsafe(6)
            PATH_TO_VIDEO = video_path(id)
            preview_path = thumbnail_path(id)
            if PATH_TO_VIDEO.exists() or find_video(id) is not None or preview_path.exists():
                continue
            try:
                size = save_video(id, source)
                break
            except FileExistsError:
                if not PATH_TO_VIDEO.exists():
                    raise
                source.seek(0)

    tag_names = tags.split()
    metadata = {
        "id": id,
        "owner_hash": owner_hash,
        "filename": file.filename,
        "size": size,
        "title": title,
        "description": description,
        "duration_seconds": duration_seconds,
    }
    if idempotency_key is not None:
        metadata["upload_key"] = idempotency_key

    published = False
    try:
        save_thumbnail(id, jpeg)
        commit_media()
        with closing(connect()) as connection:
            with connection:
                with connection.cursor() as cursor:
                    previous = previous_upload(cursor, owner_hash, idempotency_key) if idempotency_key else None
                    if previous is None:
                        metadata["tag_ids"] = get_tag_ids(cursor, tag_names)
                        cursor.execute(
                            "INSERT INTO videos (hash, metadata, indexed, processing_now) VALUES (%s, %s, %s, %s)",
                            (id, Json(metadata), False, False),
                        )
                    else:
                        metadata, tag_names = previous
            published = previous is None
    finally:
        if not published:
            shutil.rmtree(PATH_TO_VIDEO)
            preview_path.unlink(missing_ok=True)

    return upload_response(metadata, tag_names)


def upload_response(metadata, tag_names):
    return {
        "id": metadata["id"],
        "owner_hash": metadata["owner_hash"],
        "filename": metadata["filename"],
        "size": metadata["size"],
        "title": metadata["title"],
        "description": metadata["description"],
        "duration_seconds": metadata.get("duration_seconds"),
        "tags": tag_names,
        "tag_ids": metadata["tag_ids"],
        "stored": True,
    }
