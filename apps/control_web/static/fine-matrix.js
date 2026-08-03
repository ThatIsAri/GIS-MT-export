(function () {
    "use strict";

    const API_URL = "/api/fine-matrix";
    const RESET_URL = "/api/fine-matrix/reset";

    const state = {
        loaded: false,
        loading: false,
        dirty: false,
        items: [],
        abortController: null
    };

    const byId = (id) => document.getElementById(id);


    function matrixIcon() {
        return `
            <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect
                    x="3"
                    y="4"
                    width="18"
                    height="16"
                    rx="2"
                ></rect>

                <path d="M3 9H21"></path>
                <path d="M10 4V20"></path>
                <path d="M15.5 12.5V16.5"></path>
                <path d="M13.5 14.5H17.5"></path>
            </svg>
        `;
    }


    function createInterface() {
        if (
            byId(
                "fine-matrix-modal"
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

        button.id = "open-fine-matrix";
        button.type = "button";

        button.className = (
            "button button--fine-matrix"
        );

        button.innerHTML = `
            <span
                class="fine-matrix-button__icon"
                aria-hidden="true"
            >
                ${matrixIcon()}
            </span>

            <span
                class="fine-matrix-button__text"
            >
                <span
                    class="fine-matrix-button__title"
                >
                    Матрица штрафов
                </span>

                <span
                    class="fine-matrix-button__subtitle"
                >
                    Расчёт рисков
                </span>
            </span>
        `;

        const violationsButton = byId(
            "open-violations"
        );

        if (
            violationsButton
            && violationsButton.parentElement
            === rail
        ) {
            violationsButton.insertAdjacentElement(
                "afterend",
                button
            );

        } else {
            rail.appendChild(
                button
            );
        }

        const modal = document.createElement(
            "div"
        );

        modal.id = "fine-matrix-modal";
        modal.className = "fine-matrix-modal";
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
            "fine-matrix-title"
        );

        modal.innerHTML = `
            <div
                class="fine-matrix-backdrop"
                data-close-fine-matrix
            ></div>

            <section
                class="fine-matrix-window"
            >
                <header
                    class="fine-matrix-header"
                >
                    <div>
                        <h2
                            id="fine-matrix-title"
                        >
                            Матрица штрафов
                        </h2>

                        <p>
                            Значения используются
                            для расчёта фактических
                            и вероятных финансовых рисков.
                        </p>
                    </div>

                    <button
                        class="fine-matrix-close"
                        type="button"
                        aria-label="Закрыть матрицу"
                        data-close-fine-matrix
                    >
                        ×
                    </button>
                </header>

                <div
                    id="fine-matrix-message"
                    class="fine-matrix-message"
                    hidden
                ></div>

                <div
                    class="fine-matrix-information"
                >
                    <div
                        class="fine-matrix-information__item"
                    >
                        <span>
                            Действует с
                        </span>

                        <strong
                            id="fine-matrix-effective-from"
                        >
                            —
                        </strong>
                    </div>

                    <div
                        class="
                            fine-matrix-information__item
                            fine-matrix-information__item--legal
                        "
                    >
                        <span>
                            Основание
                        </span>

                        <strong
                            id="fine-matrix-legal-document"
                        >
                            —
                        </strong>
                    </div>
                </div>

                <div
                    class="fine-matrix-content"
                >
                    <div
                        class="fine-matrix-table-wrap"
                    >
                        <table
                            class="fine-matrix-table"
                        >
                            <thead>
                                <tr>
                                    <th>
                                        Отклонение
                                    </th>

                                    <th>
                                        ИП, ₽
                                    </th>

                                    <th>
                                        Юрлицо, ₽
                                    </th>
                                </tr>
                            </thead>

                            <tbody
                                id="fine-matrix-body"
                            >
                                <tr>
                                    <td
                                        colspan="3"
                                        class="fine-matrix-empty"
                                    >
                                        Загрузка…
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <footer
                    class="fine-matrix-footer"
                >
                    <div
                        id="fine-matrix-save-state"
                        class="fine-matrix-save-state"
                    >
                        Изменений нет
                    </div>

                    <div
                        class="fine-matrix-actions"
                    >
                        <button
                            id="fine-matrix-reset"
                            class="button button--secondary"
                            type="button"
                        >
                            Вернуть нормативные значения
                        </button>

                        <button
                            id="fine-matrix-save"
                            class="button button--primary"
                            type="button"
                            disabled
                        >
                            Сохранить изменения
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
        const modalIds = [
            "entity-modal",
            "document-catalog-modal",
            "datamatrix-storage-modal",
            "violations-modal",
            "fine-matrix-modal",
            "job-details-modal"
        ];

        const ordinaryModalOpened = (
            modalIds.some(
                (id) => {
                    const modal = byId(
                        id
                    );

                    return (
                        modal
                        && !modal.hidden
                    );
                }
            )
        );

        const pipelineModal = (
            document.querySelector(
                "[data-pipeline-config-backdrop]"
            )
        );

        document.body.classList.toggle(
            "modal-open",
            Boolean(
                ordinaryModalOpened
                || (
                    pipelineModal
                    && !pipelineModal.hidden
                )
            )
        );
    }


    function showMessage(
        kind,
        message
    ) {
        const target = byId(
            "fine-matrix-message"
        );

        if (!target) {
            return;
        }

        if (!message) {
            target.hidden = true;
            target.textContent = "";

            target.className = (
                "fine-matrix-message"
            );

            return;
        }

        target.hidden = false;
        target.textContent = message;

        target.className = (
            "fine-matrix-message "
            + `fine-matrix-message--${kind}`
        );
    }


    function renderLoading() {
        const body = byId(
            "fine-matrix-body"
        );

        if (!body) {
            return;
        }

        body.innerHTML = `
            <tr>
                <td
                    colspan="3"
                    class="fine-matrix-empty"
                >
                    <span
                        class="fine-matrix-loading"
                    >
                        <span
                            class="fine-matrix-spinner"
                            aria-hidden="true"
                        ></span>

                        <span>
                            Загрузка матрицы…
                        </span>
                    </span>
                </td>
            </tr>
        `;
    }


    function parseNumber(
        value
    ) {
        const prepared = String(
            value ?? ""
        )
            .trim()
            .replaceAll(
                "\u00a0",
                ""
            )
            .replaceAll(
                " ",
                ""
            )
            .replace(
                ",",
                "."
            );

        if (!prepared) {
            return null;
        }

        const number = Number(
            prepared
        );

        return Number.isFinite(
            number
        )
            ? number
            : null;
    }


    function normalizeAmount(
        value
    ) {
        const number = parseNumber(
            value
        );

        return (
            number === null
                ? ""
                : number.toFixed(
                    2
                )
        );
    }


    function formatAmount(
        value
    ) {
        const number = parseNumber(
            value
        );

        if (number === null) {
            return "";
        }

        return new Intl.NumberFormat(
            "ru-RU",
            {
                minimumFractionDigits: 0,
                maximumFractionDigits: 2
            }
        ).format(
            number
        );
    }


    function formatDate(
        value
    ) {
        if (!value) {
            return "—";
        }

        const parts = String(
            value
        )
            .slice(
                0,
                10
            )
            .split(
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


    function calculationModeText(
        item
    ) {
        const mode = String(
            item.calculation_mode || ""
        ).toUpperCase();

        if (
            mode === "PER_UNIT"
        ) {
            return (
                "Сумма применяется "
                + "к каждой единице товара."
            );
        }

        if (
            mode === "FIXED_TIER"
        ) {
            return (
                "Фиксированная сумма "
                + "для указанного диапазона."
            );
        }

        return "";
    }


    function quantityRangeText(
        item
    ) {
        const from = (
            item.quantity_from
        );

        const to = (
            item.quantity_to
        );

        if (
            from === null
            && to === null
        ) {
            return "";
        }

        if (
            from !== null
            && to !== null
        ) {
            return (
                `Количество: ${from}–${to}.`
            );
        }

        if (
            from !== null
        ) {
            return (
                `Количество: от ${from}.`
            );
        }

        return (
            `Количество: до ${to}.`
        );
    }


    function helpItems(
        item
    ) {
        const result = [];

        if (
            item.product_scope
        ) {
            result.push(
                {
                    label: "Товары",
                    value: item.product_scope
                }
            );
        }

        const quantity = (
            quantityRangeText(
                item
            )
        );

        if (quantity) {
            result.push(
                {
                    label: "Диапазон",
                    value: quantity
                }
            );
        }

        const calculation = (
            calculationModeText(
                item
            )
        );

        if (calculation) {
            result.push(
                {
                    label: "Расчёт",
                    value: calculation
                }
            );
        }

        if (
            item.calculation_note
        ) {
            result.push(
                {
                    label: "Примечание",
                    value: item.calculation_note
                }
            );
        }

        if (
            item.legal_basis
        ) {
            result.push(
                {
                    label: "Основание",
                    value: item.legal_basis
                }
            );
        }

        return result;
    }


    function floatingHelpElement() {
        let tooltip = byId(
            "fine-matrix-floating-help"
        );

        if (tooltip) {
            return tooltip;
        }

        tooltip = document.createElement(
            "div"
        );

        tooltip.id = (
            "fine-matrix-floating-help"
        );

        tooltip.className = (
            "fine-matrix-floating-help"
        );

        tooltip.setAttribute(
            "role",
            "tooltip"
        );

        tooltip.hidden = true;

        document.body.appendChild(
            tooltip
        );

        return tooltip;
    }


    function fillFloatingHelp(
        tooltip,
        item
    ) {
        tooltip.replaceChildren();

        const title = document.createElement(
            "div"
        );

        title.className = (
            "fine-matrix-floating-help__title"
        );

        title.textContent = "Справка";

        tooltip.appendChild(
            title
        );

        helpItems(
            item
        ).forEach(
            (detail) => {
                const row = document.createElement(
                    "div"
                );

                row.className = (
                    "fine-matrix-floating-help__row"
                );

                const label = document.createElement(
                    "div"
                );

                label.className = (
                    "fine-matrix-floating-help__label"
                );

                label.textContent = (
                    detail.label
                );

                const value = document.createElement(
                    "div"
                );

                value.className = (
                    "fine-matrix-floating-help__value"
                );

                value.textContent = (
                    detail.value
                );

                row.append(
                    label,
                    value
                );

                tooltip.appendChild(
                    row
                );
            }
        );
    }


    function positionFloatingHelp(
        button,
        tooltip
    ) {
        const margin = 12;
        const gap = 9;

        const buttonRect = (
            button.getBoundingClientRect()
        );

        const width = Math.min(
            360,
            Math.max(
                240,
                window.innerWidth
                - margin * 2
            )
        );

        tooltip.style.width = (
            `${width}px`
        );

        tooltip.style.left = "0px";
        tooltip.style.top = "0px";

        const tooltipRect = (
            tooltip.getBoundingClientRect()
        );

        let left = (
            buttonRect.right
            - width
        );

        left = Math.max(
            margin,
            Math.min(
                left,
                window.innerWidth
                - width
                - margin
            )
        );

        let placement = "above";

        let top = (
            buttonRect.top
            - tooltipRect.height
            - gap
        );

        if (
            top < margin
        ) {
            placement = "below";

            top = (
                buttonRect.bottom
                + gap
            );
        }

        if (
            top
            + tooltipRect.height
            > window.innerHeight
            - margin
        ) {
            top = Math.max(
                margin,
                window.innerHeight
                - tooltipRect.height
                - margin
            );
        }

        const anchorCenter = (
            buttonRect.left
            + buttonRect.width / 2
        );

        const arrowLeft = Math.max(
            18,
            Math.min(
                width - 18,
                anchorCenter - left
            )
        );

        tooltip.dataset.placement = (
            placement
        );

        tooltip.style.left = (
            `${Math.round(left)}px`
        );

        tooltip.style.top = (
            `${Math.round(top)}px`
        );

        tooltip.style.setProperty(
            "--fine-matrix-help-arrow-left",
            `${Math.round(arrowLeft)}px`
        );
    }


    function showFloatingHelp(
        button,
        item
    ) {
        const tooltip = (
            floatingHelpElement()
        );

        fillFloatingHelp(
            tooltip,
            item
        );

        tooltip.hidden = false;

        window.requestAnimationFrame(
            () => {
                if (
                    !tooltip.hidden
                ) {
                    positionFloatingHelp(
                        button,
                        tooltip
                    );
                }
            }
        );
    }


    function hideFloatingHelp() {
        const tooltip = byId(
            "fine-matrix-floating-help"
        );

        if (!tooltip) {
            return;
        }

        tooltip.hidden = true;
        tooltip.replaceChildren();

        tooltip.removeAttribute(
            "data-placement"
        );

        tooltip.style.removeProperty(
            "left"
        );

        tooltip.style.removeProperty(
            "top"
        );

        tooltip.style.removeProperty(
            "width"
        );

        tooltip.style.removeProperty(
            "--fine-matrix-help-arrow-left"
        );
    }


    function createHelpBadge(
        item
    ) {
        if (
            !helpItems(
                item
            ).length
        ) {
            return null;
        }

        const wrapper = document.createElement(
            "div"
        );

        wrapper.className = (
            "fine-matrix-help"
        );

        const button = document.createElement(
            "button"
        );

        button.type = "button";

        button.className = (
            "fine-matrix-help__button"
        );

        button.setAttribute(
            "aria-label",
            (
                "Показать справку "
                + "по отклонению: "
                + item.violation_name
            )
        );

        button.title = "Справка";
        button.textContent = "?";

        button.addEventListener(
            "mouseenter",
            () => {
                showFloatingHelp(
                    button,
                    item
                );
            }
        );

        button.addEventListener(
            "mouseleave",
            hideFloatingHelp
        );

        button.addEventListener(
            "focus",
            () => {
                showFloatingHelp(
                    button,
                    item
                );
            }
        );

        button.addEventListener(
            "blur",
            hideFloatingHelp
        );

        wrapper.appendChild(
            button
        );

        return wrapper;
    }


    function createViolationCell(
        item
    ) {
        const cell = document.createElement(
            "td"
        );

        cell.className = (
            "fine-matrix-violation"
        );

        const title = document.createElement(
            "div"
        );

        title.className = (
            "fine-matrix-violation__title"
        );

        title.textContent = (
            item.violation_name
        );

        cell.appendChild(
            title
        );

        const help = createHelpBadge(
            item
        );

        if (help) {
            cell.appendChild(
                help
            );
        }

        return cell;
    }


    function createAmountInput(
        item,
        fieldName,
        label
    ) {
        const input = document.createElement(
            "input"
        );

        input.type = "text";
        input.inputMode = "decimal";
        input.autocomplete = "off";

        input.className = (
            "fine-matrix-amount"
        );

        input.value = formatAmount(
            item[
                fieldName
            ]
        );

        input.dataset.amountField = (
            fieldName
        );

        input.setAttribute(
            "aria-label",
            `${label}: ${item.violation_name}`
        );

        input.addEventListener(
            "focus",
            () => {
                input.value = normalizeAmount(
                    input.value
                );

                input.select();
            }
        );

        input.addEventListener(
            "input",
            () => {
                input.classList.remove(
                    "is-invalid"
                );

                setDirty(
                    true
                );
            }
        );

        input.addEventListener(
            "blur",
            () => {
                const number = parseNumber(
                    input.value
                );

                if (
                    number === null
                    || number < 0
                ) {
                    input.classList.add(
                        "is-invalid"
                    );

                    return;
                }

                input.classList.remove(
                    "is-invalid"
                );

                input.value = formatAmount(
                    number
                );
            }
        );

        return input;
    }


    function renderRows(
        items
    ) {
        hideFloatingHelp();

        const body = byId(
            "fine-matrix-body"
        );

        if (!body) {
            return;
        }

        body.replaceChildren();

        if (!items.length) {
            body.innerHTML = `
                <tr>
                    <td
                        colspan="3"
                        class="fine-matrix-empty"
                    >
                        Активные строки матрицы
                        не найдены.
                    </td>
                </tr>
            `;

            return;
        }

        const fragment = (
            document.createDocumentFragment()
        );

        items.forEach(
            (item) => {
                const row = document.createElement(
                    "tr"
                );

                row.dataset.ruleId = String(
                    item.id
                );

                const individualCell = (
                    document.createElement(
                        "td"
                    )
                );

                individualCell.className = (
                    "fine-matrix-amount-cell"
                );

                individualCell.appendChild(
                    createAmountInput(
                        item,
                        (
                            "individual_"
                            + "entrepreneur_amount"
                        ),
                        "Штраф для ИП"
                    )
                );

                const legalCell = (
                    document.createElement(
                        "td"
                    )
                );

                legalCell.className = (
                    "fine-matrix-amount-cell"
                );

                legalCell.appendChild(
                    createAmountInput(
                        item,
                        "legal_entity_amount",
                        (
                            "Штраф для "
                            + "юридического лица"
                        )
                    )
                );

                row.append(
                    createViolationCell(
                        item
                    ),
                    individualCell,
                    legalCell
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


    function setDirty(
        dirty
    ) {
        state.dirty = Boolean(
            dirty
        );

        const saveButton = byId(
            "fine-matrix-save"
        );

        const saveState = byId(
            "fine-matrix-save-state"
        );

        if (saveButton) {
            saveButton.disabled = (
                state.loading
                || !state.dirty
            );
        }

        if (saveState) {
            saveState.textContent = (
                state.dirty
                    ? (
                        "Есть несохранённые "
                        + "изменения"
                    )
                    : "Изменений нет"
            );

            saveState.classList.toggle(
                "is-dirty",
                state.dirty
            );
        }
    }


    function setLoading(
        loading
    ) {
        state.loading = Boolean(
            loading
        );

        document
            .querySelectorAll(
                "#fine-matrix-modal "
                + ".fine-matrix-amount"
            )
            .forEach(
                (input) => {
                    input.disabled = (
                        state.loading
                    );
                }
            );

        const saveButton = byId(
            "fine-matrix-save"
        );

        const resetButton = byId(
            "fine-matrix-reset"
        );

        const closeButton = document.querySelector(
            "#fine-matrix-modal "
            + ".fine-matrix-close"
        );

        if (saveButton) {
            saveButton.disabled = (
                state.loading
                || !state.dirty
            );

            saveButton.textContent = (
                state.loading
                    ? "Сохранение…"
                    : "Сохранить изменения"
            );
        }

        if (resetButton) {
            resetButton.disabled = (
                state.loading
            );
        }

        if (closeButton) {
            closeButton.disabled = (
                state.loading
            );
        }
    }


    async function parseJsonResponse(
        response
    ) {
        let payload = null;

        try {
            payload = await response.json();

        } catch {
            payload = null;
        }

        if (!response.ok) {
            throw new Error(
                payload?.error
                || (
                    "Не удалось выполнить "
                    + "операцию с матрицей."
                )
            );
        }

        return payload;
    }


    function applyPayload(
        payload
    ) {
        state.items = Array.isArray(
            payload.items
        )
            ? payload.items
            : [];

        renderRows(
            state.items
        );

        const effectiveFrom = byId(
            "fine-matrix-effective-from"
        );

        const legalDocument = byId(
            "fine-matrix-legal-document"
        );

        if (effectiveFrom) {
            effectiveFrom.textContent = (
                formatDate(
                    payload.effective_from
                )
            );
        }

        if (legalDocument) {
            legalDocument.textContent = (
                payload.legal_document
                || "—"
            );
        }

        state.loaded = true;

        setDirty(
            false
        );
    }


    async function loadMatrix() {
        state.abortController?.abort();

        const controller = (
            new AbortController()
        );

        state.abortController = (
            controller
        );

        showMessage(
            "",
            ""
        );

        renderLoading();

        setLoading(
            true
        );

        try {
            const response = await fetch(
                API_URL,
                {
                    method: "GET",

                    headers: {
                        "Accept":
                            "application/json"
                    },

                    cache: "no-store",

                    signal: controller.signal
                }
            );

            const payload = (
                await parseJsonResponse(
                    response
                )
            );

            applyPayload(
                payload
            );

        } catch (error) {
            if (
                error.name === "AbortError"
            ) {
                return;
            }

            showMessage(
                "error",
                error.message
            );

            const body = byId(
                "fine-matrix-body"
            );

            if (body) {
                body.innerHTML = `
                    <tr>
                        <td
                            colspan="3"
                            class="fine-matrix-empty"
                        >
                            Не удалось загрузить матрицу.
                        </td>
                    </tr>
                `;
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
        }
    }


    function collectItems() {
        const rows = Array.from(
            document.querySelectorAll(
                "#fine-matrix-body "
                + "tr[data-rule-id]"
            )
        );

        const result = [];

        let invalidInput = null;

        rows.forEach(
            (row) => {
                const individualInput = (
                    row.querySelector(
                        "[data-amount-field="
                        + "\"individual_entrepreneur_amount\"]"
                    )
                );

                const legalInput = (
                    row.querySelector(
                        "[data-amount-field="
                        + "\"legal_entity_amount\"]"
                    )
                );

                const individualAmount = (
                    parseNumber(
                        individualInput?.value
                    )
                );

                const legalAmount = (
                    parseNumber(
                        legalInput?.value
                    )
                );

                if (
                    individualAmount === null
                    || individualAmount < 0
                ) {
                    individualInput?.classList.add(
                        "is-invalid"
                    );

                    invalidInput = (
                        invalidInput
                        || individualInput
                    );
                }

                if (
                    legalAmount === null
                    || legalAmount < 0
                ) {
                    legalInput?.classList.add(
                        "is-invalid"
                    );

                    invalidInput = (
                        invalidInput
                        || legalInput
                    );
                }

                result.push(
                    {
                        id: Number(
                            row.dataset.ruleId
                        ),

                        individual_entrepreneur_amount: (
                            individualAmount !== null
                                ? individualAmount.toFixed(
                                    2
                                )
                                : ""
                        ),

                        legal_entity_amount: (
                            legalAmount !== null
                                ? legalAmount.toFixed(
                                    2
                                )
                                : ""
                        )
                    }
                );
            }
        );

        if (invalidInput) {
            invalidInput.focus();

            throw new Error(
                "Проверьте суммы штрафов. "
                + "Все значения должны быть "
                + "неотрицательными числами."
            );
        }

        return result;
    }


    async function saveMatrix() {
        let items;

        try {
            items = collectItems();

        } catch (error) {
            showMessage(
                "error",
                error.message
            );

            return;
        }

        hideFloatingHelp();

        showMessage(
            "",
            ""
        );

        setLoading(
            true
        );

        try {
            const response = await fetch(
                API_URL,
                {
                    method: "PUT",

                    headers: {
                        "Accept":
                            "application/json",

                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify(
                        {
                            items: items
                        }
                    )
                }
            );

            const payload = (
                await parseJsonResponse(
                    response
                )
            );

            applyPayload(
                payload
            );

            showMessage(
                "success",
                "Матрица штрафов сохранена."
            );

        } catch (error) {
            showMessage(
                "error",
                error.message
            );

        } finally {
            setLoading(
                false
            );
        }
    }


    async function resetMatrix() {
        const confirmed = window.confirm(
            "Вернуть все суммы штрафов "
            + "к нормативным значениям? "
            + "Текущие изменения будут заменены."
        );

        if (!confirmed) {
            return;
        }

        hideFloatingHelp();

        showMessage(
            "",
            ""
        );

        setLoading(
            true
        );

        try {
            const response = await fetch(
                RESET_URL,
                {
                    method: "POST",

                    headers: {
                        "Accept":
                            "application/json",

                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify(
                        {}
                    )
                }
            );

            const payload = (
                await parseJsonResponse(
                    response
                )
            );

            applyPayload(
                payload
            );

            showMessage(
                "success",
                (
                    "Восстановлены "
                    + "нормативные значения."
                )
            );

        } catch (error) {
            showMessage(
                "error",
                error.message
            );

        } finally {
            setLoading(
                false
            );
        }
    }


    function openMatrix() {
        const modal = byId(
            "fine-matrix-modal"
        );

        if (!modal) {
            return;
        }

        modal.hidden = false;

        syncBodyModalState();

        if (!state.loaded) {
            loadMatrix();
        }
    }


    function closeMatrix() {
        hideFloatingHelp();

        if (state.loading) {
            return;
        }

        if (state.dirty) {
            const confirmed = window.confirm(
                "В матрице есть несохранённые "
                + "изменения. Закрыть окно "
                + "без сохранения?"
            );

            if (!confirmed) {
                return;
            }
        }

        state.abortController?.abort();
        state.abortController = null;

        const modal = byId(
            "fine-matrix-modal"
        );

        if (modal) {
            modal.hidden = true;
        }

        if (state.dirty) {
            state.loaded = false;
            state.dirty = false;
        }

        showMessage(
            "",
            ""
        );

        syncBodyModalState();

        byId(
            "open-fine-matrix"
        )?.focus();
    }


    function bindEvents() {
        byId(
            "open-fine-matrix"
        )?.addEventListener(
            "click",
            openMatrix
        );

        document
            .querySelectorAll(
                "[data-close-fine-matrix]"
            )
            .forEach(
                (target) => {
                    target.addEventListener(
                        "click",
                        closeMatrix
                    );
                }
            );

        byId(
            "fine-matrix-save"
        )?.addEventListener(
            "click",
            saveMatrix
        );

        byId(
            "fine-matrix-reset"
        )?.addEventListener(
            "click",
            resetMatrix
        );

        document.addEventListener(
            "keydown",
            (event) => {
                const modal = byId(
                    "fine-matrix-modal"
                );

                if (
                    event.key === "Escape"
                    && modal
                    && !modal.hidden
                ) {
                    closeMatrix();
                }

                if (
                    event.ctrlKey
                    && event.key === "Enter"
                    && modal
                    && !modal.hidden
                    && state.dirty
                    && !state.loading
                ) {
                    event.preventDefault();

                    saveMatrix();
                }
            }
        );

        document.addEventListener(
            "scroll",
            hideFloatingHelp,
            true
        );

        window.addEventListener(
            "resize",
            hideFloatingHelp
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