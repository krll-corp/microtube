import os
import secrets
import shutil
from contextlib import closing
import av
import psycopg2
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from psycopg2.extras import Json
from microtube_auth import require_user
from microtube_storage import find_video, save_video, video_path
from microtube_tags import get_tag_ids

app = FastAPI()

def validate_upload(file):
    if file.size is not None and file.size > 2 * 1024 ** 3:
        raise HTTPException(413, "Video exceeds 2 GiB")
    try:
        with av.open(file.file, format="mp4") as container:
            brand = container.metadata.get("major_brand", "").strip()
            stream = next((stream for stream in container.streams.video
                           if not stream.disposition & av.stream.Disposition.attached_pic), None)
            if not brand or brand.startswith(("qt", "3g", "M4A", "mjp2")) or stream is None:
                raise ValueError("Expected an MP4 video track")
            if next(container.decode(stream), None) is None:
                raise ValueError("Missing video frames")
    except (av.FFmpegError, ValueError) as error:
        raise HTTPException(415, "Expected an MP4 with a readable video track") from error
    finally:
        file.file.seek(0)

@app.post("/upload")
def run(
    file: UploadFile,
    owner_hash: str = Depends(require_user),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    validate_upload(file)
    while True:
        id = secrets.token_urlsafe(6)
        PATH_TO_VIDEO = video_path(id)
        if PATH_TO_VIDEO.exists() or find_video(id) is not None:
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
