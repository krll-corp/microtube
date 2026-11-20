import asyncio
import os
import re
import shutil
import unittest
from base64 import b64encode
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from copilot import CopilotClient, StdioRuntimeConnection
from copilot.generated.rpc import PermissionDecisionReject
from copilot.session import ModelCapabilitiesOverride, ModelSupportsOverride
from playwright.async_api import async_playwright, expect

from fixture_videos import make_visual_clip, seed_videos
from support import PROJECT, ROOT, account, account_credentials, address, child_environment


def provider_settings():
    keys = ("AI_UI_BASE_URL", "AI_UI_MODEL", "AI_UI_API_KEY")
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        raise ValueError("Set " + ", ".join(missing))
    base_url, model, api_key = (os.environ[key] for key in keys)
    url = urlsplit(base_url)
    local = url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
    if not url.hostname or url.username or url.password or (url.scheme != "https" and not local):
        raise ValueError("AI_UI_BASE_URL must be an HTTPS endpoint or local HTTP endpoint")
    return model, {
        "type": "openai", "wire_api": "completions",
        "base_url": base_url, "api_key": api_key,
    }


class VisualTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.videos = seed_videos()

    async def asyncSetUp(self):
        self.case = self._testMethodName.removeprefix("test_").replace("_", "-")
        self.artifacts = ROOT / "output" / "playwright" / PROJECT / self.case
        self.artifacts.mkdir(parents=True)
        self.shots = []
        self.review_shots = []
        self.actions = []
        self.model, self.provider = provider_settings()

        playwright = await self.enterAsyncContext(async_playwright())
        browser = await playwright.chromium.launch(env=child_environment())
        self.addAsyncCleanup(browser.close)
        self.context = await browser.new_context(color_scheme="light")
        self.page = await self.context.new_page()
        self.page.set_default_timeout(8_000)
        await self.page.route(re.compile(r"^http://127\.0\.0\.1:808[0-3]/"), self.redirect_to_test_port)

        directory = self.enterContext(TemporaryDirectory(prefix="microtube-byok-"))
        self.copilot = await self.enterAsyncContext(CopilotClient(
            connection=StdioRuntimeConnection(path=shutil.which("copilot")),
            use_logged_in_user=False, mode="empty", env=child_environment(),
            base_directory=directory, working_directory=directory, log_level="error",
        ))
        self.session = await self.enterAsyncContext(await self.new_session())

    async def redirect_to_test_port(self, route):
        # Keep links to the UI's default ports inside this Compose project.
        url = urlsplit(route.request.url)
        service = {8080: "main", 8081: "monitor", 8082: "upload", 8083: "auth"}[url.port]
        target = address(service) + url.path
        if url.query:
            target += "?" + url.query
        await route.fulfill(status=302, headers={"Location": target})

    async def new_session(self, max_output_tokens=600):
        return await self.copilot.create_session(
            model=self.model, provider={**self.provider, "max_output_tokens": max_output_tokens},
            available_tools=[],
            model_capabilities=ModelCapabilitiesOverride(supports=ModelSupportsOverride(vision=True)),
            on_permission_request=lambda req, inv: PermissionDecisionReject(),
        )

    async def ask(self, session, prompt, *shots):
        attachments = [
            {"type": "blob", "data": b64encode(shot.read_bytes()).decode(),
             "mimeType": "image/png", "displayName": shot.name}
            for shot in shots
        ]
        reply = await session.send_and_wait(prompt, attachments=attachments, timeout=60)
        if reply is None or not getattr(reply.data, "content", None):
            self.fail("The BYOK model returned no text")
        return reply.data.content.strip()

    async def screenshot(self, checkpoint=None):
        suffix = checkpoint or ("initial" if not self.shots else "after")
        path = self.artifacts / f"{len(self.shots):02}-{suffix}.png"
        await self.page.wait_for_function("""() => [...document.images].filter(image => {
            const bounds = image.getBoundingClientRect();
            return bounds.width && bounds.height && bounds.top < innerHeight && bounds.bottom > 0;
        }).every(image => image.complete && image.naturalWidth > 0)""")
        await self.page.screenshot(path=path, animations="disabled", mask=[self.page.locator("#password")])
        self.shots.append(path)
        if checkpoint:
            self.review_shots.append(path)

    async def step(self, goal, actions, verify, *, checkpoint=None):
        if not self.shots:
            await self.screenshot()
        choices = dict(zip("AB", actions, strict=True))
        labels = "\n".join(f"{key} — {label}" for key, (label, _) in choices.items())
        choice = await self.ask(
            self.session, f"Goal — {goal}\nUse the current screenshot. Reply with only A or B.\n{labels}",
            self.shots[-1],
        )
        self.assertTrue(choice in choices, "The model must choose a listed action")
        label, action = choices[choice]
        self.actions.append(label)
        try:
            await action()
            await verify()
        finally:
            await self.screenshot(checkpoint)

    async def asyncTearDown(self):
        if len(self.shots) < 2:
            return
        trace = "\n".join(f"- {action}" for action in self.actions)
        shots = list(dict.fromkeys([self.shots[0], *self.review_shots, self.shots[-1]]))
        frames = "\n".join(f"- {shot.name}" for shot in shots)
        async with await self.new_session(max_output_tokens=2048) as reviewer:
            notes = await self.ask(
                reviewer,
                f"Review the MicroTube {self.case} flow for UI and UX issues. The attached screenshots are listed "
                "in chronological order. Magenta rectangles over password fields are screenshot masks. "
                "Use the action trace for context and quote only clearly legible text. Give at most three "
                "observations. Name the screenshot and explain the impact of each issue, or say you found none."
                f"\nScreenshots\n{frames}\nActions taken\n{trace}",
                *shots,
            )
        (self.artifacts / "review.md").write_text(
            f"# {self.case}\n\nActions\n\n{trace}\n\nScreenshots\n\n{frames}\n\n{notes}\n", encoding="utf-8",
        )

    def link(self, name):
        return self.page.get_by_role("link", name=name, exact=True)

    def button(self, name):
        return self.page.get_by_role("button", name=name, exact=True)

    def catalog_card(self, title):
        heading = self.page.get_by_role("heading", name=title, exact=True)
        return self.page.locator(".video-grid .video-card").filter(has=heading)

    async def expect_home(self):
        await expect(self.page).to_have_url(address("main") + "/")
        await expect(self.catalog_card("Forest trail")).to_be_visible()

    async def open_catalog(self):
        await self.page.goto(address("main"))
        await self.expect_home()

    async def expect_watch_page(self, title):
        await expect(self.page.get_by_role("heading", name=title, level=1, exact=True)).to_be_visible()
        await expect(self.page.locator("video")).to_have_js_property("videoWidth", 640)

    async def expect_forest_first(self):
        await expect(self.page.locator(".search-heading")).to_have_text('Search results for “forest”')
        await expect(self.page.locator(".video-grid .video-card h3").first).to_have_text("Forest trail")

    async def expect_playing(self):
        await self.page.wait_for_function("""() => {
            const player = document.querySelector("video");
            return player && !player.paused && player.currentTime > 0.25;
        }""")

    async def test_registration(self):
        auth = address("auth")
        await self.page.goto(auth)
        username = self.page.get_by_label("Username")
        password = self.page.get_by_label("Password")

        async def fill_form():
            await username.fill("fixture-visual-user")
            await password.fill("fixture-visual-password")

        await self.step("Prepare a new account", [
            ("Fill the Username and Password fields", fill_form),
            ("Open Home", self.link("Home").click),
        ], lambda: expect(username).to_have_value("fixture-visual-user"))

        async def signed_in():
            await self.expect_home()
            response = await self.context.request.get(auth + "/api/auth/me")
            self.assertEqual(response.status, 200)
            await expect(self.link("Upload")).to_be_visible()

        await self.step("Register the new account", [
            ("Click Register", self.button("Register").click),
            ("Click Sign in", self.button("Sign in").click),
        ], signed_in)

        await self.step("Open the upload form", [
            ("Click Upload", self.link("Upload").click),
            ("Open Account", self.link("Account").click),
        ], lambda: expect(self.page.locator("#upload-form")).to_be_visible())

        async def choose_file(name, content_type, buffer):
            async with self.page.expect_file_chooser() as selection:
                await self.button("Choose MP4").click()
            chooser = await selection.value
            await chooser.set_files({"name": name, "mimeType": content_type, "buffer": buffer})

        async def choose_text():
            await choose_file("notes.txt", "text/plain", b"Test file")

        feedback = self.page.locator("#feedback")

        async def text_file_rejected():
            await expect(feedback).to_have_text("Please choose a video file with the .mp4 extension.")
            await feedback.scroll_into_view_if_needed()

        await self.step("Check what happens when you select a text file", [
            ("Choose notes.txt", choose_text),
            ("Open Home", self.link("Home").click),
        ], text_file_rejected, checkpoint="invalid-file")

        async def choose_mp4():
            clip = await asyncio.to_thread(make_visual_clip, 4, "5b4b68")
            await choose_file("test.mp4", "video/mp4", clip)

        async def preview_ready():
            preview = self.page.locator("#video-preview")
            await expect(preview).to_be_visible()
            await expect(preview).to_have_js_property("videoWidth", 640)
            await expect(feedback).to_be_hidden()
            await preview.scroll_into_view_if_needed()

        await self.step("Choose a playable MP4 after the file error", [
            ("Choose notes.txt again", choose_text),
            ("Scroll to Choose MP4 and select test.mp4", choose_mp4),
        ], preview_ready)

        title = "CI upload playback"
        title_input = self.page.get_by_label("Video title")

        async def fill_metadata():
            await title_input.fill(title)
            await self.page.get_by_label("Tags", exact=True).fill("ci upload")

        await self.step("Give the video a title and tags", [
            ("Fill the title and tags", fill_metadata),
            ("Open Account", self.link("Account").click),
        ], lambda: expect(title_input).to_have_value(title))

        async def publish():
            resume = asyncio.Event()

            async def hold_upload(route):
                await resume.wait()
                await route.continue_()

            await self.page.route("**/api/upload/upload", hold_upload, times=1)
            try:
                await self.button("Upload video").click()
                submit = self.page.locator("#submit-button")
                await expect(submit).to_be_disabled()
                await expect(self.page.get_by_role("progressbar")).to_be_visible()
                await submit.scroll_into_view_if_needed()
                await self.screenshot("uploading")
            finally:
                resume.set()

        async def published():
            await expect(feedback).to_contain_text("uploaded successfully")
            await self.link("Watch video").scroll_into_view_if_needed()

        await self.step("Publish the new video", [
            ("Open Home", self.link("Home").click),
            ("Click Upload video", publish),
        ], published, checkpoint="published")
        await self.step("Open the newly published video", [
            ("Click Watch video", self.link("Watch video").click),
            ("Open Home", self.link("Home").click),
        ], lambda: self.expect_watch_page(title))

    async def test_guest_search(self):
        username, password = "fixture-search-user", "fixture-search-password"
        await asyncio.to_thread(account, username, password)
        await self.open_catalog()
        search = self.page.get_by_role("searchbox", name="Search videos")
        await self.step("Enter the query forest without signing in", [
            ("Type forest in Search videos", lambda: search.fill("forest")),
            ("Open Account", self.link("Account").click),
        ], lambda: expect(search).to_have_value("forest"))
        await self.step("Submit the guest search", [
            ("Open Home", self.link("Home").click),
            ("Click the Search videos button", self.button("Search videos").click),
        ], lambda: expect(self.page.locator(".catalog-status")).to_have_text("Sign in to search videos."),
            checkpoint="sign-in-required")

        await self.step("Follow the link in the sign-in notice", [
            ("Click Sign in in the search notice", self.link("Sign in").click),
            ("Open Home", self.link("Home").click),
        ], lambda: expect(self.page.get_by_label("Username")).to_be_visible())

        async def sign_in():
            await self.page.get_by_label("Username").fill(username)
            await self.page.get_by_label("Password").fill(password)
            await self.button("Sign in").click()

        async def signed_in():
            await self.expect_home()
            await expect(self.link("Upload")).to_be_visible()

        await self.step("Sign in with the prepared test account", [
            ("Open Home", self.link("Home").click),
            ("Fill the credentials and click Sign in", sign_in),
        ], signed_in)

        async def search_again():
            await search.fill("forest")
            await self.button("Search videos").click()

        async def clear_search():
            await search.clear()
            await search.press("Enter")

        await self.step("Repeat the forest search after signing in", [
            ("Search for forest", search_again),
            ("Open Account", self.link("Account").click),
        ], self.expect_forest_first, checkpoint="results")
        await self.step("Clear the search and restore the catalog", [
            ("Open the first result", self.catalog_card("Forest trail").click),
            ("Clear the search field and press Enter", clear_search),
        ], self.expect_home)

    async def test_watch(self):
        video = self.videos["Forest trail"]
        await self.open_catalog()
        player = self.page.locator("video")
        related = self.page.locator(".related-list .video-card")

        async def player_loaded():
            await self.expect_watch_page("Forest trail")
            await expect(player).to_have_attribute("src", f"/api/video/videos?id={video['id']}")
            await expect(related).to_have_count(3)

        await self.step("Open the video about walking among trees", [
            ("Open Ocean waves", self.catalog_card("Ocean waves").click),
            ("Open Forest trail", self.catalog_card("Forest trail").click),
        ], player_loaded)

        await self.step("Start playback", [
            ("Press Space on the player to play", lambda: player.press("Space")),
            ("Open Account", self.link("Account").click),
        ], self.expect_playing, checkpoint="playing")
        await self.step("Pause the playing video", [
            ("Click Dark theme", self.button("Dark theme").click),
            ("Press Space on the player to pause", lambda: player.press("Space")),
        ], lambda: expect(player).to_have_js_property("paused", True))

        paused_at = await player.evaluate("video => video.currentTime")

        async def verify_seek():
            await self.page.wait_for_function(
                "before => document.querySelector('video').currentTime > before + 1", arg=paused_at,
            )
            await expect(player).to_have_js_property("paused", True)

        await self.step("Seek forward while the video is paused", [
            ("Press ArrowRight on the player", lambda: player.press("ArrowRight")),
            ("Press Space on the player", lambda: player.press("Space")),
        ], verify_seek, checkpoint="seeked")

        related_title = await related.first.locator("h3").inner_text()
        await self.step("Open the first related video", [
            ("Open Account", self.link("Account").click),
            (f"Open {related_title} in Related videos", related.first.click),
        ], lambda: self.expect_watch_page(related_title))
        await self.step("Return to the original Forest trail video", [
            ("Go back in the browser", self.page.go_back),
            ("Open the catalog", self.link("MicroTube — home").click),
        ], player_loaded)

    async def test_mobile(self):
        await self.page.set_viewport_size({"width": 390, "height": 844})
        await self.open_catalog()
        cards = self.page.locator(".video-grid .video-card")
        await expect(cards.nth(2)).to_be_visible()
        title = await cards.nth(2).locator("h3").inner_text()

        async def fits():
            self.assertTrue(await self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))

        async def player_above_related():
            await self.expect_watch_page(title)
            related = self.page.locator(".related")
            await expect(related.get_by_role("heading", name="Related videos")).to_be_visible()
            player_box = await self.page.locator("video").bounding_box()
            related_box = await related.bounding_box()
            self.assertGreaterEqual(related_box["y"], player_box["y"] + player_box["height"])
            await fits()

        async def dark_and_fits():
            await expect(self.page.locator("html")).to_have_attribute("data-theme", "dark")
            await fits()

        await fits()
        await self.step("Scroll to more videos in the mobile catalog", [
            ("Scroll down the catalog", lambda: self.page.mouse.wheel(0, 610)),
            ("Tap Account", self.link("Account").click),
        ], lambda: expect(cards.nth(2)).to_be_in_viewport(ratio=0.5))
        await self.step(f"Open {title} from the scrolled catalog", [
            ("Scroll up the catalog", lambda: self.page.mouse.wheel(0, -610)),
            (f"Tap {title}", cards.nth(2).click),
        ], player_above_related)
        await self.step("Turn on dark mode on the mobile watch page", [
            ("Tap Dark theme", self.button("Dark theme").click),
            ("Tap Use system theme", self.button("Use system theme").click),
        ], dark_and_fits)
        await self.step("Scroll down to see related videos below the player", [
            ("Tap Account", self.link("Account").click),
            ("Scroll down the watch page", lambda: self.page.mouse.wheel(0, 510)),
        ], lambda: expect(self.page.locator(".related-list .video-card").first).to_be_in_viewport(ratio=0.5),
            checkpoint="mobile-related")

        async def dark_catalog():
            await self.expect_home()
            await dark_and_fits()

        await self.step("Return to the catalog with dark mode enabled", [
            ("Tap Back to catalog", self.page.locator(".back-link").click),
            ("Open the first related video", self.page.locator(".related-list .video-card").first.click),
        ], dark_catalog)

    async def test_keyboard(self):
        response = await self.context.request.post(
            address("auth") + "/api/auth/register", form=account_credentials(),
        )
        self.assertEqual(response.status, 201)
        await self.open_catalog()
        keyboard = self.page.keyboard
        await keyboard.press("Tab")
        await expect(self.link("MicroTube — home")).to_be_focused()
        await keyboard.press("Tab")
        search_button = self.button("Search videos")
        await expect(search_button).to_be_focused()
        search = self.page.get_by_role("searchbox", name="Search videos")

        async def search_focused():
            await expect(search).to_be_focused()
            form = self.page.get_by_role("search")
            await expect(form).to_have_css("outline-style", "solid")
            await expect(form).to_have_css("outline-width", "2px")

        await self.step("Move focus into the search field using the keyboard", [
            ("Press Tab", lambda: keyboard.press("Tab")),
            ("Press Enter", lambda: keyboard.press("Enter")),
        ], search_focused, checkpoint="search-focus")
        await self.step("Move focus backward to the search button", [
            ("Press Tab", lambda: keyboard.press("Tab")),
            ("Press Shift+Tab", lambda: keyboard.press("Shift+Tab")),
        ], lambda: expect(search_button).to_be_focused())

        async def type_query():
            await keyboard.press("Tab")
            await keyboard.type("forest")

        await self.step("Return to the search field and type forest", [
            ("Press Tab and type forest", type_query),
            ("Press Shift+Tab", lambda: keyboard.press("Shift+Tab")),
        ], lambda: expect(search).to_have_value("forest"))
        await self.step("Submit the focused search from the keyboard", [
            ("Press Enter", lambda: keyboard.press("Enter")),
            ("Press Tab", lambda: keyboard.press("Tab")),
        ], self.expect_forest_first)

        async def tab_to(target):
            for _ in range(24):
                await keyboard.press("Tab")
                if await target.evaluate("element => document.activeElement === element"):
                    return
            self.fail("Tab navigation could not reach the requested control")

        async def open_search_result():
            await tab_to(self.catalog_card("Forest trail"))
            await keyboard.press("Enter")

        await self.step("Open the first search result using the keyboard", [
            ("Press Shift+Tab", lambda: keyboard.press("Shift+Tab")),
            ("Tab to Forest trail and press Enter", open_search_result),
        ], lambda: self.expect_watch_page("Forest trail"))

        related = self.page.locator(".related-list .video-card").first
        related_title = await related.locator("h3").inner_text()

        async def related_focused():
            await expect(related).to_be_focused()
            await related.scroll_into_view_if_needed()

        await self.step("Move keyboard focus to the first related video", [
            (f"Tab to {related_title} in Related videos", lambda: tab_to(related)),
            ("Press Shift+Tab", lambda: keyboard.press("Shift+Tab")),
        ], related_focused, checkpoint="related-focus")
        await self.step("Open the focused related video", [
            ("Press Shift+Tab", lambda: keyboard.press("Shift+Tab")),
            ("Press Enter", lambda: keyboard.press("Enter")),
        ], lambda: self.expect_watch_page(related_title))

        async def play_related():
            await tab_to(self.page.locator("video"))
            await keyboard.press("Space")

        await self.step("Start playing the related video with the keyboard", [
            ("Tab to the player and press Space", play_related),
            ("Press Shift+Tab", lambda: keyboard.press("Shift+Tab")),
        ], self.expect_playing)
