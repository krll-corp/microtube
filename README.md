# microtube
A YouTube clone without the bloatware | student project

**This is a student pet project.** We are aiming to create a scalable cluster with a minimalistic video player.

---
![main page render](assets/main-page.png)

The renders in `assets/main-page.png` and `assets/video-page.png` are design
references, not current application screenshots. See `AGENTS.md` for the pixel-style
design direction and future dark-theme considerations.

## Launch

On the first run, copy `.env.example` to `.env` and set `POSTGRES_PASSWORD`.
Keep your existing `.env` when updating. For an existing database, use its current password.

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

The first AI startup downloads the model; subsequent starts reuse its cache.
To wait for startup checks, use `docker compose up -d --build --wait --wait-timeout 1200`.

| Service | Local address | Current role |
| --- | --- | --- |
| `frontend-main` | http://127.0.0.1:8080 | Demo catalog, local filtering and watch-page UI |
| `frontend-upload` | http://127.0.0.1:8082 | Creator upload UI with preview and progress |
| `frontend-monitor` | http://127.0.0.1:8081 | HTTP availability monitor |
| `frontend-auth` | http://127.0.0.1:8083 | Login and registration form |
| `backend-video` | http://127.0.0.1:3030/docs | Video streaming with a bounded RAM cache |
| `backend-text` | http://127.0.0.1:3031/docs | Authenticated text search skeleton |
| `backend-upload` | http://127.0.0.1:3032/docs | Receives a file and metadata after login |
| `backend-auth` | http://127.0.0.1:3033/docs | Registration, login, logout and session information |
| `backend-indexing` | No HTTP endpoint | Background worker saving video and tag embeddings |
| `backend-ai-video` | http://127.0.0.1:4001/docs | Video embeddings |
| `backend-ai-text` | http://127.0.0.1:4002/docs | Text embeddings |
| `db-videos` | Internal: `db-videos:5432` | PostgreSQL database `videos` |
| `db-users` | Internal: `db-users:5432` | Login and password hashes |

Open the login form on port `8083`, register or log in, then open the upload form
on port `8082`. Use the same hostname for both pages. Both login and password are
case-sensitive and hashed in the browser as `SHA256(SHA256(UTF8(value)))`, with
the binary digest as input to the second hash. Only the two hexadecimal hashes
are sent as form fields `login_hash` and `password_hash` and stored in `users`.
Registration and login return a random token and set an HttpOnly session cookie.
The upload UI sends this cookie with its XMLHttpRequest; API clients can instead
use `Authorization: Bearer <token>`.

`GET /auth/me` returns the current login hash, and `POST /auth/logout` invalidates
the current token. Sessions expire after `AUTH_TOKEN_TTL_SECONDS` (default `3600`)
and are kept in one process's memory: restarting auth logs everyone out. This
version runs one auth instance. Streaming stays public; upload and search require
login. AI services and indexing do not use user authentication.

The shared dependency is `backend/shared/microtube_auth.py`, mounted read-only at
`/shared` with `PYTHONPATH=/shared`. It calls `backend-auth:3034/user` with a Bearer
token and returns the authenticated user's `login_hash`; an invalid session
returns `null` from auth and is rejected by the dependency with `401`.
The internal `/check` endpoint still returns `true` or `false`.
Port `3034` is not published on the host.
Changes to the shared module require restarting the services that import it.

For an existing users volume, apply the new table once; initialization scripts
only run automatically for a fresh database:

```bash
docker compose exec -T db-users sh -c 'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/users/init.sql
```

Client-side double SHA-256 is a prototype choice: the password hash itself can
be used to log in and must be treated as a password. A fast unsalted hash does not
provide modern password-storage protection ([OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)). (TODO)
Browser hashing needs HTTPS outside localhost (also TODO). With HTTPS, set
`AUTH_COOKIE_SECURE=true` so the session cookie is only sent over HTTPS.

The upload UI posts `file`, `title`, `description`, and `tags` via XMLHttpRequest
to `/api/upload/upload` on port `8082`, proxied to `backend-upload:3032/upload`.
Tags are separated by whitespace. The UI shows upload progress and the server's
response. The endpoint stores the file in `/videos/<id>`, writes its metadata to
PostgreSQL, and returns `stored: true`.
The metadata JSON and upload response include `owner_hash`, taken from the
authenticated session's `login_hash`. A form field cannot override this value.
Existing videos without an owner need an explicit assignment; their original
uploader cannot be inferred from the stored metadata.

In `backend-indexing`, the worker polls unindexed videos every 60 seconds.
`run(video)` claims a video with a PostgreSQL session advisory lock and sets
`processing_now = true`, then requests a video embedding and one text embedding
per tag. Valid 768-dimensional vectors are saved to `vectors` as
`{"video": [...], "text": [[...], ...]}` with tag vectors in metadata order.
The vectors, `indexed = true`, and `processing_now = false` are committed together.
On error, the video remains unindexed and is retried on the next poll; other videos
continue processing. Session locks are released on disconnect, so interrupted
videos can be picked up again even if `processing_now` was left true.
Completed videos are skipped. Successes and errors are logged.

`GET /embedding/text?text=dog` returns a normalized 768-dimensional vector. The
text service uses the same model and shared model cache as the video service,
with the unused vision and audio encoders disabled. `TEXT_AI_PORT` defaults to
`4002` on the host; both AI containers use port `4001` internally.

`GET /videos?id=<id>` on `backend-video` streams an uploaded MP4 inline. It checks
that the ID exists in PostgreSQL and that the file exists in `/videos`. HTTP
`Range` requests support seeking (`206 Partial Content`); `HEAD` returns headers
without reading the file body. `GET /videos` without an ID is the health check.

The process keeps recently requested small files in an LRU RAM cache, capped by
`VIDEO_CACHE_MB` (default `64` MiB; `0` disables caching). Files larger than the
budget stream from disk in chunks. The cache is cleared on container restart and
invalidated when a file changes. `X-Cache` reports `MISS`, `HIT`, or `BYPASS`;
multipart ranges use disk streaming. Database checks still run on cache hits.

For example: `curl -H 'Range: bytes=0-1023' 'http://127.0.0.1:3030/videos?id=<id>'`.

Useful commands:

```bash
docker compose ps
docker compose logs -f backend-ai-video
docker compose stop
docker compose exec db-videos psql -U admin -d videos
```

note: docker compose creates a shared network

`BIND_ADDRESS` selects the host interface for published ports: `127.0.0.1` for
local access, a private/VPN IP for that interface, or `0.0.0.0` for all IPv4
interfaces. It does not change container DNS or create networking across hosts.
Within this Compose network, services use names such as `backend-ai-video:4001`.

volumes: `microtube-videos-db`, `microtube-users-db`,`microtube-videos`, and `microtube-hf-cache`. They survive container recreation and `docker compose down`. 

Files are stored as `/videos/<id>`; the database stores this ID in `hash` and the JSON metadata in `metadata`.

## Documentation maintenance

**Coding agents MUST keep `README.md` up to date.** Changes to documented
functionality, APIs, setup, configuration, or deployment must include the
necessary README updates in the same task. Describe implemented behavior
accurately, distinguish plans from working features, and avoid unrelated rewrites.