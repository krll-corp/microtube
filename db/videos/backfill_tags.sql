BEGIN;

INSERT INTO tags (tag)
SELECT DISTINCT value
FROM videos
CROSS JOIN LATERAL jsonb_array_elements_text(metadata->'tags') AS names(value)
WHERE btrim(value) <> ''
ORDER BY value
ON CONFLICT (tag) DO NOTHING;

UPDATE videos SET metadata = jsonb_set(metadata, '{tag_ids}', (
    SELECT COALESCE(jsonb_agg(tags.tag_id ORDER BY names.position), '[]'::jsonb)
    FROM jsonb_array_elements_text(videos.metadata->'tags')
        WITH ORDINALITY AS names(value, position)
    JOIN tags ON tags.tag = names.value
));

DO $$
DECLARE
    item RECORD;
BEGIN
    FOR item IN
        SELECT tags.tag_id, videos.vectors->'text'->(names.position::integer - 1) AS value
        FROM videos
        CROSS JOIN LATERAL jsonb_array_elements_text(metadata->'tags')
            WITH ORDINALITY AS names(value, position)
        JOIN tags ON tags.tag = names.value
        WHERE tags.vector IS NULL
        ORDER BY tags.tag_id, videos.hash
    LOOP
        BEGIN
            UPDATE tags SET vector = item.value::text::vector
            WHERE tag_id = item.tag_id AND vector IS NULL;
        EXCEPTION WHEN data_exception OR check_violation THEN
            RAISE WARNING 'Skipping invalid legacy vector for tag %', item.tag_id;
        END;
    END LOOP;
END $$;

-- Keep the source if any tag embedding could not be migrated.
UPDATE videos SET vectors = vectors - 'text'
WHERE vectors ? 'text' AND NOT EXISTS (
    SELECT 1
    FROM jsonb_array_elements_text(videos.metadata->'tags') AS names(value)
    LEFT JOIN tags ON tags.tag = names.value
    WHERE tags.vector IS NULL
);

COMMIT;
