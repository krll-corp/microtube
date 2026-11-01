import os
import secrets
import shutil
import psycopg2
from fastapi import Depends, FastAPI, Form, UploadFile
from psycopg2.extras import Json
from microtube_auth import require_user
from microtube_storage import find_video, save_video, video_path

connection = psycopg2.connect(database="videos", user=os.getenv("POSTGRES_USER", "admin"), password=os.environ["POSTGRES_PASSWORD"], host="db-videos", port=5432)

app = FastAPI()

@app.post("/upload")
def run(
    file: UploadFile,
    owner_hash: str = Depends(require_user),
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
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

    metadata = {
        "id": id,
        "owner_hash": owner_hash,
        "filename": file.filename,
        "size": size,
        "title": title,
        "description": description,
        "tags": tags.split(),
    }

    try:
        with connection:
            with connection.cursor() as cursor:
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
        "tags": tags.split(),
        "stored": True,
    }
