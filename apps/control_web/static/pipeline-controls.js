(function () {
    "use strict";

    const TASK_AUTHORIZATION = "AUTHORIZATION";
    const TASK_EXPORT_UPD = "EXPORT_UPD";
    const TASK_PROCESS_UPD = "PROCESS_UPD";

    const taskTitles = {
        AUTHORIZATION: "Авторизация",
        EXPORT_UPD: "Экспорт УПД",
        PROCESS_UPD: "Обработка УПД"
    };

    let loadedConfig = null;
    let organizations = [];

    let taskSelections = {
        AUTHORIZATION: new Set(),
        EXPORT_UPD: new Set(),
        PROCESS_UPD: new Set()
    };

    let activeOrganizationTask = null;
    let temporaryOrganizationSelection = new Set();

    let selectedStartsAt = null;
    let originalStartsAtTimestamp = null;
    let dateTimeDraft = null;
    let calendarCursor = null;


    function $(selector) {
        return document.querySelector(
            selector
        );
    }


    function $all(selector) {
        return Array.from(
            document.querySelectorAll(
                selector
            )
        );
    }


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


    function setBanner(
        kind,
        message
    ) {
        const banner = $(
            "[data-pipeline-banner]"
        );

        if (!banner) {
            return;
        }

        banner.hidden = false;
        banner.textContent = message;
        banner.className = "pipeline-banner";

        if (kind === "success") {
            banner.classList.add(
                "pipeline-banner-success"
            );

        } else if (kind === "warning") {
            banner.classList.add(
                "pipeline-banner-warning"
            );

        } else if (kind === "error") {
            banner.classList.add(
                "pipeline-banner-error"
            );
        }
    }


    function clearBanner() {
        const banner = $(
            "[data-pipeline-banner]"
        );

        if (!banner) {
            return;
        }

        banner.hidden = true;
        banner.textContent = "";
        banner.className = "pipeline-banner";
    }


    function updateToggleButton(
        isEnabled
    ) {
        const button = $(
            "[data-pipeline-toggle]"
        );

        if (!button) {
            return;
        }

        if (isEnabled) {
            button.textContent = "Стоп";

            button.classList.remove(
                "pipeline-action-button-primary"
            );

            button.classList.add(
                "pipeline-action-button-danger"
            );

        } else {
            button.textContent = "Старт";

            button.classList.remove(
                "pipeline-action-button-danger"
            );

            button.classList.add(
                "pipeline-action-button-primary"
            );
        }
    }


    function setTopButtonsBusy(
        isBusy
    ) {
        [
            "[data-pipeline-config-open]",
            "[data-pipeline-toggle]",
            "[data-pipeline-test]"
        ].forEach(
            function (selector) {
                const button = $(
                    selector
                );

                if (button) {
                    button.disabled = isBusy;
                }
            }
        );
    }


    function setConfigBusy(
        isBusy
    ) {
        const saveButton = $(
            "[data-pipeline-config-save]"
        );

        const cancelButton = $(
            "[data-pipeline-config-cancel]"
        );

        const closeButton = $(
            "[data-pipeline-config-close]"
        );

        if (saveButton) {
            saveButton.disabled = isBusy;

            saveButton.textContent = (
                isBusy
                    ? "Сохранение…"
                    : "Сохранить"
            );
        }

        if (cancelButton) {
            cancelButton.disabled = isBusy;
        }

        if (closeButton) {
            closeButton.disabled = isBusy;
        }
    }


    async function parseJsonResponse(
        response
    ) {
        let payload = null;

        try {
            payload = await response.json();

        } catch (_error) {
            throw new Error(
                "Сервер вернул ответ в неизвестном формате."
            );
        }

        if (!response.ok) {
            const error = new Error(
                payload.message
                || payload.error
                || "Не удалось выполнить запрос."
            );

            error.field = (
                payload.field
                || null
            );

            error.status = response.status;

            throw error;
        }

        return payload;
    }


    async function loadPipelineState() {
        const response = await fetch(
            "/api/pipeline/state",
            {
                method: "GET",
                cache: "no-store",

                headers: {
                    Accept: "application/json"
                }
            }
        );

        const payload = await parseJsonResponse(
            response
        );

        const state = (
            payload.state
            || {}
        );

        updateToggleButton(
            Boolean(
                state.pipeline_enabled
            )
        );
    }


    function openConfigBackdrop() {
        const backdrop = $(
            "[data-pipeline-config-backdrop]"
        );

        if (!backdrop) {
            return;
        }

        backdrop.hidden = false;

        document.body.classList.add(
            "modal-open"
        );
    }


    function closeConfigBackdrop() {
        const backdrop = $(
            "[data-pipeline-config-backdrop]"
        );

        if (!backdrop) {
            return;
        }

        closeDateTimePicker();
        closeOrganizationPicker();

        backdrop.hidden = true;

        document.body.classList.remove(
            "modal-open"
        );
    }


    function clearConfigErrors() {
        $all(
            "[data-config-error]"
        ).forEach(
            function (element) {
                element.textContent = "";
            }
        );

        const generalError = $(
            "[data-config-general-error]"
        );

        if (generalError) {
            generalError.hidden = true;
            generalError.textContent = "";
        }
    }


    function setConfigFieldError(
        field,
        message
    ) {
        const element = $(
            `[data-config-error="${field}"]`
        );

        if (element) {
            element.textContent = message;
            return true;
        }

        return false;
    }


    function setConfigGeneralError(
        message
    ) {
        const element = $(
            "[data-config-general-error]"
        );

        if (!element) {
            return;
        }

        element.hidden = false;
        element.textContent = message;
    }


    function getCheckbox(
        selector
    ) {
        const element = $(
            selector
        );

        return Boolean(
            element
            && element.checked
        );
    }


    function setCheckbox(
        selector,
        value
    ) {
        const element = $(
            selector
        );

        if (element) {
            element.checked = Boolean(
                value
            );
        }
    }


    function startOfLocalDay(
        value
    ) {
        return new Date(
            value.getFullYear(),
            value.getMonth(),
            value.getDate(),
            0,
            0,
            0,
            0
        );
    }


    function sameLocalDay(
        first,
        second
    ) {
        return (
            first.getFullYear()
            === second.getFullYear()

            && first.getMonth()
            === second.getMonth()

            && first.getDate()
            === second.getDate()
        );
    }


    function roundToNextMinute(
        value
    ) {
        const result = new Date(
            value
        );

        result.setSeconds(
            0,
            0
        );

        result.setMinutes(
            result.getMinutes()
            + 1
        );

        return result;
    }


    function defaultStartsAt() {
        const result = roundToNextMinute(
            new Date()
        );

        result.setMinutes(
            Math.ceil(
                result.getMinutes()
                / 5
            )
            * 5
        );

        return result;
    }


    function formatStartsAt(
        value
    ) {
        if (
            !(value instanceof Date)
            || Number.isNaN(
                value.getTime()
            )
        ) {
            return "Выберите дату и время";
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
        ).format(
            value
        );
    }


    function updateStartsAtText() {
        const target = $(
            "[data-starts-at-text]"
        );

        if (target) {
            target.textContent = formatStartsAt(
                selectedStartsAt
            );
        }
    }


    function refreshEnabledStates() {
        const autorunEnabled = getCheckbox(
            "[data-autorun-enabled]"
        );

        const schedule = $(
            "[data-autorun-schedule]"
        );

        const startsAtButton = $(
            "[data-starts-at-open]"
        );

        if (schedule) {
            schedule.disabled = !autorunEnabled;
        }

        if (startsAtButton) {
            startsAtButton.disabled = !autorunEnabled;
        }

        const exportEnabled = getTaskEnabled(
            TASK_EXPORT_UPD
        );

        const periodFrom = $(
            "[data-export-period-from]"
        );

        const periodTo = $(
            "[data-export-period-to]"
        );

        if (periodFrom) {
            periodFrom.disabled = !exportEnabled;
        }

        if (periodTo) {
            periodTo.disabled = !exportEnabled;
        }
    }


    function getTaskEnabled(
        taskCode
    ) {
        const element = $(
            `[data-task-enabled="${taskCode}"]`
        );

        return Boolean(
            element
            && element.checked
        );
    }


    function setTaskEnabled(
        taskCode,
        value
    ) {
        const element = $(
            `[data-task-enabled="${taskCode}"]`
        );

        if (element) {
            element.checked = Boolean(
                value
            );
        }
    }


    function organizationDisplayName(
        organization
    ) {
        return (
            organization.gis_mt_name
            || organization.short_name
            || `Организация ${organization.id}`
        );
    }


    function updateSelectedSummary(
        taskCode
    ) {
        const target = $(
            `[data-selected-summary="${taskCode}"]`
        );

        if (!target) {
            return;
        }

        if (
            taskCode
            === TASK_PROCESS_UPD
        ) {
            target.textContent = (
                "Функция ещё не доступна"
            );

            return;
        }

        const ids = (
            taskSelections[
                taskCode
            ]
            || new Set()
        );

        const selectedOrganizations = (
            organizations.filter(
                function (item) {
                    return ids.has(
                        Number(
                            item.id
                        )
                    );
                }
            )
        );

        if (!selectedOrganizations.length) {
            target.textContent = (
                "Организации не выбраны"
            );

            return;
        }

        const names = selectedOrganizations
            .slice(
                0,
                2
            )
            .map(
                organizationDisplayName
            );

        if (
            selectedOrganizations.length
            > 2
        ) {
            names.push(
                (
                    "ещё "
                    + (
                        selectedOrganizations.length
                        - 2
                    )
                )
            );
        }

        target.innerHTML = (
            `<strong>Выбрано: `
            + `${selectedOrganizations.length}`
            + "</strong>"
            + ` · ${names.map(escapeHtml).join(", ")}`
        );
    }


    function updateAllSelectedSummaries() {
        Object.keys(
            taskSelections
        ).forEach(
            updateSelectedSummary
        );
    }


    function populateConfig(
        payload
    ) {
        loadedConfig = (
            payload.config
            || {}
        );

        organizations = (
            Array.isArray(
                payload.organizations
            )
                ? payload.organizations
                : []
        );

        const autorun = (
            loadedConfig.autorun
            || {}
        );

        const tasks = (
            loadedConfig.tasks
            || {}
        );

        const authorization = (
            tasks.authorization
            || {}
        );

        const exportUpd = (
            tasks.export_upd
            || {}
        );

        setCheckbox(
            "[data-autorun-enabled]",
            Boolean(
                autorun.enabled
            )
        );

        const schedule = $(
            "[data-autorun-schedule]"
        );

        if (schedule) {
            schedule.value = (
                autorun.schedule
                || "DAILY"
            );
        }

        if (autorun.starts_at) {
            selectedStartsAt = new Date(
                autorun.starts_at
            );

            originalStartsAtTimestamp = (
                selectedStartsAt.getTime()
            );

        } else {
            selectedStartsAt = defaultStartsAt();
            originalStartsAtTimestamp = null;
        }

        if (
            Number.isNaN(
                selectedStartsAt.getTime()
            )
        ) {
            selectedStartsAt = defaultStartsAt();
            originalStartsAtTimestamp = null;
        }

        updateStartsAtText();

        setTaskEnabled(
            TASK_AUTHORIZATION,
            Boolean(
                authorization.enabled
            )
        );

        setTaskEnabled(
            TASK_EXPORT_UPD,
            Boolean(
                exportUpd.enabled
            )
        );

        taskSelections = {
            AUTHORIZATION: new Set(
                (
                    authorization.entity_ids
                    || []
                ).map(
                    Number
                )
            ),

            EXPORT_UPD: new Set(
                (
                    exportUpd.entity_ids
                    || []
                ).map(
                    Number
                )
            ),

            PROCESS_UPD: new Set()
        };

        const today = (
            new Date()
            .toISOString()
            .slice(
                0,
                10
            )
        );

        const periodFrom = $(
            "[data-export-period-from]"
        );

        const periodTo = $(
            "[data-export-period-to]"
        );

        if (periodFrom) {
            periodFrom.value = (
                exportUpd.period_from
                || today
            );
        }

        if (periodTo) {
            periodTo.value = (
                exportUpd.period_to
                || today
            );
        }

        refreshEnabledStates();
        updateAllSelectedSummaries();
        clearConfigErrors();
    }


    async function loadConfiguration() {
        const response = await fetch(
            "/api/pipeline/config",
            {
                method: "GET",
                cache: "no-store",

                headers: {
                    Accept: "application/json"
                }
            }
        );

        const payload = await parseJsonResponse(
            response
        );

        populateConfig(
            payload
        );
    }


    async function openConfiguration() {
        clearBanner();
        setTopButtonsBusy(true);
        openConfigBackdrop();
        setConfigBusy(true);

        try {
            await loadConfiguration();

        } catch (error) {
            setConfigGeneralError(
                error.message
                || "Не удалось загрузить конфигурацию."
            );

        } finally {
            setConfigBusy(false);
            setTopButtonsBusy(false);
        }
    }


    function isAllowedPastStartsAt(
        value
    ) {
        if (
            !(value instanceof Date)
        ) {
            return false;
        }

        if (
            value.getTime()
            >= Date.now()
        ) {
            return true;
        }

        return (
            originalStartsAtTimestamp
            !== null

            && Math.abs(
                value.getTime()
                - originalStartsAtTimestamp
            )
            < 1000
        );
    }


    function showStartsAtPopoverError(
        message
    ) {
        const target = $(
            "[data-starts-at-error]"
        );

        if (!target) {
            return;
        }

        target.hidden = !message;
        target.textContent = message || "";
    }


    function renderCalendar() {
        const grid = $(
            "[data-calendar-grid]"
        );

        const title = $(
            "[data-calendar-title]"
        );

        const previousButton = $(
            "[data-calendar-prev]"
        );

        const hourRange = $(
            "[data-hour-range]"
        );

        const minuteRange = $(
            "[data-minute-range]"
        );

        const hourValue = $(
            "[data-hour-value]"
        );

        const minuteValue = $(
            "[data-minute-value]"
        );

        if (
            !grid
            || !title
            || !dateTimeDraft
            || !calendarCursor
        ) {
            return;
        }

        const monthNames = [
            "Январь",
            "Февраль",
            "Март",
            "Апрель",
            "Май",
            "Июнь",
            "Июль",
            "Август",
            "Сентябрь",
            "Октябрь",
            "Ноябрь",
            "Декабрь"
        ];

        title.textContent = (
            monthNames[
                calendarCursor.getMonth()
            ]
            + " "
            + calendarCursor.getFullYear()
        );

        const currentMonth = new Date(
            new Date().getFullYear(),
            new Date().getMonth(),
            1
        );

        if (previousButton) {
            previousButton.disabled = (
                calendarCursor.getTime()
                <= currentMonth.getTime()
            );
        }

        const firstDay = new Date(
            calendarCursor.getFullYear(),
            calendarCursor.getMonth(),
            1
        );

        const daysInMonth = new Date(
            calendarCursor.getFullYear(),
            calendarCursor.getMonth() + 1,
            0
        ).getDate();

        const mondayOffset = (
            firstDay.getDay()
            + 6
        ) % 7;

        const today = startOfLocalDay(
            new Date()
        );

        const elements = [];

        for (
            let index = 0;
            index < mondayOffset;
            index += 1
        ) {
            elements.push(
                (
                    '<span class="'
                    + 'pipeline-calendar-day-placeholder'
                    + '"></span>'
                )
            );
        }

        for (
            let day = 1;
            day <= daysInMonth;
            day += 1
        ) {
            const value = new Date(
                calendarCursor.getFullYear(),
                calendarCursor.getMonth(),
                day,
                0,
                0,
                0,
                0
            );

            const disabled = (
                value.getTime()
                < today.getTime()
            );

            const isSelected = sameLocalDay(
                value,
                dateTimeDraft
            );

            const isToday = sameLocalDay(
                value,
                new Date()
            );

            const classes = [
                "pipeline-calendar-day"
            ];

            if (isSelected) {
                classes.push(
                    "pipeline-calendar-day--selected"
                );
            }

            if (isToday) {
                classes.push(
                    "pipeline-calendar-day--today"
                );
            }

            elements.push(
                (
                    '<button type="button" '
                    + `class="${classes.join(" ")}" `
                    + `data-calendar-day="${day}" `
                    + (
                        disabled
                            ? "disabled"
                            : ""
                    )
                    + ">"
                    + day
                    + "</button>"
                )
            );
        }

        grid.innerHTML = elements.join(
            ""
        );

        $all(
            "[data-calendar-day]"
        ).forEach(
            function (button) {
                button.addEventListener(
                    "click",
                    function () {
                        const day = Number(
                            button.dataset.calendarDay
                        );

                        dateTimeDraft.setFullYear(
                            calendarCursor.getFullYear(),
                            calendarCursor.getMonth(),
                            day
                        );

                        if (
                            sameLocalDay(
                                dateTimeDraft,
                                new Date()
                            )
                            && dateTimeDraft.getTime()
                            < Date.now()
                        ) {
                            const adjusted = defaultStartsAt();

                            dateTimeDraft.setHours(
                                adjusted.getHours(),
                                adjusted.getMinutes(),
                                0,
                                0
                            );
                        }

                        showStartsAtPopoverError(
                            ""
                        );

                        renderCalendar();
                    }
                );
            }
        );

        if (hourRange) {
            hourRange.value = String(
                dateTimeDraft.getHours()
            );
        }

        if (minuteRange) {
            minuteRange.value = String(
                dateTimeDraft.getMinutes()
            );
        }

        if (hourValue) {
            hourValue.textContent = String(
                dateTimeDraft.getHours()
            ).padStart(
                2,
                "0"
            );
        }

        if (minuteValue) {
            minuteValue.textContent = String(
                dateTimeDraft.getMinutes()
            ).padStart(
                2,
                "0"
            );
        }
    }


    function openDateTimePicker() {
        const popover = $(
            "[data-datetime-popover]"
        );

        const startsAtButton = $(
            "[data-starts-at-open]"
        );

        if (
            !popover
            || !startsAtButton
            || startsAtButton.disabled
        ) {
            return;
        }

        dateTimeDraft = new Date(
            selectedStartsAt
            || defaultStartsAt()
        );

        calendarCursor = new Date(
            dateTimeDraft.getFullYear(),
            dateTimeDraft.getMonth(),
            1
        );

        showStartsAtPopoverError(
            ""
        );

        renderCalendar();

        popover.hidden = false;
    }


    function closeDateTimePicker() {
        const popover = $(
            "[data-datetime-popover]"
        );

        if (popover) {
            popover.hidden = true;
        }

        dateTimeDraft = null;
        calendarCursor = null;

        showStartsAtPopoverError(
            ""
        );
    }


    function applyDateTimePicker() {
        if (!dateTimeDraft) {
            return;
        }

        if (
            !isAllowedPastStartsAt(
                dateTimeDraft
            )
        ) {
            showStartsAtPopoverError(
                (
                    "Нельзя указать дату и время "
                    + "раньше текущего момента."
                )
            );

            return;
        }

        selectedStartsAt = new Date(
            dateTimeDraft
        );

        updateStartsAtText();

        setConfigFieldError(
            "autorun.starts_at",
            ""
        );

        closeDateTimePicker();
    }


    function normalizeSearch(
        value
    ) {
        return String(
            value
            || ""
        )
            .toLocaleUpperCase(
                "ru-RU"
            )
            .replace(
                /\s+/g,
                " "
            )
            .trim();
    }


    function organizationMatchesSearch(
        organization,
        searchValue
    ) {
        if (!searchValue) {
            return true;
        }

        const haystack = normalizeSearch(
            [
                organizationDisplayName(
                    organization
                ),
                organization.short_name,
                organization.inn
            ]
                .filter(
                    Boolean
                )
                .join(
                    " "
                )
        );

        return haystack.includes(
            searchValue
        );
    }


    function updateSelectAllCheckbox() {
        const selectAll = $(
            "[data-organization-select-all]"
        );

        const count = $(
            "[data-organization-count]"
        );

        if (!selectAll) {
            return;
        }

        const total = organizations.length;

        const selected = organizations.filter(
            function (organization) {
                return temporaryOrganizationSelection.has(
                    Number(
                        organization.id
                    )
                );
            }
        ).length;

        selectAll.checked = (
            total > 0
            && selected === total
        );

        selectAll.indeterminate = (
            selected > 0
            && selected < total
        );

        if (count) {
            count.textContent = (
                selected
                + " из "
                + total
            );
        }
    }


    function renderOrganizationPicker() {
        const list = $(
            "[data-organization-list]"
        );

        const empty = $(
            "[data-organization-empty]"
        );

        const search = $(
            "[data-organization-search]"
        );

        if (
            !list
            || !empty
        ) {
            return;
        }

        const searchValue = normalizeSearch(
            search
                ? search.value
                : ""
        );

        const filtered = organizations.filter(
            function (organization) {
                return organizationMatchesSearch(
                    organization,
                    searchValue
                );
            }
        );

        empty.hidden = (
            filtered.length > 0
        );

        list.innerHTML = filtered.map(
            function (organization) {
                const entityId = Number(
                    organization.id
                );

                const checked = (
                    temporaryOrganizationSelection.has(
                        entityId
                    )
                );

                return `
                    <label class="pipeline-tree-item">
                        <input
                            type="checkbox"
                            value="${entityId}"
                            data-organization-checkbox
                            ${checked ? "checked" : ""}
                        >

                        <span>
                            <span class="pipeline-tree-item__name">
                                ${escapeHtml(
                                    organizationDisplayName(
                                        organization
                                    )
                                )}
                            </span>

                            <span class="pipeline-tree-item__meta">
                                ИНН ${escapeHtml(
                                    organization.inn
                                )}
                            </span>
                        </span>

                        <span class="pipeline-tree-item__status">
                            ${escapeHtml(
                                organization.status
                            )}
                        </span>
                    </label>
                `;
            }
        ).join(
            ""
        );

        $all(
            "[data-organization-checkbox]"
        ).forEach(
            function (checkbox) {
                checkbox.addEventListener(
                    "change",
                    function () {
                        const entityId = Number(
                            checkbox.value
                        );

                        if (checkbox.checked) {
                            temporaryOrganizationSelection.add(
                                entityId
                            );

                        } else {
                            temporaryOrganizationSelection.delete(
                                entityId
                            );
                        }

                        updateSelectAllCheckbox();
                    }
                );
            }
        );

        updateSelectAllCheckbox();
    }


    function openOrganizationPicker(
        taskCode
    ) {
        const backdrop = $(
            "[data-organization-picker-backdrop]"
        );

        const subtitle = $(
            "[data-organization-picker-subtitle]"
        );

        const search = $(
            "[data-organization-search]"
        );

        if (
            !backdrop
            || !taskSelections[
                taskCode
            ]
        ) {
            return;
        }

        activeOrganizationTask = taskCode;

        temporaryOrganizationSelection = new Set(
            taskSelections[
                taskCode
            ]
        );

        if (subtitle) {
            subtitle.textContent = (
                "Задание: "
                + (
                    taskTitles[
                        taskCode
                    ]
                    || taskCode
                )
            );
        }

        if (search) {
            search.value = "";
        }

        renderOrganizationPicker();

        backdrop.hidden = false;

        window.setTimeout(
            function () {
                if (search) {
                    search.focus();
                }
            },
            0
        );
    }


    function closeOrganizationPicker() {
        const backdrop = $(
            "[data-organization-picker-backdrop]"
        );

        if (backdrop) {
            backdrop.hidden = true;
        }

        activeOrganizationTask = null;
        temporaryOrganizationSelection = new Set();
    }


    function saveOrganizationPicker() {
        if (!activeOrganizationTask) {
            return;
        }

        taskSelections[
            activeOrganizationTask
        ] = new Set(
            temporaryOrganizationSelection
        );

        updateSelectedSummary(
            activeOrganizationTask
        );

        setConfigFieldError(
            (
                activeOrganizationTask
                === TASK_AUTHORIZATION
            )
                ? "tasks.authorization.entity_ids"
                : "tasks.export_upd.entity_ids",
            ""
        );

        closeOrganizationPicker();
    }


    function validateConfiguration() {
        clearConfigErrors();

        let valid = true;

        const autorunEnabled = getCheckbox(
            "[data-autorun-enabled]"
        );

        const authorizationEnabled = getTaskEnabled(
            TASK_AUTHORIZATION
        );

        const exportEnabled = getTaskEnabled(
            TASK_EXPORT_UPD
        );

        const periodFrom = (
            $(
                "[data-export-period-from]"
            )?.value
            || ""
        );

        const periodTo = (
            $(
                "[data-export-period-to]"
            )?.value
            || ""
        );

        if (autorunEnabled) {
            if (!selectedStartsAt) {
                setConfigFieldError(
                    "autorun.starts_at",
                    "Укажите дату и время начала."
                );

                valid = false;

            } else if (
                !isAllowedPastStartsAt(
                    selectedStartsAt
                )
            ) {
                setConfigFieldError(
                    "autorun.starts_at",
                    (
                        "Нельзя указать дату и время "
                        + "раньше текущего момента."
                    )
                );

                valid = false;
            }
        }

        if (
            authorizationEnabled
            && taskSelections[
                TASK_AUTHORIZATION
            ].size === 0
        ) {
            setConfigFieldError(
                "tasks.authorization.entity_ids",
                "Выберите хотя бы одну организацию."
            );

            valid = false;
        }

        if (exportEnabled) {
            if (!authorizationEnabled) {
                setConfigGeneralError(
                    (
                        "Экспорт УПД требует "
                        + "включённой авторизации."
                    )
                );

                valid = false;
            }

            if (
                taskSelections[
                    TASK_EXPORT_UPD
                ].size === 0
            ) {
                setConfigFieldError(
                    "tasks.export_upd.entity_ids",
                    "Выберите хотя бы одну организацию."
                );

                valid = false;
            }

            if (
                !periodFrom
                || !periodTo
            ) {
                setConfigFieldError(
                    "tasks.export_upd.period",
                    "Укажите обе даты периода."
                );

                valid = false;

            } else if (
                periodFrom > periodTo
            ) {
                setConfigFieldError(
                    "tasks.export_upd.period",
                    (
                        "Дата «с» не может "
                        + "быть позже даты «по»."
                    )
                );

                valid = false;
            }

            const missingAuthorization = Array.from(
                taskSelections[
                    TASK_EXPORT_UPD
                ]
            ).filter(
                function (entityId) {
                    return !taskSelections[
                        TASK_AUTHORIZATION
                    ].has(
                        entityId
                    );
                }
            );

            if (
                missingAuthorization.length
                > 0
            ) {
                setConfigFieldError(
                    "tasks.export_upd.entity_ids",
                    (
                        "Все организации экспорта "
                        + "должны участвовать в авторизации."
                    )
                );

                valid = false;
            }
        }

        return valid;
    }


    function buildConfigurationPayload() {
        return {
            autorun: {
                enabled: getCheckbox(
                    "[data-autorun-enabled]"
                ),

                schedule: (
                    $(
                        "[data-autorun-schedule]"
                    )?.value
                    || "DAILY"
                ),

                starts_at: (
                    selectedStartsAt
                        ? selectedStartsAt.toISOString()
                        : null
                )
            },

            tasks: {
                authorization: {
                    enabled: getTaskEnabled(
                        TASK_AUTHORIZATION
                    ),

                    entity_ids: Array.from(
                        taskSelections[
                            TASK_AUTHORIZATION
                        ]
                    ).sort(
                        function (a, b) {
                            return a - b;
                        }
                    )
                },

                export_upd: {
                    enabled: getTaskEnabled(
                        TASK_EXPORT_UPD
                    ),

                    period_from: (
                        $(
                            "[data-export-period-from]"
                        )?.value
                        || null
                    ),

                    period_to: (
                        $(
                            "[data-export-period-to]"
                        )?.value
                        || null
                    ),

                    entity_ids: Array.from(
                        taskSelections[
                            TASK_EXPORT_UPD
                        ]
                    ).sort(
                        function (a, b) {
                            return a - b;
                        }
                    )
                },

                process_upd: {
                    enabled: false,
                    entity_ids: []
                }
            }
        };
    }


    async function saveConfiguration(
        event
    ) {
        event.preventDefault();

        if (!validateConfiguration()) {
            return;
        }

        setConfigBusy(
            true
        );

        try {
            const response = await fetch(
                "/api/pipeline/config",
                {
                    method: "PUT",

                    headers: {
                        "Content-Type":
                            "application/json",

                        Accept:
                            "application/json"
                    },

                    body: JSON.stringify(
                        buildConfigurationPayload()
                    )
                }
            );

            const payload = await parseJsonResponse(
                response
            );

            loadedConfig = (
                payload.config
                || loadedConfig
            );

            if (
                loadedConfig
                && loadedConfig.autorun
                && loadedConfig.autorun.starts_at
            ) {
                originalStartsAtTimestamp = new Date(
                    loadedConfig.autorun.starts_at
                ).getTime();
            }

            closeConfigBackdrop();

            setBanner(
                "success",
                (
                    payload.message
                    || "Конфигурация сохранена."
                )
            );

        } catch (error) {
            if (
                error.field
                && setConfigFieldError(
                    error.field,
                    error.message
                )
            ) {
                return;
            }

            setConfigGeneralError(
                error.message
                || "Не удалось сохранить конфигурацию."
            );

        } finally {
            setConfigBusy(
                false
            );
        }
    }


    async function togglePipelineState() {
        clearBanner();
        setTopButtonsBusy(true);

        try {
            const button = $(
                "[data-pipeline-toggle]"
            );

            const currentlyEnabled = Boolean(
                button
                && button.textContent.trim()
                === "Стоп"
            );

            const response = await fetch(
                "/api/pipeline/toggle",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json",

                        Accept:
                            "application/json"
                    },

                    body: JSON.stringify(
                        {
                            enabled: !currentlyEnabled
                        }
                    )
                }
            );

            const payload = await parseJsonResponse(
                response
            );

            const enabled = Boolean(
                payload.state
                && payload.state.pipeline_enabled
            );

            updateToggleButton(
                enabled
            );

            setBanner(
                "success",
                (
                    payload.message
                    || "Состояние конвейера изменено."
                )
            );

        } catch (error) {
            setBanner(
                "error",
                (
                    error.message
                    || "Не удалось изменить состояние."
                )
            );

        } finally {
            setTopButtonsBusy(
                false
            );
        }
    }


    async function runTestRequest() {
        clearBanner();
        setTopButtonsBusy(true);

        try {
            const response = await fetch(
                "/api/pipeline/test",
                {
                    method: "POST",

                    headers: {
                        Accept:
                            "application/json"
                    }
                }
            );

            const payload = await parseJsonResponse(
                response
            );

            setBanner(
                "success",
                (
                    payload.message
                    || "Тестовый запуск зарегистрирован."
                )
            );

        } catch (error) {
            setBanner(
                "error",
                (
                    error.message
                    || "Не удалось запустить тест."
                )
            );

        } finally {
            setTopButtonsBusy(
                false
            );
        }
    }


    function bindEvents() {
        $(
            "[data-pipeline-config-open]"
        )?.addEventListener(
            "click",
            openConfiguration
        );

        $(
            "[data-pipeline-config-close]"
        )?.addEventListener(
            "click",
            closeConfigBackdrop
        );

        $(
            "[data-pipeline-config-cancel]"
        )?.addEventListener(
            "click",
            closeConfigBackdrop
        );

        $(
            "[data-pipeline-toggle]"
        )?.addEventListener(
            "click",
            togglePipelineState
        );

        $(
            "[data-pipeline-test]"
        )?.addEventListener(
            "click",
            runTestRequest
        );

        $(
            "[data-pipeline-config-form]"
        )?.addEventListener(
            "submit",
            saveConfiguration
        );

        $(
            "[data-autorun-enabled]"
        )?.addEventListener(
            "change",
            refreshEnabledStates
        );

        $all(
            "[data-task-enabled]"
        ).forEach(
            function (checkbox) {
                checkbox.addEventListener(
                    "change",
                    refreshEnabledStates
                );
            }
        );

        $(
            "[data-starts-at-open]"
        )?.addEventListener(
            "click",
            openDateTimePicker
        );

        $(
            "[data-datetime-cancel]"
        )?.addEventListener(
            "click",
            closeDateTimePicker
        );

        $(
            "[data-datetime-apply]"
        )?.addEventListener(
            "click",
            applyDateTimePicker
        );

        $(
            "[data-calendar-prev]"
        )?.addEventListener(
            "click",
            function () {
                if (!calendarCursor) {
                    return;
                }

                calendarCursor = new Date(
                    calendarCursor.getFullYear(),
                    calendarCursor.getMonth() - 1,
                    1
                );

                renderCalendar();
            }
        );

        $(
            "[data-calendar-next]"
        )?.addEventListener(
            "click",
            function () {
                if (!calendarCursor) {
                    return;
                }

                calendarCursor = new Date(
                    calendarCursor.getFullYear(),
                    calendarCursor.getMonth() + 1,
                    1
                );

                renderCalendar();
            }
        );

        $(
            "[data-hour-range]"
        )?.addEventListener(
            "input",
            function (event) {
                if (!dateTimeDraft) {
                    return;
                }

                dateTimeDraft.setHours(
                    Number(
                        event.target.value
                    )
                );

                showStartsAtPopoverError(
                    ""
                );

                renderCalendar();
            }
        );

        $(
            "[data-minute-range]"
        )?.addEventListener(
            "input",
            function (event) {
                if (!dateTimeDraft) {
                    return;
                }

                dateTimeDraft.setMinutes(
                    Number(
                        event.target.value
                    )
                );

                showStartsAtPopoverError(
                    ""
                );

                renderCalendar();
            }
        );

        $all(
            "[data-open-organization-picker]"
        ).forEach(
            function (button) {
                button.addEventListener(
                    "click",
                    function () {
                        openOrganizationPicker(
                            button.dataset
                                .openOrganizationPicker
                        );
                    }
                );
            }
        );

        $(
            "[data-organization-picker-close]"
        )?.addEventListener(
            "click",
            closeOrganizationPicker
        );

        $(
            "[data-organization-picker-cancel]"
        )?.addEventListener(
            "click",
            closeOrganizationPicker
        );

        $(
            "[data-organization-picker-save]"
        )?.addEventListener(
            "click",
            saveOrganizationPicker
        );

        $(
            "[data-organization-search]"
        )?.addEventListener(
            "input",
            renderOrganizationPicker
        );

        $(
            "[data-organization-select-all]"
        )?.addEventListener(
            "change",
            function (event) {
                if (event.target.checked) {
                    organizations.forEach(
                        function (organization) {
                            temporaryOrganizationSelection.add(
                                Number(
                                    organization.id
                                )
                            );
                        }
                    );

                } else {
                    temporaryOrganizationSelection.clear();
                }

                renderOrganizationPicker();
            }
        );

        const configBackdrop = $(
            "[data-pipeline-config-backdrop]"
        );

        const organizationBackdrop = $(
            "[data-organization-picker-backdrop]"
        );

        configBackdrop?.addEventListener(
            "click",
            function (event) {
                if (
                    event.target
                    === configBackdrop
                ) {
                    closeConfigBackdrop();
                }
            }
        );

        organizationBackdrop?.addEventListener(
            "click",
            function (event) {
                if (
                    event.target
                    === organizationBackdrop
                ) {
                    closeOrganizationPicker();
                }
            }
        );

        document.addEventListener(
            "click",
            function (event) {
                const popover = $(
                    "[data-datetime-popover]"
                );

                const shell = (
                    event.target.closest(
                        ".pipeline-datetime-shell"
                    )
                );

                if (
                    popover
                    && !popover.hidden
                    && !shell
                ) {
                    closeDateTimePicker();
                }
            }
        );

        document.addEventListener(
            "keydown",
            function (event) {
                if (
                    event.key
                    !== "Escape"
                ) {
                    return;
                }

                const organizationBackdrop = $(
                    "[data-organization-picker-backdrop]"
                );

                const dateTimePopover = $(
                    "[data-datetime-popover]"
                );

                if (
                    organizationBackdrop
                    && !organizationBackdrop.hidden
                ) {
                    closeOrganizationPicker();
                    return;
                }

                if (
                    dateTimePopover
                    && !dateTimePopover.hidden
                ) {
                    closeDateTimePicker();
                    return;
                }

                const configBackdrop = $(
                    "[data-pipeline-config-backdrop]"
                );

                if (
                    configBackdrop
                    && !configBackdrop.hidden
                ) {
                    closeConfigBackdrop();
                }
            }
        );
    }


    document.addEventListener(
        "DOMContentLoaded",
        function () {
            bindEvents();

            loadPipelineState().catch(
                function (error) {
                    setBanner(
                        "warning",
                        (
                            error.message
                            || (
                                "Не удалось загрузить "
                                + "состояние конвейера."
                            )
                        )
                    );
                }
            );
        }
    );
})();