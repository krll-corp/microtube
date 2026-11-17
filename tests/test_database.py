import unittest

from support import compose


class DatabaseTests(unittest.TestCase):
    def query(self, database, sql):
        result = compose(
            "exec", "-T", f"db-{database}", "psql", "-XqAt", "-v", "ON_ERROR_STOP=1",
            "-U", "ci", "-d", database,
            input=f"BEGIN;\n{sql}\nROLLBACK;\n", text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_users_store_one_password_hash_per_login(self):
        rows = self.query("users", """
            INSERT INTO users VALUES ('fixture-user', 'fixture-password');
            INSERT INTO users VALUES ('fixture-user', 'different')
                ON CONFLICT (login_hash) DO NOTHING;
            SELECT password_hash FROM users WHERE login_hash = 'fixture-user';
        """)
        self.assertEqual(rows, ["fixture-password"])

    def test_video_keeps_metadata_and_initial_state(self):
        rows = self.query("videos", """
            INSERT INTO videos (hash, metadata)
                VALUES ('dbtest01', '{"title":"Fixture","duration_seconds":2}');
            SELECT metadata->>'title', metadata->>'duration_seconds',
                   indexed, processing_now, vector IS NULL
                FROM videos WHERE hash = 'dbtest01';
        """)
        self.assertEqual(rows, ["Fixture|2|f|f|t"])

    def test_tags_reuse_the_same_identity(self):
        rows = self.query("videos", """
            INSERT INTO tags (tag) VALUES ('fixture-tag');
            INSERT INTO tags (tag) VALUES ('fixture-tag')
                ON CONFLICT (tag) DO NOTHING;
            SELECT count(tag_id) FROM tags WHERE tag = 'fixture-tag';
        """)
        self.assertEqual(rows, ["1"])

    def test_pgvector_orders_by_cosine_distance(self):
        rows = self.query("videos", """
            INSERT INTO videos (hash, vector) VALUES
                ('dbtest01', array_prepend(1::real, array_fill(0::real, ARRAY[767]))::vector),
                ('dbtest02', (ARRAY[0::real, 1::real] || array_fill(0::real, ARRAY[766]))::vector);
            SELECT hash, vector_dims(vector) FROM videos
                WHERE hash IN ('dbtest01', 'dbtest02')
                ORDER BY vector <=> (SELECT vector FROM videos WHERE hash = 'dbtest01');
        """)
        self.assertEqual(rows, ["dbtest01|768", "dbtest02|768"])

    def test_watch_history_is_unique_and_follows_video_deletion(self):
        rows = self.query("videos", """
            INSERT INTO videos (hash) VALUES ('dbtest01');
            INSERT INTO watch_history (login_hash, video_id)
                VALUES ('fixture-user', 'dbtest01'), ('fixture-user', 'dbtest01')
                ON CONFLICT (login_hash, video_id) DO NOTHING;
            SELECT count(*) FROM watch_history WHERE video_id = 'dbtest01';
            DELETE FROM videos WHERE hash = 'dbtest01';
            SELECT count(*) FROM watch_history WHERE video_id = 'dbtest01';
        """)
        self.assertEqual(rows, ["1", "0"])
