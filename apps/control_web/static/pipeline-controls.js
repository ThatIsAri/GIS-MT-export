(function () {
    "use strict";

    const TASK_AUTHORIZATION = "AUTHORIZATION";
    const TASK_EXPORT_UPD = "EXPORT_UPD";
    const TASK_PROCESS_UPD = "PROCESS_UPD";
    const TASK_TRACK_VIOLATIONS = "TRACK_VIOLATIONS";

    const TASK_CODES = [
        TASK_AUTHORIZATION,
        TASK_EXPORT_UPD,
        TASK_PROCESS_UPD,
        TASK_TRACK_VIOLATIONS
    ];

    const TASK_TITLES = {
        AUTHORIZATION: "Авторизация",
        EXPORT_UPD: "Экспорт УПД/УКД",
        PROCESS_UPD: "Обработка УПД/УКД",
        TRACK_VIOLATIONS: "Отслеживание отклонений в продаже"
    };

    const TASK_DEPENDENCIES = {
        EXPORT_UPD: TASK_AUTHORIZATION,
        PROCESS_UPD: TASK_EXPORT_UPD,
        TRACK_VIOLATIONS: TASK_AUTHORIZATION
    };

    let loadedConfig = null;
    let organizations = [];

    let taskSelections = {
        AUTHORIZATION: new Set(),
        EXPORT_UPD: new Set(),
        PROCESS_UPD: new Set(),
        TRACK_VIOLATIONS: new Set()
    };

    let activeOrganizationTask = null;
    let temporaryOrganizationSelection = new Set();

    let selectedStartsAt = null;
    let originalStartsAtTimestamp = null;
    let dateTimeDraft = null;
    let calendarCursor = null;


    function $(selector) {
        return document.querySelector(selector);
    }


    function $all(selector) {
        return Array.from(
            document.querySelectorAll(selector)
        );
    }


    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    async function parseJsonResponse(response) {
        let payload;

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

            error.field = payload.field || null;
            error.status = response.status;

            throw error;
        }

        return payload;
    }


    function setBanner(kind, message) {
        const banner = $("[data-pipeline-banner]");

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
        const banner = $("[data-pipeline-banner]");

        if (!banner) {
            return;
        }

        banner.hidden = true;
        banner.textContent = "";
        banner.className = "pipeline-banner";
    }


    function updateToggleButton(isEnabled) {
        const button = $("[data-pipeline-toggle]");

        if (!button) {
            return;
        }

        button.textContent = isEnabled ? "Стоп" : "Старт";

        button.classList.toggle(
            "pipeline-action-button-danger",
            isEnabled
        );

        button.classList.toggle(
            "pipeline-action-button-primary",
            !isEnabled
        );
    }


    function setTopButtonsBusy(isBusy) {
        [
            "[data-pipeline-config-open]",
            "[data-pipeline-toggle]",
            "[data-pipeline-test]"
        ].forEach(function (selector) {
            const button = $(selector);

            if (button) {
                button.disabled = isBusy;
            }
        });
    }


    function setConfigBusy(isBusy) {
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
            saveButton.textContent = isBusy
                ? "Сохранение…"
                : "Сохранить";
        }

        if (cancelButton) {
            cancelButton.disabled = isBusy;
        }

        if (closeButton) {
            closeButton.disabled = isBusy;
        }
    }


    function getCheckbox(selector) {
        const element = $(selector);

        return Boolean(element && element.checked);
    }


    function setCheckbox(selector, value) {
        const element = $(selector);

        if (element) {
            element.checked = Boolean(value);
        }
    }


    function getTaskEnabled(taskCode) {
        return getCheckbox(
            `[data-task-enabled="${taskCode}"]`
        );
    }


    function setTaskEnabled(taskCode, value) {
        setCheckbox(
            `[data-task-enabled="${taskCode}"]`,
            value
        );
    }


    function updateTaskSwitchLabels() {
        $all("[data-task-enabled]").forEach(
            function (checkbox) {
                const label = checkbox
                    .closest(".pipeline-switch")
                    ?.querySelector(
                        ".pipeline-switch__label"
                    );

                if (label) {
                    label.textContent = checkbox.checked
                        ? "Да"
                        : "Нет";
                }
            }
        );

        const autorunCheckbox = $(
            "[data-autorun-enabled]"
        );

        const autorunLabel = autorunCheckbox
            ?.closest(".pipeline-switch")
            ?.querySelector(
                ".pipeline-switch__label"
            );

        if (autorunLabel && autorunCheckbox) {
            autorunLabel.textContent = autorunCheckbox.checked
                ? "Включён"
                : "Выключен";
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

        updateTaskSwitchLabels();
    }


    function openConfigBackdrop() {
        const backdrop = $(
            "[data-pipeline-config-backdrop]"
        );

        if (!backdrop) {
            return;
        }

        backdrop.hidden = false;
        document.body.classList.add("modal-open");
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
        document.body.classList.remove("modal-open");
    }


    function clearConfigErrors() {
        $all("[data-config-error]").forEach(
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


    function setConfigFieldError(field, message) {
        const element = $(
            `[data-config-error="${field}"]`
        );

        if (!element) {
            return false;
        }

        element.textContent = message || "";
        return true;
    }


    function setConfigGeneralError(message) {
        const element = $(
            "[data-config-general-error]"
        );

        if (!element) {
            return;
        }

        element.hidden = false;
        element.textContent = message;
    }


    function setPickerMessage(message) {
        const element = $(
            "[data-organization-picker-message]"
        );

        if (!element) {
            return;
        }

        element.hidden = !message;
        element.textContent = message || "";
    }


    function organizationDisplayName(organization) {
        return (
            organization.gis_mt_name
            || organization.short_name
            || `Организация ${organization.id}`
        );
    }


    function updateSelectedSummary(taskCode) {
        const target = $(
            `[data-selected-summary="${taskCode}"]`
        );

        if (!target) {
            return;
        }

        const ids = taskSelections[taskCode]
            || new Set();

        const selectedOrganizations = organizations.filter(
            function (organization) {
                return ids.has(
                    Number(organization.id)
                );
            }
        );

        if (!selectedOrganizations.length) {
            target.textContent = "Организации не выбраны";
            return;
        }

        const names = selectedOrganizations
            .slice(0, 2)
            .map(organizationDisplayName);

        if (selectedOrganizations.length > 2) {
            names.push(
                `ещё ${selectedOrganizations.length - 2}`
            );
        }

        target.innerHTML = (
            `<strong>Выбрано: ${selectedOrganizations.length}</strong>`
            + ` · ${names.map(escapeHtml).join(", ")}`
        );
    }


    function updateAllSelectedSummaries() {
        TASK_CODES.forEach(updateSelectedSummary);
    }


    function defaultStartsAt() {
        const value = new Date();

        value.setSeconds(0, 0);
        value.setMinutes(value.getMinutes() + 1);
        value.setMinutes(
            Math.ceil(value.getMinutes() / 5) * 5
        );

        return value;
    }


    function formatStartsAt(value) {
        if (
            !(value instanceof Date)
            || Number.isNaN(value.getTime())
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
        ).format(value);
    }


    function updateStartsAtText() {
        const target = $("[data-starts-at-text]");

        if (target) {
            target.textContent = formatStartsAt(
                selectedStartsAt
            );
        }
    }


    function startOfLocalDay(value) {
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


    function sameLocalDay(first, second) {
        return (
            first.getFullYear() === second.getFullYear()
            && first.getMonth() === second.getMonth()
            && first.getDate() === second.getDate()
        );
    }


    function isAllowedPastStartsAt(value) {
        if (!(value instanceof Date)) {
            return false;
        }

        if (value.getTime() >= Date.now()) {
            return true;
        }

        return (
            originalStartsAtTimestamp !== null
            && Math.abs(
                value.getTime()
                - originalStartsAtTimestamp
            ) < 1000
        );
    }


    function showStartsAtPopoverError(message) {
        const target = $("[data-starts-at-error]");

        if (!target) {
            return;
        }

        target.hidden = !message;
        target.textContent = message || "";
    }


    function renderCalendar() {
        const grid = $("[data-calendar-grid]");
        const title = $("[data-calendar-title]");
        const previousButton = $("[data-calendar-prev]");
        const hourRange = $("[data-hour-range]");
        const minuteRange = $("[data-minute-range]");
        const hourValue = $("[data-hour-value]");
        const minuteValue = $("[data-minute-value]");

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
            `${monthNames[calendarCursor.getMonth()]} `
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
            firstDay.getDay() + 6
        ) % 7;

        const today = startOfLocalDay(new Date());
        const elements = [];

        for (let index = 0; index < mondayOffset; index += 1) {
            elements.push(
                '<span class="pipeline-calendar-day-placeholder"></span>'
            );
        }

        for (let day = 1; day <= daysInMonth; day += 1) {
            const value = new Date(
                calendarCursor.getFullYear(),
                calendarCursor.getMonth(),
                day,
                0,
                0,
                0,
                0
            );

            const disabled = value.getTime() < today.getTime();
            const classes = ["pipeline-calendar-day"];

            if (sameLocalDay(value, dateTimeDraft)) {
                classes.push(
                    "pipeline-calendar-day--selected"
                );
            }

            if (sameLocalDay(value, new Date())) {
                classes.push(
                    "pipeline-calendar-day--today"
                );
            }

            elements.push(
                `<button type="button" `
                + `class="${classes.join(" ")}" `
                + `data-calendar-day="${day}" `
                + `${disabled ? "disabled" : ""}>`
                + `${day}</button>`
            );
        }

        grid.innerHTML = elements.join("");

        $all("[data-calendar-day]").forEach(
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
                            && dateTimeDraft.getTime() < Date.now()
                        ) {
                            const adjusted = defaultStartsAt();

                            dateTimeDraft.setHours(
                                adjusted.getHours(),
                                adjusted.getMinutes(),
                                0,
                                0
                            );
                        }

                        showStartsAtPopoverError("");
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
            ).padStart(2, "0");
        }

        if (minuteValue) {
            minuteValue.textContent = String(
                dateTimeDraft.getMinutes()
            ).padStart(2, "0");
        }
    }


    function openDateTimePicker() {
        const popover = $("[data-datetime-popover]");
        const button = $("[data-starts-at-open]");

        if (!popover || !button || button.disabled) {
            return;
        }

        dateTimeDraft = new Date(
            selectedStartsAt || defaultStartsAt()
        );

        calendarCursor = new Date(
            dateTimeDraft.getFullYear(),
            dateTimeDraft.getMonth(),
            1
        );

        showStartsAtPopoverError("");
        renderCalendar();
        popover.hidden = false;
    }


    function closeDateTimePicker() {
        const popover = $("[data-datetime-popover]");

        if (popover) {
            popover.hidden = true;
        }

        dateTimeDraft = null;
        calendarCursor = null;
        showStartsAtPopoverError("");
    }


    function applyDateTimePicker() {
        if (!dateTimeDraft) {
            return;
        }

        if (!isAllowedPastStartsAt(dateTimeDraft)) {
            showStartsAtPopoverError(
                "Нельзя указать дату и время раньше текущего момента."
            );
            return;
        }

        selectedStartsAt = new Date(dateTimeDraft);
        updateStartsAtText();
        setConfigFieldError("autorun.starts_at", "");
        closeDateTimePicker();
    }


    function normalizeSearch(value) {
        return String(value || "")
            .toLocaleUpperCase("ru-RU")
            .replace(/\s+/g, " ")
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
                organizationDisplayName(organization),
                organization.short_name,
                organization.gis_mt_name,
                organization.inn
            ].filter(Boolean).join(" ")
        );

        return haystack.includes(searchValue);
    }


    function dependencyForTask(taskCode) {
        return TASK_DEPENDENCIES[taskCode] || null;
    }


    function dependencyErrorMessage(taskCode) {
        const dependency = dependencyForTask(taskCode);

        if (!dependency) {
            return "";
        }

        return (
            `Организацию нельзя добавить к заданию «${TASK_TITLES[taskCode]}»: `
            + `сначала добавьте её в задание «${TASK_TITLES[dependency]}».`
        );
    }


    function eligibleOrganizationIds(taskCode) {
        const dependency = dependencyForTask(taskCode);

        if (!dependency) {
            return new Set(
                organizations.map(function (organization) {
                    return Number(organization.id);
                })
            );
        }

        if (!getTaskEnabled(dependency)) {
            return new Set();
        }

        return new Set(taskSelections[dependency]);
    }


    function pruneDependentSelections(parentTaskCode) {
        const directDependents = Object.entries(
            TASK_DEPENDENCIES
        )
            .filter(function (entry) {
                return entry[1] === parentTaskCode;
            })
            .map(function (entry) {
                return entry[0];
            });

        directDependents.forEach(function (taskCode) {
            const allowed = taskSelections[parentTaskCode];

            taskSelections[taskCode] = new Set(
                Array.from(taskSelections[taskCode]).filter(
                    function (entityId) {
                        return allowed.has(entityId);
                    }
                )
            );

            pruneDependentSelections(taskCode);
        });
    }


    function disableDependentTasks(parentTaskCode) {
        Object.entries(TASK_DEPENDENCIES)
            .filter(function (entry) {
                return entry[1] === parentTaskCode;
            })
            .forEach(function (entry) {
                const taskCode = entry[0];

                setTaskEnabled(taskCode, false);
                taskSelections[taskCode].clear();
                disableDependentTasks(taskCode);
            });
    }


    function updateSelectAllCheckbox() {
        const checkbox = $(
            "[data-organization-select-all]"
        );

        if (!checkbox || !activeOrganizationTask) {
            return;
        }

        const eligible = eligibleOrganizationIds(
            activeOrganizationTask
        );

        const eligibleIds = Array.from(eligible);
        const selectedCount = eligibleIds.filter(
            function (entityId) {
                return temporaryOrganizationSelection.has(
                    entityId
                );
            }
        ).length;

        checkbox.checked = (
            eligibleIds.length > 0
            && selectedCount === eligibleIds.length
        );

        checkbox.indeterminate = (
            selectedCount > 0
            && selectedCount < eligibleIds.length
        );

        checkbox.disabled = eligibleIds.length === 0;
    }


    function renderOrganizationPicker() {
        const list = $("[data-organization-list]");
        const count = $("[data-organization-count]");
        const empty = $("[data-organization-empty]");
        const search = normalizeSearch(
            $("[data-organization-search]")?.value
        );

        if (!list || !activeOrganizationTask) {
            return;
        }

        const eligible = eligibleOrganizationIds(
            activeOrganizationTask
        );

        const dependency = dependencyForTask(
            activeOrganizationTask
        );

        const filtered = organizations.filter(
            function (organization) {
                return organizationMatchesSearch(
                    organization,
                    search
                );
            }
        );

        if (count) {
            count.textContent = String(
                organizations.length
            );
        }

        if (empty) {
            empty.hidden = filtered.length > 0;
        }

        list.innerHTML = filtered.map(
            function (organization) {
                const entityId = Number(organization.id);
                const allowed = eligible.has(entityId);
                const checked = (
                    allowed
                    && temporaryOrganizationSelection.has(entityId)
                );

                const statusText = allowed
                    ? organization.status
                    : (
                        dependency
                            ? `Сначала: ${TASK_TITLES[dependency]}`
                            : organization.status
                    );

                return `
                    <label
                        class="pipeline-tree-item"
                        ${allowed ? "" : "data-organization-ineligible"}
                    >
                        <input
                            type="checkbox"
                            value="${entityId}"
                            data-organization-checkbox
                            ${checked ? "checked" : ""}
                            ${allowed ? "" : "disabled"}
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
                                ИНН ${escapeHtml(organization.inn)}
                            </span>
                        </span>

                        <span class="pipeline-tree-item__status">
                            ${escapeHtml(statusText)}
                        </span>
                    </label>
                `;
            }
        ).join("");

        $all("[data-organization-checkbox]").forEach(
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

                        setPickerMessage("");
                        updateSelectAllCheckbox();
                    }
                );
            }
        );

        $all("[data-organization-ineligible]").forEach(
            function (label) {
                label.addEventListener(
                    "click",
                    function (event) {
                        event.preventDefault();
                        setPickerMessage(
                            dependencyErrorMessage(
                                activeOrganizationTask
                            )
                        );
                    }
                );
            }
        );

        updateSelectAllCheckbox();
    }


    function openOrganizationPicker(taskCode) {
        if (!TASK_CODES.includes(taskCode)) {
            return;
        }

        const backdrop = $(
            "[data-organization-picker-backdrop]"
        );

        if (!backdrop) {
            return;
        }

        activeOrganizationTask = taskCode;

        const eligible = eligibleOrganizationIds(taskCode);

        temporaryOrganizationSelection = new Set(
            Array.from(taskSelections[taskCode]).filter(
                function (entityId) {
                    return eligible.has(entityId);
                }
            )
        );

        const title = $("#organization-picker-title");
        const subtitle = $(
            "[data-organization-picker-subtitle]"
        );
        const search = $("[data-organization-search]");

        if (title) {
            title.textContent = TASK_TITLES[taskCode];
        }

        if (subtitle) {
            subtitle.textContent = (
                "Выберите организации, для которых "
                + "будет выполняться это задание."
            );
        }

        if (search) {
            search.value = "";
        }

        setPickerMessage(
            eligible.size === 0
            && dependencyForTask(taskCode)
                ? dependencyErrorMessage(taskCode)
                : ""
        );

        renderOrganizationPicker();
        backdrop.hidden = false;
        search?.focus();
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
        setPickerMessage("");
    }


    function saveOrganizationPicker() {
        if (!activeOrganizationTask) {
            return;
        }

        const taskCode = activeOrganizationTask;
        const eligible = eligibleOrganizationIds(taskCode);

        taskSelections[taskCode] = new Set(
            Array.from(temporaryOrganizationSelection).filter(
                function (entityId) {
                    return eligible.has(entityId);
                }
            )
        );

        pruneDependentSelections(taskCode);
        updateAllSelectedSummaries();
        closeOrganizationPicker();
    }


    function populateConfig(payload) {
        loadedConfig = payload.config || {};
        organizations = Array.isArray(payload.organizations)
            ? payload.organizations
            : [];

        const autorun = loadedConfig.autorun || {};
        const tasks = loadedConfig.tasks || {};
        const authorization = tasks.authorization || {};
        const exportUpd = tasks.export_upd || {};
        const processUpd = tasks.process_upd || {};
        const trackViolations = (
            tasks.track_violations || {}
        );

        setCheckbox(
            "[data-autorun-enabled]",
            Boolean(autorun.enabled)
        );

        const schedule = $(
            "[data-autorun-schedule]"
        );

        if (schedule) {
            schedule.value = autorun.schedule || "DAILY";
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

        if (Number.isNaN(selectedStartsAt.getTime())) {
            selectedStartsAt = defaultStartsAt();
            originalStartsAtTimestamp = null;
        }

        updateStartsAtText();

        setTaskEnabled(
            TASK_AUTHORIZATION,
            Boolean(authorization.enabled)
        );

        setTaskEnabled(
            TASK_EXPORT_UPD,
            Boolean(exportUpd.enabled)
        );

        setTaskEnabled(
            TASK_PROCESS_UPD,
            Boolean(processUpd.enabled)
        );

        setTaskEnabled(
            TASK_TRACK_VIOLATIONS,
            Boolean(trackViolations.enabled)
        );

        taskSelections = {
            AUTHORIZATION: new Set(
                (authorization.entity_ids || []).map(Number)
            ),
            EXPORT_UPD: new Set(
                (exportUpd.entity_ids || []).map(Number)
            ),
            PROCESS_UPD: new Set(
                (processUpd.entity_ids || []).map(Number)
            ),
            TRACK_VIOLATIONS: new Set(
                (trackViolations.entity_ids || []).map(Number)
            )
        };

        const today = new Date()
            .toISOString()
            .slice(0, 10);

        const periodFrom = $(
            "[data-export-period-from]"
        );

        const periodTo = $(
            "[data-export-period-to]"
        );

        if (periodFrom) {
            periodFrom.value = (
                exportUpd.period_from || today
            );
        }

        if (periodTo) {
            periodTo.value = (
                exportUpd.period_to || today
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

        const payload = await parseJsonResponse(response);
        populateConfig(payload);
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


    function taskSelectionArray(taskCode) {
        return Array.from(
            taskSelections[taskCode] || []
        ).sort(function (first, second) {
            return first - second;
        });
    }


    function validateSubset(
        childTask,
        parentTask,
        field,
        message
    ) {
        const missing = taskSelectionArray(childTask)
            .filter(function (entityId) {
                return !taskSelections[parentTask].has(
                    entityId
                );
            });

        if (!missing.length) {
            return true;
        }

        setConfigFieldError(field, message);
        return false;
    }


    function validateConfiguration() {
        clearConfigErrors();

        let valid = true;

        if (
            getCheckbox("[data-autorun-enabled]")
            && !selectedStartsAt
        ) {
            setConfigFieldError(
                "autorun.starts_at",
                "Укажите дату и время начала."
            );
            valid = false;
        }

        if (
            getCheckbox("[data-autorun-enabled]")
            && selectedStartsAt
            && !isAllowedPastStartsAt(selectedStartsAt)
        ) {
            setConfigFieldError(
                "autorun.starts_at",
                "Нельзя указать дату и время раньше текущего момента."
            );
            valid = false;
        }

        const authorizationEnabled = getTaskEnabled(
            TASK_AUTHORIZATION
        );

        const exportEnabled = getTaskEnabled(
            TASK_EXPORT_UPD
        );

        const processEnabled = getTaskEnabled(
            TASK_PROCESS_UPD
        );

        const violationsEnabled = getTaskEnabled(
            TASK_TRACK_VIOLATIONS
        );

        if (
            authorizationEnabled
            && taskSelections[TASK_AUTHORIZATION].size === 0
        ) {
            setConfigFieldError(
                "tasks.authorization.entity_ids",
                "Выберите хотя бы одну организацию."
            );
            valid = false;
        }

        if (exportEnabled) {
            if (!authorizationEnabled) {
                setConfigFieldError(
                    "tasks.export_upd.entity_ids",
                    "Сначала включите задание «Авторизация»."
                );
                valid = false;
            }

            if (taskSelections[TASK_EXPORT_UPD].size === 0) {
                setConfigFieldError(
                    "tasks.export_upd.entity_ids",
                    "Выберите хотя бы одну организацию."
                );
                valid = false;
            }

            const periodFrom = $(
                "[data-export-period-from]"
            )?.value || "";

            const periodTo = $(
                "[data-export-period-to]"
            )?.value || "";

            if (!periodFrom || !periodTo) {
                setConfigFieldError(
                    "tasks.export_upd.period",
                    "Укажите обе даты периода."
                );
                valid = false;
            } else if (periodFrom > periodTo) {
                setConfigFieldError(
                    "tasks.export_upd.period",
                    "Дата «с» не может быть позже даты «по»."
                );
                valid = false;
            }

            if (!validateSubset(
                TASK_EXPORT_UPD,
                TASK_AUTHORIZATION,
                "tasks.export_upd.entity_ids",
                "Все организации экспорта должны участвовать в авторизации."
            )) {
                valid = false;
            }
        }

        if (processEnabled) {
            if (!exportEnabled) {
                setConfigFieldError(
                    "tasks.process_upd.enabled",
                    "Сначала включите задание «Экспорт УПД/УКД»."
                );
                valid = false;
            }

            if (taskSelections[TASK_PROCESS_UPD].size === 0) {
                setConfigFieldError(
                    "tasks.process_upd.entity_ids",
                    "Выберите хотя бы одну организацию."
                );
                valid = false;
            }

            if (!validateSubset(
                TASK_PROCESS_UPD,
                TASK_EXPORT_UPD,
                "tasks.process_upd.entity_ids",
                "Организацию можно добавить только после добавления в «Экспорт УПД/УКД»."
            )) {
                valid = false;
            }
        }

        if (violationsEnabled) {
            if (!authorizationEnabled) {
                setConfigFieldError(
                    "tasks.track_violations.enabled",
                    "Сначала включите задание «Авторизация»."
                );
                valid = false;
            }

            if (
                taskSelections[TASK_TRACK_VIOLATIONS].size
                === 0
            ) {
                setConfigFieldError(
                    "tasks.track_violations.entity_ids",
                    "Выберите хотя бы одну организацию."
                );
                valid = false;
            }

            if (!validateSubset(
                TASK_TRACK_VIOLATIONS,
                TASK_AUTHORIZATION,
                "tasks.track_violations.entity_ids",
                "Организацию можно добавить только после добавления в «Авторизацию»."
            )) {
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
                schedule: $(
                    "[data-autorun-schedule]"
                )?.value || "DAILY",
                starts_at: selectedStartsAt
                    ? selectedStartsAt.toISOString()
                    : null
            },
            tasks: {
                authorization: {
                    enabled: getTaskEnabled(
                        TASK_AUTHORIZATION
                    ),
                    entity_ids: taskSelectionArray(
                        TASK_AUTHORIZATION
                    )
                },
                export_upd: {
                    enabled: getTaskEnabled(
                        TASK_EXPORT_UPD
                    ),
                    period_from: $(
                        "[data-export-period-from]"
                    )?.value || null,
                    period_to: $(
                        "[data-export-period-to]"
                    )?.value || null,
                    entity_ids: taskSelectionArray(
                        TASK_EXPORT_UPD
                    )
                },
                process_upd: {
                    enabled: getTaskEnabled(
                        TASK_PROCESS_UPD
                    ),
                    entity_ids: taskSelectionArray(
                        TASK_PROCESS_UPD
                    )
                },
                track_violations: {
                    enabled: getTaskEnabled(
                        TASK_TRACK_VIOLATIONS
                    ),
                    entity_ids: taskSelectionArray(
                        TASK_TRACK_VIOLATIONS
                    )
                }
            }
        };
    }


    async function saveConfiguration(event) {
        event.preventDefault();

        if (!validateConfiguration()) {
            return;
        }

        setConfigBusy(true);

        try {
            const response = await fetch(
                "/api/pipeline/config",
                {
                    method: "PUT",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json"
                    },
                    body: JSON.stringify(
                        buildConfigurationPayload()
                    )
                }
            );

            const payload = await parseJsonResponse(response);

            loadedConfig = payload.config || loadedConfig;
            closeConfigBackdrop();
            setBanner(
                "success",
                payload.message
                || "Конфигурация конвейера сохранена."
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
            setConfigBusy(false);
        }
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

        const payload = await parseJsonResponse(response);
        const state = payload.state || {};

        updateToggleButton(
            Boolean(state.pipeline_enabled)
        );

        const testButton = $("[data-pipeline-test]");

        if (testButton) {
            testButton.disabled = Boolean(
                state.test_running
                || state.current_run_uuid
            );
        }
    }


    async function togglePipelineState() {
        clearBanner();
        setTopButtonsBusy(true);

        try {
            const button = $("[data-pipeline-toggle]");
            const desiredEnabled = (
                button?.textContent.trim() !== "Стоп"
            );

            const response = await fetch(
                "/api/pipeline/toggle",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json"
                    },
                    body: JSON.stringify({
                        enabled: desiredEnabled
                    })
                }
            );

            const payload = await parseJsonResponse(response);

            updateToggleButton(
                Boolean(
                    payload.state?.pipeline_enabled
                )
            );

            setBanner(
                "success",
                payload.message
                || "Состояние конвейера изменено."
            );
        } catch (error) {
            setBanner(
                "error",
                error.message
                || "Не удалось изменить состояние конвейера."
            );
        } finally {
            setTopButtonsBusy(false);
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
                        Accept: "application/json"
                    }
                }
            );

            const payload = await parseJsonResponse(response);

            setBanner(
                "success",
                payload.message
                || "Тестовый запуск поставлен в очередь."
            );
        } catch (error) {
            setBanner(
                "error",
                error.message
                || "Не удалось запустить тест."
            );
        } finally {
            setTopButtonsBusy(false);
        }
    }


    function bindEvents() {
        $("[data-pipeline-config-open]")
            ?.addEventListener(
                "click",
                openConfiguration
            );

        $("[data-pipeline-config-close]")
            ?.addEventListener(
                "click",
                closeConfigBackdrop
            );

        $("[data-pipeline-config-cancel]")
            ?.addEventListener(
                "click",
                closeConfigBackdrop
            );

        $("[data-pipeline-toggle]")
            ?.addEventListener(
                "click",
                togglePipelineState
            );

        $("[data-pipeline-test]")
            ?.addEventListener(
                "click",
                runTestRequest
            );

        $("[data-pipeline-config-form]")
            ?.addEventListener(
                "submit",
                saveConfiguration
            );

        $("[data-autorun-enabled]")
            ?.addEventListener(
                "change",
                refreshEnabledStates
            );

        $all("[data-task-enabled]").forEach(
            function (checkbox) {
                checkbox.addEventListener(
                    "change",
                    function () {
                        const taskCode = checkbox.dataset
                            .taskEnabled;

                        if (!checkbox.checked) {
                            disableDependentTasks(
                                taskCode
                            );
                            pruneDependentSelections(
                                taskCode
                            );
                            updateAllSelectedSummaries();
                        }

                        refreshEnabledStates();
                    }
                );
            }
        );

        $("[data-starts-at-open]")
            ?.addEventListener(
                "click",
                openDateTimePicker
            );

        $("[data-datetime-cancel]")
            ?.addEventListener(
                "click",
                closeDateTimePicker
            );

        $("[data-datetime-apply]")
            ?.addEventListener(
                "click",
                applyDateTimePicker
            );

        $("[data-calendar-prev]")
            ?.addEventListener(
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

        $("[data-calendar-next]")
            ?.addEventListener(
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

        $("[data-hour-range]")
            ?.addEventListener(
                "input",
                function (event) {
                    if (!dateTimeDraft) {
                        return;
                    }

                    dateTimeDraft.setHours(
                        Number(event.target.value)
                    );

                    showStartsAtPopoverError("");
                    renderCalendar();
                }
            );

        $("[data-minute-range]")
            ?.addEventListener(
                "input",
                function (event) {
                    if (!dateTimeDraft) {
                        return;
                    }

                    dateTimeDraft.setMinutes(
                        Number(event.target.value)
                    );

                    showStartsAtPopoverError("");
                    renderCalendar();
                }
            );

        $all("[data-open-organization-picker]").forEach(
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

        $("[data-organization-picker-close]")
            ?.addEventListener(
                "click",
                closeOrganizationPicker
            );

        $("[data-organization-picker-cancel]")
            ?.addEventListener(
                "click",
                closeOrganizationPicker
            );

        $("[data-organization-picker-save]")
            ?.addEventListener(
                "click",
                saveOrganizationPicker
            );

        $("[data-organization-search]")
            ?.addEventListener(
                "input",
                renderOrganizationPicker
            );

        $("[data-organization-select-all]")
            ?.addEventListener(
                "change",
                function (event) {
                    if (!activeOrganizationTask) {
                        return;
                    }

                    const eligible = eligibleOrganizationIds(
                        activeOrganizationTask
                    );

                    if (event.target.checked) {
                        temporaryOrganizationSelection = new Set(
                            eligible
                        );
                    } else {
                        temporaryOrganizationSelection.clear();
                    }

                    setPickerMessage("");
                    renderOrganizationPicker();
                }
            );

        $("[data-pipeline-config-backdrop]")
            ?.addEventListener(
                "click",
                function (event) {
                    if (
                        event.target
                        === event.currentTarget
                    ) {
                        closeConfigBackdrop();
                    }
                }
            );

        $("[data-organization-picker-backdrop]")
            ?.addEventListener(
                "click",
                function (event) {
                    if (
                        event.target
                        === event.currentTarget
                    ) {
                        closeOrganizationPicker();
                    }
                }
            );

        document.addEventListener(
            "keydown",
            function (event) {
                if (event.key !== "Escape") {
                    return;
                }

                const organizationBackdrop = $(
                    "[data-organization-picker-backdrop]"
                );

                if (
                    organizationBackdrop
                    && !organizationBackdrop.hidden
                ) {
                    closeOrganizationPicker();
                    return;
                }

                const dateTimePopover = $(
                    "[data-datetime-popover]"
                );

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


    async function initialize() {
        bindEvents();

        try {
            await loadPipelineState();
        } catch (_error) {
            updateToggleButton(false);
        }

        window.setInterval(
            async function () {
                try {
                    await loadPipelineState();
                } catch (_error) {
                    return;
                }
            },
            5000
        );
    }


    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initialize
        );
    } else {
        initialize();
    }
})();