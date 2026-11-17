import os
import subprocess
import unittest
from hashlib import sha256
from tempfile import TemporaryDirectory
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from support import account, address, make_clip, upload


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        env = os.environ.copy()
        env.pop("COPILOT_GITHUB_TOKEN", None)
        cls.browser = playwright.chromium.launch(env=env)
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(color_scheme="light")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(8_000)

    def card(self, title):
        heading = self.page.get_by_role("heading", name=title, exact=True)
        return self.page.locator("a.video-card").filter(has=heading)

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

    def click_with_copilot(self, goal, controls):
        actions = []
        for key, control in controls.items():
            expect(control).to_be_visible()
            label = control.get_attribute("aria-label") or " ".join(control.inner_text().split())
            actions.append(f"{key}: {label}")
        prompt = f"{goal}\nChoose one action and reply with only its key.\n" + "\n".join(actions)

        # Playwright executes the choice. Copilot gets labels and no executable tools.
        with TemporaryDirectory(prefix="microtube-copilot-") as directory:
            result = subprocess.run(
                ["copilot", "-s", "--disable-builtin-mcps", "--disable-mcp-server=computer-use",
                 "--no-custom-instructions", "--no-ask-user", "--available-tools=ask_user", "-p", prompt],
                cwd=directory, capture_output=True, text=True, timeout=90,
            )
        self.assertEqual(result.returncode, 0, "Copilot CLI failed. Check Copilot access for the repository owner.")
        key = result.stdout.strip()
        self.assertTrue(key in controls, "Copilot must choose a listed action")
        controls[key].click()

    @unittest.skipUnless(os.getenv("COPILOT_GITHUB_TOKEN"), "Copilot check is opt-in")
    def test_copilot_opens_the_requested_video_and_chooses_dark_mode(self):
        opener = account()
        clip = make_clip(1)
        upload(opener, "Ocean waves", clip)
        upload(opener, "Forest trail", clip)
        self.page.goto(address("main"))
        self.click_with_copilot("Open the video about walking among trees.", {
            "A": self.card("Ocean waves"),
            "B": self.card("Forest trail"),
        })
        expect(self.page.get_by_role("heading", name="Forest trail", level=1)).to_be_visible()
        self.click_with_copilot("Switch to the dark theme.", {
            "A": self.page.get_by_role("button", name="Dark theme"),
            "B": self.page.get_by_role("button", name="Use system theme"),
        })
        expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
