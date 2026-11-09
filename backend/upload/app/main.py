import os
import secrets
import shutil
from contextlib import closing
from typing import Annotated
import av
import psycopg2
from fastapi import Depends, FastAPI, Form, Header, HTTPException, UploadFile
from psycopg2.extras import Json
from microtube_auth import require_user
from microtube_media import encode_thumbnail, first_video_frame
from microtube_storage import find_video, save_thumbnail, save_video, thumbnail_path, video_path
from microtube_tags import get_tag_ids

app = FastAPI()

def validate_upload(file):
    try:
        with av.open(file.file, format="mp4") as container:
            brand = container.metadata.get("major_brand", "").strip()
            if not brand or brand.startswith(("qt", "3g", "M4A", "mjp2")):
                raise ValueError("Expected an MP4 video track")
            return first_video_frame(container)
    except (av.FFmpegError, ValueError) as error:
        raise HTTPException(415, "Expected an MP4 with a readable video track") from error
    finally:
        file.file.seek(0)

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


def previous_upload(cursor, owner_hash, key):
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


@app.post("/upload")
def run(
    file: UploadFile,
    owner_hash: str = Depends(require_user),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    thumbnail: UploadFile | None = None,
    idempotency_key: Annotated[str | None, Header(pattern=r"^[a-f0-9]{32}$")] = None,
):
    frame = validate_upload(file)
    jpeg = uploaded_thumbnail(thumbnail) if thumbnail and thumbnail.filename else encode_thumbnail(frame)
    del frame
    while True:
        id = secrets.token_urlsafe(6)
        PATH_TO_VIDEO = video_path(id)
        preview_path = thumbnail_path(id)
        if PATH_TO_VIDEO.exists() or find_video(id) is not None or preview_path.exists():
            continue
        try:
            size = save_video(id, file.file)
            break
        except FileExistsError:
            if not PATH_TO_VIDEO.exists():
                raise
            file.file.seek(0)

    tag_names = tags.split()
    metadata = {
        "id": id,
        "owner_hash": owner_hash,
        "filename": file.filename,
        "size": size,
        "title": title,
        "description": description,
    }
    if idempotency_key is not None:
        metadata["upload_key"] = idempotency_key

    published = False
    try:
        save_thumbnail(id, jpeg)
        with closing(psycopg2.connect(
            database="videos", user=os.getenv("POSTGRES_USER", "admin"),
            password=os.environ["POSTGRES_PASSWORD"], host="db-videos", port=5432,
            connect_timeout=5,
        )) as connection:
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

    return {
        "id": metadata["id"],
        "owner_hash": metadata["owner_hash"],
        "filename": metadata["filename"],
        "size": metadata["size"],
        "title": metadata["title"],
        "description": metadata["description"],
        "tags": tag_names,
        "tag_ids": metadata["tag_ids"],
        "stored": True,
    }
