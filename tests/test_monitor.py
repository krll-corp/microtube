import unittest

from support import client, request


class MonitorTests(unittest.TestCase):
    def test_cluster_routes(self):
        opener = client()
        for name in ("monitor", "main", "auth-ui", "upload-ui", "auth-api",
                     "video-api", "upload-api", "text-api", "ai-video", "ai-text"):
            with self.subTest(service=name):
                body, _ = request(opener, "monitor", f"/checks/{name}")
                self.assertTrue(body)

    def test_main_serves_shared_styles(self):
        body, headers = request(client(), "main", "/shared/base.css")
        self.assertEqual(headers.get_content_type(), "text/css")
        self.assertIn(b"@font-face", body)
