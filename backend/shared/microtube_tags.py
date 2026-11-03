def get_tag_ids(cursor, tags):
    ids = {}
    # Consistent lock order also handles concurrent uploads with shared tags.
    for tag in sorted(set(tags)):
        cursor.execute(
            "INSERT INTO tags (tag) VALUES (%s) "
            "ON CONFLICT (tag) DO UPDATE SET tag = EXCLUDED.tag RETURNING tag_id",
            (tag,),
        )
        ids[tag] = cursor.fetchone()[0]
    return [ids[tag] for tag in tags]
