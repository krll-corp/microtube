import json
import unittest
from secrets import token_hex
from urllib.parse import urlencode

from support import account, client, make_clip, request, upload


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.opener = client()
        self.login_hash = token_hex(32)
        self.password_hash = token_hex(32)

    def auth(self, route, data=None, status=200, headers=None):
        if data is not None:
            data = urlencode(data).encode()
            headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        return request(self.opener, "auth", f"/api/auth/{route}", data=data, status=status, headers=headers)

    def register(self, status=201):
        return self.auth("register", self.credentials(), status)

    def credentials(self, password=None):
        return {"login_hash": self.login_hash, "password_hash": password or self.password_hash}

    def test_registration_sets_a_session_cookie(self):
        self.auth("me", status=401)
        _, headers = self.register()
        cookie = headers["Set-Cookie"].lower()
        self.assertIn("microtube_token=", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertEqual(json.loads(self.auth("me")[0]), {"login_hash": self.login_hash})

    def test_duplicate_registration_is_rejected(self):
        self.register()
        self.register(status=409)

    def test_register_issues_bearer_token_for_new_account(self):
        body, _ = self.register()
        token = json.loads(body)["token"]
        self.opener = client()
        body, _ = self.auth("me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(json.loads(body), {"login_hash": self.login_hash})

    def test_login_and_logout(self):
        self.register()
        self.opener = client()
        self.auth("login", self.credentials(token_hex(32)), status=401)
        body, _ = self.auth("login", self.credentials())
        token = json.loads(body)["token"]
        self.assertEqual(json.loads(self.auth("me")[0]), {"login_hash": self.login_hash})
        self.auth("logout", {})
        self.auth("me", status=401, headers={"Authorization": f"Bearer {token}"})


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clip = make_clip(2)

    def test_upload_requires_a_session(self):
        request(client(), "upload", "/api/upload/upload", data=b"", status=401)
        request(client(), "upload", "/api/upload/part?kind=video&offset=0", data=b"part",
                headers={"Idempotency-Key": token_hex(16)}, status=401)

    def test_upload_persists_owner_duration_and_tag_order(self):
        opener = account()
        body, _ = request(opener, "auth", "/api/auth/me")
        title = "Upload " + token_hex(4)
        first, second = ("tag-" + token_hex(4) for _ in range(2))
        result = upload(opener, title, self.clip, tags=f"{first}  {second} {first}")
        self.assertEqual(result["owner_hash"], json.loads(body)["login_hash"])
        self.assertEqual(result["size"], len(self.clip))
        self.assertAlmostEqual(result["duration_seconds"], 2, places=2)
        self.assertTrue(result["stored"])
        self.assertEqual(result["tag_ids"][0], result["tag_ids"][2])
        self.assertNotEqual(result["tag_ids"][0], result["tag_ids"][1])
        body, _ = request(client(), "main", f"/api/video/metadata?id={result['id']}")
        metadata = json.loads(body)
        self.assertEqual(metadata["tags"], [first, second, first])
        self.assertEqual(metadata["title"], title)
        self.assertEqual(metadata["duration_seconds"], result["duration_seconds"])

    def test_idempotency_key_is_scoped_to_owner(self):
        opener = account()
        key = token_hex(16)
        result = upload(opener, "Original upload", self.clip, tags="original", key=key)
        repeated = upload(opener, "Retried upload", self.clip, tags="retry", key=key)
        self.assertEqual(repeated, result)
        other = upload(account(), "Another owner's upload", self.clip, key=key)
        self.assertNotEqual(other["id"], result["id"])

    def test_upload_resumes_at_the_stored_offset(self):
        opener = account()
        other = account()
        key = {"Idempotency-Key": token_hex(16)}
        split = len(self.clip) // 2
        first, rest = self.clip[:split], self.clip[split:]

        def part(client, offset, data):
            body, _ = request(client, "upload", f"/api/upload/part?kind=video&offset={offset}",
                              data=data, headers=key)
            return json.loads(body)["offset"]

        def finish(client, status=200):
            data = urlencode({"title": "Resumed upload", "filename": "resumed.mp4", "size": len(self.clip)}).encode()
            body, _ = request(client, "upload", "/api/upload/upload", data=data, headers=key, status=status)
            return json.loads(body)

        self.assertEqual(part(opener, 0, first), split)
        self.assertEqual(part(opener, 0, first), split)
        self.assertEqual(part(opener, split + 1, rest), split)
        self.assertEqual(part(other, split, rest), 0)
        finish(opener, status=409)
        finish(other, status=409)
        self.assertEqual(part(opener, split, rest), len(self.clip))

        result = finish(opener)
        self.assertEqual(finish(opener), result)
        self.assertEqual(result["filename"], "resumed.mp4")
        body, _ = request(client(), "main", f"/api/video/videos?id={result['id']}")
        self.assertEqual(body, self.clip)
