WITH query AS (
    SELECT %s::vector(768) AS vector
), tag_scores AS MATERIALIZED (
    SELECT tag_id, 1 - (tags.vector <=> query.vector) AS score
    FROM tags CROSS JOIN query
    WHERE tags.vector IS NOT NULL
), video_tags AS (
    SELECT videos.hash, MAX(tag_scores.score) AS tag_score
    FROM videos
    CROSS JOIN LATERAL jsonb_array_elements_text(videos.metadata->'tag_ids') AS ids(value)
    JOIN tag_scores ON tag_scores.tag_id = ids.value::bigint
    WHERE videos.indexed
    GROUP BY videos.hash
), scores AS (
    SELECT videos.hash, 1 - (videos.vector <=> query.vector) AS video_score,
        video_tags.tag_score
    FROM videos CROSS JOIN query
    LEFT JOIN video_tags USING (hash)
    WHERE videos.indexed
), ranked AS (
    SELECT hash, video_score, tag_score,
        -- TODO: Decide how to combine video/tag scores; MAX is provisional.
        GREATEST(video_score, tag_score) AS score
    FROM scores
    WHERE video_score IS NOT NULL OR tag_score IS NOT NULL
    ORDER BY score DESC, hash
    LIMIT %s
)
SELECT ranked.hash AS id, videos.metadata, ranked.score, ranked.video_score, ranked.tag_score
FROM ranked JOIN videos USING (hash)
ORDER BY ranked.score DESC, ranked.hash;
