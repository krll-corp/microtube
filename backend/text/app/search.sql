WITH ranked AS (
    SELECT videos.hash,
        -- TODO: Decide how to combine video/tag scores; MAX is provisional.
        MAX(similarity.score) AS score,
        MAX(similarity.score) FILTER (WHERE embedding.kind = 'video') AS video_score,
        MAX(similarity.score) FILTER (WHERE embedding.kind = 'text') AS tag_score
    FROM videos
    CROSS JOIN (SELECT %s::double precision[] AS value) AS query
    CROSS JOIN LATERAL (
        SELECT 'video' AS kind, vectors->'video' AS value
        UNION ALL
        SELECT 'text', value
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(vectors->'text') = 'array'
                THEN vectors->'text' ELSE '[]'::jsonb END
        ) AS tags(value)
    ) AS embedding
    CROSS JOIN LATERAL (
        WITH parsed AS MATERIALIZED (
            SELECT CASE WHEN jsonb_typeof(embedding.value) = 'array' THEN
                CASE WHEN jsonb_array_length(embedding.value) = 768
                    AND NOT (embedding.value @? 'strict $[*] ? (
                        @.type() != "number" || @ > 1.7976931348623157e308 || @ < -1.7976931348623157e308
                        || (@ != 0 && @ < 5e-324 && @ > -5e-324)
                    )')
                    THEN ARRAY(SELECT value::double precision
                        FROM jsonb_array_elements(embedding.value) AS elements(value))
                END
            END AS value
        )
        SELECT LEAST(1.0, GREATEST(-1.0,
            SUM(scaled.value * CASE WHEN ABS(query.value[components.position::integer]) < 1e-150
                THEN 0 ELSE query.value[components.position::integer] END)
                / NULLIF(SQRT(SUM(scaled.value * scaled.value)), 0)
        )) AS score
        FROM parsed
        CROSS JOIN LATERAL (
            SELECT MAX(ABS(value)) AS maximum FROM unnest(parsed.value) AS values(value)
        ) AS scale
        CROSS JOIN LATERAL unnest(parsed.value) WITH ORDINALITY AS components(value, position)
        CROSS JOIN LATERAL (
            -- Treat tiny relative components as zero to avoid float underflow.
            SELECT CASE WHEN components.value = 0 THEN 0
                WHEN (ABS(components.value) < 1e-150 OR scale.maximum > 1e150)
                    AND LN(ABS(components.value)) - LN(scale.maximum) < LN(1e-150::double precision)
                    THEN 0
                ELSE components.value / NULLIF(scale.maximum, 0)
            END AS value
        ) AS scaled
        HAVING COUNT(*) = 768 AND MAX(scale.maximum) > 0
    ) AS similarity
    WHERE videos.indexed
    GROUP BY videos.hash
    ORDER BY score DESC, videos.hash
    LIMIT %s
)
SELECT ranked.hash AS id, videos.metadata, ranked.score, ranked.video_score, ranked.tag_score
FROM ranked JOIN videos USING (hash)
ORDER BY ranked.score DESC, ranked.hash;
