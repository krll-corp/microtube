(() => {
    const app = document.getElementById("app-main");
    const searchForm = document.getElementById("search-form");
    const searchInput = document.getElementById("global-search");
    const serviceUrl = port => `${location.protocol}//${location.hostname}:${port}/`;
    document.getElementById("upload-link").href = serviceUrl(8082);
    document.getElementById("account-link").href = serviceUrl(8083);
    document.getElementById("status-link").href = serviceUrl(8081);

    const videos = [
        {
            id: "demo-1", title: "Travel to the Carpathians", duration: "12:34",
            description: "Mountain trails, lakes and views of the Ukrainian Carpathians.",
            tags: ["nature", "mountains", "travel"], category: "Travel",
            crop: [39, 253, 475, 287]
        },
        {
            id: "demo-2", title: "Python Basics", duration: "08:21",
            description: "First steps in Python: variables and simple code examples.",
            tags: ["technology", "python", "learning"], category: "Technology",
            crop: [538, 253, 461, 287]
        },
        {
            id: "demo-3", title: "City at Dusk", duration: "10:17",
            description: "Evening light and the streets of an old city.",
            tags: ["city", "travel"], category: "Travel",
            crop: [1023, 253, 475, 287]
        },
        {
            id: "demo-4", title: "How Space Works", duration: "15:06",
            description: "A short journey to the stars and an introduction to space.",
            tags: ["space", "science", "education"], category: "Learning",
            crop: [39, 607, 475, 283]
        },
        {
            id: "demo-5", title: "Light and Framing", duration: "09:48",
            description: "How to notice light and choose a camera angle.",
            tags: ["photography", "creativity", "learning"], category: "Learning",
            crop: [538, 607, 461, 283]
        },
        {
            id: "demo-6", title: "Ocean Waves", duration: "11:29",
            description: "Waves and sunset over the ocean.",
            tags: ["ocean", "nature"], category: "Travel",
            crop: [1023, 607, 475, 283]
        }
    ];
    const categories = ["All", "Technology", "Learning", "Travel"];
    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);

    function spriteStyle(crop, hideDuration = false) {
        let [x, y, width, height] = crop;
        if (hideDuration) height -= 40;
        const frameWidth = Math.min(width, height * 16 / 9);
        const frameHeight = frameWidth * 9 / 16;
        x += (width - frameWidth) / 2;
        y += (height - frameHeight) / 2;
        return `background-size:${1536 / frameWidth * 100}% auto;`
            + `background-position:${x / (1536 - frameWidth) * 100}% ${y / (1024 - frameHeight) * 100}%`;
    }

    function thumbnail(video) {
        return `<div class="thumbnail" style="${spriteStyle(video.crop)}">
            <span class="duration">${escapeHtml(video.duration)}</span></div>`;
    }

    function card(video) {
        return `<a class="video-card" href="/?demo=${encodeURIComponent(video.id)}">
            ${thumbnail(video)}<h3>${escapeHtml(video.title)}</h3></a>`;
    }

    function renderHome(params) {
        const query = params.get("search") || "";
        const selected = categories.includes(params.get("category")) ? params.get("category") : "All";
        const normalized = query.trim().toLocaleLowerCase("en");
        searchInput.value = query;
        document.title = normalized ? `Search: ${query} — MicroTube` : "MicroTube";
        const results = videos.filter(video => (selected === "All" || video.category === selected)
            && [video.title, video.description, ...video.tags].join(" ").toLocaleLowerCase("en").includes(normalized));
        app.innerHTML = `<nav class="category-bar" aria-label="Categories">${categories.map(category => {
            const target = new URLSearchParams();
            if (query) target.set("search", query);
            if (category !== "All") target.set("category", category);
            return `<a href="/?${target}"${category === selected ? ' aria-current="page"' : ""}>${category}</a>`;
        }).join("")}</nav>
        ${normalized ? `<h1 class="search-heading">Results for “${escapeHtml(query)}”</h1>` : ""}
        ${results.length ? `<div class="video-grid">${results.map(card).join("")}</div>`
            : `<div class="empty-state" role="status"><h2>No videos found</h2>
                <p>Try another search or <a href="/">browse all videos</a>.</p></div>`}`;
    }

    function renderWatch(params) {
        const demoId = params.get("demo");
        const demo = videos.find(video => video.id === demoId);
        const id = params.get("video");
        if (!demo && !/^[A-Za-z0-9_-]{8}$/.test(id || "")) {
            document.title = "Video not found — MicroTube";
            app.innerHTML = '<div class="empty-state"><h1>Video not found</h1><a href="/">Back to catalog</a></div>';
            return;
        }
        const title = demo?.title || params.get("title") || "Video on MicroTube";
        const description = demo?.description || params.get("description") || "";
        const tags = demo?.tags || (params.get("tags") || "").split(/[\s,]+/).filter(Boolean);
        const related = videos.filter(video => video.id !== demoId).slice(0, 3);
        const reference = demo?.id === "demo-1";
        const previewStyle = demo && spriteStyle(reference ? [36, 165, 1089, 594] : demo.crop, !reference);
        document.title = `${title} — MicroTube`;
        app.innerHTML = `<div class="watch-layout"><section class="video-detail">
            ${demo ? `<div class="player-frame demo-frame${reference ? " watch-reference" : ""}" style="${previewStyle}"
                role="img" aria-label="${escapeHtml(title)} — demo still"></div>`
                : '<div class="player-frame"><video controls playsinline preload="metadata" aria-label="Video player"></video></div>'}
            <h1>${escapeHtml(title)}</h1>
            <nav class="tags" aria-label="Tags">${tags.map(tag => `<a href="/?search=${encodeURIComponent(tag)}">#${escapeHtml(tag)}</a>`).join("")}</nav>
            ${description ? `<p class="description">${escapeHtml(description)}</p>` : ""}
            ${demo ? `<p class="demo-note">Demo still. <a href="${serviceUrl(8082)}">Upload an MP4</a> to play a real video.</p>`
                : '<p class="notice" id="video-error" role="status" hidden>Could not play the video. Check its ID and the service availability.</p>'}
            <a class="back-link" href="/">← Back to catalog</a>
        </section><aside class="related"><h2>Related videos</h2>
            <p class="related-note">Examples from the demo catalog</p>
            <div class="related-list">${related.map(card).join("")}</div>
        </aside></div>`;
        if (!demo) {
            const player = app.querySelector("video");
            player.src = `/api/video/videos?id=${encodeURIComponent(id)}`;
            player.addEventListener("error", () => { document.getElementById("video-error").hidden = false; });
        }
    }

    function route() {
        const params = new URLSearchParams(location.search);
        if (params.has("demo") || params.has("video")) renderWatch(params);
        else renderHome(params);
    }

    searchForm.addEventListener("submit", event => {
        event.preventDefault();
        const query = searchInput.value.trim();
        const target = query ? '/?search=' + encodeURIComponent(query) : '/';
        history.pushState({}, "", target);
        route();
    });
    window.addEventListener("popstate", route);
    route();
})();
