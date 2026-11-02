import math
import os
from contextlib import closing
from pathlib import Path
import psycopg2
import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from psycopg2.extras import RealDictCursor
from microtube_auth import require_user

app = FastAPI()
SEARCH_SQL = Path(__file__).with_name("search.sql").read_text()

def connect():
    return psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        port=5432,
    )

def get_embedding(url, params):
    response = requests.get(url, params=params, timeout=600)
    response.raise_for_status()
    embedding = response.json()
    if (
        not isinstance(embedding, list)
        or len(embedding) != 768
        or not all(type(value) in (int, float) and math.isfinite(value) for value in embedding)
    ):
        raise ValueError(f"Invalid embedding from {url}")
    return embedding

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
            cursor.execute(SEARCH_SQL, (embedding, limit))
            return cursor.fetchall()
