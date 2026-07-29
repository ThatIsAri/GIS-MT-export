(function () {
    "use strict";

    const API_URL = (
        "/api/datamatrix-storage"
    );

    const PAGE_SIZE = 100;

    const state = {
        loaded: false,
        loading: false,
        page: 1,
        totalPages: 1,
        abortController: null
    };


    function storageBrandLogoSvg() {
        return `
            <svg
                viewBox="0 0 48 48"
                aria-hidden="true"
            >
                <rect
                    x="1"
                    y="1"
                    width="46"
                    height="46"
                    rx="11"
                    fill="#111111"
                ></rect>

                <path
                    d="M13.5 24.5L20.5 31.5L35 16"
                    fill="none"
                    stroke="#ffd600"
                    stroke-width="4"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                ></path>

                <path
                    d="M14 15.5H25"
                    fill="none"
                    stroke="#ffd600"
                    stroke-width="3"
                    stroke-linecap="round"
                ></path>
            </svg>
        `;
    }


    function copyIconSvg() {
        return `
            <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
            >
                <rect
                    x="8"
                    y="8"
                    width="11"
                    height="11"
                    rx="2"
                ></rect>

                <path
                    d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"
                ></path>
            </svg>
        `;
    }


    function copiedIconSvg() {
        return `
            <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
            >
                <path
                    d="M5 12.5L9.5 17L19 7.5"
                ></path>
            </svg>
        `;
    }


    function createInterface() {
        if (
            document.getElementById(
                "datamatrix-storage-modal"
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
            "open-datamatrix-storage"
        );

        button.type = "button";

        button.className = (
            "button "
            + "button--datamatrix-storage"
        );

        button.innerHTML = `
            <span
                class="datamatrix-storage-button__logo"
                aria-hidden="true"
            >
                ${storageBrandLogoSvg()}
            </span>

            <span
                class="datamatrix-storage-button__text"
            >
                <span
                    class="datamatrix-storage-button__brand"
                >
                    Честный ЗНАК
                </span>

                <span
                    class="datamatrix-storage-button__title"
                >
                    Хранилище Datamatrix
                </span>
            </span>
        `;

        rail.appendChild(
            button
        );

        const modal = document.createElement(
            "div"
        );

        modal.id = (
            "datamatrix-storage-modal"
        );

        modal.className = (
            "datamatrix-storage-modal"
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
            "datamatrix-storage-title"
        );

        modal.innerHTML = `
            <div
                class="datamatrix-storage-backdrop"
                data-close-datamatrix-storage
            ></div>

            <section
                class="datamatrix-storage-window"
            >
                <header
                    class="datamatrix-storage-header"
                >
                    <h2
                        id="datamatrix-storage-title"
                    >
                        Хранилище Datamatrix
                    </h2>

                    <button
                        class="datamatrix-storage-close"
                        type="button"
                        aria-label="Закрыть хранилище"
                        data-close-datamatrix-storage
                    >
                        ×
                    </button>
                </header>

                <form
                    id="datamatrix-storage-form"
                    class="datamatrix-storage-toolbar"
                    novalidate
                >
                    <div
                        class="
                            datamatrix-storage-field
                            datamatrix-storage-field--search
                        "
                    >
                        <label
                            for="datamatrix-storage-query"
                        >
                            Поиск
                        </label>

                        <input
                            id="datamatrix-storage-query"
                            type="search"
                            autocomplete="off"
                            maxlength="200"
                        >
                    </div>

                    <div
                        class="datamatrix-storage-field"
                    >
                        <label
                            for="datamatrix-storage-entity"
                        >
                            Организация
                        </label>

                        <select
                            id="datamatrix-storage-entity"
                        >
                            <option value="">
                                Все организации
                            </option>
                        </select>
                    </div>

                    <div
                        class="datamatrix-storage-actions"
                    >
                        <button
                            id="datamatrix-storage-search-button"
                            class="button button--primary"
                            type="submit"
                        >
                            Поиск
                        </button>

                        <button
                            id="datamatrix-storage-reset"
                            class="button button--secondary"
                            type="button"
                        >
                            Сбросить
                        </button>
                    </div>
                </form>

                <div
                    id="datamatrix-storage-message"
                    class="datamatrix-storage-message"
                    hidden
                ></div>

                <div
                    class="datamatrix-storage-content"
                >
                    <div
                        class="datamatrix-storage-table-wrap"
                    >
                        <table
                            class="datamatrix-storage-table"
                        >
                            <thead>
                                <tr>
                                    <th>КИ</th>
                                    <th>Наименование</th>
                                    <th>Количество</th>
                                    <th>Организация</th>
                                    <th>
                                        Адрес склада получателя
                                    </th>
                                </tr>
                            </thead>

                            <tbody
                                id="datamatrix-storage-body"
                            >
                                <tr>
                                    <td
                                        colspan="5"
                                        class="datamatrix-storage-empty"
                                    >
                                        Загрузка…
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <footer
                    class="datamatrix-storage-footer"
                >
                    <div
                        id="datamatrix-storage-summary"
                        class="datamatrix-storage-summary"
                    >
                        —
                    </div>

                    <div
                        class="datamatrix-storage-pagination"
                    >
                        <button
                            id="datamatrix-storage-previous"
                            class="button button--secondary"
                            type="button"
                            disabled
                        >
                            Назад
                        </button>

                        <span
                            id="datamatrix-storage-page"
                            class="datamatrix-storage-page"
                        >
                            Страница 1 из 1
                        </span>

                        <button
                            id="datamatrix-storage-next"
                            class="button button--secondary"
                            type="button"
                            disabled
                        >
                            Далее
                        </button>
                    </div>
                </footer>
            </section>
        `;

        document.body.appendChild(
            modal
        );

        bindEvents();
    }


    function getModal() {
        return document.getElementById(
            "datamatrix-storage-modal"
        );
    }


    function getQueryInput() {
        return document.getElementById(
            "datamatrix-storage-query"
        );
    }


    function getEntitySelect() {
        return document.getElementById(
            "datamatrix-storage-entity"
        );
    }


    function getBody() {
        return document.getElementById(
            "datamatrix-storage-body"
        );
    }


    function setMessage(
        kind,
        message
    ) {
        const element = document.getElementById(
            "datamatrix-storage-message"
        );

        if (!element) {
            return;
        }

        if (!message) {
            element.hidden = true;
            element.textContent = "";

            element.className = (
                "datamatrix-storage-message"
            );

            return;
        }

        element.hidden = false;
        element.textContent = message;

        element.className = (
            "datamatrix-storage-message "
            + `datamatrix-storage-message--${kind}`
        );
    }


    function setSummary(message) {
        const element = document.getElementById(
            "datamatrix-storage-summary"
        );

        if (element) {
            element.textContent = (
                message || "—"
            );
        }
    }


    function syncBodyModalState() {
        const modalIds = [
            "entity-modal",
            "document-catalog-modal",
            "datamatrix-storage-modal"
        ];

        const anyOpened = modalIds.some(
            (modalId) => {
                const modal = (
                    document.getElementById(
                        modalId
                    )
                );

                return (
                    modal
                    && !modal.hidden
                );
            }
        );

        document.body.classList.toggle(
            "modal-open",
            anyOpened
        );
    }


    function openStorage() {
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

        loadStorage(
            state.loaded
                ? state.page
                : 1
        );
    }


    function closeStorage() {
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

        modal.hidden = true;

        syncBodyModalState();

        document.getElementById(
            "open-datamatrix-storage"
        )?.focus();
    }


    function setLoading(isLoading) {
        state.loading = isLoading;

        const ids = [
            "datamatrix-storage-search-button",
            "datamatrix-storage-reset",
            "datamatrix-storage-previous",
            "datamatrix-storage-next"
        ];

        ids.forEach(
            (id) => {
                const element = (
                    document.getElementById(
                        id
                    )
                );

                if (element) {
                    element.disabled = (
                        isLoading
                    );
                }
            }
        );

        const queryInput = getQueryInput();
        const entitySelect = getEntitySelect();

        if (queryInput) {
            queryInput.disabled = (
                isLoading
            );
        }

        if (entitySelect) {
            entitySelect.disabled = (
                isLoading
            );
        }

        const searchButton = (
            document.getElementById(
                "datamatrix-storage-search-button"
            )
        );

        if (searchButton) {
            searchButton.textContent = (
                isLoading
                    ? "Загрузка…"
                    : "Поиск"
            );
        }
    }


    function renderLoading() {
        const body = getBody();

        if (!body) {
            return;
        }

        body.replaceChildren();

        const row = document.createElement(
            "tr"
        );

        const cell = document.createElement(
            "td"
        );

        cell.colSpan = 5;

        cell.className = (
            "datamatrix-storage-empty"
        );

        const loading = document.createElement(
            "div"
        );

        loading.className = (
            "datamatrix-storage-loading"
        );

        const spinner = document.createElement(
            "span"
        );

        spinner.className = (
            "datamatrix-storage-spinner"
        );

        spinner.setAttribute(
            "aria-hidden",
            "true"
        );

        const text = document.createElement(
            "span"
        );

        text.textContent = (
            "Загрузка хранилища…"
        );

        loading.append(
            spinner,
            text
        );

        cell.appendChild(
            loading
        );

        row.appendChild(
            cell
        );

        body.appendChild(
            row
        );
    }


    function renderEmpty(message) {
        const body = getBody();

        if (!body) {
            return;
        }

        body.replaceChildren();

        const row = document.createElement(
            "tr"
        );

        const cell = document.createElement(
            "td"
        );

        cell.colSpan = 5;

        cell.className = (
            "datamatrix-storage-empty"
        );

        cell.textContent = message;

        row.appendChild(
            cell
        );

        body.appendChild(
            row
        );
    }


    function formatDate(value) {
        if (!value) {
            return "";
        }

        const parts = String(
            value
        ).slice(
            0,
            10
        ).split(
            "-"
        );

        if (parts.length !== 3) {
            return String(
                value
            );
        }

        return (
            `${parts[2]}.${parts[1]}.${parts[0]}`
        );
    }


    function appendSecondaryText(
        container,
        value
    ) {
        if (!value) {
            return;
        }

        const secondary = (
            document.createElement(
                "div"
            )
        );

        secondary.className = (
            "datamatrix-storage-secondary"
        );

        secondary.textContent = value;

        container.appendChild(
            secondary
        );
    }


    async function copyCode(
        value,
        button
    ) {
        if (!value) {
            return;
        }

        try {
            if (
                navigator.clipboard
                && window.isSecureContext
            ) {
                await navigator.clipboard.writeText(
                    value
                );

            } else {
                const textarea = (
                    document.createElement(
                        "textarea"
                    )
                );

                textarea.value = value;

                textarea.setAttribute(
                    "readonly",
                    ""
                );

                textarea.style.position = (
                    "fixed"
                );

                textarea.style.left = (
                    "-9999px"
                );

                textarea.style.top = (
                    "0"
                );

                textarea.style.opacity = (
                    "0"
                );

                document.body.appendChild(
                    textarea
                );

                textarea.focus();
                textarea.select();

                const copied = (
                    document.execCommand(
                        "copy"
                    )
                );

                textarea.remove();

                if (!copied) {
                    throw new Error(
                        "Команда копирования "
                        + "не была выполнена."
                    );
                }
            }

            const previousHtml = (
                button.innerHTML
            );

            button.innerHTML = (
                copiedIconSvg()
            );

            button.classList.add(
                "is-copied"
            );

            button.title = (
                "Скопировано"
            );

            button.setAttribute(
                "aria-label",
                "Скопировано"
            );

            button.disabled = true;

            window.setTimeout(
                () => {
                    button.innerHTML = (
                        previousHtml
                    );

                    button.classList.remove(
                        "is-copied"
                    );

                    button.title = (
                        "Копировать КИ"
                    );

                    button.setAttribute(
                        "aria-label",
                        "Копировать КИ"
                    );

                    button.disabled = false;
                },
                1200
            );

        } catch {
            setMessage(
                "error",
                "Не удалось скопировать КИ."
            );
        }
    }


    function createCodeCell(item) {
        const cell = document.createElement(
            "td"
        );

        const wrapper = (
            document.createElement(
                "div"
            )
        );

        wrapper.className = (
            "datamatrix-storage-code-cell"
        );

        const code = document.createElement(
            "code"
        );

        code.className = (
            "datamatrix-storage-code"
        );

        code.textContent = (
            item.code || "—"
        );

        code.title = (
            item.code || ""
        );

        const copyButton = (
            document.createElement(
                "button"
            )
        );

        copyButton.className = (
            "datamatrix-storage-copy"
        );

        copyButton.type = "button";

        copyButton.innerHTML = (
            copyIconSvg()
        );

        copyButton.title = (
            "Копировать КИ"
        );

        copyButton.setAttribute(
            "aria-label",
            "Копировать КИ"
        );

        if (!item.code) {
            copyButton.disabled = true;

            copyButton.title = (
                "КИ отсутствует"
            );

            copyButton.setAttribute(
                "aria-label",
                "КИ отсутствует"
            );
        }

        copyButton.addEventListener(
            "click",
            () => {
                copyCode(
                    item.code || "",
                    copyButton
                );
            }
        );

        wrapper.append(
            code,
            copyButton
        );

        cell.appendChild(
            wrapper
        );

        return cell;
    }


    function createProductCell(item) {
        const cell = document.createElement(
            "td"
        );

        const primary = document.createElement(
            "div"
        );

        primary.className = (
            "datamatrix-storage-primary"
        );

        primary.textContent = (
            item.product_name || "—"
        );

        cell.appendChild(
            primary
        );

        if (item.product_code) {
            appendSecondaryText(
                cell,
                `Код товара: ${item.product_code}`
            );
        }

        return cell;
    }


    function createQuantityCell(item) {
        const cell = document.createElement(
            "td"
        );

        cell.className = (
            "datamatrix-storage-quantity"
        );

        cell.textContent = (
            item.quantity || "1"
        );

        return cell;
    }


    function createOrganizationCell(item) {
        const cell = document.createElement(
            "td"
        );

        const organization = (
            item.organization || {}
        );

        const primary = document.createElement(
            "div"
        );

        primary.className = (
            "datamatrix-storage-primary"
        );

        primary.textContent = (
            organization.name || "—"
        );

        cell.appendChild(
            primary
        );

        if (organization.inn) {
            appendSecondaryText(
                cell,
                `ИНН ${organization.inn}`
            );
        }

        if (item.source_document_date) {
            appendSecondaryText(
                cell,
                `УПД от ${formatDate(
                    item.source_document_date
                )}`
            );
        }

        return cell;
    }


    function createAddressCell(item) {
        const cell = document.createElement(
            "td"
        );

        cell.className = (
            "datamatrix-storage-address"
        );

        cell.textContent = (
            item.receiver_warehouse_address
            || "—"
        );

        return cell;
    }


    function renderRows(items) {
        const body = getBody();

        if (!body) {
            return;
        }

        body.replaceChildren();

        if (!items.length) {
            renderEmpty(
                "По заданным условиям "
                + "ничего не найдено."
            );

            return;
        }

        const fragment = (
            document.createDocumentFragment()
        );

        items.forEach(
            (item) => {
                const row = (
                    document.createElement(
                        "tr"
                    )
                );

                row.append(
                    createCodeCell(
                        item
                    ),

                    createProductCell(
                        item
                    ),

                    createQuantityCell(
                        item
                    ),

                    createOrganizationCell(
                        item
                    ),

                    createAddressCell(
                        item
                    )
                );

                fragment.appendChild(
                    row
                );
            }
        );

        body.appendChild(
            fragment
        );
    }


    function populateOrganizations(
        organizations,
        selectedValue
    ) {
        const select = getEntitySelect();

        if (!select) {
            return;
        }

        select.replaceChildren();

        const allOption = (
            document.createElement(
                "option"
            )
        );

        allOption.value = "";

        allOption.textContent = (
            "Все организации"
        );

        select.appendChild(
            allOption
        );

        organizations.forEach(
            (organization) => {
                const option = (
                    document.createElement(
                        "option"
                    )
                );

                option.value = String(
                    organization.id
                );

                const count = Number(
                    organization.unit_count || 0
                );

                option.textContent = (
                    `${organization.name} · ${count}`
                );

                select.appendChild(
                    option
                );
            }
        );

        select.value = selectedValue;

        if (
            select.value
            !== selectedValue
        ) {
            select.value = "";
        }
    }


    function renderPagination(
        pagination
    ) {
        state.page = Number(
            pagination.page || 1
        );

        state.totalPages = Number(
            pagination.total_pages || 1
        );

        const previousButton = (
            document.getElementById(
                "datamatrix-storage-previous"
            )
        );

        const nextButton = (
            document.getElementById(
                "datamatrix-storage-next"
            )
        );

        const pageElement = (
            document.getElementById(
                "datamatrix-storage-page"
            )
        );

        if (previousButton) {
            previousButton.disabled = (
                !pagination.has_previous
            );
        }

        if (nextButton) {
            nextButton.disabled = (
                !pagination.has_next
            );
        }

        if (pageElement) {
            pageElement.textContent = (
                `Страница ${state.page} `
                + `из ${state.totalPages}`
            );
        }

        const totalCount = Number(
            pagination.total_count || 0
        );

        if (!totalCount) {
            setSummary(
                "Найдено: 0"
            );

            return;
        }

        setSummary(
            `Показано ${pagination.first_item}`
            + `–${pagination.last_item} `
            + `из ${totalCount}`
        );
    }


    function currentFilters() {
        return {
            query: String(
                getQueryInput()?.value || ""
            ).trim(),

            entityId: String(
                getEntitySelect()?.value || ""
            ).trim()
        };
    }


    async function loadStorage(page) {
        const filters = currentFilters();

        if (
            filters.query
            && filters.query.length < 3
        ) {
            setMessage(
                "error",
                "Для поиска введите "
                + "не менее трёх символов."
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
            API_URL,
            window.location.origin
        );

        url.searchParams.set(
            "page",
            String(
                page
            )
        );

        url.searchParams.set(
            "page_size",
            String(
                PAGE_SIZE
            )
        );

        if (filters.query) {
            url.searchParams.set(
                "q",
                filters.query
            );
        }

        if (filters.entityId) {
            url.searchParams.set(
                "entity_id",
                filters.entityId
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
                        "Не удалось получить данные "
                        + "хранилища DataMatrix."
                    )
                );
            }

            state.loaded = true;

            populateOrganizations(
                Array.isArray(
                    payload.organizations
                )
                    ? payload.organizations
                    : [],

                filters.entityId
            );

            renderRows(
                Array.isArray(
                    payload.items
                )
                    ? payload.items
                    : []
            );

            renderPagination(
                payload.pagination || {}
            );

        } catch (error) {
            if (
                error.name === "AbortError"
            ) {
                return;
            }

            const message = (
                error.message
                || (
                    "Не удалось загрузить "
                    + "хранилище DataMatrix."
                )
            );

            setMessage(
                "error",
                message
            );

            renderEmpty(
                message
            );

            setSummary(
                "—"
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

            const previousButton = (
                document.getElementById(
                    "datamatrix-storage-previous"
                )
            );

            const nextButton = (
                document.getElementById(
                    "datamatrix-storage-next"
                )
            );

            if (previousButton) {
                previousButton.disabled = (
                    state.page <= 1
                );
            }

            if (nextButton) {
                nextButton.disabled = (
                    state.page
                    >= state.totalPages
                );
            }
        }
    }


    function submitSearch(event) {
        event.preventDefault();

        loadStorage(
            1
        );
    }


    function resetSearch() {
        const queryInput = (
            getQueryInput()
        );

        const entitySelect = (
            getEntitySelect()
        );

        if (queryInput) {
            queryInput.value = "";
        }

        if (entitySelect) {
            entitySelect.value = "";
        }

        setMessage(
            "",
            ""
        );

        loadStorage(
            1
        );
    }


    function bindEvents() {
        document.getElementById(
            "open-datamatrix-storage"
        )?.addEventListener(
            "click",
            openStorage
        );

        document
            .querySelectorAll(
                "[data-close-datamatrix-storage]"
            )
            .forEach(
                (element) => {
                    element.addEventListener(
                        "click",
                        closeStorage
                    );
                }
            );

        document.getElementById(
            "datamatrix-storage-form"
        )?.addEventListener(
            "submit",
            submitSearch
        );

        document.getElementById(
            "datamatrix-storage-reset"
        )?.addEventListener(
            "click",
            resetSearch
        );

        document.getElementById(
            "datamatrix-storage-previous"
        )?.addEventListener(
            "click",
            () => {
                if (state.page > 1) {
                    loadStorage(
                        state.page - 1
                    );
                }
            }
        );

        document.getElementById(
            "datamatrix-storage-next"
        )?.addEventListener(
            "click",
            () => {
                if (
                    state.page
                    < state.totalPages
                ) {
                    loadStorage(
                        state.page + 1
                    );
                }
            }
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
                    closeStorage();
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