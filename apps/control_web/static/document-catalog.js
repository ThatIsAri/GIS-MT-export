(function () {
    "use strict";

    const CATALOG_API_URL = (
        "/api/document-catalog"
    );

    const DOWNLOAD_API_URL = (
        "/api/document-catalog/download"
    );

    const state = {
        loaded: false,
        loading: false,
        abortController: null,
        directoryControllers: new Map()
    };


    function escapeHtml(value) {
        return String(
            value ?? ""
        )
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    function formatFileSize(value) {
        const size = Number(
            value
        );

        if (
            !Number.isFinite(size)
            || size < 0
        ) {
            return "—";
        }

        if (size < 1024) {
            return `${size} Б`;
        }

        const kilobytes = (
            size / 1024
        );

        if (kilobytes < 1024) {
            return (
                `${kilobytes.toFixed(1)} КБ`
            );
        }

        const megabytes = (
            kilobytes / 1024
        );

        if (megabytes < 1024) {
            return (
                `${megabytes.toFixed(1)} МБ`
            );
        }

        const gigabytes = (
            megabytes / 1024
        );

        return (
            `${gigabytes.toFixed(1)} ГБ`
        );
    }


    function formatDateTime(value) {
        if (!value) {
            return "—";
        }

        const parsed = new Date(
            value
        );

        if (
            Number.isNaN(
                parsed.getTime()
            )
        ) {
            return String(
                value
            );
        }

        return new Intl.DateTimeFormat(
            "ru-RU",
            {
                dateStyle: "short",
                timeStyle: "short"
            }
        ).format(
            parsed
        );
    }


    function fileTypeLabel(extension) {
        const prepared = String(
            extension || ""
        )
            .replace(
                /^\./,
                ""
            )
            .trim()
            .toUpperCase();

        return (
            prepared || "ФАЙЛ"
        ).slice(
            0,
            8
        );
    }


    function folderIconSvg() {
        return `
            <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
            >
                <path
                    d="M3.5 6.5h6l2 2h9v10h-17z"
                ></path>
            </svg>
        `;
    }


    function fileIconSvg() {
        return `
            <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
            >
                <path
                    d="M6 3.5h8l4 4v13H6z"
                ></path>

                <path
                    d="M14 3.5v4h4"
                ></path>
            </svg>
        `;
    }


    function createInterface() {
        if (
            document.getElementById(
                "document-catalog-modal"
            )
        ) {
            return;
        }

        const rail = document.querySelector(
            ".page-action-rail"
        );

        if (!rail) {
            return;
        }

        const button = document.createElement(
            "button"
        );

        button.id = (
            "open-document-catalog"
        );

        button.className = (
            "button "
            + "button--document-catalog"
        );

        button.type = "button";

        button.innerHTML = `
            <span
                class="document-catalog-button-icon"
            >
                ${folderIconSvg()}
            </span>

            <span>
                Каталог документов
            </span>
        `;

        rail.appendChild(
            button
        );

        const modal = document.createElement(
            "div"
        );

        modal.id = (
            "document-catalog-modal"
        );

        modal.className = (
            "document-catalog-modal"
        );

        modal.hidden = true;

        modal.setAttribute(
            "role",
            "dialog"
        );

        modal.setAttribute(
            "aria-modal",
            "true"
        );

        modal.setAttribute(
            "aria-labelledby",
            "document-catalog-title"
        );

        modal.innerHTML = `
            <div
                class="document-catalog-backdrop"
                data-close-document-catalog
            ></div>

            <section
                class="document-catalog-window"
            >
                <header
                    class="document-catalog-header"
                >
                    <h2
                        id="document-catalog-title"
                    >
                        Каталог документов
                    </h2>

                    <button
                        class="document-catalog-close"
                        type="button"
                        aria-label="Закрыть каталог"
                        data-close-document-catalog
                    >
                        ×
                    </button>
                </header>

                <div
                    class="document-catalog-toolbar"
                >
                    <div
                        class="document-catalog-search"
                    >
                        <label
                            for="document-catalog-query"
                        >
                            Поиск
                        </label>

                        <div
                            class="document-catalog-search-row"
                        >
                            <input
                                id="document-catalog-query"
                                type="search"
                                maxlength="200"
                                autocomplete="off"
                                placeholder=""
                            >

                            <button
                                id="document-catalog-search-button"
                                class="button button--primary"
                                type="button"
                            >
                                Поиск
                            </button>

                            <button
                                id="document-catalog-reset-button"
                                class="button button--secondary"
                                type="button"
                            >
                                Сбросить
                            </button>
                        </div>
                    </div>
                </div>

                <div
                    id="document-catalog-message"
                    class="document-catalog-message"
                    hidden
                ></div>

                <div
                    id="document-catalog-content"
                    class="document-catalog-content"
                >
                    <div
                        class="document-catalog-empty"
                    >
                        Каталог ещё не загружен.
                    </div>
                </div>
            </section>
        `;

        document.body.appendChild(
            modal
        );

        bindEvents();
    }


    function getModal() {
        return document.getElementById(
            "document-catalog-modal"
        );
    }


    function getQueryInput() {
        return document.getElementById(
            "document-catalog-query"
        );
    }


    function getContent() {
        return document.getElementById(
            "document-catalog-content"
        );
    }


    function setMessage(
        kind,
        message
    ) {
        const element = document.getElementById(
            "document-catalog-message"
        );

        if (!element) {
            return;
        }

        if (!message) {
            element.hidden = true;
            element.textContent = "";

            element.className = (
                "document-catalog-message"
            );

            return;
        }

        element.hidden = false;
        element.textContent = message;

        element.className = (
            "document-catalog-message "
            + `document-catalog-message--${kind}`
        );
    }


    function syncBodyModalState() {
        const catalogModal = getModal();

        const entityModal = document.getElementById(
            "entity-modal"
        );

        const catalogOpened = (
            catalogModal
            && !catalogModal.hidden
        );

        const entityOpened = (
            entityModal
            && !entityModal.hidden
        );

        document.body.classList.toggle(
            "modal-open",
            Boolean(
                catalogOpened
                || entityOpened
            )
        );
    }


    function openCatalog() {
        const modal = getModal();

        if (!modal) {
            return;
        }

        modal.hidden = false;

        syncBodyModalState();

        window.setTimeout(
            () => {
                getQueryInput()?.focus();
            },
            0
        );

        if (!state.loaded) {
            loadCatalog(
                ""
            );
        }
    }


    function closeCatalog() {
        const modal = getModal();

        if (!modal) {
            return;
        }

        if (
            state.abortController
        ) {
            state.abortController.abort();
            state.abortController = null;
        }

        if (state.directoryControllers.size) {
            state.loaded = false;
        }

        state.directoryControllers.forEach(
            (controller) => controller.abort()
        );
        state.directoryControllers.clear();

        modal.hidden = true;

        syncBodyModalState();

        document.getElementById(
            "open-document-catalog"
        )?.focus();
    }


    function setLoading(isLoading) {
        state.loading = isLoading;

        const searchButton = (
            document.getElementById(
                "document-catalog-search-button"
            )
        );

        const resetButton = (
            document.getElementById(
                "document-catalog-reset-button"
            )
        );

        const input = getQueryInput();

        if (searchButton) {
            searchButton.disabled = (
                isLoading
            );

            searchButton.textContent = (
                isLoading
                    ? "Поиск…"
                    : "Поиск"
            );
        }

        if (resetButton) {
            resetButton.disabled = (
                isLoading
            );
        }

        if (input) {
            input.disabled = (
                isLoading
            );
        }
    }


    function renderLoading() {
        const content = getContent();

        if (!content) {
            return;
        }

        content.innerHTML = `
            <div
                class="document-catalog-loading"
            >
                <span
                    class="document-catalog-spinner"
                    aria-hidden="true"
                ></span>

                <span>
                    Загрузка каталога…
                </span>
            </div>
        `;
    }


    function renderError(message) {
        const content = getContent();

        if (!content) {
            return;
        }

        content.innerHTML = `
            <div
                class="document-catalog-empty"
            >
                ${escapeHtml(message)}
            </div>
        `;
    }


    function renderFile(node) {
        const downloadUrl = (
            DOWNLOAD_API_URL
            + "?path="
            + encodeURIComponent(
                node.path || ""
            )
        );

        return `
            <div
                class="document-catalog-file"
            >
                <span
                    class="document-catalog-file-icon"
                >
                    ${fileIconSvg()}
                </span>

                <span
                    class="document-catalog-file-type"
                >
                    ${escapeHtml(
                        fileTypeLabel(
                            node.extension
                        )
                    )}
                </span>

                <div
                    class="document-catalog-file-main"
                >
                    <div
                        class="document-catalog-file-name"
                        title="${escapeHtml(
                            node.name
                        )}"
                    >
                        ${escapeHtml(
                            node.name
                        )}
                    </div>

                    <div
                        class="document-catalog-file-meta"
                    >
                        <span>
                            ${escapeHtml(
                                formatFileSize(
                                    node.size
                                )
                            )}
                        </span>

                        <span>
                            ${escapeHtml(
                                formatDateTime(
                                    node.modified_at
                                )
                            )}
                        </span>
                    </div>
                </div>

                <a
                    class="document-catalog-download"
                    href="${downloadUrl}"
                    download
                >
                    Скачать
                </a>
            </div>
        `;
    }


    function renderDirectoryNode({
        name,
        subtitle,
        children,
        kind,
        path,
        lazy,
        loaded,
        hasChildren,
        count,
        fixedCount
    }) {
        const preparedChildren = (
            Array.isArray(children)
                ? children
                : []
        );
        const isLoaded = Boolean(loaded);
        const isLazy = Boolean(lazy);
        let childHtml = "";

        if (isLoaded) {
            childHtml = preparedChildren.length
                ? preparedChildren
                    .map(renderNode)
                    .join("")
                : `
                    <div
                        class="document-catalog-node-empty"
                    >
                        Папка пуста.
                    </div>
                `;
        } else if (hasChildren === false) {
            childHtml = `
                <div
                    class="document-catalog-node-empty"
                >
                    Папка пуста.
                </div>
            `;
        } else {
            childHtml = `
                <div
                    class="document-catalog-node-empty"
                >
                    Содержимое загрузится при раскрытии.
                </div>
            `;
        }

        const subtitleHtml = subtitle
            ? `
                <span
                    class="document-catalog-node-subtitle"
                >
                    ${escapeHtml(subtitle)}
                </span>
            `
            : "";
        const numericCount = Number(count);
        const hasExplicitCount = (
            count !== null
            && count !== undefined
            && Number.isFinite(numericCount)
            && numericCount >= 0
        );
        const countText = hasExplicitCount
            ? numericCount.toLocaleString("ru-RU")
            : (
                isLoaded
                    ? String(preparedChildren.length)
                    : (hasChildren === false ? "0" : "…")
            );

        return `
            <details
                class="
                    document-catalog-node
                    document-catalog-node--${escapeHtml(kind)}
                "
                data-catalog-path="${escapeHtml(path || "")}"
                data-catalog-lazy="${isLazy ? "true" : "false"}"
                data-catalog-loaded="${isLoaded ? "true" : "false"}"
                data-catalog-count-fixed="${fixedCount ? "true" : "false"}"
            >
                <summary>
                    <span
                        class="document-catalog-chevron"
                        aria-hidden="true"
                    ></span>

                    <span
                        class="document-catalog-folder-icon"
                    >
                        ${folderIconSvg()}
                    </span>

                    <span
                        class="document-catalog-node-heading"
                    >
                        <span
                            class="document-catalog-node-name"
                        >
                            ${escapeHtml(name)}
                        </span>

                        ${subtitleHtml}
                    </span>

                    <span
                        class="document-catalog-node-count"
                        data-catalog-count
                    >
                        ${countText}
                    </span>
                </summary>

                <div
                    class="document-catalog-node-children"
                    data-catalog-children
                >
                    ${childHtml}
                </div>
            </details>
        `;
    }


    function renderOrganization(
        organization
    ) {
        const subtitleParts = [];

        if (organization.inn) {
            subtitleParts.push(
                `ИНН ${organization.inn}`
            );
        }

        if (
            organization.short_name
            && organization.short_name
                !== organization.name
        ) {
            subtitleParts.push(
                organization.short_name
            );
        }

        return renderDirectoryNode(
            {
                name: (
                    organization.name
                ),
                subtitle: (
                    subtitleParts.join(
                        " · "
                    )
                ),
                children: (
                    organization.children
                ),
                kind: "organization",
                path: organization.path,
                lazy: organization.lazy,
                loaded: organization.loaded,
                hasChildren: organization.has_children,
                count: organization.document_count,
                fixedCount: true
            }
        );
    }


    function renderNode(node) {
        if (
            node.type === "file"
        ) {
            return renderFile(
                node
            );
        }

        return renderDirectoryNode(
            {
                name: node.name,
                subtitle: "",
                children: node.children,
                kind: "directory",
                path: node.path,
                lazy: node.lazy,
                loaded: node.loaded,
                hasChildren: node.has_children,
                count: node.document_count,
                fixedCount: false
            }
        );
    }


    async function loadDirectory(details) {
        const path = String(
            details.dataset.catalogPath || ""
        );

        if (
            !path
            || details.dataset.catalogLoaded === "true"
            || state.directoryControllers.has(path)
        ) {
            return;
        }

        const childrenElement = details.querySelector(
            ":scope > [data-catalog-children]"
        );
        const countElement = details.querySelector(
            ":scope > summary [data-catalog-count]"
        );

        if (!childrenElement) {
            return;
        }

        const controller = new AbortController();
        state.directoryControllers.set(path, controller);
        childrenElement.innerHTML = `
            <div class="document-catalog-loading">
                <span
                    class="document-catalog-spinner"
                    aria-hidden="true"
                ></span>
                <span>Загрузка папки…</span>
            </div>
        `;

        const url = new URL(
            CATALOG_API_URL,
            window.location.origin
        );
        url.searchParams.set("path", path);

        try {
            const response = await fetch(
                url.toString(),
                {
                    method: "GET",
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store",
                    signal: controller.signal
                }
            );
            let payload = null;

            try {
                payload = await response.json();
            } catch {
                payload = null;
            }

            if (!response.ok) {
                throw new Error(
                    payload?.error
                    || "Не удалось открыть папку."
                );
            }

            const items = Array.isArray(payload?.items)
                ? payload.items
                : [];
            childrenElement.innerHTML = items.length
                ? items.map(renderNode).join("")
                : `
                    <div
                        class="document-catalog-node-empty"
                    >
                        Папка пуста.
                    </div>
                `;
            details.dataset.catalogLoaded = "true";

            if (
                countElement
                && details.dataset.catalogCountFixed !== "true"
            ) {
                countElement.textContent = String(items.length);
            }

            if (payload?.summary?.truncated) {
                setMessage(
                    "warning",
                    "В папке показана только первая часть файлов. Используйте поиск."
                );
            }
        } catch (error) {
            if (error.name === "AbortError") {
                return;
            }

            childrenElement.innerHTML = `
                <div
                    class="document-catalog-node-empty"
                >
                    ${escapeHtml(
                        error.message
                        || "Не удалось открыть папку."
                    )}
                </div>
            `;
        } finally {
            if (
                state.directoryControllers.get(path)
                === controller
            ) {
                state.directoryControllers.delete(path);
            }
        }
    }


    function renderCatalog(payload) {
        const content = getContent();

        if (!content) {
            return;
        }

        const organizations = Array.isArray(
            payload.organizations
        )
            ? payload.organizations
            : [];

        const query = String(
            payload.query || ""
        );

        if (!organizations.length) {
            content.innerHTML = `
                <div
                    class="document-catalog-empty"
                >
                    ${
                        query
                            ? (
                                "По указанной комбинации "
                                + "ничего не найдено."
                            )
                            : (
                                "Организации отсутствуют."
                            )
                    }
                </div>
            `;

            return;
        }

        content.innerHTML = `
            <div
                class="document-catalog-tree"
            >
                ${organizations
                    .map(
                        renderOrganization
                    )
                    .join("")}
            </div>
        `;

        const summary = (
            payload.summary || {}
        );

        if (
            summary.truncated
        ) {
            setMessage(
                "warning",
                (
                    "Каталог слишком большой. "
                    + "Часть элементов не показана. "
                    + "Используйте поиск."
                )
            );

        } else {
            setMessage(
                "",
                ""
            );
        }
    }


    async function loadCatalog(query) {
        if (state.loading) {
            return;
        }

        const preparedQuery = String(
            query || ""
        ).trim();

        if (
            preparedQuery
            && preparedQuery.length < 3
        ) {
            setMessage(
                "error",
                (
                    "Для поиска необходимо "
                    + "ввести не менее трёх "
                    + "символов."
                )
            );

            getQueryInput()?.focus();

            return;
        }

        if (
            state.abortController
        ) {
            state.abortController.abort();
        }

        const abortController = (
            new AbortController()
        );

        state.abortController = (
            abortController
        );

        setLoading(
            true
        );

        setMessage(
            "",
            ""
        );

        renderLoading();

        const url = new URL(
            CATALOG_API_URL,
            window.location.origin
        );

        if (preparedQuery) {
            url.searchParams.set(
                "q",
                preparedQuery
            );
        }

        try {
            const response = await fetch(
                url.toString(),
                {
                    method: "GET",
                    headers: {
                        "Accept": (
                            "application/json"
                        )
                    },
                    cache: "no-store",
                    signal: (
                        abortController.signal
                    )
                }
            );

            let payload;

            try {
                payload = (
                    await response.json()
                );

            } catch {
                payload = null;
            }

            if (!response.ok) {
                throw new Error(
                    payload?.error
                    || (
                        "Не удалось получить "
                        + "каталог документов."
                    )
                );
            }

            state.loaded = true;

            renderCatalog(
                payload || {}
            );

        } catch (error) {
            if (
                error.name
                === "AbortError"
            ) {
                return;
            }

            const message = (
                error.message
                || (
                    "Не удалось загрузить "
                    + "каталог документов."
                )
            );

            setMessage(
                "error",
                message
            );

            renderError(
                message
            );

        } finally {
            if (
                state.abortController
                === abortController
            ) {
                state.abortController = null;
            }

            setLoading(
                false
            );
        }
    }


    function startSearch() {
        const input = getQueryInput();

        if (!input) {
            return;
        }

        loadCatalog(
            input.value
        );
    }


    function resetSearch() {
        const input = getQueryInput();

        if (input) {
            input.value = "";
        }

        loadCatalog(
            ""
        );
    }


    function bindEvents() {
        document.getElementById(
            "open-document-catalog"
        )?.addEventListener(
            "click",
            openCatalog
        );

        document
            .querySelectorAll(
                "[data-close-document-catalog]"
            )
            .forEach(
                (element) => {
                    element.addEventListener(
                        "click",
                        closeCatalog
                    );
                }
            );

        document.getElementById(
            "document-catalog-search-button"
        )?.addEventListener(
            "click",
            startSearch
        );

        document.getElementById(
            "document-catalog-reset-button"
        )?.addEventListener(
            "click",
            resetSearch
        );

        getContent()?.addEventListener(
            "toggle",
            (event) => {
                const details = event.target;

                if (
                    details instanceof HTMLDetailsElement
                    && details.open
                    && details.dataset.catalogLazy === "true"
                    && details.dataset.catalogLoaded !== "true"
                ) {
                    loadDirectory(details);
                }
            },
            true
        );

        document.addEventListener(
            "keydown",
            (event) => {
                const modal = getModal();

                if (
                    event.key === "Escape"
                    && modal
                    && !modal.hidden
                ) {
                    closeCatalog();
                }
            }
        );
    }


    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            createInterface
        );

    } else {
        createInterface();
    }
})();