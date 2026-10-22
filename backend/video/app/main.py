import os
import psycopg2
from pathlib import Path
from fastapi import FastAPI

connection = psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        port=5432,
    )

app = FastAPI()

videos = []

@app.get("/videos")
def load(id: str):
    if id is None:
        return {"status": "200 OK"}
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(f"select 1 from videos where hash = {id}"),
        metadata = cursor.fetchone()["metadata"]
    except Exception:
        pass
    with open(f"/videos/{id}", "rb") as v:
        videos.append = v.read()
        #TODO: stream video to frontend