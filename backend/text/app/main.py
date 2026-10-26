import math
import os
import psycopg2
import requests
from fastapi import Depends, FastAPI
from microtube_auth import require_user

app = FastAPI()

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
def run(req: str):
    text_embedding = get_embedding("http://backend-ai-text:4001/embedding/text", {"text": req})
    return "backend-text-search"
