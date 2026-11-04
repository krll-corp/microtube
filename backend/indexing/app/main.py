import logging
import os
import time
from contextlib import closing

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from microtube_embeddings import get_embedding


def connect():
    return psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        port=5432,
    )


def index_tags(tag_ids):
    with closing(connect()) as connection:
        for tag_id in dict.fromkeys(tag_ids):
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT tag, vector IS NOT NULL FROM tags WHERE tag_id = %s", (tag_id,))
                    row = cursor.fetchone()
                    if row is None:
                        raise LookupError(f"Tag {tag_id} disappeared during indexing")
                    tag, indexed = row
            if not indexed:
                embedding = get_embedding("http://backend-ai-text:4001/embedding/text", {"text": tag})
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE tags SET vector = %s::vector WHERE tag_id = %s AND vector IS NULL",
                            (Json(embedding), tag_id),
                        )


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
                    "WHERE hash = %s AND indexed = FALSE RETURNING metadata->'tag_ids'",
                    (video_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        tag_ids = row[0]
        logging.info("Starting indexing for %s", video_id)
        try:
            vector = get_embedding("http://backend-ai-video:4001/embedding/video", {"hash": video_id})
            index_tags(tag_ids)
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE videos SET vector = %s::vector, "
                        "indexed = TRUE, processing_now = FALSE "
                        "WHERE hash = %s",
                        (Json(vector), video_id),
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
        video_id, len(vector), len(tag_ids),
    )
    return vector


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
