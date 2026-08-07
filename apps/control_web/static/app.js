const refreshState = document.getElementById(
    "refresh-state"
);

const openEntityModalButton = document.getElementById(
    "open-entity-modal"
);

const entityModal = document.getElementById(
    "entity-modal"
);

const entityForm = document.getElementById(
    "entity-form"
);

const saveEntityButton = document.getElementById(
    "save-entity"
);

const entityTypeInput = document.getElementById(
    "entity-type"
);

const innInput = document.getElementById(
    "entity-inn"
);

const innLabel = document.getElementById(
    "inn-label"
);

const kppField = document.getElementById(
    "kpp-field"
);

const kppInput = document.getElementById(
    "entity-kpp"
);

const thumbprintInput = document.getElementById(
    "certificate-thumbprint"
);

const generalFormError = document.getElementById(
    "entity-form-general-error"
);

const toast = document.getElementById(
    "toast"
);

const jobGroupsGrid = document.getElementById(
    "job-groups-grid"
);

const jobDetailsModal = document.getElementById(
    "job-details-modal"
);

const jobDetailsTitle = document.getElementById(
    "job-details-modal-title"
);

const jobDetailsSubtitle = document.getElementById(
    "job-details-modal-subtitle"
);

const jobDetailsLastStatus = document.getElementById(
    "job-details-last-status"
);

const jobDetailsCounters = document.getElementById(
    "job-details-counters"
);

const jobDetailsContent = document.getElementById(
    "job-details-content"
);

const activeAuthStatuses = new Set([
    "PENDING",
    "WAITING_CERTIFICATE",
    "PROCESSING",
]);

const activeSyncStatuses = new Set([
    "CREATED",
    "PUBLISHED",
    "PROCESSING",
    "RETRY_WAIT",
]);

const successStatuses = new Set([
    "SUCCESS",
]);

const retryStatuses = new Set([
    "RETRY_WAIT",
]);

const errorStatuses = new Set([
    "DEAD",
    "ERROR",
    "CANCELLED",
]);

const JOB_GROUP_ORDER = [
    "AUTHORIZATION",
    "EXPORT_UPD",
    "PROCESS_UPD",
    "TRACK_VIOLATIONS",
    "DOWNLOAD_SALES",
];

const JOB_GROUP_META = {
    AUTHORIZATION: {
        title: "Задания авторизаций",
        subtitle: "Токены в базе не сохраняются.",
        type: "auth",
    },

    EXPORT_UPD: {
        title: "Задания скачиваний",
        subtitle: (
            "Скачивание XML и связанных "
            + "данных документов."
        ),
        type: "sync",
    },

    PROCESS_UPD: {
        title: "Задания обработки УПД/УКД",
        subtitle: (
            "Разбор документов, КИ и раскрытие "
            + "упаковок до КИ единицы."
        ),
        type: "sync",
    },

    TRACK_VIOLATIONS: {
        title: "Задания скачивания отклонений",
        subtitle: (
            "Получение отклонений оборота "
            + "подконтрольной продукции."
        ),
        type: "sync",
    },

    DOWNLOAD_SALES: {
        title: "Задания скачивания продаж",
        subtitle: (
            "Получение корректных розничных продаж "
            + "из отчётов ГИС МТ."
        ),
        type: "sync",
    },
};

let latestDashboard = null;
let activeJobGroupCode = null;


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


function formatDate(value) {
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
        return escapeHtml(
            value
        );
    }

    return new Intl.DateTimeFormat(
        "ru-RU",
        {
            dateStyle: "short",
            timeStyle: "medium",
        }
    ).format(
        parsed
    );
}


function statusClass(status) {
    const prepared = String(
        status || ""
    ).toUpperCase();

    if (
        [
            "SUCCESS",
            "ACTIVE",
            "ONLINE",
            "ДОСТУПНА",
        ].includes(
            prepared
        )
    ) {
        return "success";
    }

    if (
        [
            "PENDING",
            "WAITING_CERTIFICATE",
            "PROCESSING",
            "PUBLISHED",
            "CREATED",
            "RETRY_WAIT",
            "SETUP",
            "ИЗВЕСТНА",
        ].includes(
            prepared
        )
    ) {
        return "warning";
    }

    if (
        [
            "ERROR",
            "DEAD",
            "DISABLED",
            "OFFLINE",
            "CANCELLED",
            "НЕТ",
        ].includes(
            prepared
        )
    ) {
        return "danger";
    }

    return "neutral";
}


