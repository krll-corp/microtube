import io
import json
import runpy
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from support import account, client, make_clip, request, upload


class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        creator = account()
        cls.clip = make_clip(2)
        cls.video = upload(creator, "Range test clip", cls.clip, tags="second first")
        upload(creator, "Catalog pagination clip", cls.clip)
        cls.url = f"/api/video/videos?id={cls.video['id']}"

    def setUp(self):
        self.guest = client()

    def get(self, path, **options):
        return request(self.guest, "main", path, **options)

    def test_public_playback_and_head(self):
        body, headers = self.get(self.url)
        self.assertEqual(body, self.clip)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        body, headers = self.get(self.url, method="HEAD")
        self.assertEqual(body, b"")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(int(headers["Content-Length"]), len(self.clip))

    def test_closed_and_suffix_ranges(self):
        size = len(self.clip)
        for spec, start, end in (("7-21", 7, 22), ("-25", size - 25, size)):
            with self.subTest(spec=spec):
                body, headers = self.get(self.url, headers={"Range": f"bytes={spec}"}, status=206)
                self.assertEqual(body, self.clip[start:end])
                self.assertEqual(headers["Content-Range"], f"bytes {start}-{end - 1}/{size}")

    def test_multipart_ranges(self):
        body, headers = self.get(self.url, headers={"Range": "bytes=2-8,31-37"}, status=206)
        message = f"Content-Type: {headers['Content-Type']}\r\n\r\n".encode() + body
        parts = list(BytesParser(policy=policy.default).parsebytes(message).iter_parts())
        self.assertEqual([part.get_payload(decode=True) for part in parts],
                         [self.clip[2:9], self.clip[31:38]])
        size = len(self.clip)
        self.assertEqual([part["Content-Range"] for part in parts],
                         [f"bytes 2-8/{size}", f"bytes 31-37/{size}"])

    def test_range_past_end_reports_file_size(self):
        size = len(self.clip)
        _, headers = self.get(self.url, headers={"Range": f"bytes={size}-"}, status=416)
        self.assertEqual(headers["Content-Range"], f"bytes */{size}")

    def test_metadata_and_conditional_request(self):
        path = f"/api/video/metadata?id={self.video['id']}"
        body, headers = self.get(path)
        metadata = json.loads(body)
        self.assertEqual(metadata["title"], "Range test clip")
        self.assertEqual(metadata["duration_seconds"], 2)
        self.assertEqual(metadata["tags"], ["second", "first"])
        body, _ = self.get(path, headers={"If-None-Match": headers["ETag"]}, status=304)
        self.assertEqual(body, b"")

    def test_upload_provides_a_jpeg_thumbnail(self):
        body, headers = self.get(f"/api/video/thumbnail?id={self.video['id']}")
        self.assertEqual(headers.get_content_type(), "image/jpeg")
        self.assertTrue(body.startswith(b"\xff\xd8") and body.endswith(b"\xff\xd9"))

    def test_catalog_continues_after_first_card(self):
        path = "/api/video/catalog?limit="
        expected = json.loads(self.get(path + "2")[0])["items"]
        self.assertEqual(len(expected), 2)
        path += "1"
        page = json.loads(self.get(path)[0])
        self.assertEqual(page["items"], expected[:1])
        first_id = expected[0]["id"]
        self.assertEqual(page["next_after"], first_id)
        second = json.loads(self.get(f"{path}&after={first_id}")[0])
        self.assertEqual(second["items"], expected[1:])


class StorageTests(unittest.TestCase):
    def test_seekable_reads_span_multiple_storage_parts(self):
        module = Path(__file__).resolve().parents[1] / "backend/shared/microtube_storage.py"
        storage = runpy.run_path(str(module))
        save = storage["save_video"]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(save.__globals__, VIDEO_STORAGE_DIR=Path(directory).resolve(), CHUNK_SIZE=4):
                data = b"abcdefghij"
                self.assertEqual(save("range001", io.BytesIO(data)), len(data))
                with storage["open_video"](storage["find_video"]("range001")) as source:
                    source.seek(3)
                    self.assertEqual(source.read(4), b"defg")
                    source.seek(-2, io.SEEK_END)
                    self.assertEqual(source.read(), b"ij")
