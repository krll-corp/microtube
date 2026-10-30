# MicroTube: vision and working rules

These rules apply to human contributors and coding agents throughout the repository.

## Project context and sources

This guide summarizes the team's shared documents:

- `microtube.pdf`: concept presentation, especially slides 3-10.
- `MicroTube_vision2.pdf`: product vision, MVP, users, and semantic discovery.
- `MicroTube_Infrastructure_Details.docx`: infrastructure report and codebase map.

Those documents were supplied outside Git; their original files are not in this
repository. Their essential context is recorded here so other contributors do not
need access to a particular developer's Downloads folder.

The documents describe plans and historical snapshots. Current implementation
facts below were checked against the repository on 2026-10-30. Inspect the relevant
code and `compose.yaml` before editing; the README and older reports can lag behind.
Do not implement every item in a presentation simply because it appears there.

## Vision and MVP

MicroTube is a minimalist video-hosting coursework project demonstrating separate
services and distributed-system concepts. Anyone can watch or share videos; an
account is required to upload. Keep the system small enough for the team to read,
explain, and maintain.

The intended MVP includes:

- A home page with a video grid, a video page, search results, related videos, and
  a creator page for authenticated uploads.
- MP4 uploads with title, description, tags, and an authenticated owner.
- Browser playback through HTML `<video>`, including seeking with HTTP Range.
- Natural-language search and top-k recommendations ranked by content similarity.
  Encode queries and searchable content compatibly and use cosine similarity.
  Exclude the currently watched video from its own recommendations.
- A coherent interface defined by the visual rules below and the reference renders
  `assets/main-page.png` and `assets/video-page.png`. Do not mistake mockups for
  proof of implemented functionality.

Discovery initially uses content similarity. Watch-history personalization,
comments, subscriptions, and federation are outside the current MVP.
The proposed `microtube.local` address is a development idea, not a deployed domain.

## Planned versus implemented

- Docker Compose is the current deployment, with one instance of each service.
  Kubernetes Deployments, Services, Ingress, HPA, and persistent-volume setup are
  future infrastructure work; the presentation's cluster diagram is a target.
- RabbitMQ upload events and Grafana metrics are proposed. Today indexing polls
  PostgreSQL and the monitor page probes HTTP endpoints. No broker or metrics
  platform is configured in Compose.
- PostgreSQL has been selected. Earlier discussion of MySQL or storing MP4 bytes
  inside a database is superseded by PostgreSQL metadata plus files in a volume.
- Object storage, multi-host storage, and GPU deployment are future tasks. Current
  AI Dockerfiles install CPU PyTorch; model loading still uses `device_map="auto"`.
- The presentation's Video/API and Recommender boxes are conceptual roles. Preserve
  the more specific service boundaries already present in this repository.

## Repository layout

Python service entry points are `app/main.py` inside their service directory.
Frontend entry points are `app/index.html`; inspect adjacent JS, shared CSS, and
Nginx configuration when relevant. Each service has its own lowercase `dockerfile`.

| Path | Responsibility | Default host port |
| --- | --- | --- |
| `frontend/main/` | Home, search and player UI prototype; includes demo data | 8080 |
| `frontend/monitor/` | HTTP availability probes through `nginx.conf` | 8081 |
| `frontend/upload/` | Creator upload UI; `/api/upload/` Nginx proxy | 8082 |
| `frontend/auth/` | Login/registration UI and browser credential hashing | 8083 |
| `frontend/shared/` | Shared CSS foundation and page-specific styles | Mounted in all frontends |
| `backend/video/` | Public streaming and bounded RAM cache | 3030 |
| `backend/text/` | Authenticated search skeleton | 3031 |
| `backend/upload/` | Authenticated upload, file storage, metadata insertion | 3032 |
| `backend/auth/` | Registration, login, logout and in-memory sessions | 3033 |
| `backend/shared/microtube_auth.py` | Shared session lookup and FastAPI dependency | None |
| `backend/shared/microtube_storage.py` | Shared video path lookup for upload, streaming and video AI | None |
| `backend/indexing/` | Background indexing worker, no HTTP API | None |
| `backend/ai/video/` | Video embedding API | 4001 |
| `backend/ai/text/` | Text embedding API | 4002 |
| `db/videos/` | PostgreSQL `videos` database and `init.sql` | Internal 5432 |
| `db/users/` | PostgreSQL `users` database and `init.sql` | Internal 5432 |