function badge(
    status,
    fallback = "—"
) {
    const text = (
        status
        || fallback
    );

    return (
        `<span class="badge badge--${statusClass(text)}">`
        + `${escapeHtml(text)}`
        + "</span>"
    );
}


function showToast(message) {
    if (!toast) {
        return;
    }

    toast.textContent = message;

    toast.classList.add(
        "toast--visible"
    );

    window.setTimeout(
        () => {
            toast.classList.remove(
                "toast--visible"
            );
        },
        3500
    );
}


function syncBodyModalState() {
    const openElements = [
        entityModal,
        jobDetailsModal,
        document.getElementById(
            "document-catalog-modal"
        ),
        document.getElementById(
            "datamatrix-storage-modal"
        ),
        document.getElementById(
            "violations-modal"
        ),
        document.querySelector(
            "[data-pipeline-config-backdrop]"
        ),
    ].filter(Boolean);

    const hasVisibleModal = openElements.some(
        (element) => !element.hidden
    );

    document.body.classList.toggle(
        "modal-open",
        hasVisibleModal
    );
}


function renderEntities(entities) {
    const body = document.getElementById(
        "entities-body"
    );

    if (!body) {
        return;
    }

    if (!entities.length) {
        body.innerHTML = `
            <tr>
                <td colspan="7" class="empty">
                    Организации ещё не добавлены.
                </td>
            </tr>
        `;

        return;
    }

    body.innerHTML = entities
        .map(
            (entity) => {
                const displayName = (
                    entity.gis_mt_name
                    || entity.short_name
                );

                const subtitle = (
                    entity.gis_mt_name
                    && entity.gis_mt_name
                        !== entity.short_name
                )
                    ? entity.short_name
                    : entity.status;

                const certificateText = (
                    Number(
                        entity.certificate_count || 0
                    ) > 0
                )
                    ? badge("НАСТРОЕНА")
                    : badge("НЕТ");

                return `
                    <tr>
                        <td>
                            ${escapeHtml(entity.id)}
                        </td>

                        <td>
                            <span class="entity-name">
                                ${escapeHtml(displayName)}
                            </span>

                            <span class="entity-subtitle">
                                ${escapeHtml(subtitle)}
                            </span>
                        </td>

                        <td class="monospace">
                            ${escapeHtml(entity.inn)}
                        </td>

                        <td>
                            ${certificateText}
                        </td>

                        <td>
                            ${badge(entity.active_auth_status)}
                        </td>

                        <td>
                            ${badge(entity.active_sync_status)}
                        </td>

                        <td class="monospace">
                            data/official/${escapeHtml(
                                entity.storage_slug
                            )}
                        </td>
                    </tr>
                `;
            }
        )
        .join("");
}


function sumStatusCounts(
    counts,
    statuses
) {
    return Object.entries(
        counts
    )
        .filter(
            ([status]) => statuses.has(
                String(status).toUpperCase()
            )
        )
        .reduce(
            (
                sum,
                [, count]
            ) => (
                sum
                + Number(
                    count || 0
                )
            ),
            0
        );
}


function summarizeJobsFallback(
    jobs,
    activeStatuses
) {
    const counts = {};

    jobs.forEach(
        (job) => {
            const status = String(
                job.status || ""
            ).toUpperCase();

            counts[status] = (
                Number(
                    counts[status] || 0
                ) + 1
            );
        }
    );

    const lastJob = jobs[0] || null;

    return {
        total_count: jobs.length,

        dead_count: sumStatusCounts(
            counts,
            errorStatuses
        ),

        retry_count: sumStatusCounts(
            counts,
            retryStatuses
        ),

        success_count: sumStatusCounts(
            counts,
            successStatuses
        ),

        running_count: sumStatusCounts(
            counts,
            activeStatuses
        ),

        last_status: (
            lastJob?.status || null
        ),

        last_requested_at: (
            lastJob?.requested_at || null
        ),

        jobs: jobs,
    };
}


