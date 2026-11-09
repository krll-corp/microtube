import os
import secrets
import shutil
from contextlib import closing
import av
import psycopg2
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from psycopg2.extras import Json
from microtube_auth import require_user
from microtube_media import encode_thumbnail, first_video_frame
from microtube_storage import find_video, save_thumbnail, save_video, thumbnail_path, video_path
from microtube_tags import get_tag_ids

app = FastAPI()

def validate_upload(file):
    if file.size is not None and file.size > 2 * 1024 ** 3:
        raise HTTPException(413, "Video exceeds 2 GiB")
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
    limit = 5 * 1024 ** 2
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "Thumbnail exceeds 5 MiB")
    try:
        if data.startswith(b"\xff\xd8"):
            codec = "mjpeg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            codec = "png"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            codec = "webp"
        else:
            raise ValueError("Unknown image format")
        decoder = av.CodecContext.create(codec, "r")
        decoder.options = {"max_pixels": "16000000"}
        frames = decoder.decode(av.Packet(data))
        if not frames:
            raise ValueError("Missing thumbnail frame")
        return encode_thumbnail(frames[0])
    except (av.FFmpegError, ValueError) as error:
        raise HTTPException(415, "Expected a JPEG, PNG or WebP thumbnail up to 16 megapixels") from error

@app.post("/upload")
def run(
    file: UploadFile,
    owner_hash: str = Depends(require_user),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    thumbnail: UploadFile | None = None,
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

    try:
        save_thumbnail(id, jpeg)
        with closing(psycopg2.connect(
            database="videos", user=os.getenv("POSTGRES_USER", "admin"),
            password=os.environ["POSTGRES_PASSWORD"], host="db-videos", port=5432,
            connect_timeout=5,
        )) as connection:
            with connection:
                with connection.cursor() as cursor:
                    metadata["tag_ids"] = get_tag_ids(cursor, tag_names)
                    cursor.execute(
                        "INSERT INTO videos (hash, metadata, indexed, processing_now) VALUES (%s, %s, %s, %s)",
                        (id, Json(metadata), False, False),
                    )
    except Exception:
        shutil.rmtree(PATH_TO_VIDEO)
        preview_path.unlink(missing_ok=True)
        raise

    return {
        "id": id,
        "owner_hash": owner_hash,
        "filename": file.filename,
        "size": size,
        "title": title,
        "description": description,
        "tags": tag_names,
        "tag_ids": metadata["tag_ids"],
        "stored": True,
    }
