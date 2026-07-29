(function () {
    "use strict";

    function violationsIconSvg() {
        return `
            <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
            >
                <path
                    d="M12 3.5L21 19H3L12 3.5Z"
                ></path>

                <path
                    d="M12 9V13.5"
                ></path>

                <path
                    d="M12 17H12.01"
                ></path>
            </svg>
        `;
    }


    function createInterface() {
        if (
            document.getElementById(
                "violations-modal"
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

        button.id = "open-violations";
        button.type = "button";

        button.className = (
            "button "
            + "button--violations"
        );

        button.innerHTML = `
            <span
                class="violations-button__icon"
            >
                ${violationsIconSvg()}
            </span>

            <span
                class="violations-button__text"
            >
                <span
                    class="violations-button__title"
                >
                    Отклонения
                </span>

                <span
                    class="violations-button__subtitle"
                >
                    Контроль ГИС МТ
                </span>
            </span>
        `;

        rail.appendChild(
            button
        );

        const modal = document.createElement(
            "div"
        );

        modal.id = "violations-modal";
        modal.className = "violations-modal";
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
            "violations-title"
        );

        modal.innerHTML = `
            <div
                class="violations-backdrop"
                data-close-violations
            ></div>

            <section
                class="violations-window"
            >
                <header
                    class="violations-header"
                >
                    <div>
                        <h2
                            id="violations-title"
                        >
                            Отклонения
                        </h2>

                        <p>
                            Отклонения оборота
                            подконтрольной продукции
                            по данным ГИС МТ
                        </p>
                    </div>

                    <button
                        class="violations-close"
                        type="button"
                        aria-label="Закрыть окно отклонений"
                        data-close-violations
                    >
                        ×
                    </button>
                </header>

                <form
                    class="violations-toolbar"
                    novalidate
                >
                    <div
                        class="
                            violations-field
                            violations-field--search
                        "
                    >
                        <label
                            for="violations-query"
                        >
                            Поиск
                        </label>

                        <input
                            id="violations-query"
                            type="search"
                            autocomplete="off"
                            disabled
                        >
                    </div>

                    <div
                        class="violations-field"
                    >
                        <label
                            for="violations-entity"
                        >
                            Организация
                        </label>

                        <select
                            id="violations-entity"
                            disabled
                        >
                            <option>
                                Все организации
                            </option>
                        </select>
                    </div>

                    <div
                        class="violations-field"
                    >
                        <label
                            for="violations-period-from"
                        >
                            Период с
                        </label>

                        <input
                            id="violations-period-from"
                            type="date"
                            disabled
                        >
                    </div>

                    <div
                        class="violations-field"
                    >
                        <label
                            for="violations-period-to"
                        >
                            Период по
                        </label>

                        <input
                            id="violations-period-to"
                            type="date"
                            disabled
                        >
                    </div>

                    <div
                        class="violations-actions"
                    >
                        <button
                            class="button button--primary"
                            type="button"
                            disabled
                        >
                            Применить
                        </button>
                    </div>
                </form>

                <div
                    class="violations-content"
                >
                    <div
                        class="violations-table-wrap"
                    >
                        <table
                            class="violations-table"
                        >
                            <thead>
                                <tr>
                                    <th>
                                        Дата операции
                                    </th>

                                    <th>
                                        Организация
                                    </th>

                                    <th>
                                        КИ / GTIN
                                    </th>

                                    <th>
                                        Вид отклонения
                                    </th>

                                    <th>
                                        Результат
                                    </th>

                                    <th>
                                        Торговая точка
                                    </th>

                                    <th>
                                        ККТ
                                    </th>

                                    <th>
                                        Нивелировано
                                    </th>
                                </tr>
                            </thead>

                            <tbody>
                                <tr>
                                    <td
                                        colspan="8"
                                        class="violations-empty"
                                    >
                                        Выгрузка отклонений
                                        подключена к конвейеру.
                                        Список будет выведен
                                        на следующем этапе.
                                    </td>
                                </tr>
                            </tbody>
                        </table>
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
            "violations-modal"
        );
    }


    function syncBodyModalState() {
        const modalIds = [
            "entity-modal",
            "document-catalog-modal",
            "datamatrix-storage-modal",
            "violations-modal"
        ];

        const anyOpened = modalIds.some(
            (modalId) => {
                const modal = (
                    document.getElementById(
                        modalId
                    )
                );

                return Boolean(
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


    function openViolations() {
        const modal = getModal();

        if (!modal) {
            return;
        }

        modal.hidden = false;

        syncBodyModalState();
    }


    function closeViolations() {
        const modal = getModal();

        if (!modal) {
            return;
        }

        modal.hidden = true;

        syncBodyModalState();

        document.getElementById(
            "open-violations"
        )?.focus();
    }


    function bindEvents() {
        document.getElementById(
            "open-violations"
        )?.addEventListener(
            "click",
            openViolations
        );

        document
            .querySelectorAll(
                "[data-close-violations]"
            )
            .forEach(
                (element) => {
                    element.addEventListener(
                        "click",
                        closeViolations
                    );
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