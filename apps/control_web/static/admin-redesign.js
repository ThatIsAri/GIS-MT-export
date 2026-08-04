(function () {
    "use strict";

    const DASHBOARD_URL = "/api/dashboard";
    const NOTIFICATION_LIFETIME_MS = 5200;
    const NOTIFICATION_LIMIT = 4;
    const DEDUPLICATION_WINDOW_MS = 2200;

    const observedMessageElements = new WeakSet();
    const recentNotifications = new Map();
    const jobToneMemory = new Map();
    const jobCounterMemory = new Map();
    const operationButtonStateMemory = new WeakMap();

    let lastRunTooltip = null;
    let dateTimePopoverOrigin = null;
    let dateTimePopoverNextSibling = null;

    function byId(id) {
        return document.getElementById(id);
    }

    function query(selector, root = document) {
        return root.querySelector(selector);
    }

    function queryAll(selector, root = document) {
        return Array.from(
            root.querySelectorAll(selector)
        );
    }

    function formatDateTime(value) {
        if (!value) {
            return "—";
        }

        const parsed = new Date(value);

        if (Number.isNaN(parsed.getTime())) {
            return String(value);
        }

        return new Intl.DateTimeFormat(
            "ru-RU",
            {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit"
            }
        ).format(parsed);
    }

    function totalRunningJobs(jobGroups) {
        if (
            !jobGroups
            || typeof jobGroups !== "object"
        ) {
            return 0;
        }

        return Object.values(jobGroups).reduce(
            (sum, group) => (
                sum
                + Number(
                    group?.running_count
                    || 0
                )
            ),
            0
        );
    }

    function setText(id, value) {
        const element = byId(id);

        if (element) {
            element.textContent = String(value);
        }
    }

    function visibleModalExists() {
        return [
            ".modal:not([hidden])",
            ".pipeline-modal-backdrop:not([hidden])",
            ".document-catalog-modal:not([hidden])",
            ".datamatrix-storage-modal:not([hidden])",
            ".violations-modal:not([hidden])",
            ".fine-matrix-modal:not([hidden])"
        ].some(
            (selector) => Boolean(
                query(selector)
            )
        );
    }

    function syncBodyModalState() {
        document.body.classList.toggle(
            "modal-open",
            visibleModalExists()
        );
    }

    function notificationStack() {
        let stack = byId(
            "notification-stack"
        );

        if (stack) {
            return stack;
        }

        stack = document.createElement(
            "div"
        );

        stack.id = "notification-stack";
        stack.className = "notification-stack";

        stack.setAttribute(
            "aria-live",
            "polite"
        );

        stack.setAttribute(
            "aria-atomic",
            "false"
        );

        document.body.appendChild(stack);

        return stack;
    }

    function notificationMeta(type) {
        if (type === "warning") {
            return {
                title: "Внимание",
                icon: "!"
            };
        }

        if (type === "error") {
            return {
                title: "Ошибка",
                icon: "×"
            };
        }

        return {
            title: "Успех",
            icon: "✓"
        };
    }

    function normalizeNotificationType(type) {
        return (
            type === "warning"
            || type === "error"
        )
            ? type
            : "success";
    }

    function notificationKey(
        type,
        message
    ) {
        return (
            `${normalizeNotificationType(type)}::`
            + String(message || "")
                .replace(
                    /\s+/g,
                    " "
                )
                .trim()
        );
    }

    function isDuplicateNotification(
        type,
        message
    ) {
        const key = notificationKey(
            type,
            message
        );

        const now = Date.now();

        const previous = (
            recentNotifications.get(key)
        );

        recentNotifications.set(
            key,
            now
        );

        for (
            const [
                storedKey,
                timestamp
            ]
            of recentNotifications
        ) {
            if (
                now - timestamp
                > DEDUPLICATION_WINDOW_MS * 4
            ) {
                recentNotifications.delete(
                    storedKey
                );
            }
        }

        return Boolean(
            previous
            && now - previous
            < DEDUPLICATION_WINDOW_MS
        );
    }

    function removeNotification(bubble) {
        if (
            !bubble
            || bubble.dataset.closing === "1"
        ) {
            return;
        }

        bubble.dataset.closing = "1";

        bubble.classList.add(
            "notification-bubble--closing"
        );

        window.setTimeout(
            () => bubble.remove(),
            180
        );
    }

    function showNotification(
        message,
        type = "success",
        options = {}
    ) {
        const preparedMessage = String(
            message || ""
        )
            .replace(
                /\s+/g,
                " "
            )
            .trim();

        if (!preparedMessage) {
            return null;
        }

        const preparedType = (
            normalizeNotificationType(type)
        );

        if (
            !options.force
            && isDuplicateNotification(
                preparedType,
                preparedMessage
            )
        ) {
            return null;
        }

        const stack = notificationStack();

        const meta = notificationMeta(
            preparedType
        );

        const bubble = document.createElement(
            "section"
        );

        const icon = document.createElement(
            "span"
        );

        const content = document.createElement(
            "div"
        );

        const title = document.createElement(
            "strong"
        );

        const text = document.createElement(
            "div"
        );

        const close = document.createElement(
            "button"
        );

        const progress = document.createElement(
            "span"
        );

        bubble.className = (
            "notification-bubble "
            + `notification-bubble--${preparedType}`
        );

        bubble.setAttribute(
            "role",
            preparedType === "error"
                ? "alert"
                : "status"
        );

        icon.className = (
            "notification-bubble__icon"
        );

        icon.textContent = meta.icon;

        icon.setAttribute(
            "aria-hidden",
            "true"
        );

        content.className = (
            "notification-bubble__content"
        );

        title.className = (
            "notification-bubble__title"
        );

        title.textContent = (
            options.title
            || meta.title
        );

        text.className = (
            "notification-bubble__text"
        );

        text.textContent = preparedMessage;

        content.append(
            title,
            text
        );

        close.className = (
            "notification-bubble__close"
        );

        close.type = "button";
        close.textContent = "×";

        close.setAttribute(
            "aria-label",
            "Закрыть уведомление"
        );

        close.addEventListener(
            "click",
            () => removeNotification(
                bubble
            )
        );

        progress.className = (
            "notification-bubble__progress"
        );

        bubble.append(
            icon,
            content,
            close,
            progress
        );

        stack.prepend(bubble);

        while (
            stack.children.length
            > NOTIFICATION_LIMIT
        ) {
            stack
                .lastElementChild
                ?.remove();
        }

        const lifetime = Number(
            options.duration
            || NOTIFICATION_LIFETIME_MS
        );

        progress.style.animationDuration = (
            `${lifetime}ms`
        );

        if (options.persistent) {
            progress.hidden = true;

        } else {
            window.setTimeout(
                () => removeNotification(
                    bubble
                ),
                lifetime
            );
        }

        return bubble;
    }

    function classifyMessage(
        element,
        message
    ) {
        const classes = String(
            element?.className || ""
        ).toLowerCase();

        const prepared = String(
            message || ""
        ).toLowerCase();

        if (
            classes.includes("error")
            || classes.includes("danger")
            || /ошиб|не удалось|некоррект|нельзя|отказ|dead|failed/.test(
                prepared
            )
        ) {
            return "error";
        }

        if (
            classes.includes("warning")
            || /вниман|предупреж|несохран|проверь|сверьте|ожидани|retry/.test(
                prepared
            )
        ) {
            return "warning";
        }

        return "success";
    }

    function isMessageElementVisible(element) {
        if (
            !element
            || element.hidden
        ) {
            return false;
        }

        if (
            element.id === "toast"
            && !element.classList.contains(
                "toast--visible"
            )
        ) {
            return false;
        }

        const style = window.getComputedStyle(
            element
        );

        return (
            style.display !== "none"
            && style.visibility !== "hidden"
        );
    }

    function emitMessageElement(element) {
        if (
            !isMessageElementVisible(element)
        ) {
            return;
        }

        const message = String(
            element.textContent || ""
        )
            .replace(
                /\s+/g,
                " "
            )
            .trim();

        if (
            !message
            || message === "Загрузка…"
            || message === "Изменений нет"
        ) {
            return;
        }

        if (
            element
                .dataset
                .adminNotificationMessage
            === message
        ) {
            return;
        }

        element
            .dataset
            .adminNotificationMessage = (
                message
            );

        showNotification(
            message,
            classifyMessage(
                element,
                message
            )
        );
    }

    function observeMessageElement(element) {
        if (
            !element
            || observedMessageElements.has(
                element
            )
        ) {
            return;
        }

        observedMessageElements.add(
            element
        );

        const observer = new MutationObserver(
            () => emitMessageElement(
                element
            )
        );

        observer.observe(
            element,
            {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: [
                    "class",
                    "hidden",
                    "style"
                ]
            }
        );

        emitMessageElement(element);
    }

    function attachMessageObservers(
        root = document
    ) {
        [
            "#toast",
            "[data-pipeline-banner]",
            "#document-catalog-message",
            "#datamatrix-storage-message",
            "#violations-message",
            "#fine-matrix-message",
            "#entity-form-general-error",
            "[data-config-general-error]",
            "[data-organization-picker-message]",
            "[data-starts-at-error]"
        ].forEach(
            (selector) => {
                queryAll(
                    selector,
                    root
                ).forEach(
                    observeMessageElement
                );
            }
        );
    }

    function observeDynamicMessages() {
        attachMessageObservers();

        const trackedSelector = (
            "#toast, "
            + "[data-pipeline-banner], "
            + "#document-catalog-message, "
            + "#datamatrix-storage-message, "
            + "#violations-message, "
            + "#fine-matrix-message, "
            + "#entity-form-general-error, "
            + "[data-config-general-error], "
            + "[data-organization-picker-message], "
            + "[data-starts-at-error]"
        );

        const observer = new MutationObserver(
            (records) => {
                for (const record of records) {
                    for (
                        const node
                        of record.addedNodes
                    ) {
                        if (
                            !(
                                node
                                instanceof Element
                            )
                        ) {
                            continue;
                        }

                        attachMessageObservers(
                            node
                        );

                        if (
                            node.matches?.(
                                trackedSelector
                            )
                        ) {
                            observeMessageElement(
                                node
                            );
                        }
                    }
                }
            }
        );

        observer.observe(
            document.body,
            {
                childList: true,
                subtree: true
            }
        );
    }

    function observeUnsavedState() {
        const attach = () => {
            const stateElement = byId(
                "fine-matrix-save-state"
            );

            if (
                !stateElement
                || stateElement
                    .dataset
                    .adminDirtyObserver
                === "1"
            ) {
                return;
            }

            stateElement
                .dataset
                .adminDirtyObserver = "1";

            let wasDirty = (
                stateElement
                    .classList
                    .contains(
                        "is-dirty"
                    )
            );

            const observer = new MutationObserver(
                () => {
                    const isDirty = (
                        stateElement
                            .classList
                            .contains(
                                "is-dirty"
                            )
                        || /несохран/i.test(
                            stateElement.textContent
                            || ""
                        )
                    );

                    if (
                        isDirty
                        && !wasDirty
                    ) {
                        showNotification(
                            (
                                "В матрице штрафов есть "
                                + "несохранённые изменения."
                            ),
                            "warning",
                            {
                                duration: 6500
                            }
                        );
                    }

                    wasDirty = isDirty;
                }
            );

            observer.observe(
                stateElement,
                {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: [
                        "class"
                    ]
                }
            );
        };

        attach();

        new MutationObserver(
            attach
        ).observe(
            document.body,
            {
                childList: true,
                subtree: true
            }
        );
    }

    function notifyInvalidForm(form) {
        window.setTimeout(
            () => {
                const invalidField = query(
                    (
                        ".form-field--invalid, "
                        + ".pipeline-field--invalid, "
                        + ".is-invalid"
                    ),
                    form
                );

                const visibleErrors = queryAll(
                    (
                        ".form-field__error, "
                        + ".pipeline-field__error, "
                        + ".pipeline-inline-error, "
                        + ".pipeline-form-error"
                    ),
                    form
                ).filter(
                    (element) => (
                        !element.hidden
                        && String(
                            element.textContent
                            || ""
                        ).trim()
                    )
                );

                if (
                    !invalidField
                    && !visibleErrors.length
                ) {
                    return;
                }

                const message = (
                    visibleErrors.length
                        ? String(
                            visibleErrors[0]
                                .textContent
                        ).trim()
                        : (
                            "Заполните обязательные поля "
                            + "и проверьте введённые значения."
                        )
                );

                showNotification(
                    message,
                    "error",
                    {
                        duration: 6500
                    }
                );
            },
            0
        );
    }

    function initFormValidationNotifications() {
        document.addEventListener(
            "submit",
            (event) => {
                if (
                    event.target
                    instanceof HTMLFormElement
                ) {
                    notifyInvalidForm(
                        event.target
                    );
                }
            },
            true
        );
    }

    function hideLastRunTooltip() {
        lastRunTooltip?.remove();
        lastRunTooltip = null;
    }

    function showLastRunTooltip(button) {
        hideLastRunTooltip();

        const tooltip = document.createElement(
            "div"
        );

        const title = document.createElement(
            "strong"
        );

        const body = document.createElement(
            "div"
        );

        const meta = document.createElement(
            "span"
        );

        tooltip.className = (
            "metric-run-tooltip"
        );

        title.textContent = (
            "Ошибка регламентного запуска"
        );

        body.textContent = (
            button.dataset.message
            || "Нет подробностей."
        );

        meta.textContent = (
            button.dataset.date
            || "—"
        );

        tooltip.append(
            title,
            body,
            meta
        );

        document.body.appendChild(
            tooltip
        );

        const rect = (
            button.getBoundingClientRect()
        );

        const tooltipRect = (
            tooltip.getBoundingClientRect()
        );

        const margin = 12;

        let left = rect.right + 10;
        let top = rect.top - 10;

        if (
            left + tooltipRect.width
            > window.innerWidth - margin
        ) {
            left = (
                rect.left
                - tooltipRect.width
                - 10
            );
        }

        if (left < margin) {
            left = margin;
        }

        if (
            top + tooltipRect.height
            > window.innerHeight - margin
        ) {
            top = (
                window.innerHeight
                - tooltipRect.height
                - margin
            );
        }

        if (top < margin) {
            top = margin;
        }

        tooltip.style.left = (
            `${Math.round(left)}px`
        );

        tooltip.style.top = (
            `${Math.round(top)}px`
        );

        lastRunTooltip = tooltip;
    }

    function showLastRunInfo(pipeline) {
        const statusElement = byId(
            "pipeline-last-run-status"
        );

        const dateElement = byId(
            "pipeline-last-run-date"
        );

        const alertButton = byId(
            "pipeline-last-run-alert"
        );

        if (
            !statusElement
            || !dateElement
            || !alertButton
        ) {
            return;
        }

        const status = String(
            pipeline?.last_autorun_status
            || ""
        ).toUpperCase();

        const message = String(
            pipeline?.last_autorun_message
            || ""
        ).trim();

        const finishedAt = (
            pipeline?.last_autorun_finished_at
            || pipeline?.last_autorun_started_at
            || null
        );

        const formattedDate = (
            formatDateTime(
                finishedAt
            )
        );

        dateElement.textContent = (
            formattedDate
        );

        alertButton.dataset.message = (
            message
            || "Подробности отсутствуют."
        );

        alertButton.dataset.date = (
            formattedDate
        );

        statusElement.className = (
            "metric-run-status__text"
        );

        if (!status) {
            statusElement.textContent = (
                "Нет данных"
            );

            alertButton.hidden = true;

            return;
        }

        if (status === "SUCCESS") {
            statusElement.textContent = (
                "Успешно"
            );

            statusElement.classList.add(
                "is-success"
            );

            alertButton.hidden = true;

            return;
        }

        if (
            status === "PROCESSING"
            || pipeline?.autorun_running
        ) {
            statusElement.textContent = (
                "Выполняется"
            );

            statusElement.classList.add(
                "is-running"
            );

            alertButton.hidden = true;

            return;
        }

        statusElement.textContent = (
            status
            || "Ошибка"
        );

        statusElement.classList.add(
            "is-error"
        );

        alertButton.hidden = false;
    }

    function applyDashboardMetrics(data) {
        setText(
            "active-jobs-total",
            totalRunningJobs(
                data?.job_groups
                || {}
            )
        );

        setText(
            "count-datamatrix-total",
            Number(
                data
                    ?.metrics
                    ?.datamatrix_count
                || 0
            )
        );

        showLastRunInfo(
            data?.pipeline
            || {}
        );
    }

    async function loadDashboardMetrics() {
        if (
            !byId(
                "active-jobs-total"
            )
            && !byId(
                "count-datamatrix-total"
            )
            && !byId(
                "pipeline-last-run-status"
            )
        ) {
            return;
        }

        try {
            const response = await fetch(
                DASHBOARD_URL,
                {
                    cache: "no-store"
                }
            );

            const payload = (
                await response.json()
            );

            if (!response.ok) {
                throw new Error(
                    payload.error
                    || (
                        "Не удалось загрузить "
                        + "показатели панели."
                    )
                );
            }

            applyDashboardMetrics(
                payload
            );

        } catch (error) {
            showNotification(
                error?.message
                || String(error),
                "error"
            );
        }
    }

    function jobCardTone(card) {
        return [
            "running",
            "success",
            "warning",
            "danger",
            "neutral"
        ].find(
            (tone) => (
                card.classList.contains(
                    `job-overview-card--${tone}`
                )
            )
        ) || "neutral";
    }

    function animateClassOnce(
        element,
        className,
        fallbackTimeoutMs
    ) {
        element.classList.remove(
            className
        );

        void element.offsetWidth;

        element.classList.add(
            className
        );

        let cleared = false;

        const clear = () => {
            if (cleared) {
                return;
            }

            cleared = true;

            element.classList.remove(
                className
            );
        };

        element.addEventListener(
            "animationend",
            clear,
            {
                once: true
            }
        );

        window.setTimeout(
            clear,
            fallbackTimeoutMs
        );
    }

    function animateJobToneChange(card) {
        animateClassOnce(
            card,
            "job-overview-card--tone-change",
            2600
        );
    }

    function jobCounterCode(counter) {
        return [
            "total",
            "error",
            "retry",
            "success"
        ].find(
            (modifier) => (
                counter.classList.contains(
                    `job-counter--${modifier}`
                )
            )
        ) || "unknown";
    }

    function animateJobCounterChange(circle) {
        animateClassOnce(
            circle,
            "job-counter__circle--value-change",
            2600
        );
    }

    function reconcileJobCounters(
        card,
        cardKey
    ) {
        queryAll(
            ".job-counter",
            card
        ).forEach(
            (counter) => {
                const modifier = (
                    jobCounterCode(
                        counter
                    )
                );

                const circle = query(
                    ".job-counter__circle",
                    counter
                );

                if (!circle) {
                    return;
                }

                const value = String(
                    circle.textContent || ""
                ).trim();

                const memoryKey = (
                    `${cardKey}:${modifier}`
                );

                const previousValue = (
                    jobCounterMemory.get(
                        memoryKey
                    )
                );

                if (
                    previousValue
                    === undefined
                ) {
                    jobCounterMemory.set(
                        memoryKey,
                        value
                    );

                    return;
                }

                if (
                    previousValue
                    !== value
                ) {
                    jobCounterMemory.set(
                        memoryKey,
                        value
                    );

                    animateJobCounterChange(
                        circle
                    );
                }
            }
        );
    }

    function reconcileJobCards() {
        queryAll(
            "[data-job-group-button]"
        ).forEach(
            (card) => {
                const key = String(
                    card
                        .dataset
                        .jobGroupButton
                    || ""
                );

                if (!key) {
                    return;
                }

                reconcileJobCounters(
                    card,
                    key
                );

                const currentTone = (
                    jobCardTone(
                        card
                    )
                );

                const previousTone = (
                    jobToneMemory.get(
                        key
                    )
                );

                if (
                    previousTone
                    === undefined
                ) {
                    jobToneMemory.set(
                        key,
                        currentTone
                    );

                    return;
                }

                if (
                    previousTone
                    !== currentTone
                ) {
                    jobToneMemory.set(
                        key,
                        currentTone
                    );

                    animateJobToneChange(
                        card
                    );
                }
            }
        );
    }

    function initJobCardTransitionObserver() {
        const grid = byId(
            "job-groups-grid"
        );

        if (!grid) {
            return;
        }

        reconcileJobCards();

        const observer = new MutationObserver(
            () => {
                window.requestAnimationFrame(
                    reconcileJobCards
                );
            }
        );

        observer.observe(
            grid,
            {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: [
                    "class"
                ]
            }
        );
    }

    function openOrganizationsModal() {
        const modal = byId(
            "organizations-modal"
        );

        if (!modal) {
            return;
        }

        modal.hidden = false;

        syncBodyModalState();
    }

    function closeOrganizationsModal() {
        const modal = byId(
            "organizations-modal"
        );

        if (
            !modal
            || modal.hidden
        ) {
            return;
        }

        modal.hidden = true;

        syncBodyModalState();
    }

    function initOrganizationsModal() {
        byId(
            "open-organizations-list"
        )?.addEventListener(
            "click",
            openOrganizationsModal
        );

        queryAll(
            "[data-close-organizations-modal]"
        ).forEach(
            (element) => {
                element.addEventListener(
                    "click",
                    closeOrganizationsModal
                );
            }
        );
    }

    function initToolsMenu() {
        const toggleButton = byId(
            "tools-fab-toggle"
        );

        const menu = byId(
            "tools-fab-menu"
        );

        if (
            !toggleButton
            || !menu
        ) {
            return;
        }

        const setOpen = (
            isOpen
        ) => {
            menu.hidden = !isOpen;

            toggleButton.classList.toggle(
                "is-open",
                isOpen
            );

            toggleButton.setAttribute(
                "aria-expanded",
                String(isOpen)
            );
        };

        toggleButton.setAttribute(
            "aria-expanded",
            "false"
        );

        toggleButton.addEventListener(
            "click",
            () => setOpen(
                menu.hidden
            )
        );

        byId(
            "open-entity-modal"
        )?.addEventListener(
            "click",
            () => setOpen(
                false
            )
        );

        document.addEventListener(
            "click",
            (event) => {
                if (
                    toggleButton.contains(
                        event.target
                    )
                    || menu.contains(
                        event.target
                    )
                ) {
                    return;
                }

                setOpen(false);
            }
        );
    }

    function operationButtonFingerprint(button) {
        return [
            String(
                button.textContent || ""
            )
                .replace(
                    /\s+/g,
                    " "
                )
                .trim(),

            Array.from(
                button.classList
            )
                .filter(
                    (className) => (
                        className
                        !== "pipeline-action-button--state-change"
                    )
                )
                .sort()
                .join(" "),

            String(
                button.disabled
            ),

            String(
                button.getAttribute(
                    "aria-label"
                ) || ""
            ),

            String(
                button.getAttribute(
                    "title"
                ) || ""
            )
        ].join("|");
    }

    function animateOperationButtonChange(button) {
        animateClassOnce(
            button,
            "pipeline-action-button--state-change",
            2600
        );
    }

    function reconcileOperationButtons() {
        queryAll(
            (
                ".admin-operations-body "
                + ".pipeline-action-button"
            )
        ).forEach(
            (button) => {
                const fingerprint = (
                    operationButtonFingerprint(
                        button
                    )
                );

                const previousFingerprint = (
                    operationButtonStateMemory.get(
                        button
                    )
                );

                if (
                    previousFingerprint
                    === undefined
                ) {
                    operationButtonStateMemory.set(
                        button,
                        fingerprint
                    );

                    return;
                }

                if (
                    previousFingerprint
                    !== fingerprint
                ) {
                    operationButtonStateMemory.set(
                        button,
                        fingerprint
                    );

                    animateOperationButtonChange(
                        button
                    );
                }
            }
        );
    }

    function initOperationButtonStateObserver() {
        const actions = query(
            (
                ".admin-operations-body "
                + ".pipeline-actions"
            )
        );

        if (!actions) {
            return;
        }

        reconcileOperationButtons();

        const observer = new MutationObserver(
            () => {
                window.requestAnimationFrame(
                    reconcileOperationButtons
                );
            }
        );

        observer.observe(
            actions,
            {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: [
                    "class",
                    "disabled",
                    "aria-label",
                    "title"
                ]
            }
        );
    }

    function updatePipelineButtonTitles() {
        const configButton = query(
            "[data-pipeline-config-open]"
        );

        const testButton = query(
            "[data-pipeline-test]"
        );

        const toggleButton = query(
            "[data-pipeline-toggle]"
        );

        if (configButton) {
            configButton.title = (
                "Конфигурация"
            );

            configButton.setAttribute(
                "aria-label",
                "Конфигурация"
            );
        }

        if (testButton) {
            testButton.title = "Тест";

            testButton.setAttribute(
                "aria-label",
                "Тест"
            );
        }

        if (toggleButton) {
            const label = (
                String(
                    toggleButton.textContent
                    || ""
                ).trim()
                || "Старт / Стоп"
            );

            toggleButton.title = label;

            toggleButton.setAttribute(
                "aria-label",
                label
            );
        }
    }

    function initPipelineButtonObserver() {
        const toggleButton = query(
            "[data-pipeline-toggle]"
        );

        if (!toggleButton) {
            return;
        }

        const observer = new MutationObserver(
            updatePipelineButtonTitles
        );

        observer.observe(
            toggleButton,
            {
                childList: true,
                subtree: true,
                characterData: true
            }
        );

        updatePipelineButtonTitles();
    }

    function restoreDateTimePopover(
        popover
    ) {
        if (!dateTimePopoverOrigin) {
            return;
        }

        popover.classList.remove(
            "pipeline-datetime-popover--portal"
        );

        if (
            dateTimePopoverNextSibling
            && dateTimePopoverNextSibling
                .parentNode
            === dateTimePopoverOrigin
        ) {
            dateTimePopoverOrigin.insertBefore(
                popover,
                dateTimePopoverNextSibling
            );

        } else {
            dateTimePopoverOrigin.appendChild(
                popover
            );
        }
    }

    function portalDateTimePopover(
        popover
    ) {
        if (
            !dateTimePopoverOrigin
            && popover.parentElement
        ) {
            dateTimePopoverOrigin = (
                popover.parentElement
            );

            dateTimePopoverNextSibling = (
                popover.nextSibling
            );
        }

        if (
            popover.parentElement
            !== document.body
        ) {
            document.body.appendChild(
                popover
            );
        }

        popover.classList.add(
            "pipeline-datetime-popover--portal"
        );
    }

    function initDateTimePopoverPortal() {
        const popover = query(
            "[data-datetime-popover]"
        );

        if (!popover) {
            return;
        }

        dateTimePopoverOrigin = (
            popover.parentElement
        );

        dateTimePopoverNextSibling = (
            popover.nextSibling
        );

        const sync = () => {
            if (popover.hidden) {
                restoreDateTimePopover(
                    popover
                );

            } else {
                portalDateTimePopover(
                    popover
                );
            }
        };

        const observer = new MutationObserver(
            sync
        );

        observer.observe(
            popover,
            {
                attributes: true,
                attributeFilter: [
                    "hidden"
                ]
            }
        );

        sync();
    }

    function initLastRunTooltip() {
        const button = byId(
            "pipeline-last-run-alert"
        );

        if (!button) {
            return;
        }

        button.addEventListener(
            "mouseenter",
            () => showLastRunTooltip(
                button
            )
        );

        button.addEventListener(
            "mouseleave",
            hideLastRunTooltip
        );

        button.addEventListener(
            "focus",
            () => showLastRunTooltip(
                button
            )
        );

        button.addEventListener(
            "blur",
            hideLastRunTooltip
        );

        window.addEventListener(
            "resize",
            hideLastRunTooltip
        );

        document.addEventListener(
            "scroll",
            hideLastRunTooltip,
            true
        );
    }

    function initGlobalErrorNotifications() {
        window.addEventListener(
            "unhandledrejection",
            (event) => {
                const message = (
                    event.reason?.message
                    || event.reason
                    || (
                        "Необработанная "
                        + "ошибка операции."
                    )
                );

                showNotification(
                    String(message),
                    "error",
                    {
                        duration: 7000
                    }
                );
            }
        );
    }

    function initEscapeHandling() {
        document.addEventListener(
            "keydown",
            (event) => {
                if (
                    event.key
                    !== "Escape"
                ) {
                    return;
                }

                closeOrganizationsModal();
                hideLastRunTooltip();

                const menu = byId(
                    "tools-fab-menu"
                );

                const toggle = byId(
                    "tools-fab-toggle"
                );

                if (menu) {
                    menu.hidden = true;
                }

                toggle?.classList.remove(
                    "is-open"
                );

                toggle?.setAttribute(
                    "aria-expanded",
                    "false"
                );
            }
        );
    }

    function initialize() {
        initOrganizationsModal();
        initToolsMenu();
        initPipelineButtonObserver();
        initOperationButtonStateObserver();
        initDateTimePopoverPortal();
        initLastRunTooltip();
        initFormValidationNotifications();
        initGlobalErrorNotifications();
        initEscapeHandling();
        initJobCardTransitionObserver();
        observeDynamicMessages();
        observeUnsavedState();
        loadDashboardMetrics();

        window.setInterval(
            loadDashboardMetrics,
            5000
        );
    }

    window.AdminUiNotifications = {
        showSuccess(
            message,
            options
        ) {
            return showNotification(
                message,
                "success",
                options
            );
        },

        showWarning(
            message,
            options
        ) {
            return showNotification(
                message,
                "warning",
                options
            );
        },

        showError(
            message,
            options
        ) {
            return showNotification(
                message,
                "error",
                options
            );
        }
    };

    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initialize,
            {
                once: true
            }
        );

    } else {
        initialize();
    }
})();