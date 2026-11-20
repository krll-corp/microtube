import unittest
from hashlib import sha256
from time import monotonic, sleep
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from support import account, account_credentials, address, child_environment, compose, make_clip, upload


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch(env=child_environment())
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(color_scheme="light")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(8_000)

    def card(self, title):
        heading = self.page.get_by_role("heading", name=title, exact=True)
        return self.page.locator("a.video-card").filter(has=heading)

    def playback_details(self, video_id):
        home = address("main")
        deadline = monotonic() + 30
        while True:
            metadata = self.context.request.get(f"{home}/api/video/metadata?id={video_id}").json()
            if "playback" in metadata or monotonic() >= deadline:
                break
            sleep(0.2)
        self.assertIn("playback", metadata)
        return metadata["playback"]

    def test_registration_form_creates_account_and_opens_home(self):
        auth = address("auth")
        home = address("main") + "/"
        # The UI links to port 8080. Route that navigation to this test stack.
        self.page.route("http://127.0.0.1:8080/", lambda route: route.fulfill(
            status=302, headers={"Location": home},
        ))
        self.page.goto(auth)
        username = "browser-" + uuid4().hex
        self.page.get_by_label("Username").fill(username)
        self.page.get_by_label("Password").fill("fixture-password")
        with self.page.expect_response(auth + "/api/auth/register") as registered:
            self.page.get_by_role("button", name="Register").click()
        self.assertEqual(registered.value.status, 201)
        expect(self.page).to_have_url(home)
        session = self.context.request.get(auth + "/api/auth/me")
        self.assertEqual(session.status, 200)
        expected = sha256(sha256(username.encode()).digest()).hexdigest()
        self.assertEqual(session.json(), {"login_hash": expected})
        expect(self.page.get_by_role("link", name="Upload", exact=True)).to_be_visible()
        self.page.goto(address("upload"))
        expect(self.page.locator("#upload-form")).to_be_visible()

    def test_guest_is_redirected_from_upload_page(self):
        home = address("main")
        with self.page.expect_response(home + "/api/auth/me") as session:
            self.page.goto(home)
        self.assertEqual(session.value.status, 401)
        expect(self.page.locator("#upload-link")).to_be_hidden()
        for path in ("/", "/index.html"):
            with self.subTest(path=path):
                response = self.context.request.get(address("upload") + path, max_redirects=0)
                self.assertEqual(response.status, 302)
                self.assertEqual(response.headers["location"], "http://127.0.0.1:8083/")

    def test_upload_shows_transcode_progress_only_when_needed(self):
        auth = address("auth")
        registered = self.context.request.post(auth + "/api/auth/register", form=account_credentials(),
                                               headers={"Origin": auth})
        self.assertEqual(registered.status, 201)
        self.page.goto(address("upload"))
        transcode = self.page.locator("#transcode-wrap")
        for name, clip, mode in (
            ("direct.mp4", make_clip(2), "direct"),
            ("remux.mkv", make_clip(2, "matroska"), "remux"),
            ("transcode.avi", make_clip(2, "avi", "mpeg4"), "transcode"),
        ):
            with self.subTest(name=name):
                self.page.locator("#video-file").set_input_files({
                    "name": name, "mimeType": "application/octet-stream", "buffer": clip,
                })
                self.page.get_by_label("Video title").fill(name)
                with self.page.expect_response("**/api/upload/upload") as submitted:
                    self.page.get_by_role("button", name="Upload video").click()
                self.assertEqual(submitted.value.status, 200 if mode == "direct" else 202)
                if mode == "transcode":
                    expect(transcode).to_be_visible()
                    expect(self.page.locator("#progress-bar")).to_have_attribute("value", "100")
                    expect(transcode.locator("progress")).to_have_attribute("value", "100")
                else:
                    expect(transcode).to_be_hidden()
                expect(self.page.get_by_role("link", name="Watch video")).to_be_visible()

    def test_hd_upload_provides_selectable_playback(self):
        clip = compose(
            "exec", "-T", "backend-upload", "ffmpeg", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=s=1920x1080:r=12", "-f", "lavfi", "-i", "sine",
            "-t", "3", "-c:v", "libx264", "-threads:v", "2", "-c:a", "aac",
            "-movflags", "+empty_moov+frag_keyframe", "-f", "mp4", "pipe:1", capture_output=True,
        ).stdout
        auth = address("auth")
        registered = self.context.request.post(auth + "/api/auth/register", form=account_credentials(),
                                               headers={"Origin": auth})
        self.assertEqual(registered.status, 201)
        self.page.goto(address("upload"))
        self.page.locator("#video-file").set_input_files({"name": "hd.mp4", "mimeType": "video/mp4", "buffer": clip})
        self.page.get_by_label("Video title").fill("HD playback fixture")
        with self.page.expect_response("**/api/upload/upload") as uploaded:
            self.page.get_by_role("button", name="Upload video").click()
        self.assertEqual(uploaded.value.status, 200)
        video_id = uploaded.value.json()["id"]
        home = address("main")
        playback = self.playback_details(video_id)
        self.assertEqual([variant["height"] for variant in playback["variants"]], [720, 1080])
        manifest = self.context.request.get(home + playback["master"])
        self.assertEqual(manifest.status, 200)
        self.assertIn("application/vnd.apple.mpegurl", manifest.headers["content-type"])

        self.page.goto(f"{home}/?video={video_id}")
        quality = self.page.get_by_role("combobox", name="Quality")
        expect(quality.locator("option")).to_have_text(["Auto", "720p", "1080p"])
        quality.select_option(label="1080p")
        self.page.locator("video").evaluate("video => { video.muted = true; video.play().catch(() => {}); }")
        self.page.wait_for_function(
            "document.querySelector('video').videoHeight === 1080 && document.querySelector('video').currentTime > 0",
        )

    def test_single_hls_variant_has_an_init_file(self):
        clip = compose(
            "exec", "-T", "backend-upload", "ffmpeg", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=s=1280x720:r=8", "-t", "1",
            "-c:v", "libx264", "-threads:v", "2", "-movflags", "+empty_moov+frag_keyframe",
            "-f", "mp4", "pipe:1", capture_output=True,
        ).stdout
        video_id = upload(account(), "720p playlist fixture", clip)["id"]
        variant, = self.playback_details(video_id)["variants"]
        playlist = address("main") + variant["url"]
        response = self.context.request.get(playlist)
        self.assertEqual(response.status, 200)
        self.assertIn('#EXT-X-MAP:URI="720-init.mp4"', response.text())
        init = self.context.request.get(playlist.rsplit("/", 1)[0] + "/720-init.mp4")
        self.assertEqual(init.status, 200)
        self.assertEqual(init.body()[4:8], b"ftyp")

    def test_catalog_card_opens_watch_page(self):
        title = "Browser fixture"
        video = upload(account(), title, make_clip(2))
        self.page.goto(address("main"))
        card = self.card(title)
        expect(card.locator("time")).to_have_text("0:02")
        card.click()
        expect(self.page.get_by_role("heading", name=title, level=1)).to_be_visible()
        expect(self.page.locator("video")).to_have_attribute("src", f"/api/video/videos?id={video['id']}")

    def test_guest_search_shows_sign_in_link(self):
        self.page.goto(address("main"))
        search = self.page.get_by_role("searchbox", name="Search videos")
        search.fill("forest")
        search.press("Enter")
        status = self.page.locator(".catalog-status")
        expect(status).to_have_text("Sign in to search videos.")
        expect(status.get_by_role("link", name="Sign in")).to_be_visible()
