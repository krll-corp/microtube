import json
import unittest
from urllib.parse import urlencode
from uuid import uuid4

from support import account, client, compose, make_clip, request, upload


INDEX_VIDEOS = """
import sys
from main import run, watcher

for video in watcher():
    if video["hash"] in sys.argv[1:]:
        run(video)
"""

SEED_INDEXED_VIDEOS = """
import sys
from contextlib import closing
from main import connect

vector = "[0,0,1," + ",".join(["0"] * 765) + "]"
with closing(connect()) as connection, connection, connection.cursor() as cursor:
    cursor.executemany(
        "INSERT INTO videos (hash, vector, indexed) VALUES (%s, %s::vector, TRUE)",
        [(video_id, vector) for video_id in sys.argv[1:]],
    )
"""


def worker(code, *args):
    compose("exec", "-T", "backend-indexing", "python", "-c", code, *args)


def get_json(opener, path):
    body, headers = request(opener, "main", path)
    return json.loads(body), headers


class DiscoveryTests(unittest.TestCase):
    def test_search_requires_a_session(self):
        request(client(), "main", "/api/search?req=forest", status=401)

    def test_indexing_exposes_tag_matches_and_related_videos(self):
        viewer = account()
        clip = make_clip(1)
        forest = upload(viewer, "Forest", clip, tags="forest")["id"]
        ocean = upload(viewer, "Ocean", clip, tags="ocean")["id"]
        pending = upload(viewer, "Pending", clip, tags="forest")["id"]

        worker(INDEX_VIDEOS, forest, ocean)
        results, _ = get_json(viewer, "/api/search?req=forest&limit=100")
        matches = [row for row in results if row["id"] in {forest, ocean, pending}]
        self.assertEqual([row["id"] for row in matches], [forest, ocean])
        self.assertGreater(matches[0]["tag_score"], matches[1]["tag_score"])
        self.assertEqual(matches[0]["video_score"], matches[1]["video_score"])

        related, _ = get_json(viewer, f"/api/video/related?id={forest}")
        ids = {card["id"] for card in related["items"]}
        self.assertIn(ocean, ids)
        self.assertTrue(ids.isdisjoint({forest, pending}))

    def test_personal_feed_uses_distinct_watches_and_private_cursor(self):
        watched = [uuid4().hex[:8] for _ in range(25)]
        candidates = sorted([uuid4().hex[:8] for _ in range(2)])
        worker(SEED_INDEXED_VIDEOS, *watched, *candidates)
        viewer = account()
        history = "/api/video/history?id="
        feed = "/api/video/feed?limit=1"

        request(client(), "main", history + watched[0], method="POST", status=401)
        for video_id in [*watched[:-1], watched[0]]:
            request(viewer, "main", history + video_id, method="POST", status=204)
        shuffled, _ = get_json(viewer, feed)
        self.assertIn("seed", shuffled["next"])

        request(viewer, "main", history + watched[-1], method="POST", status=204)
        first, headers = get_json(viewer, feed)
        self.assertEqual(headers.get("Cache-Control"), "private, no-store")
        self.assertEqual([card["id"] for card in first["items"]], candidates[:1])
        self.assertIn("pool", first["next"])
        next_page = f"{feed}&{urlencode(first['next'])}"
        second, _ = get_json(viewer, next_page)
        self.assertEqual([card["id"] for card in second["items"]], candidates[1:])
        request(account(), "main", next_page, status=409)
