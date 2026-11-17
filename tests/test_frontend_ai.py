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

from support import PROJECT, ROOT, account, address, child_environment, make_clip, upload


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
    async def asyncSetUp(self):
        self.case = self._testMethodName.removeprefix("test_").replace("_", "-")
        self.artifacts = ROOT / "output" / "playwright" / PROJECT / self.case
        self.artifacts.mkdir(parents=True)
        self.shots = []
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

    async def screenshot(self):
        suffix = "initial" if not self.shots else "after"
        path = self.artifacts / f"{len(self.shots):02}-{suffix}.png"
        await self.page.screenshot(path=path, animations="disabled", mask=[self.page.locator("#password")])
        self.shots.append(path)

    async def step(self, goal, actions, verify):
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
            await self.screenshot()

    async def asyncTearDown(self):
        if len(self.shots) < 2:
            return
        trace = "\n".join(f"- {action}" for action in self.actions)
        async with await self.new_session(max_output_tokens=2048) as reviewer:
            notes = await self.ask(
                reviewer,
                f"Review the MicroTube {self.case} flow for UI and UX issues. The first image is the initial state "
                f"and the second is the final state. Describe observable issues and their impact, or say that "
                f"you found none. Give at most three observations.\nActions taken\n{trace}",
                self.shots[0], self.shots[-1],
            )
        (self.artifacts / "review.md").write_text(f"# {self.case}\n\nActions\n\n{trace}\n\n{notes}\n", encoding="utf-8")

    def link(self, name):
        return self.page.get_by_role("link", name=name, exact=True)

    def button(self, name):
        return self.page.get_by_role("button", name=name, exact=True)

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
            await expect(self.page).to_have_url(address("main") + "/")
            response = await self.context.request.get(auth + "/api/auth/me")
            self.assertEqual(response.status, 200)

        await self.step("Register the new account", [
            ("Click Register", self.button("Register").click),
            ("Click Sign in", self.button("Sign in").click),
        ], signed_in)

    async def test_guest_search(self):
        await self.page.goto(address("main"))
        search = self.page.get_by_role("searchbox", name="Search videos")
        await self.step("Enter the query forest without signing in", [
            ("Type forest in Search videos", lambda: search.fill("forest")),
            ("Open Account", self.link("Account").click),
        ], lambda: expect(search).to_have_value("forest"))
        await self.step("Submit the guest search", [
            ("Open Home", self.link("Home").click),
            ("Click the Search videos button", self.button("Search videos").click),
        ], self.expect_sign_in)

    async def expect_sign_in(self):
        await expect(self.page.locator(".catalog-status")).to_have_text("Sign in to search videos.")

    async def test_watch(self):
        opener = account()
        clip = make_clip(1)
        upload(opener, "Ocean waves", clip)
        video = upload(opener, "Forest trail", clip)
        await self.page.goto(address("main"))

        def card(title):
            heading = self.page.get_by_role("heading", name=title, exact=True)
            return self.page.locator("a.video-card").filter(has=heading)

        async def player_loaded():
            await expect(self.page.get_by_role("heading", name="Forest trail", level=1)).to_be_visible()
            await expect(self.page.locator("video")).to_have_attribute("src", f"/api/video/videos?id={video['id']}")

        await expect(card("Forest trail")).to_be_visible()
        await self.step("Open the video about walking among trees", [
            ("Open Ocean waves", card("Ocean waves").click),
            ("Open Forest trail", card("Forest trail").click),
        ], player_loaded)
        await self.step("Switch the video page to dark mode", [
            ("Click Dark theme", self.button("Dark theme").click),
            ("Click Use system theme", self.button("Use system theme").click),
        ], lambda: expect(self.page.locator("html")).to_have_attribute("data-theme", "dark"))

    async def test_mobile(self):
        await self.page.set_viewport_size({"width": 390, "height": 844})
        await self.page.goto(address("main"))

        async def fits():
            self.assertTrue(await self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))

        async def on_account():
            await expect(self.page.get_by_role("heading", name="Sign in / register")).to_be_visible()
            await fits()

        async def on_home():
            await expect(self.page).to_have_url(address("main") + "/")
            await fits()

        await self.step("Open the account page on a phone", [
            ("Tap Upload", self.link("Upload").click),
            ("Tap Account", self.link("Account").click),
        ], on_account)
        await self.step("Return to the mobile catalog", [
            ("Tap Home", self.link("Home").click),
            ("Tap Upload", self.link("Upload").click),
        ], on_home)

    async def test_keyboard(self):
        await self.page.goto(address("main"))
        await self.page.keyboard.press("Tab")
        await expect(self.link("MicroTube — home")).to_be_focused()
        await self.page.keyboard.press("Tab")
        await expect(self.button("Search videos")).to_be_focused()
        search = self.page.get_by_role("searchbox", name="Search videos")
        await self.step("Move focus into the search field using the keyboard", [
            ("Press Tab", lambda: self.page.keyboard.press("Tab")),
            ("Press Enter", lambda: self.page.keyboard.press("Enter")),
        ], lambda: expect(search).to_be_focused())
        await self.step("Type forest without moving focus", [
            ("Press Tab", lambda: self.page.keyboard.press("Tab")),
            ("Type forest", lambda: self.page.keyboard.type("forest")),
        ], lambda: expect(search).to_have_value("forest"))
        await self.step("Submit the focused search from the keyboard", [
            ("Press Enter", lambda: self.page.keyboard.press("Enter")),
            ("Press Tab", lambda: self.page.keyboard.press("Tab")),
        ], self.expect_sign_in)
