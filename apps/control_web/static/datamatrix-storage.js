(function () {
    "use strict";

    const API_URL = "/api/datamatrix-storage";
    const PAGE_SIZE = 100;

    const state = {
        loaded: false,
        loading: false,
        page: 1,
        totalPages: 1,
        abortController: null
    };

    const byId = (id) => document.getElementById(id);

    function brandIcon() {
        return `
            <svg viewBox="0 0 48 48" aria-hidden="true">
                <rect
                    x="1"
                    y="1"
                    width="46"
                    height="46"
                    rx="11"
                ></rect>

                <path
                    d="M13.5 24.5L20.5 31.5L35 16"
                ></path>

                <path
                    d="M14 15.5H25"
                ></path>
            </svg>
        `;
    }

    function copyIcon() {
        return `
            <svg viewBox="0 0 24 24" aria-hidden="true">
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

    function checkIcon() {
        return `
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                    d="M5 12.5L9.5 17L19 7.5"
                ></path>
            </svg>
        `;
    }

    function createInterface() {
        if (
            byId(
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

        const openButton = document.createElement(
            "button"
        );

        openButton.id = "open-datamatrix-storage";
        openButton.type = "button";

        openButton.className = (
            "button "
            + "button--datamatrix-storage"
        );

        openButton.innerHTML = `
            <span
                class="datamatrix-storage-button__logo"
                aria-hidden="true"
            >
                ${brandIcon()}
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
                    Хранилище DataMatrix
                </span>
            </span>
        `;

        rail.appendChild(
            openButton
        );

        const modal = document.createElement(
            "div"
        );

        modal.id = "datamatrix-storage-modal";
        modal.className = "datamatrix-storage-modal";
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
                    <div>
                        <h2
                            id="datamatrix-storage-title"
                        >
                            Хранилище DataMatrix
                        </h2>

                        <p>
                            Конечные КИ единиц товара,
                            раскрытые из упаковок и
                            агрегатов УПД/УКД.
                        </p>
                    </div>

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
                            placeholder="
                                КИ, GTIN, товар,
                                организация или адрес
                            "
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
                        class="datamatrix-storage-field"
                    >
                        <label
                            for="
                                datamatrix-storage-quantity-status
                            "
                        >
                            Проверка количества
                        </label>

                        <select
                            id="
                                datamatrix-storage-quantity-status
                            "
                        >
                            <option value="ALL">
                                Все статусы
                            </option>

                            <option value="MATCHED">
                                Количество совпало
                            </option>

                            <option value="MISMATCH">
                                Есть расхождение
                            </option>

                            <option value="NOT_CHECKED">
                                Не проверено
                            </option>
                        </select>
                    </div>

                    <div
                        class="datamatrix-storage-actions"
                    >
                        <button
                            id="
                                datamatrix-storage-search-button
                            "
                            class="button button--primary"
                            type="submit"
                        >
                            Найти
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
                    class="datamatrix-storage-metrics"
                >
                    <div
                        class="datamatrix-storage-metric"
                    >
                        <span>
                            КИ единиц
                        </span>

                        <strong
                            id="
                                datamatrix-storage-unit-count
                            "
                        >
                            —
                        </strong>
                    </div>

                    <div
                        class="datamatrix-storage-metric"
                    >
                        <span>
                            Исходные КИ
                        </span>

                        <strong
                            id="
                                datamatrix-storage-source-count
                            "
                        >
                            —
                        </strong>
                    </div>

                    <div
                        class="datamatrix-storage-metric"
                    >
                        <span>
                            Агрегаты
                        </span>

                        <strong
                            id="
                                datamatrix-storage-aggregate-count
                            "
                        >
                            —
                        </strong>
                    </div>

                    <div
                        class="
                            datamatrix-storage-metric
                            datamatrix-storage-metric--warning
                        "
                    >
                        <span>
                            Расхождения
                        </span>

                        <strong
                            id="
                                datamatrix-storage-mismatch-count
                            "
                        >
                            —
                        </strong>
                    </div>
                </div>

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
                                    <th>
                                        КИ единицы
                                    </th>

                                    <th>
                                        Товар
                                    </th>

                                    <th>
                                        Исходный КИ
                                    </th>

                                    <th>
                                        Проверка количества
                                    </th>

                                    <th>
                                        Организация и склад
                                    </th>
                                </tr>
                            </thead>

                            <tbody
                                id="datamatrix-storage-body"
                            >
                                <tr>
                                    <td
                                        colspan="5"
                                        class="
                                            datamatrix-storage-empty
                                        "
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
                        class="
                            datamatrix-storage-pagination
                        "
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

    function syncBodyModalState() {
        const anyOpened = [
            "entity-modal",
            "document-catalog-modal",
            "datamatrix-storage-modal"
        ].some(
            (id) => {
                const modal = byId(
                    id
                );

                return (
                    modal
                    && !modal.hidden
                );
            }
        );

        document.body.classList.toggle(
            "modal-open",
            Boolean(
                anyOpened
            )
        );
    }

    function openStorage() {
        const modal = byId(
            "datamatrix-storage-modal"
        );

        if (!modal) {
            return;
        }

        modal.hidden = false;

        syncBodyModalState();

        window.setTimeout(
            () => {
                byId(
                    "datamatrix-storage-query"
                )?.focus();
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
        const modal = byId(
            "datamatrix-storage-modal"
        );

        if (!modal) {
            return;
        }

        state.abortController?.abort();
        state.abortController = null;

        modal.hidden = true;

        syncBodyModalState();

        byId(
            "open-datamatrix-storage"
        )?.focus();
    }

    function setMessage(
        kind,
        message
    ) {
        const element = byId(
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

    function setLoading(
        loading
    ) {
        state.loading = loading;

        [
            "datamatrix-storage-query",
            "datamatrix-storage-entity",
            "datamatrix-storage-quantity-status",
            "datamatrix-storage-search-button",
            "datamatrix-storage-reset"
        ].forEach(
            (id) => {
                const element = byId(
                    id
                );

                if (element) {
                    element.disabled = loading;
                }
            }
        );

        const button = byId(
            "datamatrix-storage-search-button"
        );

        if (button) {
            button.textContent = (
                loading
                    ? "Загрузка…"
                    : "Найти"
            );
        }
    }

    function renderMessageRow(
        message,
        loading
    ) {
        const body = byId(
            "datamatrix-storage-body"
        );

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

        if (loading) {
            const wrapper = (
                document.createElement(
                    "span"
                )
            );

            wrapper.className = (
                "datamatrix-storage-loading"
            );

            const spinner = (
                document.createElement(
                    "span"
                )
            );

            spinner.className = (
                "datamatrix-storage-spinner"
            );

            spinner.setAttribute(
                "aria-hidden",
                "true"
            );

            const text = (
                document.createElement(
                    "span"
                )
            );

            text.textContent = message;

            wrapper.append(
                spinner,
                text
            );

            cell.appendChild(
                wrapper
            );

        } else {
            cell.textContent = message;
        }

        row.appendChild(
            cell
        );

        body.appendChild(
            row
        );
    }

    function setMetrics(
        summary
    ) {
        const values = {
            "datamatrix-storage-unit-count": (
                summary.unit_count
            ),

            "datamatrix-storage-source-count": (
                summary.source_count
            ),

            "datamatrix-storage-aggregate-count": (
                summary.aggregate_count
            ),

            "datamatrix-storage-mismatch-count": (
                summary.mismatch_source_count
            )
        };

        Object.entries(
            values
        ).forEach(
            (
                [
                    id,
                    value
                ]
            ) => {
                const element = byId(
                    id
                );

                if (element) {
                    element.textContent = Number(
                        value || 0
                    ).toLocaleString(
                        "ru-RU"
                    );
                }
            }
        );
    }

    function formatDate(
        value
    ) {
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

        return (
            parts.length === 3
                ? (
                    `${parts[2]}.`
                    + `${parts[1]}.`
                    + `${parts[0]}`
                )
                : String(
                    value
                )
        );
    }

    function appendText(
        container,
        value,
        className
    ) {
        if (!value) {
            return;
        }

        const element = (
            document.createElement(
                "div"
            )
        );

        element.className = className;
        element.textContent = value;

        container.appendChild(
            element
        );
    }

    function statusMeta(
        status
    ) {
        const prepared = String(
            status || ""
        ).toUpperCase();

        if (
            prepared === "MATCHED"
        ) {
            return {
                label: "Количество совпало",
                className: "is-success"
            };
        }

        if (
            prepared === "MISMATCH"
        ) {
            return {
                label: "Есть расхождение",
                className: "is-warning"
            };
        }

        return {
            label: "Не проверено",
            className: "is-neutral"
        };
    }

    function productSourceLabel(
        source
    ) {
        const prepared = String(
            source || ""
        ).toUpperCase();

        if (
            prepared
            === "GIS_MT_PRODUCT"
        ) {
            return (
                "Наименование из ГИС МТ"
            );
        }

        if (
            prepared
            === "EDO_DOCUMENT"
        ) {
            return (
                "Наименование из ЭДО"
            );
        }

        return (
            "Источник наименования "
            + "не определён"
        );
    }

    async function copyText(
        value,
        button,
        label
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

                document.body.appendChild(
                    textarea
                );

                textarea.select();

                if (
                    !document.execCommand(
                        "copy"
                    )
                ) {
                    throw new Error(
                        "COPY_FAILED"
                    );
                }

                textarea.remove();
            }

            const previous = (
                button.innerHTML
            );

            button.innerHTML = (
                checkIcon()
            );

            button.classList.add(
                "is-copied"
            );

            button.title = (
                "Скопировано"
            );

            button.disabled = true;

            window.setTimeout(
                () => {
                    button.innerHTML = (
                        previous
                    );

                    button.classList.remove(
                        "is-copied"
                    );

                    button.title = label;
                    button.disabled = false;
                },
                1200
            );

        } catch {
            setMessage(
                "error",
                "Не удалось скопировать значение."
            );
        }
    }

    function createCodeBlock(
        value,
        label
    ) {
        const wrapper = (
            document.createElement(
                "div"
            )
        );

        wrapper.className = (
            "datamatrix-storage-code-cell"
        );

        const code = (
            document.createElement(
                "code"
            )
        );

        code.className = (
            "datamatrix-storage-code"
        );

        code.textContent = (
            value || "—"
        );

        code.title = (
            value || ""
        );

        const button = (
            document.createElement(
                "button"
            )
        );

        button.type = "button";

        button.className = (
            "datamatrix-storage-copy"
        );

        button.innerHTML = (
            copyIcon()
        );

        button.title = label;

        button.setAttribute(
            "aria-label",
            label
        );

        button.disabled = !value;

        button.addEventListener(
            "click",
            () => {
                copyText(
                    value,
                    button,
                    label
                );
            }
        );

        wrapper.append(
            code,
            button
        );

        return wrapper;
    }

    function createUnitCell(
        item
    ) {
        const cell = document.createElement(
            "td"
        );

        cell.appendChild(
            createCodeBlock(
                item.code || "",
                "Копировать КИ единицы"
            )
        );

        const details = [];

        if (item.gtin) {
            details.push(
                `GTIN ${item.gtin}`
            );
        }

        details.push(
            "Количество: 1"
        );

        appendText(
            cell,
            details.join(
                " · "
            ),
            "datamatrix-storage-secondary"
        );

        return cell;
    }

    function createProductCell(
        item
    ) {
        const cell = document.createElement(
            "td"
        );

        appendText(
            cell,
            (
                item.product_name
                || "Наименование не найдено"
            ),
            "datamatrix-storage-primary"
        );

        if (item.product_code) {
            appendText(
                cell,
                `Код товара: ${item.product_code}`,
                "datamatrix-storage-secondary"
            );
        }

        appendText(
            cell,
            productSourceLabel(
                item.product_name_source
            ),
            "datamatrix-storage-secondary"
        );

        if (
            item.document_product_name
            && (
                item.document_product_name
                !== item.product_name
            )
        ) {
            appendText(
                cell,
                (
                    "В документе: "
                    + item.document_product_name
                ),
                "datamatrix-storage-secondary"
            );
        }

        return cell;
    }

    function createSourceCell(
        item
    ) {
        const cell = document.createElement(
            "td"
        );

        const source = (
            item.source || {}
        );

        cell.appendChild(
            createCodeBlock(
                source.code || "",
                "Копировать исходный КИ"
            )
        );

        const details = [
            (
                source.code_kind
                === "AGGREGATE"
                    ? "Агрегат"
                    : "КИ единицы"
            )
        ];

        if (source.gtin) {
            details.push(
                `GTIN ${source.gtin}`
            );
        }

        appendText(
            cell,
            details.join(
                " · "
            ),
            "datamatrix-storage-secondary"
        );

        return cell;
    }

    function createQuantityCell(
        item
    ) {
        const cell = document.createElement(
            "td"
        );

        const source = (
            item.source || {}
        );

        const meta = statusMeta(
            source.quantity_match_status
        );

        const badge = (
            document.createElement(
                "span"
            )
        );

        badge.className = (
            "datamatrix-storage-status "
            + meta.className
        );

        badge.textContent = (
            meta.label
        );

        cell.appendChild(
            badge
        );

        if (
            source.expected_unit_count
            !== null
            && source.expected_unit_count
            !== undefined
            && source.expected_unit_count
            !== ""
        ) {
            appendText(
                cell,
                (
                    "Ожидалось: "
                    + source.expected_unit_count
                    + " · раскрыто: "
                    + (
                        source.actual_unit_count
                        || 0
                    )
                ),
                "datamatrix-storage-secondary"
            );

        } else {
            appendText(
                cell,
                (
                    "Раскрыто единиц: "
                    + (
                        source.actual_unit_count
                        || 0
                    )
                ),
                "datamatrix-storage-secondary"
            );
        }

        if (source.line_quantity) {
            appendText(
                cell,
                (
                    "Количество в строке УПД: "
                    + source.line_quantity
                ),
                "datamatrix-storage-secondary"
            );
        }

        return cell;
    }

    function createOrganizationCell(
        item
    ) {
        const cell = document.createElement(
            "td"
        );

        const organization = (
            item.organization || {}
        );

        appendText(
            cell,
            (
                organization.name
                || "Организация не определена"
            ),
            "datamatrix-storage-primary"
        );

        if (organization.inn) {
            appendText(
                cell,
                `ИНН ${organization.inn}`,
                "datamatrix-storage-secondary"
            );
        }

        appendText(
            cell,
            (
                item.receiver_warehouse_address
                || "Адрес склада не определён"
            ),
            (
                item.receiver_warehouse_address
                    ? "datamatrix-storage-address"
                    : "datamatrix-storage-secondary"
            )
        );

        if (item.source_document_date) {
            appendText(
                cell,
                (
                    "Документ от "
                    + formatDate(
                        item.source_document_date
                    )
                ),
                "datamatrix-storage-secondary"
            );
        }

        return cell;
    }

    function renderRows(
        items
    ) {
        const body = byId(
            "datamatrix-storage-body"
        );

        if (!body) {
            return;
        }

        body.replaceChildren();

        if (!items.length) {
            renderMessageRow(
                (
                    "По заданным условиям "
                    + "ничего не найдено."
                ),
                false
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
                    createUnitCell(
                        item
                    ),

                    createProductCell(
                        item
                    ),

                    createSourceCell(
                        item
                    ),

                    createQuantityCell(
                        item
                    ),

                    createOrganizationCell(
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
        const select = byId(
            "datamatrix-storage-entity"
        );

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

                option.textContent = (
                    `${organization.name} · `
                    + Number(
                        organization.unit_count
                        || 0
                    ).toLocaleString(
                        "ru-RU"
                    )
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

        const previous = byId(
            "datamatrix-storage-previous"
        );

        const next = byId(
            "datamatrix-storage-next"
        );

        const page = byId(
            "datamatrix-storage-page"
        );

        const summary = byId(
            "datamatrix-storage-summary"
        );

        if (previous) {
            previous.disabled = (
                state.loading
                || !pagination.has_previous
            );
        }

        if (next) {
            next.disabled = (
                state.loading
                || !pagination.has_next
            );
        }

        if (page) {
            page.textContent = (
                `Страница ${state.page} `
                + `из ${state.totalPages}`
            );
        }

        const total = Number(
            pagination.total_count || 0
        );

        if (summary) {
            summary.textContent = (
                total
                    ? (
                        "Показано "
                        + pagination.first_item
                        + "–"
                        + pagination.last_item
                        + " из "
                        + total
                    )
                    : "Найдено: 0"
            );
        }
    }

    function currentFilters() {
        return {
            query: String(
                byId(
                    "datamatrix-storage-query"
                )?.value || ""
            ).trim(),

            entityId: String(
                byId(
                    "datamatrix-storage-entity"
                )?.value || ""
            ).trim(),

            quantityStatus: String(
                byId(
                    "datamatrix-storage-quantity-status"
                )?.value || "ALL"
            ).trim().toUpperCase()
        };
    }

    async function loadStorage(
        page
    ) {
        const filters = (
            currentFilters()
        );

        if (
            filters.query
            && filters.query.length < 3
        ) {
            setMessage(
                "error",
                (
                    "Для поиска введите "
                    + "не менее трёх символов."
                )
            );

            byId(
                "datamatrix-storage-query"
            )?.focus();

            return;
        }

        state.abortController?.abort();

        const controller = (
            new AbortController()
        );

        state.abortController = (
            controller
        );

        setLoading(
            true
        );

        setMessage(
            "",
            ""
        );

        renderMessageRow(
            "Загрузка хранилища…",
            true
        );

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

        if (
            filters.quantityStatus
            !== "ALL"
        ) {
            url.searchParams.set(
                "quantity_status",
                filters.quantityStatus
            );
        }

        try {
            const response = await fetch(
                url.toString(),
                {
                    method: "GET",

                    headers: {
                        "Accept": "application/json"
                    },

                    cache: "no-store",

                    signal: (
                        controller.signal
                    )
                }
            );

            let payload = null;

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

            setMetrics(
                payload.summary || {}
            );

            renderPagination(
                payload.pagination || {}
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
                    + "хранилище DataMatrix."
                )
            );

            setMessage(
                "error",
                message
            );

            renderMessageRow(
                message,
                false
            );

            setMetrics(
                {}
            );

            const summary = byId(
                "datamatrix-storage-summary"
            );

            if (summary) {
                summary.textContent = "—";
            }

        } finally {
            if (
                state.abortController
                === controller
            ) {
                state.abortController = null;
            }

            setLoading(
                false
            );

            const previous = byId(
                "datamatrix-storage-previous"
            );

            const next = byId(
                "datamatrix-storage-next"
            );

            if (previous) {
                previous.disabled = (
                    state.page <= 1
                );
            }

            if (next) {
                next.disabled = (
                    state.page
                    >= state.totalPages
                );
            }
        }
    }

    function resetSearch() {
        const query = byId(
            "datamatrix-storage-query"
        );

        const entity = byId(
            "datamatrix-storage-entity"
        );

        const status = byId(
            "datamatrix-storage-quantity-status"
        );

        if (query) {
            query.value = "";
        }

        if (entity) {
            entity.value = "";
        }

        if (status) {
            status.value = "ALL";
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
        byId(
            "open-datamatrix-storage"
        )?.addEventListener(
            "click",
            openStorage
        );

        document.querySelectorAll(
            "[data-close-datamatrix-storage]"
        ).forEach(
            (element) => {
                element.addEventListener(
                    "click",
                    closeStorage
                );
            }
        );

        byId(
            "datamatrix-storage-form"
        )?.addEventListener(
            "submit",
            (event) => {
                event.preventDefault();

                loadStorage(
                    1
                );
            }
        );

        byId(
            "datamatrix-storage-reset"
        )?.addEventListener(
            "click",
            resetSearch
        );

        byId(
            "datamatrix-storage-previous"
        )?.addEventListener(
            "click",
            () => {
                if (
                    !state.loading
                    && state.page > 1
                ) {
                    loadStorage(
                        state.page - 1
                    );
                }
            }
        );

        byId(
            "datamatrix-storage-next"
        )?.addEventListener(
            "click",
            () => {
                if (
                    !state.loading
                    && state.page
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
                const modal = byId(
                    "datamatrix-storage-modal"
                );

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