function normalizeJobGroups(data) {
    if (
        data
        && data.job_groups
        && typeof data.job_groups === "object"
    ) {
        return data.job_groups;
    }

    return {
        AUTHORIZATION: {
            ...JOB_GROUP_META.AUTHORIZATION,

            ...summarizeJobsFallback(
                data.auth_jobs || [],
                activeAuthStatuses
            ),
        },

        EXPORT_UPD: {
            ...JOB_GROUP_META.EXPORT_UPD,

            ...summarizeJobsFallback(
                data.sync_jobs || [],
                activeSyncStatuses
            ),
        },

        PROCESS_UPD: {
            ...JOB_GROUP_META.PROCESS_UPD,

            ...summarizeJobsFallback(
                data.process_upd_jobs || [],
                activeSyncStatuses
            ),
        },

        TRACK_VIOLATIONS: {
            ...JOB_GROUP_META.TRACK_VIOLATIONS,

            ...summarizeJobsFallback(
                data.violation_jobs || [],
                activeSyncStatuses
            ),
        },

        DOWNLOAD_SALES: {
            ...JOB_GROUP_META.DOWNLOAD_SALES,

            ...summarizeJobsFallback(
                data.sales_jobs || [],
                activeSyncStatuses
            ),
        },
    };
}


function jobCardTone(group) {
    const lastStatus = String(
        group.last_status || ""
    ).toUpperCase();

    if (
        Number(
            group.running_count || 0
        ) > 0
    ) {
        return "running";
    }

    if (
        successStatuses.has(
            lastStatus
        )
    ) {
        return "success";
    }

    if (
        retryStatuses.has(
            lastStatus
        )
    ) {
        return "warning";
    }

    if (
        errorStatuses.has(
            lastStatus
        )
    ) {
        return "danger";
    }

    return "neutral";
}


function renderCounter(
    modifier,
    value,
    label,
    compact = false
) {
    const safeLabel = escapeHtml(
        label
    );

    return `
        <div
            class="job-counter job-counter--${modifier}${
                compact
                    ? " job-counter--compact"
                    : ""
            }"
            title="${safeLabel}: ${escapeHtml(value)}"
            aria-label="${safeLabel}: ${escapeHtml(value)}"
        >
            <span class="job-counter__circle">
                ${escapeHtml(value)}
            </span>

            ${
                compact
                    ? ""
                    : `
                        <span class="job-counter__label">
                            ${safeLabel}
                        </span>
                    `
            }
        </div>
    `;
}


function renderJobCards(jobGroups) {
    if (!jobGroupsGrid) {
        return;
    }

    jobGroupsGrid.innerHTML = JOB_GROUP_ORDER
        .map(
            (code) => {
                const group = {
                    ...JOB_GROUP_META[code],
                    ...(jobGroups[code] || {}),
                };

                const tone = jobCardTone(
                    group
                );

                return `
                    <button
                        type="button"
                        class="
                            job-overview-card
                            job-overview-card--${tone}
                        "
                        data-job-group-button="${escapeHtml(code)}"
                        aria-label="
                            Открыть ${escapeHtml(group.title)}
                        "
                    >
                        <div class="job-overview-card__identity">
                            <h3 class="job-overview-card__title">
                                ${escapeHtml(group.title)}
                            </h3>

                            <div class="job-overview-card__updated">
                                Последнее задание:
                                ${formatDate(
                                    group.last_requested_at
                                )}
                            </div>
                        </div>

                        <div class="job-overview-card__controls">
                            <div
                                class="
                                    job-counters
                                    job-counters--compact
                                "
                            >
                                ${renderCounter(
                                    "total",
                                    Number(
                                        group.total_count || 0
                                    ),
                                    "Всего",
                                    true
                                )}

                                ${renderCounter(
                                    "error",
                                    Number(
                                        group.dead_count || 0
                                    ),
                                    "Error",
                                    true
                                )}

                                ${renderCounter(
                                    "retry",
                                    Number(
                                        group.retry_count || 0
                                    ),
                                    "Retry",
                                    true
                                )}

                                ${renderCounter(
                                    "success",
                                    Number(
                                        group.success_count || 0
                                    ),
                                    "Success",
                                    true
                                )}
                            </div>

                            <div class="job-overview-card__status">
                                ${badge(
                                    group.last_status,
                                    "НЕТ"
                                )}
                            </div>
                        </div>
                    </button>
                `;
            }
        )
        .join("");
}


