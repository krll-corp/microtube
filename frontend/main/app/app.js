(() => {
    const app = document.getElementById("app-main");
    const searchForm = document.getElementById("search-form");
    const searchInput = document.getElementById("global-search");
    const serviceUrl = port => `${location.protocol}//${location.hostname}:${port}/`;
    document.getElementById("upload-link").href = serviceUrl(8082);
    document.getElementById("account-link").href = serviceUrl(8083);
    document.getElementById("status-link").href = serviceUrl(8081);

    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
    let navigation = 0;
    let catalogObserver;

    function card(video) {
        const id = encodeURIComponent(video.id);
        return `<a class="video-card" href="/?video=${id}">
            <div class="thumbnail">
                <img src="/api/video/thumbnail?id=${id}" alt="" loading="lazy" decoding="async">
                <span hidden>Preview unavailable</span>
                <span class="duration" aria-label="Duration unavailable">--:--</span></div>
            <h3>${escapeHtml(video.title || "Video on MicroTube")}</h3></a>`;
    }

    function renderHome(params, version) {
        const query = params.get("search") || "";
        const normalized = query.trim().toLocaleLowerCase("en");
        searchInput.value = query;
        document.title = normalized ? `Filter: ${query} — MicroTube` : "MicroTube";
        app.innerHTML = `<nav class="category-bar" aria-label="Feed">
            <a href="/" aria-current="page">Home</a></nav>
            ${normalized ? `<h1 class="search-heading">Titles matching “${escapeHtml(query)}”</h1>` : ""}
            <div class="video-grid"></div>
            <p class="catalog-status" role="status">Loading videos...</p>`;
        const grid = app.querySelector(".video-grid");
        const status = app.querySelector(".catalog-status");
        let cursor = {};
        let loading = false;
        let finished = false;
        let visible = 0;
        const observer = new IntersectionObserver(entries => {
            if (entries.some(entry => entry.isIntersecting)) loadNext();
        }, {rootMargin: "300px"});
        catalogObserver = observer;

        async function loadNext() {
            if (loading || finished || version !== navigation) return;
            loading = true;
            observer.unobserve(status);
            status.textContent = "Loading videos...";
            try {
                const target = new URLSearchParams({limit: "24", ...cursor});
                const response = await fetch(`/api/video/feed?${target}`);
                if (!response.ok) throw new Error();
                const page = await response.json();
                if (version !== navigation) return;
                const results = page.items.filter(video =>
                    (video.title || "").toLocaleLowerCase("en").includes(normalized));
                grid.insertAdjacentHTML("beforeend", results.map(card).join(""));
                visible += results.length;
                cursor = page.next;
                finished = cursor === null;
                status.textContent = finished && visible === 0
                    ? (normalized ? "No matching titles found" : "No videos yet") : "";
                status.hidden = finished && visible > 0;
            } catch {
                if (version !== navigation) return;
                status.textContent = "Could not load videos. Reload the page to retry.";
                status.setAttribute("role", "alert");
                finished = true;
            } finally {
                loading = false;
                if (version === navigation && !finished) observer.observe(status);
            }
        }

        loadNext();
    }

    async function renderWatch(params, version) {
        const id = params.get("video");
        if (!/^[A-Za-z0-9_-]{8}$/.test(id || "")) {
            document.title = "Video not found — MicroTube";
            app.innerHTML = '<div class="empty-state"><h1>Video not found</h1><a href="/">Back to catalog</a></div>';
            return;
        }
        let details;
        app.innerHTML = '<p class="notice" role="status">Loading video...</p>';
        try {
            const response = await fetch(`/api/video/metadata?id=${encodeURIComponent(id)}`);
            if (!response.ok) {
                const error = new Error();
                error.status = response.status;
                throw error;
            }
            details = await response.json();
        } catch (error) {
            if (version !== navigation) return;
            const message = error.status === 404 ? "Video not found" : "Could not load video details";
            document.title = `${message} — MicroTube`;
            app.innerHTML = `<div class="empty-state" role="alert"><h1>${message}</h1>
                <a href="/">Back to catalog</a></div>`;
            return;
        }
        if (version !== navigation) return;
        const title = details.title || "Video on MicroTube";
        const description = details.description || "";
        const tags = details.tags || [];
        document.title = `${title} — MicroTube`;
        app.innerHTML = `<div class="watch-layout"><section class="video-detail">
            <div class="player-frame"><video controls playsinline preload="metadata" aria-label="Video player"></video></div>
            <h1>${escapeHtml(title)}</h1>
            <nav class="tags" aria-label="Tags">${tags.map(tag => `<a href="/?search=${encodeURIComponent(tag)}">#${escapeHtml(tag)}</a>`).join("")}</nav>
            ${description ? `<p class="description">${escapeHtml(description)}</p>` : ""}
            <p class="notice" id="video-error" role="status" hidden>Could not play the video. Check its ID and the service availability.</p>
            <a class="back-link" href="/">← Back to catalog</a>
        </section><aside class="related"><h2>Related videos</h2>
            <p class="related-note">Recommendations are not available yet.</p>
        </aside></div>`;
        const player = app.querySelector("video");
        const videoError = app.querySelector("#video-error");
        player.src = `/api/video/videos?id=${encodeURIComponent(id)}`;
        player.addEventListener("error", () => { videoError.hidden = false; });
        let nextReportAt = 0;
        player.addEventListener("timeupdate", async () => {
            if (Date.now() < nextReportAt || !Number.isFinite(player.duration) || player.duration <= 0) return;
            const played = player.played;
            let seconds = 0;
            for (let i = 0; i < played.length; i++) seconds += played.end(i) - played.start(i);
            if (seconds < Math.min(30, player.duration / 2)) return;
            nextReportAt = Infinity;
            try {
                const response = await fetch(`/api/video/history?id=${encodeURIComponent(id)}`, {
                    method: "POST", keepalive: true
                });
                if (response.status < 500) return;
            } catch {}
            nextReportAt = Date.now() + 5000;
        });
    }

    function route() {
        catalogObserver?.disconnect();
        const version = ++navigation;
        const params = new URLSearchParams(location.search);
        if (params.has("video")) renderWatch(params, version);
        else renderHome(params, version);
    }

    searchForm.addEventListener("submit", event => {
        event.preventDefault();
        const query = searchInput.value.trim();
        const target = query ? '/?search=' + encodeURIComponent(query) : '/';
        history.pushState({}, "", target);
        route();
    });
    window.addEventListener("popstate", route);
    app.addEventListener("error", event => {
        if (event.target.matches(".thumbnail img")) {
            event.target.hidden = true;
            event.target.nextElementSibling.hidden = false;
        }
    }, true);
    route();
})();
