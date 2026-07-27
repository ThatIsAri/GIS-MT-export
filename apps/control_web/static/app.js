const refreshState = document.getElementById(
    "refresh-state"
);

const createAuthJobsButton = document.getElementById(
    "create-auth-jobs"
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


function renderEntities(entities) {
    const body = document.getElementById(
        "entities-body"
    );

    if (!entities.length) {
        body.innerHTML = `
            <tr>
                <td
                    colspan="7"
                    class="empty"
                >
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

                let certificateText;

                if (entity.certificate_present) {
                    certificateText = badge(
                        "ДОСТУПНА"
                    );

                } else if (
                    entity.certificate_count > 0
                ) {
                    certificateText = badge(
                        "ИЗВЕСТНА"
                    );

                } else {
                    certificateText = badge(
                        "НЕТ"
                    );
                }

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


function renderAgents(agents) {
    const container = document.getElementById(
        "agents-list"
    );

    if (!agents.length) {
        container.innerHTML = `
            <div class="empty">
                Агенты ещё не подключались.
            </div>
        `;

        return;
    }

    container.innerHTML = agents
        .map(
            (agent) => `
                <div class="list-card">
                    <div class="list-card__top">
                        <span class="list-card__title">
                            ${escapeHtml(agent.host_name)}
                        </span>

                        ${badge(agent.status)}
                    </div>

                    <div class="list-card__meta">
                        Версия:
                        ${escapeHtml(agent.agent_version)}
                        <br>

                        Текущая ЭЦП:
                        ${escapeHtml(
                            agent.current_certificate_inn
                            || "—"
                        )}
                        <br>

                        Последняя связь:
                        ${formatDate(agent.last_seen_at)}
                    </div>
                </div>
            `
        )
        .join("");
}


function renderAuthJobs(jobs) {
    const container = document.getElementById(
        "auth-jobs-list"
    );

    if (!jobs.length) {
        container.innerHTML = `
            <div class="empty">
                Заданий пока нет.
            </div>
        `;

        return;
    }

    container.innerHTML = jobs
        .slice(
            0,
            12
        )
        .map(
            (job) => `
                <div class="list-card">
                    <div class="list-card__top">
                        <span class="list-card__title">
                            Организация
                            ${escapeHtml(job.legal_entity_id)}
                        </span>

                        ${badge(job.status)}
                    </div>

                    <div class="list-card__meta">
                        ${escapeHtml(job.job_uuid)}
                        <br>

                        Создано:
                        ${formatDate(job.requested_at)}

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
        .join("");
}


function renderSyncJobs(jobs) {
    const body = document.getElementById(
        "sync-jobs-body"
    );

    if (!jobs.length) {
        body.innerHTML = `
            <tr>
                <td
                    colspan="6"
                    class="empty"
                >
                    Заданий пока нет.
                </td>
            </tr>
        `;

        return;
    }

    body.innerHTML = jobs
        .slice(
            0,
            30
        )
        .map(
            (job) => `
                <tr>
                    <td class="monospace">
                        ${escapeHtml(job.job_uuid)}
                    </td>

                    <td>
                        ${escapeHtml(job.legal_entity_id)}
                    </td>

                    <td>
                        ${badge(job.status)}
                    </td>

                    <td>
                        ${escapeHtml(job.attempt_count)}
                        /
                        retry
                        ${escapeHtml(job.retry_count)}
                    </td>

                    <td>
                        ${formatDate(job.requested_at)}
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
        .join("");
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

        const entities = (
            data.entities
            || []
        );

        const authJobs = (
            data.auth_jobs
            || []
        );

        const syncJobs = (
            data.sync_jobs
            || []
        );

        const agents = (
            data.agents
            || []
        );

        document.getElementById(
            "count-entities"
        ).textContent = entities.length;

        document.getElementById(
            "count-present-certificates"
        ).textContent = entities.filter(
            (entity) => Boolean(
                entity.certificate_present
            )
        ).length;

        document.getElementById(
            "count-auth-active"
        ).textContent = authJobs.filter(
            (job) => activeAuthStatuses.has(
                job.status
            )
        ).length;

        document.getElementById(
            "count-sync-active"
        ).textContent = syncJobs.filter(
            (job) => activeSyncStatuses.has(
                job.status
            )
        ).length;

        renderEntities(
            entities
        );

        renderAgents(
            agents
        );

        renderAuthJobs(
            authJobs
        );

        renderSyncJobs(
            syncJobs
        );

        refreshState.textContent = (
            "Обновлено "
            + new Date().toLocaleTimeString(
                "ru-RU"
            )
        );

    } catch (error) {
        refreshState.textContent = (
            "Ошибка обновления"
        );

        showToast(
            error.message
        );
    }
}


async function createAuthJobs() {
    createAuthJobsButton.disabled = true;

    try {
        const response = await fetch(
            "/api/auth-jobs",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body: JSON.stringify(
                    {
                        requested_by:
                            "control-web",
                    }
                ),
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.error
                || "Не удалось создать задания."
            );
        }

        showToast(
            "Создано: "
            + data.created_count
            + "; пропущено: "
            + data.skipped_count
            + "."
        );

        await loadDashboard();

    } catch (error) {
        showToast(
            error.message
        );

    } finally {
        createAuthJobsButton.disabled = false;
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

    generalFormError.hidden = true;
    generalFormError.textContent = "";
}


function showGeneralFormError(message) {
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

    if (innInput.value.length > length) {
        innInput.value = (
            innInput.value.slice(
                0,
                length
            )
        );
    }

    kppField.hidden = !isLegalEntity;
    kppInput.required = isLegalEntity;

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
    if (!String(
        value || ""
    ).trim()) {
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
    const value = innInput.value.trim();
    const length = expectedInnLength();

    if (!value) {
        setFieldError(
            "inn",
            "Поле не должно быть пустым."
        );

        return false;
    }

    if (
        !/^\d+$/.test(
            value
        )
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

    const value = kppInput.value.trim();

    if (!value) {
        setFieldError(
            "kpp",
            "Поле не должно быть пустым."
        );

        return false;
    }

    if (
        !/^\d{9}$/.test(
            value
        )
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
    const value = thumbprintInput.value.trim();

    if (!value) {
        setFieldError(
            "thumbprint",
            "Поле не должно быть пустым."
        );

        return false;
    }

    if (
        !/^[0-9A-F]{40}$/.test(
            value
        )
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

    document.body.classList.add(
        "modal-open"
    );

    window.setTimeout(
        () => {
            document.getElementById(
                "short-name"
            ).focus();
        },
        0
    );
}


function closeEntityModal() {
    if (saveEntityButton.disabled) {
        return;
    }

    entityModal.hidden = true;

    document.body.classList.remove(
        "modal-open"
    );

    resetEntityForm();
}


async function submitEntityForm(event) {
    event.preventDefault();

    if (!validateEntityForm()) {
        const firstInvalid = document.querySelector(
            ".form-field--invalid input, "
            + ".form-field--invalid select"
        );

        if (firstInvalid) {
            firstInvalid.focus();
        }

        return;
    }

    saveEntityButton.disabled = true;
    generalFormError.hidden = true;

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

        const data = await response.json();

        if (!response.ok) {
            if (data.field) {
                setFieldError(
                    data.field,
                    data.error
                );

                const field = entityForm.elements[
                    data.field
                ];

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

        document.body.classList.remove(
            "modal-open"
        );

        resetEntityForm();

        await loadDashboard();

        showToast(
            (
                "Организация добавлена: "
                + data.entity.short_name
                + "."
            )
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


document.addEventListener(
    "keydown",
    (event) => {
        if (
            event.key === "Escape"
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


createAuthJobsButton.addEventListener(
    "click",
    createAuthJobs
);


updateEntityTypeFields();
loadDashboard();


window.setInterval(
    loadDashboard,
    5000
);