function renderAuthJobCards(jobs) {
    if (!jobs.length) {
        return `
            <div class="empty">
                Заданий пока нет.
            </div>
        `;
    }

    return `
        <div class="card-list">
            ${jobs
                .map(
                    (job) => `
                        <div class="list-card">
                            <div class="list-card__top">
                                <span class="list-card__title">
                                    Организация
                                    ${escapeHtml(
                                        job.legal_entity_id
                                    )}
                                </span>

                                ${badge(job.status)}
                            </div>

                            <div class="list-card__meta">
                                <span class="monospace">
                                    ${escapeHtml(job.job_uuid)}
                                </span>

                                <br>

                                Создано:
                                ${formatDate(job.requested_at)}

                                ${
                                    job.finished_at
                                        ? (
                                            "<br>Завершено: "
                                            + formatDate(
                                                job.finished_at
                                            )
                                        )
                                        : ""
                                }

                                ${
                                    job.last_error_message
                                        ? (
                                            "<br>Ошибка: "
                                            + escapeHtml(
                                                job.last_error_message
                                            )
                                        )
                                        : ""
                                }
                            </div>
                        </div>
                    `
                )
                .join("")}
        </div>
    `;
}


function renderSyncJobsTable(jobs) {
    if (!jobs.length) {
        return `
            <div class="empty">
                Заданий пока нет.
            </div>
        `;
    }

    return `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Задание</th>
                        <th>Организация</th>
                        <th>Статус</th>
                        <th>Попытки</th>
                        <th>Создано</th>
                        <th>Ошибка</th>
                    </tr>
                </thead>

                <tbody>
                    ${jobs
                        .map(
                            (job) => `
                                <tr>
                                    <td class="monospace">
                                        ${escapeHtml(
                                            job.job_uuid
                                        )}

                                        ${
                                            job.parent_job_uuid
                                                ? (
                                                    "<br>"
                                                    + "<span class=\"muted\">"
                                                    + "родитель: "
                                                    + escapeHtml(
                                                        job.parent_job_uuid
                                                    )
                                                    + "</span>"
                                                )
                                                : ""
                                        }
                                    </td>

                                    <td>
                                        ${escapeHtml(
                                            job.legal_entity_id
                                        )}
                                    </td>

                                    <td>
                                        ${badge(job.status)}
                                    </td>

                                    <td>
                                        ${escapeHtml(
                                            job.attempt_count || 0
                                        )}
                                        / retry
                                        ${escapeHtml(
                                            job.retry_count || 0
                                        )}
                                    </td>

                                    <td>
                                        ${formatDate(
                                            job.requested_at
                                        )}
                                    </td>

                                    <td>
                                        ${escapeHtml(
                                            job.last_error_message
                                            || "—"
                                        )}
                                    </td>
                                </tr>
                            `
                        )
                        .join("")}
                </tbody>
            </table>
        </div>
    `;
}


function openJobDetailsModal(code) {
    if (!latestDashboard) {
        return;
    }

    const jobGroups = normalizeJobGroups(
        latestDashboard
    );

    const group = {
        ...JOB_GROUP_META[code],
        ...(jobGroups[code] || {}),
    };

    activeJobGroupCode = code;

    if (jobDetailsTitle) {
        jobDetailsTitle.textContent = (
            group.title || "Задания"
        );
    }

    if (jobDetailsSubtitle) {
        jobDetailsSubtitle.textContent = (
            group.subtitle || ""
        );
    }

    if (jobDetailsLastStatus) {
        jobDetailsLastStatus.innerHTML = badge(
            group.last_status,
            "НЕТ"
        );
    }

    if (jobDetailsCounters) {
        jobDetailsCounters.innerHTML = [
            renderCounter(
                "total",
                Number(
                    group.total_count || 0
                ),
                "Всего"
            ),

            renderCounter(
                "error",
                Number(
                    group.dead_count || 0
                ),
                "Error"
            ),

            renderCounter(
                "retry",
                Number(
                    group.retry_count || 0
                ),
                "Retry"
            ),

            renderCounter(
                "success",
                Number(
                    group.success_count || 0
                ),
                "Success"
            ),
        ].join("");
    }

    if (jobDetailsContent) {
        if (
            code === "AUTHORIZATION"
        ) {
            jobDetailsContent.innerHTML = (
                renderAuthJobCards(
                    group.jobs || []
                )
            );

        } else {
            jobDetailsContent.innerHTML = (
                renderSyncJobsTable(
                    group.jobs || []
                )
            );
        }
    }

    if (jobDetailsModal) {
        jobDetailsModal.hidden = false;
    }

    syncBodyModalState();
}


