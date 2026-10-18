# microtube
A YouTube clone without the bloatware | student project

**This a a student pet project.** We are aiming to create a scalable cluster with a minimalistic video player.

---
![main page render](assets/main-page.png)

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
| `frontend-main` | http://127.0.0.1:8080 | Frontend placeholder |
| `frontend-upload` | http://127.0.0.1:8082 | Plain multipart upload form |
| `frontend-monitor` | http://127.0.0.1:8081 | Monitor page placeholder |
| `backend-video` | http://127.0.0.1:3030/docs | Video API placeholder |
| `backend-text` | http://127.0.0.1:3031/docs | Text API placeholder |
| `backend-upload` | http://127.0.0.1:3032/docs | Receives a file and metadata |
| `backend-ai-video` | http://127.0.0.1:4001/docs | Video embeddings |
| `backend-ai-text` | No HTTP endpoint yet | Runs `sleep infinity` until implemented |
| `db-videos` | Internal: `db-videos:5432` | PostgreSQL database `videos` |
| `db-users` | Internal: `db-users:5432` | Empty PostgreSQL database `users` |

The upload form posts `file`, `title`, `description`, and `tags` to `/upload` on
`UPLOAD_API_PORT` (default `3032`) on the same host as the page. Tags are separated
by whitespace. The browser displays the JSON response; no `fetch` or CORS setup
is needed for this native form submission. File storage and DB handling are still
TODO: the endpoint currently confirms receipt and returns `stored: false`.

Useful commands:

```bash
docker compose ps
docker compose logs -f backend-ai-video
docker compose stop
docker compose exec db-videos psql -U admin -d videos
```

note: docker compose creates a shared network

volumes: `microtube-videos-db`, `microtube-users-db`,`microtube-videos`, and `microtube-hf-cache`. They survive container recreation and `docker compose down`. 

Files are stored as `/videos/<sha256>`; the database stores the hash and JSON metadata. (TODO: we don't need the hash to be sha256, we can use a smaller hash)