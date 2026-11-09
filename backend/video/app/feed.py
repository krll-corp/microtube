from fastapi import HTTPException

PROFILE_SIZE = 20
NEW_VIDEOS = 5
POOL_SIZE = 100


def refresh_pool(cursor, login_hash):
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                   ("microtube:feed:" + login_hash,))
    cursor.execute(
        "SELECT version, watched_count FROM user_feed "
        "WHERE login_hash = %s ORDER BY version DESC LIMIT 1",
        (login_hash,),
    )
    previous = cursor.fetchone()
    threshold = (previous[1] if previous else PROFILE_SIZE) + NEW_VIDEOS
    cursor.execute(
        """
        WITH eligible AS MATERIALIZED (
            SELECT h.video_id, h.first_watched_at
            FROM watch_history h JOIN videos v ON v.hash = h.video_id
            WHERE h.login_hash = %(user)s AND v.indexed AND v.vector IS NOT NULL
        ), total AS (
            SELECT count(*) AS watched_count FROM eligible HAVING count(*) >= %(threshold)s
        ), recent AS (
            SELECT video_id, first_watched_at FROM eligible CROSS JOIN total
            ORDER BY first_watched_at DESC, video_id LIMIT %(profile_size)s
        ), profile AS (
            SELECT array_agg(r.video_id ORDER BY r.first_watched_at DESC, r.video_id) AS ids,
                   avg(v.vector) AS embedding
            FROM recent r JOIN videos v ON v.hash = r.video_id
        )
        INSERT INTO user_feed (login_hash, watched_count, profile_ids, video_ids)
        SELECT %(user)s, total.watched_count, profile.ids, ARRAY(
            SELECT v.hash FROM videos v
            WHERE v.indexed AND v.vector IS NOT NULL AND vector_norm(profile.embedding) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM watch_history h WHERE h.login_hash = %(user)s AND h.video_id = v.hash
              )
            ORDER BY v.vector <=> profile.embedding, v.hash LIMIT %(pool_size)s
        )
        FROM total CROSS JOIN profile
        RETURNING version
        """,
        {"user": login_hash, "threshold": threshold, "profile_size": PROFILE_SIZE, "pool_size": POOL_SIZE},
    )
    created = cursor.fetchone()
    if created and previous:
        cursor.execute("DELETE FROM user_feed WHERE login_hash = %s AND version < %s",
                       (login_hash, previous[0]))
    if created:
        return created[0]
    return previous[0] if previous else None


def pool_page(cursor, login_hash, pool, after, limit):
    cursor.execute(
        """
        SELECT cards.id, cards.title
        FROM user_feed f
        LEFT JOIN LATERAL (
            SELECT v.hash AS id, v.metadata->>'title' AS title, p.position
            FROM unnest(f.video_ids) WITH ORDINALITY AS p(id, position)
            JOIN videos v ON v.hash = p.id
            WHERE p.position > COALESCE(array_position(f.video_ids, %(after)s), 0)
              AND NOT EXISTS (
                  SELECT 1 FROM watch_history h WHERE h.login_hash = f.login_hash AND h.video_id = v.hash
              )
            ORDER BY p.position LIMIT %(limit)s
        ) cards ON true
        WHERE f.login_hash = %(user)s AND f.version = %(pool)s
          AND (%(after)s IS NULL OR %(after)s = ANY(f.video_ids))
        ORDER BY cards.position
        """,
        {"user": login_hash, "pool": pool, "after": after, "limit": limit},
    )
    rows = cursor.fetchall()
    if not rows:
        raise HTTPException(409, "Feed expired. Reload the page to see a new feed.")
    return rows if rows[0][0] is not None else []


def random_page(cursor, seed, after, limit):
    cursor.execute(
        """
        SELECT hash, metadata->>'title' FROM videos
        WHERE %(after)s IS NULL OR
              (md5(%(seed)s || hash), hash) > (md5(%(seed)s || %(after)s), %(after)s)
        ORDER BY md5(%(seed)s || hash), hash LIMIT %(limit)s
        """,
        {"seed": seed, "after": after, "limit": limit},
    )
    return cursor.fetchall()