function closeJobDetailsModal() {
    activeJobGroupCode = null;

    if (jobDetailsModal) {
        jobDetailsModal.hidden = true;
    }

    syncBodyModalState();
}


async function loadDashboard() {
    try {
        const response = await fetch(
            "/api/dashboard",
            {
                cache: "no-store",
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.error
                || "Не удалось загрузить данные."
            );
        }

        latestDashboard = data;

        const entities = (
            data.entities || []
        );

        const jobGroups = normalizeJobGroups(
            data
        );

        document.getElementById(
            "count-entities"
        ).textContent = entities.length;

        document.getElementById(
            "count-configured-certificates"
        ).textContent = entities.filter(
            (entity) => Number(
                entity.certificate_count || 0
            ) > 0
        ).length;

        document.getElementById(
            "count-auth-active"
        ).textContent = Number(
            jobGroups
                .AUTHORIZATION
                ?.running_count
            || 0
        );

        document.getElementById(
            "count-sync-active"
        ).textContent = (
            Number(
                jobGroups
                    .EXPORT_UPD
                    ?.running_count
                || 0
            )
            + Number(
                jobGroups
                    .PROCESS_UPD
                    ?.running_count
                || 0
            )
            + Number(
                jobGroups
                    .TRACK_VIOLATIONS
                    ?.running_count
                || 0
            )
            + Number(
                jobGroups
                    .DOWNLOAD_SALES
                    ?.running_count
                || 0
            )
        );

        renderEntities(
            entities
        );

        renderJobCards(
            jobGroups
        );

        if (
            activeJobGroupCode
            && jobDetailsModal
            && !jobDetailsModal.hidden
        ) {
            openJobDetailsModal(
                activeJobGroupCode
            );
        }

        if (refreshState) {
            refreshState.textContent = (
                "Обновлено "
                + new Date().toLocaleTimeString(
                    "ru-RU"
                )
            );
        }

    } catch (error) {
        if (refreshState) {
            refreshState.textContent = (
                "Ошибка обновления"
            );
        }

        showToast(
            error.message
        );
    }
}


function clearFieldError(fieldName) {
    const container = document.querySelector(
        `[data-field-container="${fieldName}"]`
    );

    const error = document.querySelector(
        `[data-field-error="${fieldName}"]`
    );

    if (container) {
        container.classList.remove(
            "form-field--invalid"
        );
    }

    if (error) {
        error.textContent = "";
    }
}


function setFieldError(
    fieldName,
    message
) {
    const container = document.querySelector(
        `[data-field-container="${fieldName}"]`
    );

    const error = document.querySelector(
        `[data-field-error="${fieldName}"]`
    );

    if (container) {
        container.classList.add(
            "form-field--invalid"
        );
    }

    if (error) {
        error.textContent = message;
    }
}


function clearAllFormErrors() {
    document
        .querySelectorAll(
            ".form-field--invalid"
        )
        .forEach(
            (element) => {
                element.classList.remove(
                    "form-field--invalid"
                );
            }
        );

    document
        .querySelectorAll(
            ".form-field__error"
        )
        .forEach(
            (element) => {
                element.textContent = "";
            }
        );

    if (generalFormError) {
        generalFormError.hidden = true;
        generalFormError.textContent = "";
    }
}


function showGeneralFormError(message) {
    if (!generalFormError) {
        return;
    }

    generalFormError.textContent = message;
    generalFormError.hidden = false;
}


function expectedInnLength() {
    return (
        entityTypeInput.value
        === "LEGAL_ENTITY"
    )
        ? 10
        : 12;
}


function updateEntityTypeFields() {
    const isLegalEntity = (
        entityTypeInput.value
        === "LEGAL_ENTITY"
    );

    const length = (
        isLegalEntity
            ? 10
            : 12
    );

    innLabel.textContent = (
        `ИНН, ${length} цифр`
    );

    innInput.maxLength = length;

    if (
        innInput.value.length
        > length
    ) {
        innInput.value = (
            innInput.value.slice(
                0,
                length
            )
        );
    }

    kppField.hidden = (
        !isLegalEntity
    );

    kppInput.required = (
        isLegalEntity
    );

    if (!isLegalEntity) {
        kppInput.value = "";

        clearFieldError(
            "kpp"
        );
    }

    clearFieldError(
        "inn"
    );
}


