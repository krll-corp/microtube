import logging
import math
import os
import time
from contextlib import closing

import psycopg2
import requests
from psycopg2.extras import Json, RealDictCursor


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


def get_vectors(video):
    video_embedding = get_embedding(
        "http://backend-ai-video:4001/embedding/video", {"hash": video["hash"]},
    )
    text_embeddings = [
        get_embedding("http://backend-ai-text:4001/embedding/text", {"text": tag})
        for tag in video["metadata"].get("tags", [])
    ]
    return {"video": video_embedding, "text": text_embeddings}


def run(video):
    video_id = video["hash"]
    with closing(connect()) as connection:
        with connection:
            with connection.cursor() as cursor:
                # A session lock survives commits and is released on disconnect.
                cursor.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                    ("microtube:indexing:" + video_id,),
                )
                if not cursor.fetchone()[0]:
                    return None
                cursor.execute(
                    "UPDATE videos SET processing_now = TRUE "
                    "WHERE hash = %s AND indexed = FALSE RETURNING metadata",
                    (video_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        logging.info("Starting indexing for %s", video_id)
        try:
            vectors = get_vectors({"hash": video_id, "metadata": row[0]})
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE videos SET vectors = %s, indexed = TRUE, processing_now = FALSE "
                        "WHERE hash = %s",
                        (Json(vectors), video_id),
                    )
                    if cursor.rowcount != 1:
                        raise LookupError(f"Video {video_id} disappeared during indexing")
        except Exception:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE videos SET processing_now = FALSE "
                        "WHERE hash = %s AND indexed = FALSE",
                        (video_id,),
                    )
            raise

    logging.info(
        "Indexed %s: video=%d dimensions, tags=%d",
        video_id, len(vectors["video"]), len(vectors["text"]),
    )
    return vectors


def watcher():
    with closing(connect()) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT hash, metadata FROM videos "
                # Include stale processing flags left by a disconnected worker.
                "WHERE indexed = FALSE ORDER BY hash"
            )
            return cursor.fetchall()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Indexing worker started")
    while True:
        try:
            for video in watcher():
                try:
                    run(video)
                except Exception:
                    logging.exception("Failed to index %s", video["hash"])
        except Exception:
            logging.exception("Indexing pass failed")
        time.sleep(60) #TODO: rate limiting + queue?