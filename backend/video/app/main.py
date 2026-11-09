import os
import re
from collections import OrderedDict
from contextlib import closing
from email.utils import formatdate
from hashlib import sha256
from secrets import token_hex
from threading import Lock

import psycopg2
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from microtube_auth import require_user, user_token
from microtube_storage import find_video, open_video
from feed import pool_page, random_page, refresh_pool

CACHE_LIMIT = max(0, int(os.getenv("VIDEO_CACHE_MB", "64"))) * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
cache = OrderedDict()
cache_lock = Lock()
app = FastAPI()


def connect():
    return psycopg2.connect(
        database="videos",
        user=os.getenv("POSTGRES_USER", "admin"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="db-videos",
        connect_timeout=5,
    )


@app.get("/catalog")
def catalog(
    limit: int = Query(default=24, ge=1, le=100),
    after: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{8}$"),
):
    with closing(connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT hash, metadata->>'title' FROM videos "
                "WHERE hash > %s ORDER BY hash LIMIT %s",
                (after or "", limit + 1),
            )
            rows = cursor.fetchall()
    return {
        "items": [{"id": row[0], "title": row[1]} for row in rows[:limit]],
        "next_after": rows[limit - 1][0] if len(rows) > limit else None,
    }


@app.post("/history", status_code=204)
def record_watch(
    id: str = Query(pattern=r"^[A-Za-z0-9_-]{8}$"),
    login_hash: str = Depends(require_user),
):
    with closing(connect()) as connection, connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO watch_history (login_hash, video_id) "
                "SELECT %s, hash FROM videos WHERE hash = %s "
                "ON CONFLICT (login_hash, video_id) DO UPDATE SET watched_at = clock_timestamp()",
                (login_hash, id),
            )
            if not cursor.rowcount:
                raise HTTPException(404, "Video not found")
    return Response(status_code=204)


@app.get("/feed")
def feed(
    limit: int = Query(default=24, ge=1, le=100),
    after: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{8}$"),
    seed: str | None = Query(default=None, pattern=r"^[a-f0-9]{16}$"),
    pool: int | None = Query(default=None, ge=1, le=9223372036854775807),
    token=Depends(user_token),
):
    if (seed and pool) or bool(after) != bool(seed or pool):
        raise HTTPException(422, "Invalid feed cursor")
    login_hash = None
    if pool is not None or (seed is None and token is not None):
        try:
            login_hash = require_user(token)
        except HTTPException as error:
            if pool is not None or error.status_code not in (401, 503):
                raise

    with closing(connect()) as connection, connection:
        with connection.cursor() as cursor:
            if after is None and login_hash is not None:
                pool = refresh_pool(cursor, login_hash)
            if pool is not None:
                rows = pool_page(cursor, login_hash, pool, after, limit + 1)
                if after is None and not rows:
                    pool = None
            if pool is None:
                seed = seed or token_hex(8)
                rows = random_page(cursor, seed, after, limit + 1)

    next_page = None
    if len(rows) > limit:
        next_page = {"after": rows[limit - 1][0]}
        if pool is not None:
            next_page["pool"] = str(pool)
        else:
            next_page["seed"] = seed
    return JSONResponse(
        {"items": [{"id": row[0], "title": row[1]} for row in rows[:limit]], "next": next_page},
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/metadata")
def metadata(request: Request, id: str = Query(pattern=r"^[A-Za-z0-9_-]{8}$")):
    with closing(connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT metadata->>'title', metadata->>'description', "
                "COALESCE((SELECT jsonb_agg(tags.tag ORDER BY ids.position) "
                "FROM jsonb_array_elements_text(videos.metadata->'tag_ids') "
                "WITH ORDINALITY AS ids(value, position) "
                "JOIN tags ON tags.tag_id = ids.value::bigint), '[]'::jsonb) "
                "FROM videos WHERE hash = %s",
                (id,),
            )
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, "Video not found", headers={"Cache-Control": "no-store"})
    response = JSONResponse({"id": id, "title": row[0], "description": row[1], "tags": row[2]})
    etag = f'"{sha256(response.body).hexdigest()}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=60, must-revalidate"}
    if any(value.strip() in (etag, "W/" + etag, "*")
           for value in request.headers.get("if-none-match", "").split(",")):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return response