function validateRequiredField(
    fieldName,
    value
) {
    if (
        !String(
            value || ""
        ).trim()
    ) {
        setFieldError(
            fieldName,
            "Поле не должно быть пустым."
        );

        return false;
    }

    clearFieldError(
        fieldName
    );

    return true;
}


function validateInn() {
    const value = (
        innInput.value.trim()
    );

    const length = (
        expectedInnLength()
    );

    if (!value) {
        setFieldError(
            "inn",
            "Поле не должно быть пустым."
        );

        return false;
    }

    if (
        !/^\d+$/.test(value)
        || value.length !== length
    ) {
        setFieldError(
            "inn",
            (
                "Некорректное значение, "
                + `должно быть ${length} символов.`
            )
        );

        return false;
    }

    clearFieldError(
        "inn"
    );

    return true;
}


function validateKpp() {
    if (
        entityTypeInput.value
        !== "LEGAL_ENTITY"
    ) {
        clearFieldError(
            "kpp"
        );

        return true;
    }

    const value = (
        kppInput.value.trim()
    );

    if (!value) {
        setFieldError(
            "kpp",
            "Поле не должно быть пустым."
        );

        return false;
    }

    if (
        !/^\d{9}$/.test(value)
    ) {
        setFieldError(
            "kpp",
            (
                "Некорректное значение, "
                + "должно быть 9 символов."
            )
        );

        return false;
    }

    clearFieldError(
        "kpp"
    );

    return true;
}


function validateThumbprint() {
    const value = (
        thumbprintInput.value.trim()
    );

    if (!value) {
        setFieldError(
            "thumbprint",
            "Поле не должно быть пустым."
        );

        return false;
    }

    if (
        !/^[0-9A-F]{40}$/.test(value)
    ) {
        setFieldError(
            "thumbprint",
            (
                "Некорректное значение, "
                + "должно быть 40 символов."
            )
        );

        return false;
    }

    clearFieldError(
        "thumbprint"
    );

    return true;
}


function validateEntityForm() {
    clearAllFormErrors();

    const formData = new FormData(
        entityForm
    );

    const checks = [
        validateRequiredField(
            "entity_type",
            formData.get(
                "entity_type"
            )
        ),

        validateRequiredField(
            "timezone_name",
            formData.get(
                "timezone_name"
            )
        ),

        validateRequiredField(
            "short_name",
            formData.get(
                "short_name"
            )
        ),

        validateRequiredField(
            "full_name",
            formData.get(
                "full_name"
            )
        ),

        validateInn(),

        validateKpp(),

        validateThumbprint(),

        validateRequiredField(
            "store_location",
            formData.get(
                "store_location"
            )
        ),

        validateRequiredField(
            "store_name",
            formData.get(
                "store_name"
            )
        ),
    ];

    return checks.every(
        Boolean
    );
}


function resetEntityForm() {
    entityForm.reset();

    entityTypeInput.value = (
        "INDIVIDUAL_ENTREPRENEUR"
    );

    document.getElementById(
        "timezone-name"
    ).value = "Europe/Moscow";

    document.getElementById(
        "store-location"
    ).value = "CurrentUser";

    document.getElementById(
        "store-name"
    ).value = "My";

    clearAllFormErrors();
    updateEntityTypeFields();
}


function openEntityModal() {
    resetEntityForm();

    entityModal.hidden = false;

    syncBodyModalState();

    window.setTimeout(
        () => {
            document.getElementById(
                "short-name"
            )?.focus();
        },
        0
    );
}


function closeEntityModal() {
    if (
        saveEntityButton.disabled
    ) {
        return;
    }

    entityModal.hidden = true;

    resetEntityForm();
    syncBodyModalState();
}


