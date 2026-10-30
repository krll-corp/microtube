import os
import re
from collections import OrderedDict
from contextlib import closing
from threading import Lock

import psycopg2
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from microtube_storage import find_video

CACHE_LIMIT = max(0, int(os.getenv("VIDEO_CACHE_MB", "64"))) * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
cache = OrderedDict()
cache_lock = Lock()
app = FastAPI()


@app.get("/videos")
@app.head("/videos", include_in_schema=False)
def load(request: Request, id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{8}$")):
    if id is None:
        return {"status": "ok"}

    with closing(psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        connect_timeout=5,
    )) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM videos WHERE hash = %s", (id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Video not found")


    path = find_video(id)
    if path is None:
        raise HTTPException(status_code=404, detail="Video file not found")
    info = path.stat()
    response = FileResponse(path, media_type="video/mp4", headers={"X-Cache": "BYPASS"})
    if request.method == "HEAD" or not 0 < info.st_size <= CACHE_LIMIT or "if-range" in request.headers:
        return response



    start, end = 0, info.st_size
    requested_range = request.headers.get("range")
    if requested_range:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested_range)
        if match is None or not any(match.groups()):
            return response
        first, last = match.groups()
        try:
            if first:
                start = int(first)
                end = min(int(last) + 1, end) if last else end
            else:
                start = max(end - int(last), 0)
        except ValueError:
            return response
        if start >= end:
            raise HTTPException(status_code=416, headers={"Content-Range": f"bytes */{info.st_size}"})


    key = (id, info.st_size, info.st_mtime_ns)
    with cache_lock:
        hit = key in cache
        if not hit:
            while cache and (sum(map(len, cache.values())) + info.st_size > CACHE_LIMIT or len(cache) >= 128):
                cache.popitem(last=False)
            with path.open("rb") as video:
                content = video.read(info.st_size + 1)
            if len(content) != info.st_size:
                return response
            cache[key] = content
        cache.move_to_end(key)
        content = cache[key]

    
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start),
        "X-Cache": "HIT" if hit else "MISS",
    }
    
    
    if requested_range:
        headers["Content-Range"] = f"bytes {start}-{end - 1}/{info.st_size}"
    return StreamingResponse(
        (content[offset:min(offset + CHUNK_SIZE, end)] for offset in range(start, end, CHUNK_SIZE)),
        status_code=206 if requested_range else 200,
        media_type="video/mp4",
        headers=headers,
    )
