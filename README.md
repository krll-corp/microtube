# microtube
A YouTube clone without the bloatware | student project

**This a a student pet project.** We are aiming to create a scalable cluster with a minimalistic video player.

---
![main page render](assets/main-page.png)

## Launch

```bash
docker compose up -d --build
```

The first AI startup downloads the model; subsequent starts reuse its cache.
To wait for startup checks, use `docker compose up -d --build --wait --wait-timeout 1200`.

| Service | Local address | Current role |
| --- | --- | --- |
| `frontend-app` | http://127.0.0.1:8080 | Frontend placeholder |
| `frontend-monitor` | http://127.0.0.1:8081 | Monitor page placeholder |
| `backend-video` | http://127.0.0.1:3030/docs | Video API placeholder |
| `backend-text` | http://127.0.0.1:3031/docs | Text API placeholder |
| `backend-ai-video` | http://127.0.0.1:4001/docs | Video embeddings |
| `backend-ai-text` | No HTTP endpoint yet | Runs `sleep infinity` until implemented |
| `db-videos` | Internal: `db-videos:5432` | PostgreSQL database `videos` |
| `db-users` | Internal: `db-users:5432` | Empty PostgreSQL database `users` |

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