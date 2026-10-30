import os
import secrets
import shutil
import psycopg2
from fastapi import Depends, FastAPI, Form, UploadFile
from psycopg2.extras import Json
from microtube_auth import require_user
from microtube_storage import find_video, video_path

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
    id = secrets.token_urlsafe(6)

    PATH_TO_VIDEO = video_path(id)
    while PATH_TO_VIDEO.exists() or find_video(id) is not None:
        id = secrets.token_urlsafe(6)
        PATH_TO_VIDEO = video_path(id)

    PATH_TO_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    with PATH_TO_VIDEO.open("xb") as destination:
        shutil.copyfileobj(file.file, destination, length=1024 * 1024)

    metadata = {
        "id": id,
        "owner_hash": owner_hash,
        "filename": file.filename,
        "size": PATH_TO_VIDEO.stat().st_size,
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
        PATH_TO_VIDEO.unlink(missing_ok=True)
        raise

    return {
        "id": id,
        "owner_hash": owner_hash,
        "filename": file.filename,
        "size": PATH_TO_VIDEO.stat().st_size,
        "title": title,
        "description": description,
        "tags": tags.split(),
        "stored": True,
    }