async function submitEntityForm(event) {
    event.preventDefault();

    if (
        !validateEntityForm()
    ) {
        const firstInvalid = (
            document.querySelector(
                ".form-field--invalid input, "
                + ".form-field--invalid select"
            )
        );

        if (firstInvalid) {
            firstInvalid.focus();
        }

        return;
    }

    saveEntityButton.disabled = true;

    if (generalFormError) {
        generalFormError.hidden = true;
    }

    const formData = new FormData(
        entityForm
    );

    const body = {
        entity_type: formData.get(
            "entity_type"
        ),

        short_name: formData.get(
            "short_name"
        ),

        full_name: formData.get(
            "full_name"
        ),

        inn: formData.get(
            "inn"
        ),

        kpp: (
            entityTypeInput.value
            === "LEGAL_ENTITY"
        )
            ? formData.get(
                "kpp"
            )
            : null,

        timezone_name: formData.get(
            "timezone_name"
        ),

        thumbprint: formData.get(
            "thumbprint"
        ),

        store_location: formData.get(
            "store_location"
        ),

        store_name: formData.get(
            "store_name"
        ),
    };

    try {
        const response = await fetch(
            "/api/entities",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body: JSON.stringify(
                    body
                ),
            }
        );

        const data = (
            await response.json()
        );

        if (!response.ok) {
            if (data.field) {
                setFieldError(
                    data.field,
                    data.error
                );

                const field = (
                    entityForm.elements[
                        data.field
                    ]
                );

                if (field) {
                    field.focus();
                }

            } else {
                showGeneralFormError(
                    data.error
                    || "Не удалось добавить организацию."
                );
            }

            return;
        }

        entityModal.hidden = true;

        resetEntityForm();
        syncBodyModalState();

        await loadDashboard();

        showToast(
            "Организация добавлена: "
            + data.entity.short_name
            + "."
        );

    } catch (error) {
        showGeneralFormError(
            error.message
            || "Не удалось добавить организацию."
        );

    } finally {
        saveEntityButton.disabled = false;
    }
}


entityTypeInput.addEventListener(
    "change",
    updateEntityTypeFields
);


innInput.addEventListener(
    "input",
    () => {
        innInput.value = (
            innInput.value.replace(
                /\D/g,
                ""
            )
        );

        clearFieldError(
            "inn"
        );
    }
);


kppInput.addEventListener(
    "input",
    () => {
        kppInput.value = (
            kppInput.value.replace(
                /\D/g,
                ""
            )
        );

        clearFieldError(
            "kpp"
        );
    }
);


thumbprintInput.addEventListener(
    "input",
    () => {
        thumbprintInput.value = (
            thumbprintInput.value
                .replace(
                    /[^0-9a-f]/gi,
                    ""
                )
                .toUpperCase()
        );

        clearFieldError(
            "thumbprint"
        );
    }
);


entityForm
    .querySelectorAll(
        "input, select"
    )
    .forEach(
        (field) => {
            field.addEventListener(
                "input",
                () => {
                    clearFieldError(
                        field.name
                    );
                }
            );

            field.addEventListener(
                "change",
                () => {
                    clearFieldError(
                        field.name
                    );
                }
            );
        }
    );


openEntityModalButton.addEventListener(
    "click",
    openEntityModal
);


document
    .querySelectorAll(
        "[data-close-entity-modal]"
    )
    .forEach(
        (element) => {
            element.addEventListener(
                "click",
                closeEntityModal
            );
        }
    );


document
    .querySelectorAll(
        "[data-close-job-details-modal]"
    )
    .forEach(
        (element) => {
            element.addEventListener(
                "click",
                closeJobDetailsModal
            );
        }
    );


jobGroupsGrid?.addEventListener(
    "click",
    (event) => {
        const button = event.target.closest(
            "[data-job-group-button]"
        );

        if (!button) {
            return;
        }

        openJobDetailsModal(
            button.getAttribute(
                "data-job-group-button"
            )
        );
    }
);


document.addEventListener(
    "keydown",
    (event) => {
        if (
            event.key !== "Escape"
        ) {
            return;
        }

        if (
            jobDetailsModal
            && !jobDetailsModal.hidden
        ) {
            closeJobDetailsModal();

            return;
        }

        if (
            entityModal
            && !entityModal.hidden
        ) {
            closeEntityModal();
        }
    }
);


entityForm.addEventListener(
    "submit",
    submitEntityForm
);


updateEntityTypeFields();
loadDashboard();


window.setInterval(
    loadDashboard,
    5000
);