def byte_ranges(value, size):
    unit, separator, value = value.partition("=")
    if not separator or unit.strip().lower() != "bytes":
        raise HTTPException(400, "Invalid range unit")
    ranges = []
    for item in value.split(","):
        match = re.fullmatch(r"\s*(\d*)-(\d*)\s*", item)
        if match is None or not any(match.groups()):
            raise HTTPException(400, "Invalid byte range")
        first, last = match.groups()
        try:
            start = int(first) if first else max(0, size - int(last))
            end = min(size, int(last) + 1) if first and last else size
        except ValueError:
            raise HTTPException(400, "Invalid byte range")
        if start < end:
            ranges.append((start, end))
    if not ranges:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def chunked_response(request, id, path):
    try:
        with open_video(path) as video:
            size, stamp, parts, block_size = video.size, video.mtime_ns, video.parts, video.chunk_size
        info = [part.stat() for part in parts]
    except (OSError, ValueError):
        raise HTTPException(404, "Video files incomplete or invalid")
    headers = {
        "Accept-Ranges": "bytes", "Content-Length": str(size), "X-Cache": "BYPASS",
        "ETag": f'"{stamp:x}-{size:x}"',
        "Last-Modified": formatdate(stamp / 1e9, usegmt=True),
    }
    requested = request.headers.get("range")
    if request.headers.get("if-range") not in (None, headers["ETag"], headers["Last-Modified"]):
        requested = None
    ranges = byte_ranges(requested, size) if requested else [(0, size)]
    needed = {i for start, end in ranges if end > start
              for i in range(start // block_size, (end - 1) // block_size + 1)}
    keys = {i: (id, i, stamp, info[i].st_size, info[i].st_mtime_ns) for i in needed}
    cacheable = {i for i in needed if 0 < info[i].st_size <= CACHE_LIMIT}
    if cacheable and request.method != "HEAD":
        with cache_lock:
            hit = cacheable == needed and all(keys[i] in cache for i in needed)
            headers["X-Cache"] = "HIT" if hit else "MISS"

    def content(start, end):
        while start < end:
            index, offset = divmod(start, block_size)
            count = min(end - start, info[index].st_size - offset)
            if count <= 0:
                raise OSError("Video chunk changed during read")
            data = None
            if index in cacheable:
                with cache_lock:
                    key = keys[index]
                    if key not in cache:
                        while cache and (sum(map(len, cache.values())) + info[index].st_size > CACHE_LIMIT or len(cache) >= 128):
                            cache.popitem(last=False)
                        with parts[index].open("rb") as source:
                            data = source.read(info[index].st_size + 1)
                        if len(data) != info[index].st_size:
                            raise OSError("Video chunk changed during read")
                        cache[key] = data
                    cache.move_to_end(key)
                    data = cache[key]
            if data is not None:
                for position in range(offset, offset + count, CHUNK_SIZE):
                    yield data[position:min(position + CHUNK_SIZE, offset + count)]
                del data
            else:
                with parts[index].open("rb") as source:
                    source.seek(offset)
                    remaining = count
                    while remaining:
                        data = source.read(min(CHUNK_SIZE, remaining))
                        if not data:
                            raise OSError("Video chunk truncated during read")
                        remaining -= len(data)
                        yield data
            start += count

    media_type, status = "video/mp4", 206 if requested else 200
    if len(ranges) == 1:
        start, end = ranges[0]
        headers["Content-Length"] = str(end - start)
        if requested:
            headers["Content-Range"] = f"bytes {start}-{end - 1}/{size}"
        body = content(start, end)
    else:
        boundary = token_hex(16)
        prefixes = [f"--{boundary}\r\nContent-Type: video/mp4\r\nContent-Range: bytes {start}-{end - 1}/{size}\r\n\r\n".encode()
                    for start, end in ranges]
        ending = f"--{boundary}--\r\n".encode()
        length = sum(len(prefix) + end - start + 2
                     for prefix, (start, end) in zip(prefixes, ranges))
        headers["Content-Length"] = str(length + len(ending))
        media_type = f"multipart/byteranges; boundary={boundary}"

        def multipart():
            for prefix, (start, end) in zip(prefixes, ranges):
                yield prefix
                yield from content(start, end)
                yield b"\r\n"
            yield ending

        body = multipart()
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers, media_type=media_type)
    return StreamingResponse(body, status_code=status, headers=headers, media_type=media_type)


@app.get("/videos")
@app.head("/videos", include_in_schema=False)
def load(request: Request, id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_-]{8}$")):
    if id is None:
        return {"status": "ok"}

    with closing(connect()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM videos WHERE hash = %s", (id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Video not found")


    path = find_video(id)
    if path is None:
        raise HTTPException(status_code=404, detail="Video file not found")
    if path.is_dir():
        return chunked_response(request, id, path)
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
