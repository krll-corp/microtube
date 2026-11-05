import math
import os
from contextlib import closing
from pathlib import Path
import psycopg2
import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from psycopg2.extras import RealDictCursor
from microtube_auth import require_user
from microtube_embeddings import get_embedding

app = FastAPI()
SEARCH_SQL = Path(__file__).with_name("search.sql").read_text()

def connect():
    return psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        port=5432,
        connect_timeout=5,
    )

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/search", dependencies=[Depends(require_user)])
def run(req: str = Query(min_length=1, pattern=r"\S"), limit: int = Query(default=20, ge=1, le=100)):
    try:
        embedding = get_embedding("http://backend-ai-text:4001/embedding/text", {"text": req.strip()})
        norm = math.hypot(*embedding)
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("Invalid query vector norm")
        embedding = [value / norm for value in embedding]
    except (requests.RequestException, ValueError, OverflowError) as error:
        raise HTTPException(502, "Text embedding service unavailable or returned an invalid vector") from error

    with closing(connect()) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(SEARCH_SQL, (str(embedding), limit))
            return cursor.fetchall()
