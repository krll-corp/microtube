import logging
import os
import time
from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor


def connect():
    return psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        port=5432,
    )


def run(id: str):
    with closing(connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT metadata FROM videos WHERE hash = %s", (id,))
            row = cursor.fetchone()

    return row[0] if row is not None else None


def watcher():
    with closing(connect()) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT hash, metadata FROM videos "
                "WHERE indexed = FALSE AND processing_now = FALSE"
            )
            return cursor.fetchall()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Indexing worker started (metadata only)")
    while True:
        try:
            for video in watcher():
                logging.info("Metadata loaded for %s: %s", video["hash"], video["metadata"])
        except Exception:
            logging.exception("Failed to read video metadata")
        time.sleep(60) #TODO: rate limiting + queue?