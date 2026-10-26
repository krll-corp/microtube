(() => {
    const app = document.getElementById("app-main");
    const searchForm = document.getElementById("search-form");
    const searchInput = document.getElementById("global-search");
    const accountLink = document.getElementById("account-link");
    const uploadLink = document.getElementById("upload-link");

    const authUrl = `${location.protocol}//${location.hostname}:8083/`;
    const uploadUrl = `${location.protocol}//${location.hostname}:8082/`;

    accountLink.href = authUrl;
    uploadLink.href = uploadUrl;

    const videos = [
        {
            id: "demo-1",
            title: "Подорож у Карпати",
            description: "Гірські стежки, озера та краєвиди українських Карпат.",
            tags: ["природа", "гори", "подорожі"],
            category: "Подорожі",
            duration: "12:34",
            icon: "🏔️",
            theme: "nature",
            author: "Мандрівник"
        },
        {
            id: "demo-2",
            title: "Основи Python: перші кроки",
            description: "Знайомство з Python, змінними та простими прикладами коду.",
            tags: ["технології", "python", "навчання"],
            category: "Технології",
            duration: "08:21",
            icon: "💻",
            theme: "code",
            author: "Code Notes"
        },
        {
            id: "demo-3",
            title: "Місто ввечері",
            description: "Вечірнє світло, вулички старого міста та атмосфера подорожі.",
            tags: ["місто", "подорожі", "атмосфера"],
            category: "Подорожі",
            duration: "10:17",
            icon: "🌆",
            theme: "city",
            author: "Urban Frame"
        },
        {
            id: "demo-4",
            title: "Як працює космос",
            description: "Коротка подорож до зірок і знайомство з космосом.",
            tags: ["космос", "наука", "освіта"],
            category: "Навчання",
            duration: "15:06",
            icon: "🪐",
            theme: "space",
            author: "Науковий простір"
        },
        {
            id: "demo-5",
            title: "Основи фотографії",
            description: "Як помічати світло, вибирати ракурс і створювати кадри.",
            tags: ["фото", "творчість", "навчання"],
            category: "Творчість",
            duration: "09:48",
            icon: "📷",
            theme: "photo",
            author: "Frame Lab"
        },
        {
            id: "demo-6",
            title: "Шум океану",
            description: "Хвилі, захід сонця та трохи часу для відпочинку.",
            tags: ["океан", "природа", "релакс"],
            category: "Природа",
            duration: "11:29",
            icon: "🌊",
            theme: "ocean",
            author: "Quiet Planet"
        }
    ];

    const categories = [
        "Усі",
        "Технології",
        "Навчання",
        "Подорожі",
        "Творчість",
        "Природа"
    ];

    let selectedCategory = "Усі";

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, character => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[character]);
    }

    function thumbnailMarkup(video) {
        return `
            <div class="thumbnail theme-${video.theme}">
                <span class="thumbnail-icon">${video.icon}</span>
                <span class="duration">${escapeHtml(video.duration)}</span>
            </div>
        `;
    }

    function cardMarkup(video) {
        return `
            <a class="video-card"
               href="/?demo=${encodeURIComponent(video.id)}">
                ${thumbnailMarkup(video)}
                <h3>${escapeHtml(video.title)}</h3>
                <p>${escapeHtml(video.description)}</p>
                <div class="card-meta">
                    <span class="avatar">
                        ${escapeHtml(video.author.slice(0, 1))}
                    </span>
                    <span>${escapeHtml(video.author)}</span>
                    <span>·</span>
                    <span>${video.tags.length} тег(и)</span>
                </div>
            </a>
        `;
    }

    function categoryMarkup() {
        return `
            <nav class="category-bar" aria-label="Категорії">
                ${categories.map(category => `
                    <button
                        type="button"
                        class="category-pill ${selectedCategory === category ? "active" : ""}"
                        data-category="${escapeHtml(category)}">
                        ${escapeHtml(category)}
                    </button>
                `).join("")}
            </nav>
        `;
    }

    function renderHome(query = "") {
        const normalized = query.trim().toLocaleLowerCase("uk");

        let filteredVideos = videos.filter(video => {
            const matchesCategory =
                selectedCategory === "Усі" ||
                video.category === selectedCategory;

            const searchableText = [
                video.title,
                video.description,
                video.category,
                ...video.tags
            ].join(" ").toLocaleLowerCase("uk");

            const matchesSearch = searchableText.includes(normalized);

            return matchesCategory && matchesSearch;
        });

        const heading = normalized
            ? `Результати пошуку: «${escapeHtml(query)}»`
            : selectedCategory === "Усі"
                ? "Відео для цікавого перегляду"
                : selectedCategory;

        app.innerHTML = `
            ${!normalized && selectedCategory === "Усі" ? `
                <section class="hero">
                    <div>
                        <div class="eyebrow">Відеохостинг без зайвого</div>
                        <h1>Твоя наступна історія починається тут.</h1>
                        <p>
                            Дивись цікаве, знаходь нові теми та ділися
                            власними відео. Усе потрібне — в одному місці.
                        </p>
                        <div class="hero-actions">
                            <a class="button-primary" href="${uploadUrl}">
                                + Завантажити відео
                            </a>
                            <a class="button-secondary" href="#library">
                                Переглянути каталог ↓
                            </a>
                        </div>
                    </div>
                    <div class="hero-art">
                        <span class="hero-play">▶</span>
                    </div>
                </section>
            ` : ""}

            ${categoryMarkup()}

            <section id="library">
                <div class="section-heading">
                    <div>
                        <div class="eyebrow">
                            ${normalized ? "Пошук" : "Твоя добірка"}
                        </div>
                        <h1>${heading}</h1>
                        <p>
                            Обирай тему, знаходь відео за назвою,
                            описом або тегами.
                        </p>
                    </div>
                    <span class="result-count">
                        Знайдено: ${filteredVideos.length}
                    </span>
                </div>

                ${normalized ? `
                    <div class="notice">
                        Зараз пошук працює в демонстраційному каталозі.
                        Реальне текстове API ще потребує доопрацювання.
                    </div>
                ` : ""}

                ${filteredVideos.length
                    ? `<div class="video-grid">
                        ${filteredVideos.map(cardMarkup).join("")}
                       </div>`
                    : `<div class="empty-state">
                        <strong>Нічого не знайдено</strong>
                        Спробуй інший запит або зміни категорію.
                       </div>`
                }
            </section>
        `;

        app.querySelectorAll("[data-category]").forEach(button => {
            button.addEventListener("click", () => {
                selectedCategory = button.dataset.category;
                renderHome(searchInput.value.trim());
            });
        });
    }

    function renderDemoVideo(video) {
        const related = videos.filter(item => item.id !== video.id).slice(0, 4);

        app.innerHTML = `
            <div class="video-page">
                <section class="video-detail">
                    <div class="player-frame">
                        <div class="player-placeholder">
                            <div class="hero-play">▶</div>
                            <strong>Демонстраційне відео</strong>
                            <p>
                                Ця сторінка демонструє інтерфейс перегляду.
                                Для відтворення реального відео завантаж
                                MP4 через Creator Studio.
                            </p>
                        </div>
                    </div>

                    <h1>${escapeHtml(video.title)}</h1>

                    <div class="video-toolbar">
                        <div class="author">
                            <span class="avatar">
                                ${escapeHtml(video.author.slice(0, 1))}
                            </span>
                            <strong>${escapeHtml(video.author)}</strong>
                        </div>
                        <a class="button-primary" href="${uploadUrl}">
                            Завантажити своє
                        </a>
                    </div>

                    <p class="description">
                        ${escapeHtml(video.description)}
                    </p>

                    <div class="tags">
                        ${video.tags.map(tag => `
                            <span class="tag">#${escapeHtml(tag)}</span>
                        `).join("")}
                    </div>
                </section>

                <aside class="related">
                    <h2>Схожі відео</h2>
                    <div class="related-list">
                        ${related.map(cardMarkup).join("")}
                    </div>
                </aside>
            </div>
        `;
    }

    function renderRealVideo(params) {
        const id = params.get("video");
        const title = params.get("title") || "Відео на MicroTube";
        const description = params.get("description") || "";
        const tags = (params.get("tags") || "")
            .split(/[\s,]+/)
            .filter(Boolean);

        app.innerHTML = `
            <div class="video-page">
                <section class="video-detail">
                    <div class="player-frame">
                        <video controls playsinline preload="metadata">
                            Ваш браузер не підтримує відеоплеєр.
                        </video>
                    </div>

                    <h1>${escapeHtml(title)}</h1>

                    <div class="video-toolbar">
                        <div class="author">
                            <span class="avatar">M</span>
                            <strong>Автор MicroTube</strong>
                        </div>
                        <button class="button-secondary" id="copy-link">
                            Копіювати посилання
                        </button>
                    </div>

                    <p class="description">
                        ${escapeHtml(description)}
                    </p>

                    <div class="tags">
                        ${tags.map(tag => `
                            <span class="tag">#${escapeHtml(tag)}</span>
                        `).join("")}
                    </div>

                    <div class="notice" id="video-error" hidden>
                        Не вдалося завантажити відео. Перевір, чи запущено
                        сервіс backend-video і чи правильний ID відео.
                    </div>
                </section>

                <aside class="related">
                    <h2>Схожі відео</h2>
                    <div class="related-list">
                        ${videos.slice(0, 4).map(cardMarkup).join("")}
                    </div>
                </aside>
            </div>
        `;

        const player = app.querySelector("video");
        player.src = `/api/video/videos?id=${encodeURIComponent(id)}`;

        player.addEventListener("error", () => {
            document.getElementById("video-error").hidden = false;
        });

        document.getElementById("copy-link").addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(location.href);
                document.getElementById("copy-link").textContent =
                    "Посилання скопійовано";
            } catch {
                document.getElementById("copy-link").textContent =
                    "Скопіюй URL з адресного рядка";
            }
        });
    }

    function route() {
        const params = new URLSearchParams(location.search);

        if (params.has("video")) {
            renderRealVideo(params);
            return;
        }

        if (params.has("demo")) {
            const video = videos.find(item => item.id === params.get("demo"));
            if (video) {
                renderDemoVideo(video);
                return;
            }
        }

        selectedCategory = "Усі";
        searchInput.value = params.get("search") || "";
        renderHome(searchInput.value);
    }

    searchForm.addEventListener("submit", event => {
        event.preventDefault();

        const query = searchInput.value.trim();
        const url = query
            ? `/?search=${encodeURIComponent(query)}`
            : "/";

        history.pushState({}, "", url);
        selectedCategory = "Усі";
        route();
    });

    window.addEventListener("popstate", route);

    route();
})();