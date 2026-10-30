(() => {
    const system = window.matchMedia("(prefers-color-scheme: dark)");
    const choices = ["system", "light", "dark"];

    function savedTheme() {
        try {
            const value = document.cookie.split(";").map(cookie => cookie.trim())
                .find(cookie => cookie.startsWith("microtube_theme="))?.split("=")[1];
            return choices.includes(value) ? value : null;
        } catch {
            return null;
        }
    }

    let preference = savedTheme() || "system";
    let localOverride = false;

    function applyTheme() {
        const dark = preference === "system" ? system.matches : preference === "dark";
        document.documentElement.dataset.theme = dark ? "dark" : "light";
        document.querySelector('meta[name="theme-color"]').content = dark ? "#151515" : "#ffffff";
        const toggle = document.getElementById("theme-toggle");
        if (toggle) {
            toggle.setAttribute("aria-pressed", String(dark));
            toggle.title = dark ? "Switch to light theme" : "Switch to dark theme";
            document.getElementById("theme-auto").setAttribute("aria-pressed", String(preference === "system"));
        }
    }

    function syncTheme() {
        if (!localOverride) preference = savedTheme() || preference;
        applyTheme();
    }

    function chooseTheme(value) {
        preference = value;
        try {
            document.cookie = `microtube_theme=${preference}; Path=/; Max-Age=31536000; SameSite=Lax`
                + (location.protocol === "https:" ? "; Secure" : "");
            localOverride = savedTheme() !== preference;
        } catch {
            // Keep the selection for this page if cookies are blocked.
            localOverride = true;
        }
        applyTheme();
    }

    applyTheme();
    system.addEventListener("change", applyTheme);
    window.addEventListener("pageshow", syncTheme);
    window.addEventListener("focus", syncTheme);
    document.addEventListener("DOMContentLoaded", () => {
        document.getElementById("theme-toggle").addEventListener("click", () => {
            chooseTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
        });
        document.getElementById("theme-auto").addEventListener("click", () => chooseTheme("system"));
        applyTheme();
    });
})();