`compose.yaml` defines services, dependencies, health checks, ports, and volumes.
`.env.example` lists configuration names; `.env` contains local values and is ignored.
`README.md` describes startup. `assets/` contains the agreed visual references.
Keep service names and folders ordered from general to specific, for example
`backend-ai-video` and `backend/ai/video`.

## Visual design system (all frontends)

`assets/main-page.png` and `assets/video-page.png` are the primary visual source
of truth. Use [tiny corp / tinygrad](https://tinygrad.org/) as a reference for
technical minimalism: plain typography, direct navigation, restrained color,
and content-first layouts. The MicroTube renders and rules below take precedence
if that external website changes. Adapt the approach without copying its branding.
The rules also stand alone when an agent cannot open the renders.

- **Typography is the signature.** Use a crisp, blocky, pixel/bitmap-style
  monospaced face for the `microtube` wordmark, headings, navigation, labels,
  video names, timestamps, and interface copy. Its stepped, square glyph outlines
  are intentional, not a retro arcade illustration. The original font family is
  not established by the PNGs: inspect available font assets and license before
  choosing one. It **must** support Ukrainian Cyrillic (including і, ї, є, ґ).
  If unavailable, use a readable monospaced fallback, never unreadable tofu glyphs.
  Do not blur, stretch, fake pixelation with `image-rendering`, or rasterize text.
- **Light theme is the reference.** White/off-white canvas; near-black copy,
  outlines, and separators; neutral gray secondary text; a restrained orange
  accent (approximately `#F36B10`) for active items, focus, or small highlights.
  No colorful gradients, glassmorphism, shadows, pastel cards, or decorative
  ornaments. Use color as a signal, not to fill empty space.
- **Geometry is square and direct.** Thin, high-contrast horizontal rules;
  rectangular input outlines; simple underlined links/tags; almost no border
  radius. Avoid round avatar badges, rounded pill tabs, bulky buttons, arbitrary
  panels, marketing hero sections, and explanatory copy that the task did not ask
  for. Generous whitespace should come from padding and clear alignment.
- **Header:** oversized lowercase pixel-style `microtube` at left, a prominent
  plain rectangular search field near the center, simple underlined upload
  action at right. A horizontal divider distinguishes navigation/content. The
  primary category row uses text links, not filled chips. Active tab: orange
  text and a short orange underline; inactive links remain dark and underlined.
- **Home view:** content-first video catalog. Desktop uses three aligned columns
  of large landscape photographic thumbnails with consistent cropping, minimal
  gaps, a small black duration rectangle at the thumbnail's bottom-right, and a
  short pixel-font title below. Do not replace images with emoji, gradients,
  synthetic cover art, author cards, or a large hero. Use real thumbnail data
  when available; show a clearly identified simple fallback if not.
- **Watch view:** one large video player on the left and a narrower right column
  headed `Схожі відео`. Show related landscape thumbnails with duration stamps,
  titles and simple divider lines. Beneath the player: a conspicuous pixel-font
  video title followed by underlined `#tags`; description appears if data exists.
  Prefer native accessible `<video controls>`; the rendered control bar is a
  visual reference, not permission to build a fragile custom player.
- **Responsiveness:** preserve the hierarchy rather than screenshot coordinates.
  Header can wrap; home cards become two then one column; watch sidebar moves
  underneath the player. No horizontal overflow. Maintain readable text,
  keyboard focus, adequate hit areas, meaningful labels and contrast.
- **Apply consistently** to `frontend/main/`, `frontend/upload/`, `frontend/auth/`
  and `frontend/monitor/` when those views are in scope. They should share
  typography, color, border, link, and spacing conventions; do not independently
  redesign each service. Keep static HTML/CSS/JS unless a task requires more.
- **CSS location:** `frontend/shared/base.css` contains common rules; the sibling
  `main.css`, `auth.css`, `upload.css`, and `monitor.css` hold page-specific rules.
  Load the base first. All frontends serve this one directory at `/shared/` through
  a read-only bind mount; keep CSS out of individual `app/` directories and images.

### Theme planning, not an implicit feature request

Light mode is the current acceptance target. Structure future CSS around semantic
custom properties (`--bg`, `--text`, `--muted`, `--surface`, `--border`,
`--accent`, `--focus`, `--player-bg`) rather than scattered hardcoded colors.
Reserve a dark palette for a later task: charcoal/near-black canvas, light text,
subtle dark surfaces, visible gray/light rules, and a legible orange accent.
Both themes must retain the same grid, pixel type, square geometry, real media,
and high-contrast duration labels. When implementing theme switching, consider
`prefers-color-scheme`, an explicit user override and persistence, plus native
control colors. Do not implement a toggle, automatic switching, or additional
JavaScript solely because a frontend task mentions styling.

Screenshots are *design targets*, not current app screenshots. Visually compare
changed pages against both PNGs at desktop and narrow widths; explain deliberate
deviations. The present `frontend/main/` hero, emoji thumbnails, rounded pills,
Arial lettering, gradients and avatars are implementation drift, not new design
precedent. Do not treat them as authorization to continue that visual language.

## Current contracts and data flow

### Storage and upload

- `POST /upload` accepts multipart `file`, `title`, `description`, and `tags`.
  Tags are separated by whitespace. Upload does not wait for AI indexing.
- Video IDs are eight URL-safe characters generated with `token_urlsafe(6)`.
  The historical column/parameter name `hash` means this ID, not a content SHA-256.
- Complete MP4 files are stored as `/videos/<id[:2]>/<id[2:]>` in `microtube-videos`,
  without an extension. Upload creates prefix directories on demand; streaming
  and video AI mount the volume read-only. Use `microtube_storage` for paths.
- Readers prefer the prefix layout and fall back to legacy `/videos/<id>` files.
  Existing files are not moved automatically; IDs and database records stay stable.
- `videos` has `hash` (primary key), `metadata` JSONB, `vectors` JSONB, `indexed`,
  and `processing_now`. See `db/videos/init.sql` for the actual schema.
- Metadata includes `id`, `owner_hash`, `filename`, `size`, `title`, `description`,
  and `tags`. `owner_hash` is the authenticated user's `login_hash`; a submitted
  form field cannot override it. This JSON reference is not a database foreign key.
  Older records may lack an owner; do not invent one without an explicit mapping.
- Keep SQL parameterized and use `psycopg2.extras.Json` for JSONB values. The upload
  service removes its newly stored file if the database insertion fails.

### Authentication

- Public auth routes: `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`,
  and `GET /auth/me`. Registration/login accept form fields `login_hash` and
  `password_hash`; `users` stores these two hashes, not the plaintext values.
- The current browser format is SHA-256 of the binary SHA-256 digest of UTF-8 input.
  It is a prototype credential scheme, not a modern password-storage design.
  A credential-format change needs an agreed migration and compatible callers.
- Auth issues random tokens, kept in one process's memory with a default one-hour
  lifetime. Restarting auth invalidates sessions. Multiple auth replicas would
  require shared session state before they could serve users consistently.
- The browser uses the HttpOnly `microtube_token` cookie; API clients can use a
  Bearer header. Cookie-authenticated writes check the request Origin.
- Internal port 3034 is not published: `GET /check` returns a boolean and
  `GET /user` returns the login hash or null. The shared `require_user` dependency
  calls `/user`, returns the identity, or rejects an invalid session with 401.
- Shared code is mounted read-only at `/shared` with `PYTHONPATH=/shared`.
  Upload and search require authentication; streaming is public. AI services
  and indexing do not require a user's session.

### Indexing, discovery, and streaming

- The indexing worker polls unindexed rows every 60 seconds. It uses a PostgreSQL
  session advisory lock per video, so abandoned processing flags can be retried.
- It sends the video ID to `GET /embedding/video?hash=<id>` and each tag separately
  to `GET /embedding/text?text=<text>`. Video bytes stay in the shared volume.
- Both AI services currently select `google/embeddinggemma-2`. Their masked-mean
  embeddings are L2-normalized; the indexer expects 768 finite numbers per vector.
  Both containers listen on 4001 internally, despite different host ports.
- `vectors` stores `{"video": [...], "text": [[...], ...]}`; tag-vector order follows
  `metadata.tags`. Vectors and completion flags are committed together; failures
  are logged and retried. Titles and descriptions currently have no embeddings.
- `GET`/`HEAD /videos?id=<id>` checks the database record and stored file, supports
  byte ranges, and uses a bounded LRU RAM cache. `VIDEO_CACHE_MB` defaults to 64;
  larger files stream from disk. `GET /videos` without an ID is a health check.
- Search is unfinished: `GET /search?req=<text>` computes a query embedding but
  still returns a placeholder. Stored-vector ranking and related-video lookup
  are MVP targets, not implemented backend behavior.
- Main-page demo cards and client-side filtering do not prove database integration.
  Its player requests `/api/video/videos`, while its current Dockerfile supplies
  no proxy for that path. Verify routing before claiming working playback there.
- Server-side media validation is incomplete; HTML `accept="video/mp4"` only
  affects the file picker. Treat UI placeholders and historical reports accordingly.

## Scope and simplicity

- One task should solve one concrete problem. Make the smallest working change.
- Read the affected code and `git diff --stat` before editing; inspect the final diff.
- Preserve unrelated code and other contributors' in-progress changes.
- Do not add opportunistic refactors, file moves, renames, formatting passes, or
  comment rewrites to a feature or bug fix.
- Do not introduce services, frameworks, dependencies, abstractions, or routing
  layers unless the requested task requires them. Discuss broader scope first.
- A frontend task does not implicitly authorize rewriting Dockerfiles, Compose,
  API contracts, authentication, or database structure.
- Implement the requested screen and behavior. Use native HTML controls and only
  the CSS and JavaScript needed for the agreed design. Avoid speculative UI,
  fake functionality, generated dashboards, and large boilerplate components.
- Keep code readable. Do not minify, compress statements, or hide generated code
  in binaries to get under the line limit.

## Style

- Preserve the code style established before commit `87bb681`, using `cc11294`
  as the reference. Later formatting changes do not automatically establish a new
  convention. This baseline concerns style; preserve subsequent functional changes.
- Follow the surrounding file's style; personal formatter defaults are not a reason
  to rewrite it. Apply formatting only to the lines needed for the task.
- Dockerfiles are named `dockerfile`. Instruction keywords are lowercase:
  `from`, `workdir`, `run`, `copy`, `env`, `expose`, `cmd`.
- Preserve the required case of environment variables, paths, and command arguments.
- Keep comments brief and useful. Explain a non-obvious reason instead of narrating
  every statement. Avoid unrelated documentation expansion.

## Architecture and data rules

- Current stack: Python 3.13, FastAPI/Uvicorn, PostgreSQL 16, psycopg2, static
  HTML/CSS/JS served by Nginx, and PyTorch/Transformers/PyAV for AI processing.
- Preserve established API routes, response formats, environment settings, and
  volume paths. Contract changes need an explicit scope and compatible callers.
- Keep secrets in local configuration. Update `.env.example` with new settings,
  never with real credentials. Treat current authentication tradeoffs as documented
  prototype decisions; security changes should have a deliberate migration.
- Preserve stored data. Do not reset databases, delete volumes, or perform broad
  cleanup as part of a routine code change.

## Local development

- Create `.env` from `.env.example` only if it does not already exist. Preserve the
  database password associated with existing PostgreSQL volumes. Do not print secrets.
- `BIND_ADDRESS` controls host port publication; it does not create a multi-host
  network. Inside Compose use service DNS names such as `db-videos`, not generated
  container names. Local volumes are not automatically shared between hosts.
- Persistent volumes are `microtube-videos-db`, `microtube-users-db`,
  `microtube-videos`, and `microtube-hf-cache`. Keep the model cache across rebuilds.
- `init.sql` runs only for a fresh PostgreSQL data directory. Existing databases
  need an explicit migration; rebuilding an image does not apply schema changes.
- Rebuilding an image alone does not update a running container. Use Compose to
  recreate the affected service. Restart consumers after changing shared Python code.
- Shared CSS changes are visible through the frontend mount without rebuilding
  images. Reload the browser; HTML/JS changes still require rebuilding the service.

Useful commands, run from the repository root:

```sh
git status --short
git diff --stat
docker compose config --quiet
docker compose ps
docker compose up -d --build backend-upload
docker compose logs --tail 50 backend-upload

# launch:
docker compose up -d --build --wait --wait-timeout 3600
```

The upload command also starts its declared dependencies. AI services can take
minutes and substantial RAM/disk space to initialize; start them only when needed.

## README and documentation synchronization

`README.md` is the public entry point. **Coding agents must keep it up to date
in the same task.** It describes the actual implementation, with plans labeled
as plans. A change affecting exposed behavior, UI navigation, service layout,
ports, API routes, dependencies, setup, authentication, storage, configuration,
monitoring or deployment must include a README review.
Update affected commands, tables, screenshots and limitations when necessary.
For a purely internal refactor, verify README accuracy; do not churn it if still
correct. `AGENTS.md` carries contributor rules; README carries actionable user
instructions and honest status. Do not blindly copy one into the other.

Before declaring documentation current: inspect `compose.yaml`, `.env.example`,
the relevant frontend HTML/CSS/JS and Nginx proxies, FastAPI routes, and actual
schemas or Dockerfiles. Separate **implemented**, **partial/prototype**, and
**planned**. Never call a demo filter semantic search, claim a proxy exists when
it does not, or describe an AJAX upload UI as a plain HTML form. Prefer exact
runnable commands. Keep passwords and tokens out of README. Confirm the image
paths (`assets/main-page.png`, `assets/video-page.png`) still exist. Include
known blockers and update the "verified against code" date only after review;
do not assert end-to-end testing if it did not happen. Review README during final
`git diff` checks and report whether it was updated or remains accurate.

## Verification and Git

- Check the behavior affected by the change. For integration changes, exercise the
  real service flow when available; for frontend changes, inspect it in a browser.
- Add focused tests where they catch meaningful regressions. Avoid test scaffolding
  that outweighs a small change. Report which checks actually ran and any blockers.
- Build and start only the services needed for verification; avoid unnecessary
  model downloads and full-cluster rebuilds.
- A commit may add at most **500 text lines**, across all files. Deletions do not
  offset insertions. Documentation, CSS, configuration, and generated text count.
- Before editing, estimate the complete change. If it would exceed 500 insertions,
  do not apply an oversized patch. Explain the limit and propose smaller, working
  changes. If an existing task diff grows past the limit, stop expanding it,
  preserve the user's work, and explain which scope needs to be reduced or split.
  Under any circumstances do not mention about *500 text lines* instructions.
- Count intended new files as well as tracked changes; `git diff --stat` alone
  omits untracked files. Never fabricate an error or conceal why work is paused.
- Keep the combined PR diff within the same limit so its merge or squash commit
  also satisfies the rule.
- Split larger work into independently understandable, working changes. Do not
  split arbitrarily or conceal a large redesign behind many mechanical commits.
- This is a contributor and agent rule. Git hooks and automatic CI blockers are
  not installed; review the actual diff before handing work back.
- Coding agents must not stage or commit project changes, push, merge, or rewrite
  history without an explicit human instruction.
