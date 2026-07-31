(function () {
    "use strict";

    const API_URL = "/api/violations";
    const PAGE_SIZE = 100;

    const state = {
        page: 1,
        totalPages: 1,
        loading: false,
        abortController: null
    };

    function iconSvg() {
        return `
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 3.5L21 19H3L12 3.5Z"></path>
                <path d="M12 9V13.5"></path>
                <path d="M12 17H12.01"></path>
            </svg>
        `;
    }

    function copySvg() {
        return `
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="8" y="8" width="11" height="11" rx="2"></rect>
                <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path>
            </svg>
        `;
    }

    function createInterface() {
        if (document.getElementById("violations-modal")) {
            return;
        }

        const rail = document.querySelector(".page-action-rail");

        if (!rail) {
            return;
        }

        const button = document.createElement("button");
        button.id = "open-violations";
        button.type = "button";
        button.className = "button button--violations";
        button.innerHTML = `
            <span class="violations-button__icon">${iconSvg()}</span>
            <span class="violations-button__text">
                <span class="violations-button__title">Отклонения</span>
                <span class="violations-button__subtitle">Контроль ГИС МТ</span>
            </span>
        `;
        rail.appendChild(button);

        const modal = document.createElement("div");
        modal.id = "violations-modal";
        modal.className = "violations-modal";
        modal.hidden = true;
        modal.setAttribute("role", "dialog");
        modal.setAttribute("aria-modal", "true");
        modal.setAttribute("aria-labelledby", "violations-title");
        modal.innerHTML = `
            <div class="violations-backdrop" data-close-violations></div>
            <section class="violations-window">
                <header class="violations-header">
                    <div>
                        <h2 id="violations-title">Отклонения</h2>
                        <p>Отклонения оборота подконтрольной продукции по данным ГИС МТ</p>
                    </div>
                    <button class="violations-close" type="button" aria-label="Закрыть" data-close-violations>×</button>
                </header>

                <form id="violations-form" class="violations-toolbar" novalidate>
                    <div class="violations-field violations-field--search">
                        <label for="violations-query">Поиск</label>
                        <input
                            id="violations-query"
                            type="search"
                            maxlength="200"
                            autocomplete="off"
                            placeholder="Товар, КИ, GTIN, вид отклонения, адрес"
                        >
                    </div>

                    <div class="violations-field">
                        <label for="violations-entity">Организация</label>
                        <select id="violations-entity">
                            <option value="">Все организации</option>
                        </select>
                    </div>

                    <div class="violations-field">
                        <label for="violations-kind">Вид отклонения</label>
                        <select id="violations-kind">
                            <option value="">Все виды отклонений</option>
                        </select>
                    </div>

                    <div class="violations-field">
                        <label for="violations-period-from">Период с</label>
                        <input id="violations-period-from" type="date">
                    </div>

                    <div class="violations-field">
                        <label for="violations-period-to">Период по</label>
                        <input id="violations-period-to" type="date">
                    </div>

                    <div class="violations-field">
                        <label for="violations-nivellated">Нивелировано</label>
                        <select id="violations-nivellated">
                            <option value="all">Все</option>
                            <option value="no">Нет</option>
                            <option value="yes">Да</option>
                        </select>
                    </div>

                    <div class="violations-actions">
                        <button id="violations-apply" class="button button--primary" type="submit">Применить</button>
                        <button id="violations-reset" class="button button--secondary" type="button">Сбросить</button>
                    </div>
                </form>

                <div id="violations-message" class="violations-message" hidden></div>

                <div class="violations-content">
                    <div class="violations-table-wrap">
                        <table class="violations-table">
                            <thead>
                                <tr>
                                    <th>Дата операции</th>
                                    <th>Организация</th>
                                    <th>Товарная позиция</th>
                                    <th>КИ / GTIN</th>
                                    <th>Вид отклонения</th>
                                    <th>Результат</th>
                                    <th>Торговая точка</th>
                                    <th>ККТ</th>
                                    <th>Нивелировано</th>
                                </tr>
                            </thead>
                            <tbody id="violations-body">
                                <tr><td colspan="9" class="violations-empty">Загрузка…</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <footer class="violations-footer">
                    <div id="violations-summary" class="violations-summary">—</div>
                    <div class="violations-pagination">
                        <button id="violations-previous" class="button button--secondary" type="button" disabled>Назад</button>
                        <span id="violations-page">Страница 1 из 1</span>
                        <button id="violations-next" class="button button--secondary" type="button" disabled>Далее</button>
                    </div>
                </footer>
            </section>
        `;
        document.body.appendChild(modal);
        bindEvents();
    }

    function element(id) {
        return document.getElementById(id);
    }

    function syncBodyModalState() {
        const ids = [
            "entity-modal",
            "document-catalog-modal",
            "datamatrix-storage-modal",
            "violations-modal"
        ];

        document.body.classList.toggle(
            "modal-open",
            ids.some((id) => {
                const modal = element(id);
                return modal && !modal.hidden;
            })
        );
    }

    function showMessage(kind, message) {
        const target = element("violations-message");

        if (!target) {
            return;
        }

        target.hidden = !message;
        target.textContent = message || "";
        target.className = "violations-message";

        if (message) {
            target.classList.add(`violations-message--${kind}`);
        }
    }

    function formatDate(value) {
        if (!value) {
            return "—";
        }

        const parsed = new Date(value);

        if (Number.isNaN(parsed.getTime())) {
            return String(value);
        }

        return new Intl.DateTimeFormat("ru-RU", {
            dateStyle: "short",
            timeStyle: "medium"
        }).format(parsed);
    }

    function secondary(container, text) {
        if (!text) {
            return;
        }

        const value = document.createElement("div");
        value.className = "violations-secondary";
        value.textContent = text;
        container.appendChild(value);
    }

    function productSourceText(source) {
        const values = {
            DATAMATRIX_LINK: "Определено по связанному КИ",
            CODE_HASH: "Определено по коду маркировки",
            GTIN: "Определено по GTIN в хранилище КИ",
            GTIN_ENTITY: "Определено по GTIN организации",
            GTIN_GLOBAL: "Определено по GTIN в общем хранилище",
            UPD_LINE: "Определено по товарной строке УПД",
            NOT_FOUND: "GTIN не найден в хранилище КИ"
        };

        return values[source] || values.NOT_FOUND;
    }

    async function copyValue(value, button) {
        if (!value) {
            return;
        }

        try {
            await navigator.clipboard.writeText(value);
            button.classList.add("is-copied");
            window.setTimeout(() => {
                button.classList.remove("is-copied");
            }, 1000);
        } catch (_error) {
            showMessage("error", "Не удалось скопировать КИ.");
        }
    }

    function renderRows(items) {
        const body = element("violations-body");
        body.replaceChildren();

        if (!items.length) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 9;
            cell.className = "violations-empty";
            cell.textContent = "По заданным условиям отклонения не найдены.";
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }

        const fragment = document.createDocumentFragment();

        items.forEach((item) => {
            const row = document.createElement("tr");

            const operationCell = document.createElement("td");
            operationCell.textContent = formatDate(
                item.operation_at || item.registered_at
            );
            secondary(
                operationCell,
                item.violation_number
                    ? `№ ${item.violation_number}`
                    : ""
            );

            const organizationCell = document.createElement("td");
            organizationCell.textContent = (
                item.organization?.name || "—"
            );
            secondary(
                organizationCell,
                item.organization?.inn
                    ? `ИНН ${item.organization.inn}`
                    : ""
            );

            const productCell = document.createElement("td");
            const productName = (
                item.product?.name
                || item.product_name
                || ""
            );
            const productCode = (
                item.product?.code
                || item.product_code
                || ""
            );
            const productMatchSource = (
                item.product?.match_source
                || item.product_match_source
                || "NOT_FOUND"
            );

            const productTitle = document.createElement("div");
            productTitle.className = "violations-product-name";

            if (productName) {
                productTitle.textContent = productName;
            } else {
                productTitle.textContent = "Наименование не определено";
                productTitle.classList.add(
                    "violations-product-name--missing"
                );
            }

            productCell.appendChild(productTitle);

            secondary(
                productCell,
                productCode
                    ? `Код товара: ${productCode}`
                    : ""
            );

            const source = document.createElement("div");
            source.className = (
                "violations-product-source "
                + (
                    productMatchSource === "NOT_FOUND"
                        ? "violations-product-source--missing"
                        : ""
                )
            );
            source.textContent = productSourceText(
                productMatchSource
            );
            productCell.appendChild(source);

            const codeCell = document.createElement("td");
            const codeWrapper = document.createElement("div");
            codeWrapper.className = "violations-code-cell";

            const code = document.createElement("code");
            code.textContent = item.code || item.gtin || "—";
            code.title = item.code || item.gtin || "";

            const copyButton = document.createElement("button");
            copyButton.type = "button";
            copyButton.className = "violations-copy";
            copyButton.innerHTML = copySvg();
            copyButton.title = "Копировать КИ";
            copyButton.disabled = !item.code;
            copyButton.addEventListener(
                "click",
                () => copyValue(
                    item.code,
                    copyButton
                )
            );

            codeWrapper.append(
                code,
                copyButton
            );
            codeCell.appendChild(codeWrapper);

            secondary(
                codeCell,
                item.gtin
                    ? `GTIN ${item.gtin}`
                    : ""
            );

            const kindCell = document.createElement("td");
            kindCell.textContent = (
                item.violation_kind || "—"
            );
            secondary(
                kindCell,
                item.product_group_name
                || item.product_group
                || ""
            );

            const resultCell = document.createElement("td");
            resultCell.textContent = (
                item.violation_result || "—"
            );
            secondary(
                resultCell,
                item.permission_mode_result || ""
            );

            const locationCell = document.createElement("td");
            locationCell.textContent = (
                item.location_address || "—"
            );
            secondary(
                locationCell,
                item.fias_id
                    ? `ФИАС ${item.fias_id}`
                    : ""
            );

            const kktCell = document.createElement("td");
            kktCell.textContent = (
                item.kkt_registration_number || "—"
            );
            secondary(
                kktCell,
                item.fiscal_drive_number
                    ? `ФН ${item.fiscal_drive_number}`
                    : ""
            );
            secondary(
                kktCell,
                item.document_number
                    ? `Документ ${item.document_number}`
                    : ""
            );

            const nivellatedCell = document.createElement("td");
            const badge = document.createElement("span");
            badge.className = "violations-badge";

            if (item.is_nivellated === true) {
                badge.classList.add(
                    "violations-badge--yes"
                );
                badge.textContent = "Да";
            } else if (item.is_nivellated === false) {
                badge.classList.add(
                    "violations-badge--no"
                );
                badge.textContent = "Нет";
            } else {
                badge.classList.add(
                    "violations-badge--unknown"
                );
                badge.textContent = "—";
            }

            nivellatedCell.appendChild(badge);

            row.append(
                operationCell,
                organizationCell,
                productCell,
                codeCell,
                kindCell,
                resultCell,
                locationCell,
                kktCell,
                nivellatedCell
            );

            fragment.appendChild(row);
        });

        body.appendChild(fragment);
    }

    function populateOrganizations(
        organizations,
        selected
    ) {
        const select = element("violations-entity");
        select.replaceChildren();

        const all = document.createElement("option");
        all.value = "";
        all.textContent = "Все организации";
        select.appendChild(all);

        organizations.forEach((organization) => {
            const option = document.createElement("option");
            option.value = String(organization.id);
            option.textContent = (
                `${organization.name} · `
                + `${organization.violation_count}`
            );
            select.appendChild(option);
        });

        select.value = selected || "";
    }

    function populateViolationKinds(
        violationKinds,
        selected
    ) {
        const select = element("violations-kind");
        select.replaceChildren();

        const all = document.createElement("option");
        all.value = "";
        all.textContent = "Все виды отклонений";
        select.appendChild(all);

        violationKinds.forEach((item) => {
            const option = document.createElement("option");
            option.value = item.name || "";
            option.textContent = (
                `${item.name || "Без наименования"} · `
                + `${item.violation_count || 0}`
            );
            select.appendChild(option);
        });

        select.value = selected || "";
    }

    function renderPagination(pagination) {
        state.page = Number(
            pagination.page || 1
        );

        state.totalPages = Number(
            pagination.total_pages || 1
        );

        element("violations-page").textContent = (
            `Страница ${state.page} `
            + `из ${state.totalPages}`
        );

        element("violations-previous").disabled = (
            !pagination.has_previous
        );

        element("violations-next").disabled = (
            !pagination.has_next
        );

        element("violations-summary").textContent = (
            pagination.total_count
                ? (
                    `Показано ${pagination.first_item}`
                    + `–${pagination.last_item} `
                    + `из ${pagination.total_count}`
                )
                : "Найдено: 0"
        );
    }

    function setLoading(value) {
        state.loading = value;

        [
            "violations-query",
            "violations-entity",
            "violations-kind",
            "violations-period-from",
            "violations-period-to",
            "violations-nivellated",
            "violations-apply",
            "violations-reset"
        ].forEach((id) => {
            const target = element(id);

            if (target) {
                target.disabled = value;
            }
        });

        element("violations-apply").textContent = (
            value
                ? "Загрузка…"
                : "Применить"
        );
    }

    function filters() {
        return {
            q: element(
                "violations-query"
            ).value.trim(),

            entityId: element(
                "violations-entity"
            ).value,

            violationKind: element(
                "violations-kind"
            ).value,

            dateFrom: element(
                "violations-period-from"
            ).value,

            dateTo: element(
                "violations-period-to"
            ).value,

            nivellated: element(
                "violations-nivellated"
            ).value
        };
    }

    async function load(page) {
        const current = filters();

        if (
            current.q
            && current.q.length < 3
        ) {
            showMessage(
                "error",
                "Для поиска введите не менее трёх символов."
            );
            return;
        }

        state.abortController?.abort();

        const controller = new AbortController();
        state.abortController = controller;

        setLoading(true);
        showMessage("", "");

        const url = new URL(
            API_URL,
            window.location.origin
        );

        url.searchParams.set(
            "page",
            String(page)
        );

        url.searchParams.set(
            "page_size",
            String(PAGE_SIZE)
        );

        if (current.q) {
            url.searchParams.set(
                "q",
                current.q
            );
        }

        if (current.entityId) {
            url.searchParams.set(
                "entity_id",
                current.entityId
            );
        }

        if (current.violationKind) {
            url.searchParams.set(
                "violation_kind",
                current.violationKind
            );
        }

        if (current.dateFrom) {
            url.searchParams.set(
                "date_from",
                current.dateFrom
            );
        }

        if (current.dateTo) {
            url.searchParams.set(
                "date_to",
                current.dateTo
            );
        }

        if (current.nivellated) {
            url.searchParams.set(
                "nivellated",
                current.nivellated
            );
        }

        try {
            const response = await fetch(
                url,
                {
                    headers: {
                        Accept: "application/json"
                    },
                    cache: "no-store",
                    signal: controller.signal
                }
            );

            const payload = await response.json();

            if (!response.ok) {
                throw new Error(
                    payload.error
                    || "Не удалось загрузить отклонения."
                );
            }

            populateOrganizations(
                payload.organizations || [],
                current.entityId
            );

            populateViolationKinds(
                payload.violation_kinds || [],
                current.violationKind
            );

            renderRows(
                payload.items || []
            );

            renderPagination(
                payload.pagination || {}
            );

        } catch (error) {
            if (error.name !== "AbortError") {
                showMessage(
                    "error",
                    error.message
                    || "Не удалось загрузить отклонения."
                );

                renderRows([]);
            }

        } finally {
            if (
                state.abortController
                === controller
            ) {
                state.abortController = null;
            }

            setLoading(false);
        }
    }

    function openViolations() {
        const modal = element(
            "violations-modal"
        );

        modal.hidden = false;

        syncBodyModalState();
        load(1);
    }

    function closeViolations() {
        state.abortController?.abort();

        element(
            "violations-modal"
        ).hidden = true;

        syncBodyModalState();

        element(
            "open-violations"
        )?.focus();
    }

    function reset() {
        element(
            "violations-query"
        ).value = "";

        element(
            "violations-entity"
        ).value = "";

        element(
            "violations-kind"
        ).value = "";

        element(
            "violations-period-from"
        ).value = "";

        element(
            "violations-period-to"
        ).value = "";

        element(
            "violations-nivellated"
        ).value = "all";

        load(1);
    }

    function bindEvents() {
        element(
            "open-violations"
        )?.addEventListener(
            "click",
            openViolations
        );

        document
            .querySelectorAll(
                "[data-close-violations]"
            )
            .forEach((target) => {
                target.addEventListener(
                    "click",
                    closeViolations
                );
            });

        element(
            "violations-form"
        )?.addEventListener(
            "submit",
            (event) => {
                event.preventDefault();
                load(1);
            }
        );

        element(
            "violations-reset"
        )?.addEventListener(
            "click",
            reset
        );

        element(
            "violations-previous"
        )?.addEventListener(
            "click",
            () => {
                if (state.page > 1) {
                    load(state.page - 1);
                }
            }
        );

        element(
            "violations-next"
        )?.addEventListener(
            "click",
            () => {
                if (
                    state.page
                    < state.totalPages
                ) {
                    load(state.page + 1);
                }
            }
        );

        document.addEventListener(
            "keydown",
            (event) => {
                const modal = element(
                    "violations-modal"
                );

                if (
                    event.key === "Escape"
                    && modal
                    && !modal.hidden
                ) {
                    closeViolations();
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