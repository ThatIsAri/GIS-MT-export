(function () {
    "use strict";

    const API_URL = "/api/analytics-dashboard";

    const VIOLATION_COLORS = [
        "#A45CC5",
        "#B16DD0",
        "#BD7FDB",
        "#C991E4",
        "#D7ADEB",
        "#8E49B1",
        "#7C3D9E",
        "#E3C5F2"
    ];

    const DOCUMENT_COLORS = [
        "#F2D23C",
        "#F6DF70",
        "#FAEBA2"
    ];

    const PENALTY_COLORS = [
        "#FF3D46",
        "#FF7A81"
    ];

    const SALES_COLORS = [
        "#3DB2D9",
        "#8DD5E8"
    ];

    const CIRCLE_INTRO_SETTINGS = {
        "sales-chart": {
            startAngle: "-42deg",
            duration: 1880,
            delay: 40,
            numberDelay: 260,
            titleDelay: 860
        },

        "violations-chart": {
            startAngle: "96deg",
            duration: 1720,
            delay: 210,
            numberDelay: 390,
            titleDelay: 960
        },

        "penalties-chart": {
            startAngle: "208deg",
            duration: 2060,
            delay: 110,
            numberDelay: 330,
            titleDelay: 920
        },

        "documents-chart": {
            startAngle: "302deg",
            duration: 1800,
            delay: 300,
            numberDelay: 470,
            titleDelay: 1080
        }
    };

    const CIRCLE_RENDER_CONFIG = {
        "sales-chart": {
            cardKey: "sales",
            colors: SALES_COLORS,
            sizeClass: "analytics-pie--large"
        },

        "violations-chart": {
            cardKey: "violations",
            colors: VIOLATION_COLORS,
            sizeClass: "analytics-pie--medium"
        },

        "penalties-chart": {
            cardKey: "penalties",
            colors: PENALTY_COLORS,
            sizeClass: "analytics-pie--large"
        },

        "documents-chart": {
            cardKey: "documents",
            colors: DOCUMENT_COLORS,
            sizeClass: "analytics-pie--small"
        }
    };

    const CIRCLE_TARGET_IDS = Object.keys(
        CIRCLE_RENDER_CONFIG
    );

    const ORBIT_VALUE_LAYOUTS = {
        "sales-chart": [
            {
                left: "-8%",
                top: "18%"
            },
            {
                left: "-10%",
                top: "86%"
            }
        ],

        "violations-chart": [
            {
                left: "-8%",
                top: "36%"
            },
            {
                left: "14%",
                top: "-4%"
            },
            {
                left: "48%",
                top: "-10%"
            },
            {
                left: "116%",
                top: "18%"
            },
            {
                left: "126%",
                top: "74%"
            },
            {
                left: "110%",
                top: "104%"
            },
            {
                left: "50%",
                top: "118%"
            },
            {
                left: "-12%",
                top: "94%"
            }
        ],

        "documents-chart": [
            {
                left: "-20%",
                top: "92%"
            },
            {
                left: "10%",
                top: "118%"
            },
            {
                left: "116%",
                top: "102%"
            }
        ],

        "penalties-chart": [
            {
                left: "120%",
                top: "44%"
            },
            {
                left: "80%",
                top: "112%"
            }
        ]
    };

    const CIRCLE_TITLES = {
        "sales-chart": "Продажи",
        "documents-chart": "Документы",
        "penalties-chart": "Штрафы",
        "violations-chart": "Отклонения"
    };

    const ORBIT_TITLE_LAYOUTS = {
        "sales-chart": {
            left: "-8%",
            top: "4%"
        },

        "violations-chart": {
            left: "126%",
            top: "51%"
        },

        "documents-chart": {
            left: "-34%",
            top: "72%"
        },

        "penalties-chart": {
            left: "120%",
            top: "29%"
        }
    };

    const MAGNET_SETTINGS = {
        influenceMultiplier: 1.7,

        minimumInfluence: 180,
        maximumInfluence: 330,

        circleDeadZone: 14,

        maximumMoveRatio: 0.085,
        minimumMaximumMove: 13,
        maximumMaximumMove: 27,

        maximumTilt: 5.5,
        maximumScale: 1.025,

        movementEase: 0.115,
        rotationEase: 0.1,
        scaleEase: 0.1,

        restThreshold: 0.012
    };

    const ORBIT_MAGNET_SETTINGS = {
        circleFollowRatio: 0.18,

        influenceRadius: 120,
        deadZone: 16,

        maximumShift: 8,

        movementEase: 0.14
    };

    /*
     * Индивидуальные параметры движения кругов.
     *
     * x/y — итоговое смещение при увеличенной диаграмме.
     * scale — итоговый размер.
     * stiffness/damping — характер пружины.
     * delayIn/delayOut — задержка старта каждого круга.
     * impulse — дополнительный начальный толчок.
     */
    const TREND_CIRCLE_PHYSICS = {
        sales: {
            x: 142,
            y: -20,
            scale: 0.79,

            stiffness: 0.048,
            damping: 0.79,

            scaleStiffness: 0.058,
            scaleDamping: 0.76,

            delayIn: 0,
            delayOut: 150,

            impulseX: 2.6,
            impulseY: -0.7,
            impulseScale: -0.012
        },

        violations: {
            x: 188,
            y: -36,
            scale: 0.84,

            stiffness: 0.063,
            damping: 0.75,

            scaleStiffness: 0.072,
            scaleDamping: 0.72,

            delayIn: 95,
            delayOut: 20,

            impulseX: 3.4,
            impulseY: -1.5,
            impulseScale: -0.009
        },

        penalties: {
            x: 164,
            y: 8,
            scale: 0.76,

            stiffness: 0.054,
            damping: 0.77,

            scaleStiffness: 0.065,
            scaleDamping: 0.73,

            delayIn: 155,
            delayOut: 80,

            impulseX: 3.1,
            impulseY: 0.9,
            impulseScale: -0.015
        },

        documents: {
        /*
        * Жёлтый круг уходит дальше вправо,
        * чтобы полностью освободить область диаграммы.
        */
        x: 270,
        y: 62,
        scale: 0.78,

        stiffness: 0.041,
        damping: 0.81,

        scaleStiffness: 0.052,
        scaleDamping: 0.78,

        delayIn: 230,
        delayOut: 0,

        impulseX: 3.1,
        impulseY: 2.1,
        impulseScale: -0.012
    }
    };

    const MONTH_NUMBER_MAP = {
        "январь": 1,
        "янв": 1,

        "февраль": 2,
        "фев": 2,

        "март": 3,
        "мар": 3,

        "апрель": 4,
        "апр": 4,

        "май": 5,

        "июнь": 6,
        "июн": 6,

        "июль": 7,
        "июл": 7,

        "август": 8,
        "авг": 8,

        "сентябрь": 9,
        "сен": 9,
        "сент": 9,

        "октябрь": 10,
        "окт": 10,

        "ноябрь": 11,
        "ноя": 11,

        "декабрь": 12,
        "дек": 12
    };

    let dashboardExportPayload = null;

    const trendState = {
        raw: null,

        visibleCount: 5,
        minVisibleCount: 3,
        maxVisibleCount: 12,

        expanded: false,
        initialized: false,

        expandTimer: null,
        collapseTimer: null,

        hoverDelay: 500,

        currentLayout: null,
        renderAnimationFrame: null,
        renderAnimationToken: 0,
        renderAnimationDuration: 680
    };

    const magnetState = {
        zone: null,
        zoneRect: null,

        items: [],

        pointerX: 0,
        pointerY: 0,

        pointerInside: false,

        animationFrame: null,
        lastAnimationTime: null,

        reducedMotion: (
            window.matchMedia(
                "(prefers-reduced-motion: reduce)"
            ).matches
        ),

        coarsePointer: (
            window.matchMedia(
                "(pointer: coarse)"
            ).matches
        )
    };

    const periodPickerState = {
        open: false,
        viewMonth: null,
        draftStart: null,
        draftEnd: null,
        appliedStart: null,
        appliedEnd: null,
        confirmedStart: null,
        confirmedEnd: null,
        pendingChanges: false,
        userCommitted: false
    };

    const PERIOD_WEEKDAYS = [
        "Пн",
        "Вт",
        "Ср",
        "Чт",
        "Пт",
        "Сб",
        "Вс"
    ];

    const PERIOD_MONTH_NAMES = [
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

    function byId(id) {
        return document.getElementById(id);
    }

    function numericValue(value) {
        const prepared = Number(value);

        return Number.isFinite(prepared)
            ? prepared
            : null;
    }

    function clamp(
        value,
        minimum,
        maximum
    ) {
        return Math.min(
            maximum,
            Math.max(
                minimum,
                value
            )
        );
    }

    function lerp(
        current,
        target,
        factor
    ) {
        return (
            current
            + (
                target
                - current
            )
            * factor
        );
    }

    function smoothStep(value) {
        const prepared = clamp(
            value,
            0,
            1
        );

        return (
            prepared
            * prepared
            * (
                3
                - 2
                * prepared
            )
        );
    }

    function formatNumber(
        value,
        maximumFractionDigits = 0
    ) {
        const prepared = numericValue(value);

        if (prepared === null) {
            return "—";
        }

        return new Intl.NumberFormat(
            "ru-RU",
            {
                maximumFractionDigits
            }
        ).format(prepared);
    }

    function formatThousands(value) {
        const prepared = numericValue(value);

        if (prepared === null) {
            return "—";
        }

        const thousands = prepared / 1000;

        const maximumFractionDigits = (
            Math.abs(
                thousands
                - Math.round(thousands)
            ) < 0.001

                ? 0
                : 1
        );

        return formatNumber(
            thousands,
            maximumFractionDigits
        );
    }

    function createTooltipController(
        id,
        className,
        visibleClass
    ) {
        const state = {
            element: null,
            anchor: null,
            hideTimer: null
        };

        function ensure() {
            if (state.element) {
                return state.element;
            }

            const element = document.createElement(
                "div"
            );

            element.id = id;
            element.className = className;

            element.setAttribute(
                "role",
                "tooltip"
            );

            element.dataset.side = "right";
            element.hidden = true;

            document.body.appendChild(element);

            state.element = element;

            return element;
        }

        function position(
            anchor,
            preferredSides = [
                "right",
                "left",
                "bottom",
                "top"
            ]
        ) {
            const element = ensure();

            if (
                element.hidden
                || !anchor
            ) {
                return;
            }

            const viewportPadding = 12;
            const gap = 16;

            const anchorRect = (
                anchor.getBoundingClientRect()
            );

            const tooltipRect = (
                element.getBoundingClientRect()
            );

            const candidatesBySide = {
                right: {
                    side: "right",

                    left: (
                        anchorRect.right
                        + gap
                    ),

                    top: (
                        anchorRect.top
                        + anchorRect.height / 2
                        - tooltipRect.height / 2
                    )
                },

                left: {
                    side: "left",

                    left: (
                        anchorRect.left
                        - tooltipRect.width
                        - gap
                    ),

                    top: (
                        anchorRect.top
                        + anchorRect.height / 2
                        - tooltipRect.height / 2
                    )
                },

                bottom: {
                    side: "bottom",

                    left: (
                        anchorRect.left
                        + anchorRect.width / 2
                        - tooltipRect.width / 2
                    ),

                    top: (
                        anchorRect.bottom
                        + gap
                    )
                },

                top: {
                    side: "top",

                    left: (
                        anchorRect.left
                        + anchorRect.width / 2
                        - tooltipRect.width / 2
                    ),

                    top: (
                        anchorRect.top
                        - tooltipRect.height
                        - gap
                    )
                }
            };

            const candidates = (
                preferredSides
                    .map(
                        (side) => (
                            candidatesBySide[side]
                        )
                    )
                    .filter(Boolean)
            );

            const fitsViewport = (
                candidate
            ) => (
                candidate.left >= viewportPadding
                && candidate.top >= viewportPadding

                && (
                    candidate.left
                    + tooltipRect.width
                    <= window.innerWidth
                    - viewportPadding
                )

                && (
                    candidate.top
                    + tooltipRect.height
                    <= window.innerHeight
                    - viewportPadding
                )
            );

            const selected = (
                candidates.find(
                    fitsViewport
                )

                || candidates[0]
            );

            if (!selected) {
                return;
            }

            const left = clamp(
                selected.left,
                viewportPadding,

                Math.max(
                    viewportPadding,

                    window.innerWidth
                    - tooltipRect.width
                    - viewportPadding
                )
            );

            const top = clamp(
                selected.top,
                viewportPadding,

                Math.max(
                    viewportPadding,

                    window.innerHeight
                    - tooltipRect.height
                    - viewportPadding
                )
            );

            element.dataset.side = selected.side;

            element.style.left = (
                `${left}px`
            );

            element.style.top = (
                `${top}px`
            );
        }

        function show(
            anchor,
            contentBuilder,
            preferredSides
        ) {
            const element = ensure();

            if (
                state.hideTimer
                !== null
            ) {
                window.clearTimeout(
                    state.hideTimer
                );

                state.hideTimer = null;
            }

            state.anchor = anchor;

            element.replaceChildren();

            contentBuilder(element);

            element.hidden = false;

            element.classList.add(
                visibleClass
            );

            position(
                anchor,
                preferredSides
            );
        }

        function hide() {
            const element = state.element;

            state.anchor = null;

            if (!element) {
                return;
            }

            element.classList.remove(
                visibleClass
            );

            if (
                state.hideTimer
                !== null
            ) {
                window.clearTimeout(
                    state.hideTimer
                );
            }

            state.hideTimer = (
                window.setTimeout(
                    () => {
                        element.hidden = true;

                        state.hideTimer = null;
                    },
                    90
                )
            );
        }

        function reposition(
            preferredSides
        ) {
            if (state.anchor) {
                position(
                    state.anchor,
                    preferredSides
                );
            }
        }

        return {
            ensure,
            show,
            hide,
            position,
            reposition,
            state
        };
    }

    const circleTooltip = (
        createTooltipController(
            "dashboard-circle-tooltip",
            "dashboard-circle-tooltip",
            "dashboard-circle-tooltip--visible"
        )
    );

    const trendTooltip = (
        createTooltipController(
            "dashboard-trend-tooltip",
            "dashboard-trend-tooltip",
            "dashboard-trend-tooltip--visible"
        )
    );

    function normalizeLegendSegments(
        segments,
        colors
    ) {
        return (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map(
                (
                    segment,
                    index
                ) => ({
                    label: String(
                        segment?.label
                        || segment?.name
                        || segment?.title
                        || "Без названия"
                    ),

                    value: Math.max(
                        0,
                        numericValue(
                            segment?.value
                        ) || 0
                    ),

                    color: colors[
                        index
                        % colors.length
                    ]
                })
            )
            .filter(
                (segment) => (
                    segment.value > 0
                )
            );
    }

    function fillCircleTooltip(
        container,
        segments
    ) {
        if (!segments.length) {
            const empty = document.createElement(
                "div"
            );

            empty.className = (
                "dashboard-circle-tooltip__empty"
            );

            empty.textContent = "Нет данных";

            container.appendChild(empty);

            return;
        }

        const list = document.createElement(
            "div"
        );

        list.className = (
            "dashboard-circle-tooltip__list"
        );

        segments.forEach(
            (segment) => {
                const row = document.createElement(
                    "div"
                );

                const swatch = document.createElement(
                    "span"
                );

                const label = document.createElement(
                    "span"
                );

                const value = document.createElement(
                    "strong"
                );

                row.className = (
                    "dashboard-circle-tooltip__row"
                );

                swatch.className = (
                    "dashboard-circle-tooltip__swatch"
                );

                label.className = (
                    "dashboard-circle-tooltip__label"
                );

                value.className = (
                    "dashboard-circle-tooltip__value"
                );

                swatch.style.backgroundColor = (
                    segment.color
                );

                label.textContent = segment.label;

                value.textContent = formatNumber(
                    segment.value,
                    2
                );

                row.append(
                    swatch,
                    label,
                    value
                );

                list.appendChild(row);
            }
        );

        container.appendChild(list);
    }

    function registerCircleTooltip(
        pie,
        segments,
        colors
    ) {
        if (!pie) {
            return;
        }

        const legendSegments = (
            normalizeLegendSegments(
                segments,
                colors
            )
        );

        pie.addEventListener(
            "pointerenter",
            () => {
                circleTooltip.show(
                    pie,

                    (container) => {
                        fillCircleTooltip(
                            container,
                            legendSegments
                        );
                    },

                    [
                        "right",
                        "left",
                        "bottom",
                        "top"
                    ]
                );
            }
        );

        pie.addEventListener(
            "pointermove",
            () => {
                circleTooltip.position(
                    pie,

                    [
                        "right",
                        "left",
                        "bottom",
                        "top"
                    ]
                );
            },
            {
                passive: true
            }
        );

        pie.addEventListener(
            "pointerleave",
            circleTooltip.hide
        );

        pie.addEventListener(
            "pointercancel",
            circleTooltip.hide
        );
    }

    function buildPieGradient(
        segments,
        colors
    ) {
        const prepared = (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map(
                (
                    segment,
                    index
                ) => ({
                    value: Math.max(
                        0,
                        numericValue(
                            segment?.value
                        ) || 0
                    ),

                    color: colors[
                        index
                        % colors.length
                    ]
                })
            )
            .filter(
                (segment) => (
                    segment.value > 0
                )
            );

        const total = prepared.reduce(
            (
                sum,
                segment
            ) => (
                sum
                + segment.value
            ),
            0
        );

        if (total <= 0) {
            return null;
        }

        let cursor = 0;

        const parts = [];

        prepared.forEach(
            (segment) => {
                const start = cursor;

                const finish = (
                    cursor
                    + (
                        segment.value
                        / total
                    )
                    * 100
                );

                parts.push(
                    (
                        segment.color
                        + " "
                        + start
                        + "% "
                        + finish
                        + "%"
                    )
                );

                cursor = finish;
            }
        );

        return (
            "conic-gradient("
            + parts.join(", ")
            + ")"
        );
    }

    function createPieMarkup(
        gradient,
        sizeClass
    ) {
        const classes = [
            "analytics-pie",
            sizeClass
        ];

        if (!gradient) {
            classes.push(
                "analytics-pie--empty"
            );
        }

        return `
            <div
                class="${classes.join(" ")}"
                ${gradient ? `style="background:${gradient}"` : ""}
            ></div>
        `;
    }

    let vectorPieMaskSequence = 0;

    function parseAngleDegrees(value) {
        const prepared = parseFloat(
            String(value ?? "0")
        );

        return Number.isFinite(prepared)
            ? prepared
            : 0;
    }

    function buildVectorPieSegmentsMarkup(
        segments,
        colors
    ) {
        const prepared = (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map(
                (
                    segment,
                    index
                ) => ({
                    value: Math.max(
                        0,
                        numericValue(
                            segment?.value
                        ) || 0
                    ),
                    color: colors[
                        index
                        % colors.length
                    ]
                })
            )
            .filter(
                (segment) => (
                    segment.value > 0
                )
            );

        if (!prepared.length) {
            return `
                <circle
                    cx="50"
                    cy="50"
                    r="49.95"
                    fill="${colors[0] || "#dfe6ee"}"
                ></circle>
            `;
        }

        const total = prepared.reduce(
            (
                sum,
                segment
            ) => (
                sum + segment.value
            ),
            0
        );

        if (total <= 0) {
            return `
                <circle
                    cx="50"
                    cy="50"
                    r="49.95"
                    fill="${colors[0] || "#dfe6ee"}"
                ></circle>
            `;
        }

        const pointAtAngle = (
            angleDegrees,
            radius = 49.95
        ) => {
            const radians = (
                (
                    angleDegrees
                    - 90
                )
                * Math.PI
                / 180
            );

            return {
                x: (
                    50
                    + Math.cos(radians)
                    * radius
                ),

                y: (
                    50
                    + Math.sin(radians)
                    * radius
                )
            };
        };

        const buildSectorPath = (
            startAngle,
            endAngle,
            radius = 49.95
        ) => {
            const start = pointAtAngle(
                startAngle,
                radius
            );
            const end = pointAtAngle(
                endAngle,
                radius
            );
            const span = Math.max(
                0,
                endAngle - startAngle
            );
            const largeArc = (
                span > 180
                    ? 1
                    : 0
            );

            return [
                "M 50 50",
                `L ${start.x.toFixed(4)} ${start.y.toFixed(4)}`,
                `A ${radius.toFixed(2)} ${radius.toFixed(2)} 0 ${largeArc} 1 ${end.x.toFixed(4)} ${end.y.toFixed(4)}`,
                "Z"
            ].join(" ");
        };

        const markup = [];
        const overlap = 0.055;

        markup.push(`
            <circle
                cx="50"
                cy="50"
                r="49.95"
                fill="${prepared[0].color}"
            ></circle>
        `);

        let cursor = (
            prepared[0].value
            / total
            * 360
        );

        prepared.slice(1).forEach(
            (
                segment,
                index,
                array
            ) => {
                const segmentDegrees = (
                    segment.value
                    / total
                    * 360
                );

                const startAngle = (
                    cursor
                    - overlap
                );
                const endAngle = (
                    cursor
                    + segmentDegrees
                    + (
                        index < array.length - 1
                            ? overlap
                            : 0
                    )
                );

                markup.push(`
                    <path
                        d="${buildSectorPath(startAngle, endAngle)}"
                        fill="${segment.color}"
                    ></path>
                `);

                cursor += segmentDegrees;
            }
        );

        return markup.join("");
    }

    function buildVectorRevealPath(
        progress,
        startAngleDegrees
    ) {
        const prepared = clamp(
            Number(progress) || 0,
            0,
            1
        );
        const radius = 50.4;

        if (prepared <= 0.000001) {
            return "M 50 50 Z";
        }

        if (prepared >= 0.999999) {
            return [
                "M 50 -0.4",
                "A 50.4 50.4 0 1 1 50 100.4",
                "A 50.4 50.4 0 1 1 50 -0.4",
                "Z"
            ].join(" ");
        }

        const pointAtAngle = (angleDegrees) => {
            const radians = (
                (
                    angleDegrees
                    - 90
                )
                * Math.PI
                / 180
            );

            return {
                x: (
                    50
                    + Math.cos(radians)
                    * radius
                ),
                y: (
                    50
                    + Math.sin(radians)
                    * radius
                )
            };
        };

        const sweepDegrees = Math.max(
            0.001,
            prepared * 359.999
        );
        const endAngle = (
            startAngleDegrees
            + sweepDegrees
        );
        const start = pointAtAngle(
            startAngleDegrees
        );
        const end = pointAtAngle(
            endAngle
        );
        const largeArc = (
            sweepDegrees > 180
                ? 1
                : 0
        );

        return [
            "M 50 50",
            `L ${start.x.toFixed(4)} ${start.y.toFixed(4)}`,
            `A ${radius.toFixed(2)} ${radius.toFixed(2)} 0 ${largeArc} 1 ${end.x.toFixed(4)} ${end.y.toFixed(4)}`,
            "Z"
        ].join(" ");
    }

    function createVectorPieMarkup(
        targetId,
        segments,
        colors,
        sizeClass
    ) {
        const settings = getCircleIntroSettings(
            targetId
        );
        const startAngle = (
            parseAngleDegrees(
                settings.startAngle
            )
        );
        const clipId = (
            "dashboard-pie-clip-"
            + targetId.replace(
                /[^a-z0-9_-]/gi,
                "-"
            )
            + "-"
            + (++vectorPieMaskSequence)
        );
        const hasData = (
            Array.isArray(segments)
            && segments.some(
                (segment) => (
                    Math.max(
                        0,
                        numericValue(
                            segment?.value
                        ) || 0
                    ) > 0
                )
            )
        );
        const classes = [
            "analytics-pie",
            "analytics-pie--vector",
            sizeClass
        ];

        if (!hasData) {
            classes.push(
                "analytics-pie--empty"
            );
        }

        return `
            <svg
                class="${classes.join(" ")}"
                viewBox="0 0 100 100"
                preserveAspectRatio="xMidYMid meet"
                role="img"
                aria-hidden="true"
                data-vector-pie="true"
                data-reveal-progress="0"
                data-reveal-start-angle="${startAngle.toFixed(3)}"
            >
                <defs>
                    <clipPath
                        id="${clipId}"
                        clipPathUnits="userSpaceOnUse"
                    >
                        <path
                            class="analytics-pie__reveal-shape"
                            d="${buildVectorRevealPath(0, startAngle)}"
                        ></path>
                    </clipPath>
                </defs>

                <g
                    class="analytics-pie__segments"
                    clip-path="url(#${clipId})"
                >
                    ${buildVectorPieSegmentsMarkup(
                        segments,
                        colors
                    )}
                </g>
            </svg>
        `;
    }

    function getVectorRevealShape(pie) {
        return pie?.querySelector(
            ".analytics-pie__reveal-shape"
        ) || null;
    }

    function setVectorPieRevealProgress(
        pie,
        progress
    ) {
        if (!pie) {
            return;
        }

        const shape = getVectorRevealShape(
            pie
        );

        if (!shape) {
            return;
        }

        const prepared = clamp(
            Number(progress) || 0,
            0,
            1
        );
        const startAngle = Number(
            pie.dataset.revealStartAngle
        ) || 0;

        shape.setAttribute(
            "d",
            buildVectorRevealPath(
                prepared,
                startAngle
            )
        );

        pie.dataset.revealProgress = (
            prepared.toFixed(6)
        );
    }

    function getVectorPieRevealProgress(pie) {
        const prepared = Number(
            pie?.dataset?.revealProgress
        );

        return Number.isFinite(prepared)
            ? clamp(prepared, 0, 1)
            : 1;
    }

    function easeVectorReveal(progress) {
        const prepared = clamp(
            progress,
            0,
            1
        );

        return (
            0.5
            - Math.cos(
                Math.PI
                * prepared
            ) / 2
        );
    }

    const vectorRevealFrames = new WeakMap();

    function animateVectorPieReveal(
        pie,
        fromProgress,
        toProgress,
        duration,
        delay = 0
    ) {
        if (!pie) {
            return Promise.resolve();
        }

        const previousFrame = vectorRevealFrames.get(
            pie
        );

        if (previousFrame) {
            window.cancelAnimationFrame(
                previousFrame
            );
            vectorRevealFrames.delete(
                pie
            );
        }

        if (
            magnetState.reducedMotion
            || duration <= 0
        ) {
            setVectorPieRevealProgress(
                pie,
                toProgress
            );
            return Promise.resolve();
        }

        const from = clamp(
            fromProgress,
            0,
            1
        );
        const to = clamp(
            toProgress,
            0,
            1
        );
        const startAt = (
            performance.now()
            + Math.max(0, delay)
        );

        setVectorPieRevealProgress(
            pie,
            from
        );

        return new Promise(
            (resolve) => {
                function frame(now) {
                    if (!pie.isConnected) {
                        vectorRevealFrames.delete(
                            pie
                        );
                        resolve();
                        return;
                    }

                    if (now < startAt) {
                        const frameId = (
                            window.requestAnimationFrame(
                                frame
                            )
                        );
                        vectorRevealFrames.set(
                            pie,
                            frameId
                        );
                        return;
                    }

                    const rawProgress = clamp(
                        (
                            now
                            - startAt
                        ) / duration,
                        0,
                        1
                    );
                    const eased = easeVectorReveal(
                        rawProgress
                    );
                    const current = (
                        from
                        + (
                            to
                            - from
                        ) * eased
                    );

                    setVectorPieRevealProgress(
                        pie,
                        current
                    );

                    if (rawProgress >= 1) {
                        setVectorPieRevealProgress(
                            pie,
                            to
                        );
                        vectorRevealFrames.delete(
                            pie
                        );
                        resolve();
                        return;
                    }

                    const frameId = (
                        window.requestAnimationFrame(
                            frame
                        )
                    );
                    vectorRevealFrames.set(
                        pie,
                        frameId
                    );
                }

                const frameId = (
                    window.requestAnimationFrame(
                        frame
                    )
                );
                vectorRevealFrames.set(
                    pie,
                    frameId
                );
            }
        );
    }

    function formatOrbitNumber(value) {
        const prepared = numericValue(value);

        if (prepared === null) {
            return "—";
        }

        return new Intl.NumberFormat(
            "ru-RU",
            {
                maximumFractionDigits: 0
            }
        )
            .format(prepared)
            .replace(
                /[\u00A0\u202F]/g,
                " "
            );
    }

    function buildOrbitValuesMarkup(
        targetId,
        segments
    ) {
        const layout = (
            ORBIT_VALUE_LAYOUTS[
                targetId
            ]
            || []
        );

        const preparedSegments = (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map(
                (
                    segment,
                    originalIndex
                ) => ({
                    originalIndex,

                    value: Math.max(
                        0,
                        numericValue(
                            segment?.value
                        ) || 0
                    )
                })
            )
            .filter(
                (segment) => (
                    segment.value > 0
                )
            );

        return preparedSegments
            .map(
                (
                    segment,
                    visibleIndex
                ) => {
                    const point = (
                        layout[
                            segment.originalIndex
                        ]

                        || {
                            left: "110%",

                            top: (
                                `${
                                    20
                                    + visibleIndex
                                    * 18
                                }%`
                            )
                        }
                    );

                    return `
                        <span
                            class="dashboard-orbit-item dashboard-orbit-value"
                            style="
                                left:${point.left};
                                top:${point.top};
                            "
                            data-orbit-final-value="${segment.value}"
                            aria-hidden="true"
                        >
                            ${formatOrbitNumber(
                                segment.value
                            )}
                        </span>
                    `;
                }
            )
            .join("");
    }

    function buildOrbitTitleMarkup(targetId) {
        const title = CIRCLE_TITLES[targetId];
        const point = ORBIT_TITLE_LAYOUTS[targetId];

        if (
            !title
            || !point
        ) {
            return "";
        }

        return `
            <span
                class="dashboard-orbit-item dashboard-orbit-title dashboard-orbit-title--intro"
                style="
                    left:${point.left};
                    top:${point.top};
                "
                aria-hidden="true"
            >
                ${title}
            </span>
        `;
    }

    function getCircleIntroSettings(targetId) {
        return CIRCLE_INTRO_SETTINGS[targetId] || {
            startAngle: "0deg",
            duration: 900,
            delay: 0,
            numberDelay: 180,
            titleDelay: 420
        };
    }

    function formatCasinoDigits(digitString) {
        return String(digitString || "0")
            .replace(
                /\B(?=(\d{3})+(?!\d))/g,
                " "
            );
    }

    function animateOrbitValue(element, finalValue, delay) {
        if (!element) {
            return;
        }

        const preparedFinal = Math.max(
            0,
            Math.round(
                numericValue(finalValue) || 0
            )
        );

        const finalDigits = String(preparedFinal);
        const finalText = formatOrbitNumber(preparedFinal);

        /*
         * Сначала измеряем ширину финального значения, но до первого
         * кадра сразу заменяем его стартовыми барабанами. Так реальное
         * значение не успевает мелькнуть перед анимацией.
         */
        element.textContent = finalText;

        const measuredWidth = Math.ceil(
            element.getBoundingClientRect().width
        );

        if (measuredWidth > 0) {
            element.style.minWidth = `${measuredWidth}px`;
        }

        const makeRollingDigits = () => (
            finalDigits
                .split("")
                .map(() => String(Math.floor(Math.random() * 10)))
                .join("")
        );

        element.classList.remove(
            "dashboard-orbit-value--settled",
            "dashboard-orbit-value--rolling"
        );
        element.classList.add(
            "dashboard-orbit-value--intro-pending"
        );
        element.textContent = formatCasinoDigits(
            makeRollingDigits()
        );

        if (magnetState.reducedMotion) {
            element.classList.remove(
                "dashboard-orbit-value--intro-pending"
            );
            element.textContent = finalText;
            return;
        }

        const duration = (
            980
            + finalDigits.length * 72
        );

        const startAt = performance.now() + delay;
        let lastShuffleAt = -Infinity;

        function frame(now) {
            if (!element.isConnected) {
                return;
            }

            if (now < startAt) {
                window.requestAnimationFrame(frame);
                return;
            }

            if (
                element.classList.contains(
                    "dashboard-orbit-value--intro-pending"
                )
            ) {
                element.classList.remove(
                    "dashboard-orbit-value--intro-pending"
                );
                element.classList.add(
                    "dashboard-orbit-value--rolling"
                );
            }

            const progress = clamp(
                (now - startAt) / duration,
                0,
                1
            );

            if (progress >= 1) {
                element.textContent = finalText;
                element.classList.remove(
                    "dashboard-orbit-value--rolling"
                );
                element.classList.add(
                    "dashboard-orbit-value--settled"
                );
                return;
            }

            if (now - lastShuffleAt >= 58) {
                lastShuffleAt = now;

                const digits = finalDigits
                    .split("")
                    .map(
                        (finalDigit, index) => {
                            const settleAt = (
                                0.5
                                + (
                                    index
                                    / Math.max(1, finalDigits.length - 1)
                                ) * 0.42
                            );

                            if (progress >= settleAt) {
                                return finalDigit;
                            }

                            return String(
                                Math.floor(
                                    Math.random() * 10
                                )
                            );
                        }
                    )
                    .join("");

                element.textContent = formatCasinoDigits(digits);
            }

            window.requestAnimationFrame(frame);
        }

        window.requestAnimationFrame(frame);
    }

    function prepareCircleIntro(targetId, target) {
        if (!target) {
            return;
        }

        const settings = getCircleIntroSettings(
            targetId
        );

        const pie = target.querySelector(
            ".analytics-pie"
        );

        if (pie) {
            pie.classList.remove(
                "analytics-pie--outro"
            );
            pie.classList.add(
                "analytics-pie--intro"
            );

            pie.style.setProperty(
                "--circle-intro-duration",
                `${settings.duration}ms`
            );

            pie.style.setProperty(
                "--circle-intro-delay",
                `${settings.delay}ms`
            );

            setVectorPieRevealProgress(
                pie,
                0
            );

            animateVectorPieReveal(
                pie,
                0,
                1,
                settings.duration,
                settings.delay
            ).then(
                () => {
                    if (!pie.isConnected) {
                        return;
                    }

                    /*
                     * Маску SVG не снимаем. В состоянии 1 0 она
                     * полностью раскрывает круг, поэтому последний
                     * кадр и спокойное состояние идентичны.
                     */
                    setVectorPieRevealProgress(
                        pie,
                        1
                    );

                    /*
                     * Pop-анимация немного длиннее раскрытия. Даём ей
                     * спокойно завершиться и только потом снимаем класс,
                     * чтобы в самом конце не было микроскачка масштаба.
                     */
                    window.setTimeout(
                        () => {
                            if (!pie.isConnected) {
                                return;
                            }

                            pie.classList.remove(
                                "analytics-pie--intro"
                            );
                        },
                        240
                    );
                }
            );
        }

        const title = target.querySelector(
            ".dashboard-orbit-title"
        );

        if (title) {
            title.classList.remove(
                "dashboard-orbit-title--outro"
            );
            title.classList.add(
                "dashboard-orbit-title--intro"
            );
            title.style.setProperty(
                "--circle-title-delay",
                `${settings.titleDelay}ms`
            );
        }

        target
            .querySelectorAll(
                ".dashboard-orbit-value[data-orbit-final-value]"
            )
            .forEach(
                (element, index) => {
                    element.classList.remove(
                        "dashboard-orbit-value--outro"
                    );

                    animateOrbitValue(
                        element,
                        element.getAttribute(
                            "data-orbit-final-value"
                        ),
                        settings.numberDelay
                            + index * 78
                    );
                }
            );
    }

    function getCircleSegmentsFromPayload(
        payload,
        targetId
    ) {
        const config = CIRCLE_RENDER_CONFIG[targetId];

        if (!config) {
            return [];
        }

        return payload
            ?.cards
            ?.[config.cardKey]
            ?.segments
            || [];
    }

    function getCircleDataSignature(segments) {
        return JSON.stringify(
            (Array.isArray(segments) ? segments : [])
                .map(
                    (segment) => ({
                        label: String(
                            segment?.label
                            || segment?.name
                            || segment?.title
                            || ""
                        ),
                        value: Math.max(
                            0,
                            numericValue(
                                segment?.value
                            ) || 0
                        )
                    })
                )
        );
    }

    function circleDataChanged(
        previousPayload,
        nextPayload,
        targetId
    ) {
        if (!previousPayload) {
            return true;
        }

        return getCircleDataSignature(
            getCircleSegmentsFromPayload(
                previousPayload,
                targetId
            )
        ) !== getCircleDataSignature(
            getCircleSegmentsFromPayload(
                nextPayload,
                targetId
            )
        );
    }

    function animateCircleOut(targetId) {
        const target = byId(targetId);

        if (!target) {
            return Promise.resolve();
        }

        const pie = target.querySelector(
            ".analytics-pie"
        );

        if (
            !pie
            || magnetState.reducedMotion
        ) {
            return Promise.resolve();
        }

        const settings = getCircleIntroSettings(
            targetId
        );

        const outroDuration = Math.max(
            720,
            Math.round(settings.duration * 0.54)
        );

        const outroDelay = Math.round(
            settings.delay * 0.22
        );

        pie.classList.remove(
            "analytics-pie--intro"
        );
        pie.classList.add(
            "analytics-pie--outro"
        );
        pie.style.setProperty(
            "--circle-outro-duration",
            `${outroDuration}ms`
        );
        pie.style.setProperty(
            "--circle-outro-delay",
            `${outroDelay}ms`
        );

        target
            .querySelectorAll(
                ".dashboard-orbit-value"
            )
            .forEach(
                (element) => {
                    element.classList.add(
                        "dashboard-orbit-value--outro"
                    );
                }
            );

        const title = target.querySelector(
            ".dashboard-orbit-title"
        );

        if (title) {
            title.classList.remove(
                "dashboard-orbit-title--intro"
            );
            title.classList.add(
                "dashboard-orbit-title--outro"
            );
        }

        return animateVectorPieReveal(
            pie,
            getVectorPieRevealProgress(pie),
            0,
            outroDuration,
            outroDelay
        );
    }

    function renderCircle(
        targetId,
        segments,
        colors,
        sizeClass
    ) {
        const target = byId(targetId);

        if (!target) {
            return;
        }

        target.innerHTML = (
            createVectorPieMarkup(
                targetId,
                segments,
                colors,
                sizeClass
            )

            + buildOrbitValuesMarkup(
                targetId,
                segments
            )

            + buildOrbitTitleMarkup(
                targetId
            )
        );

        prepareCircleIntro(
            targetId,
            target
        );

        registerCircleTooltip(
            target.querySelector(
                ".analytics-pie"
            ),
            segments,
            colors
        );
    }

    function startOfDay(date) {
        return new Date(
            date.getFullYear(),
            date.getMonth(),
            date.getDate()
        );
    }

    function sameDay(a, b) {
        return Boolean(a && b)
            && a.getFullYear() === b.getFullYear()
            && a.getMonth() === b.getMonth()
            && a.getDate() === b.getDate();
    }

    function addDays(date, amount) {
        const next = startOfDay(date);
        next.setDate(next.getDate() + amount);
        return next;
    }

    function addMonths(date, amount) {
        return new Date(
            date.getFullYear(),
            date.getMonth() + amount,
            1
        );
    }

    function startOfMonth(date) {
        return new Date(
            date.getFullYear(),
            date.getMonth(),
            1
        );
    }

    function formatDateForPeriod(date) {
        const prepared = startOfDay(date);
        const day = String(prepared.getDate()).padStart(2, "0");
        const month = String(prepared.getMonth() + 1).padStart(2, "0");
        const year = prepared.getFullYear();
        return `${day}.${month}.${year}`;
    }

    function formatPeriodLabel(startDate, endDate) {
        if (!startDate && !endDate) {
            return "";
        }

        if (startDate && !endDate) {
            return formatDateForPeriod(startDate);
        }

        if (!startDate && endDate) {
            return formatDateForPeriod(endDate);
        }

        return `${formatDateForPeriod(startDate)} — ${formatDateForPeriod(endDate)}`;
    }

    function parseDateFromLabelPart(value) {
        const match = String(value || "").trim().match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
        if (!match) {
            return null;
        }

        const date = new Date(
            Number(match[3]),
            Number(match[2]) - 1,
            Number(match[1])
        );

        if (Number.isNaN(date.getTime())) {
            return null;
        }

        return startOfDay(date);
    }

    function parsePeriodLabelText(label) {
        const text = String(label || "").trim();
        if (!text) {
            return { start: null, end: null };
        }

        const parts = text.split(/\s+—\s+/);
        const start = parseDateFromLabelPart(parts[0]);
        const end = parseDateFromLabelPart(parts[1] || parts[0]);

        if (start && end && end < start) {
            return { start: end, end: start };
        }

        return { start, end };
    }

    function cloneDate(value) {
        return value ? startOfDay(value) : null;
    }

    function ensureAppliedPeriodFromButton() {
        if (periodPickerState.appliedStart && periodPickerState.appliedEnd) {
            return;
        }

        const button = byId("dashboard-period-value");
        const parsed = parsePeriodLabelText(button ? button.textContent : "");

        periodPickerState.appliedStart = parsed.start || startOfDay(new Date());
        periodPickerState.appliedEnd = parsed.end || cloneDate(periodPickerState.appliedStart);
        periodPickerState.viewMonth = startOfMonth(periodPickerState.appliedStart);
        periodPickerState.draftStart = cloneDate(periodPickerState.appliedStart);
        periodPickerState.draftEnd = cloneDate(periodPickerState.appliedEnd);
    }

    function syncPeriodButtonText() {
        const button = byId("dashboard-period-value");
        if (!button) {
            return;
        }

        button.textContent = formatPeriodLabel(
            periodPickerState.appliedStart,
            periodPickerState.appliedEnd
        );
    }

    function buildPeriodMonthMarkup(monthDate) {
        const monthStart = startOfMonth(monthDate);
        const monthEnd = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0);
        const leadingOffset = (monthStart.getDay() + 6) % 7;
        const gridStart = addDays(monthStart, -leadingOffset);

        let daysMarkup = "";

        for (let index = 0; index < 42; index += 1) {
            const date = addDays(gridStart, index);
            const inCurrentMonth = date.getMonth() === monthStart.getMonth();
            const selectedStart = periodPickerState.draftStart;
            const selectedEnd = periodPickerState.draftEnd || selectedStart;
            const isSelectedStart = sameDay(date, selectedStart);
            const isSelectedEnd = Boolean(periodPickerState.draftEnd) && sameDay(date, selectedEnd);
            const isSingle = Boolean(selectedStart) && !periodPickerState.draftEnd && sameDay(date, selectedStart);
            const isInRange = Boolean(selectedStart && selectedEnd) && date >= selectedStart && date <= selectedEnd;

            const wrapClasses = ["dashboard-period-picker__day-wrap"];
            const buttonClasses = ["dashboard-period-picker__day"];

            if (!inCurrentMonth) {
                wrapClasses.push("dashboard-period-picker__day-wrap--outside");
            }

            if (isInRange) {
                wrapClasses.push("dashboard-period-picker__day-wrap--in-range");
            }

            if (isSelectedStart) {
                wrapClasses.push("dashboard-period-picker__day-wrap--range-start");
                buttonClasses.push("dashboard-period-picker__day--selected");
            }

            if (isSelectedEnd) {
                wrapClasses.push("dashboard-period-picker__day-wrap--range-end");
                buttonClasses.push("dashboard-period-picker__day--selected");
            }

            if (isSingle || (isSelectedStart && !periodPickerState.draftEnd)) {
                wrapClasses.push("dashboard-period-picker__day-wrap--single");
            }

            daysMarkup += `
                <div class="${wrapClasses.join(" ")}">
                    <button
                        class="${buttonClasses.join(" ")}"
                        type="button"
                        data-period-date="${date.toISOString()}"
                        aria-label="${formatDateForPeriod(date)}"
                    >
                        ${date.getDate()}
                    </button>
                </div>
            `;
        }

        const weekdaysMarkup = PERIOD_WEEKDAYS.map((weekday) => `
            <div class="dashboard-period-picker__weekday">${weekday}</div>
        `).join("");

        return `
            <section class="dashboard-period-picker__month">
                <div class="dashboard-period-picker__month-title">${PERIOD_MONTH_NAMES[monthStart.getMonth()]} ${monthStart.getFullYear()}</div>
                <div class="dashboard-period-picker__weekdays">${weekdaysMarkup}</div>
                <div class="dashboard-period-picker__days">${daysMarkup}</div>
            </section>
        `;
    }

    function renderPeriodPicker() {
        ensureAppliedPeriodFromButton();

        const calendars = byId("dashboard-period-picker-calendars");
        const picker = byId("dashboard-period-picker");
        const trigger = byId("dashboard-period-value");

        if (!calendars || !picker || !trigger) {
            return;
        }

        const firstMonth = periodPickerState.viewMonth || startOfMonth(periodPickerState.appliedStart || new Date());
        const secondMonth = addMonths(firstMonth, 1);

        calendars.innerHTML = buildPeriodMonthMarkup(firstMonth) + buildPeriodMonthMarkup(secondMonth);
        picker.hidden = !periodPickerState.open;
        picker.setAttribute("aria-hidden", String(!periodPickerState.open));
        trigger.setAttribute("aria-expanded", String(periodPickerState.open));
    }

    function closePeriodPicker(resetDraft) {
        if (resetDraft) {
            periodPickerState.draftStart = cloneDate(periodPickerState.appliedStart);
            periodPickerState.draftEnd = cloneDate(periodPickerState.appliedEnd);
            periodPickerState.viewMonth = startOfMonth(periodPickerState.appliedStart || new Date());
        }

        periodPickerState.open = false;
        renderPeriodPicker();
    }

    function openPeriodPicker() {
        ensureAppliedPeriodFromButton();
        periodPickerState.draftStart = cloneDate(periodPickerState.appliedStart);
        periodPickerState.draftEnd = cloneDate(periodPickerState.appliedEnd);
        periodPickerState.viewMonth = startOfMonth(periodPickerState.appliedStart || new Date());
        periodPickerState.open = true;
        renderPeriodPicker();
    }

    function handlePeriodDateSelection(date) {
        const selectedDate = startOfDay(date);

        if (!periodPickerState.draftStart || (periodPickerState.draftStart && periodPickerState.draftEnd)) {
            periodPickerState.draftStart = selectedDate;
            periodPickerState.draftEnd = null;
            renderPeriodPicker();
            return;
        }

        if (selectedDate < periodPickerState.draftStart) {
            periodPickerState.draftEnd = cloneDate(periodPickerState.draftStart);
            periodPickerState.draftStart = selectedDate;
        } else {
            periodPickerState.draftEnd = selectedDate;
        }

        renderPeriodPicker();
    }

    function datesEqual(a, b) {
        if (!a && !b) {
            return true;
        }

        if (!a || !b) {
            return false;
        }

        return sameDay(a, b);
    }

    function setFilterApplyPending(pending) {
        const nextPending = Boolean(pending);
        const filterBar = document.querySelector(
            ".dashboard-filter-bar"
        );
        const applyButton = byId(
            "dashboard-apply-filters"
        );

        periodPickerState.pendingChanges = nextPending;

        if (filterBar) {
            filterBar.classList.toggle(
                "dashboard-filter-bar--pending",
                nextPending
            );
        }

        if (applyButton) {
            applyButton.classList.toggle(
                "dashboard-header-action-button--pending",
                nextPending
            );

            applyButton.setAttribute(
                "aria-hidden",
                String(!nextPending)
            );

            applyButton.tabIndex = nextPending
                ? 0
                : -1;
        }
    }

    function updateFilterApplyPendingState() {
        const changed = (
            !datesEqual(
                periodPickerState.appliedStart,
                periodPickerState.confirmedStart
            )
            || !datesEqual(
                periodPickerState.appliedEnd,
                periodPickerState.confirmedEnd
            )
        );

        setFilterApplyPending(changed);
    }

    function markCurrentFiltersAsConfirmed() {
        periodPickerState.confirmedStart = cloneDate(
            periodPickerState.appliedStart
        );

        periodPickerState.confirmedEnd = cloneDate(
            periodPickerState.appliedEnd
        );

        setFilterApplyPending(false);
    }

    function initializePeriodPicker() {
        const trigger = byId("dashboard-period-value");
        const picker = byId("dashboard-period-picker");
        const prev = byId("dashboard-period-prev");
        const next = byId("dashboard-period-next");
        const cancel = byId("dashboard-period-cancel");
        const save = byId("dashboard-period-save");

        if (!trigger || !picker) {
            return;
        }

        ensureAppliedPeriodFromButton();
        syncPeriodButtonText();
        renderPeriodPicker();
        setFilterApplyPending(false);

        trigger.addEventListener("click", function (event) {
            event.stopPropagation();
            if (periodPickerState.open) {
                closePeriodPicker(true);
            } else {
                openPeriodPicker();
            }
        });

        picker.addEventListener("click", function (event) {
            event.stopPropagation();
            const dateButton = event.target.closest("[data-period-date]");
            if (dateButton) {
                handlePeriodDateSelection(new Date(dateButton.getAttribute("data-period-date")));
            }
        });

        if (prev) {
            prev.addEventListener("click", function () {
                periodPickerState.viewMonth = addMonths(periodPickerState.viewMonth || new Date(), -1);
                renderPeriodPicker();
            });
        }

        if (next) {
            next.addEventListener("click", function () {
                periodPickerState.viewMonth = addMonths(periodPickerState.viewMonth || new Date(), 1);
                renderPeriodPicker();
            });
        }

        if (cancel) {
            cancel.addEventListener("click", function () {
                closePeriodPicker(true);
            });
        }

        if (save) {
            save.addEventListener("click", function () {
                if (!periodPickerState.draftStart) {
                    return;
                }

                periodPickerState.appliedStart = cloneDate(periodPickerState.draftStart);
                periodPickerState.appliedEnd = cloneDate(periodPickerState.draftEnd || periodPickerState.draftStart);
                periodPickerState.userCommitted = true;
                syncPeriodButtonText();
                closePeriodPicker(false);
                updateFilterApplyPendingState();
            });
        }

        document.addEventListener("click", function (event) {
            if (!periodPickerState.open) {
                return;
            }

            const withinPicker = picker.contains(event.target);
            const withinTrigger = trigger.contains(event.target);

            if (!withinPicker && !withinTrigger) {
                closePeriodPicker(true);
            }
        });

        window.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && periodPickerState.open) {
                closePeriodPicker(true);
            }
        });
    }

    function normalizeMonthText(value) {
        return String(
            value
            ?? ""
        )
            .trim()
            .toLowerCase()
            .replace(
                /ё/g,
                "е"
            );
    }

    function getMonthNumberLabel(
        value,
        fallbackIndex
    ) {
        const text = normalizeMonthText(value);

        const isoMatch = text.match(
            /^(\d{4})[-./](\d{1,2})/
        );

        if (isoMatch) {
            return String(
                clamp(
                    Number(isoMatch[2]),
                    1,
                    12
                )
            ).padStart(
                2,
                "0"
            );
        }

        const dateMatch = text.match(
            /^\d{1,2}[-./](\d{1,2})[-./]\d{2,4}$/
        );

        if (dateMatch) {
            return String(
                clamp(
                    Number(dateMatch[1]),
                    1,
                    12
                )
            ).padStart(
                2,
                "0"
            );
        }

        if (
            /^\d{1,2}$/.test(text)
        ) {
            return String(
                clamp(
                    Number(text),
                    1,
                    12
                )
            ).padStart(
                2,
                "0"
            );
        }

        const monthEntry = (
            Object.entries(
                MONTH_NUMBER_MAP
            )
                .find(
                    ([name]) => (
                        text.startsWith(name)
                    )
                )
        );

        if (monthEntry) {
            return String(
                monthEntry[1]
            ).padStart(
                2,
                "0"
            );
        }

        return String(
            (
                fallbackIndex
                % 12
            )
            + 1
        ).padStart(
            2,
            "0"
        );
    }

    function normalizeTrendMonth(
        month,
        index
    ) {
        if (
            month
            && typeof month === "object"
        ) {
            const sourceLabel = (
                month.label
                || month.name
                || month.key
                || month.value
                || index + 1
            );

            return {
                key: String(
                    month.key
                    || month.value
                    || sourceLabel
                ),

                label: String(
                    sourceLabel
                ),

                axisLabel: (
                    getMonthNumberLabel(
                        month.month
                        || month.number
                        || month.value
                        || sourceLabel,
                        index
                    )
                ),

                forecast: Boolean(
                    month.forecast
                )
            };
        }

        return {
            key: String(
                month
                ?? index + 1
            ),

            label: String(
                month
                ?? index + 1
            ),

            axisLabel: (
                getMonthNumberLabel(
                    month,
                    index
                )
            ),

            forecast: false
        };
    }

    function normalizeTrendPayload(trend) {
        const sourceMonths = (
            Array.isArray(
                trend?.months
            )
                ? trend.months
                : []
        );

        const sourcePenalties = (
            Array.isArray(
                trend?.penalties
            )
                ? trend.penalties
                : []
        );

        const sourceViolations = (
            Array.isArray(
                trend?.violations
            )
                ? trend.violations
                : []
        );

        const safeLength = Math.min(
            sourceMonths.length,
            sourcePenalties.length,
            sourceViolations.length
        );

        const months = sourceMonths
            .slice(
                0,
                safeLength
            )
            .map(
                normalizeTrendMonth
            );

        const penalties = sourcePenalties
            .slice(
                0,
                safeLength
            )
            .map(
                (value) => (
                    Math.max(
                        0,
                        numericValue(
                            value
                        ) || 0
                    )
                )
            );

        const violations = sourceViolations
            .slice(
                0,
                safeLength
            )
            .map(
                (value) => (
                    Math.max(
                        0,
                        numericValue(
                            value
                        ) || 0
                    )
                )
            );

        const explicitForecastIndex = Number(
            trend?.forecast_start_index
        );

        let forecastStartIndex = (
            Number.isFinite(
                explicitForecastIndex
            )

                ? Math.trunc(
                    explicitForecastIndex
                )

                : months.findIndex(
                    (month) => (
                        month.forecast
                    )
                )
        );

        if (forecastStartIndex < 0) {
            forecastStartIndex = safeLength;
        }

        forecastStartIndex = clamp(
            forecastStartIndex,
            0,
            safeLength
        );

        return {
            months,
            penalties,
            violations,
            forecastStartIndex
        };
    }

    function getTrendVisibleData() {
        if (!trendState.raw) {
            return null;
        }

        const total = (
            trendState.raw.months.length
        );

        if (total === 0) {
            return null;
        }

        const minimum = Math.min(
            trendState.minVisibleCount,
            total
        );

        const maximum = Math.min(
            trendState.maxVisibleCount,
            total
        );

        const visibleCount = clamp(
            trendState.visibleCount,
            minimum,
            maximum
        );

        const startIndex = Math.max(
            0,
            total - visibleCount
        );

        return {
            months: (
                trendState.raw.months.slice(
                    startIndex
                )
            ),

            penalties: (
                trendState.raw.penalties.slice(
                    startIndex
                )
            ),

            violations: (
                trendState.raw.violations.slice(
                    startIndex
                )
            ),

            forecastStartIndex: (
                trendState.raw.forecastStartIndex
                - startIndex
            )
        };
    }

    function buildTrendPath(
        indexes,
        pointResolver
    ) {
        if (!indexes.length) {
            return "";
        }

        return indexes
            .map(
                (
                    index,
                    position
                ) => {
                    const point = (
                        pointResolver(
                            index
                        )
                    );

                    return (
                        (
                            position === 0
                                ? "M"
                                : "L"
                        )

                        + " "
                        + point.x
                        + " "
                        + point.y
                    );
                }
            )
            .join(" ");
    }

    function splitTrendIndexes(
        length,
        forecastStartIndex
    ) {
        const indexes = Array.from(
            {
                length
            },
            (
                _,
                index
            ) => index
        );

        if (forecastStartIndex <= 0) {
            return {
                actual: [],
                forecast: indexes
            };
        }

        if (forecastStartIndex >= length) {
            return {
                actual: indexes,
                forecast: []
            };
        }

        return {
            actual: indexes.slice(
                0,
                forecastStartIndex
            ),

            forecast: indexes.slice(
                Math.max(
                    0,
                    forecastStartIndex - 1
                )
            )
        };
    }

    function buildTrendPathMarkup(
        className,
        indexes,
        resolver
    ) {
        if (indexes.length < 2) {
            return "";
        }

        return `
            <path
                class="${className}"
                d="${buildTrendPath(
                    indexes,
                    resolver
                )}"
            ></path>
        `;
    }

    function niceCeil(value) {
        const prepared = Math.max(
            0,
            numericValue(value) || 0
        );

        if (prepared <= 0) {
            return 1;
        }

        const exponent = Math.floor(
            Math.log10(prepared)
        );

        const power = Math.pow(
            10,
            exponent
        );

        const fraction = (
            prepared
            / power
        );

        let niceFraction = 1;

        if (fraction > 1) {
            niceFraction = 2;
        }

        if (fraction > 2) {
            niceFraction = 5;
        }

        if (fraction > 5) {
            niceFraction = 10;
        }

        return (
            niceFraction
            * power
        );
    }

    function calculatePreferredAxis(maximum) {
        const preparedMaximum = Math.max(
            0,
            numericValue(maximum) || 0
        );

        if (preparedMaximum <= 0) {
            return {
                maximum: 5,
                step: 1,
                intervals: 5
            };
        }

        const magnitude = Math.pow(
            10,
            Math.floor(
                Math.log10(
                    preparedMaximum
                )
            )
        );

        let step = Math.max(
            1,
            magnitude / 10
        );

        let intervals = Math.ceil(
            preparedMaximum
            / step
        );

        if (intervals > 10) {
            const multipliers = [
                2,
                5,
                10
            ];

            const selectedMultiplier = (
                multipliers.find(
                    (multiplier) => (
                        Math.ceil(
                            preparedMaximum
                            / (
                                step
                                * multiplier
                            )
                        )
                        <= 10
                    )
                )
                || 10
            );

            step *= selectedMultiplier;

            intervals = Math.ceil(
                preparedMaximum
                / step
            );
        }

        const axisMaximum = (
            Math.ceil(
                preparedMaximum
                / step
            )
            * step
        );

        return {
            maximum: axisMaximum,
            step,
            intervals: Math.max(
                1,
                Math.round(
                    axisMaximum
                    / step
                )
            )
        };
    }

    function calculateTrendAxes(
        penaltyMaximum,
        violationMaximum
    ) {
        const preferredPenalty = (
            calculatePreferredAxis(
                penaltyMaximum
            )
        );

        const preferredViolation = (
            calculatePreferredAxis(
                violationMaximum
            )
        );

        const intervals = clamp(
            Math.max(
                4,
                preferredPenalty.intervals,
                preferredViolation.intervals
            ),
            4,
            10
        );

        const penaltyStep = niceCeil(
            Math.max(
                1,
                penaltyMaximum
            )
            / intervals
        );

        const violationStep = niceCeil(
            Math.max(
                1,
                violationMaximum
            )
            / intervals
        );

        return {
            intervals,

            penalties: {
                step: penaltyStep,

                maximum: (
                    penaltyStep
                    * intervals
                )
            },

            violations: {
                step: violationStep,

                maximum: (
                    violationStep
                    * intervals
                )
            }
        };
    }

    function buildTrendLayout(data) {
        const width = 980;
        const height = 360;

        const left = 118;
        const right = 18;
        const top = 20;
        const bottom = 48;

        const chartWidth = (
            width
            - left
            - right
        );

        const chartHeight = (
            height
            - top
            - bottom
        );

        const axisY = (
            top
            + chartHeight
        );

        const stepX = (
            chartWidth

            / Math.max(
                1,
                data.months.length - 1
            )
        );

        const rawPenaltyMaximum = Math.max(
            0,
            ...data.penalties
        );

        const rawViolationMaximum = Math.max(
            0,
            ...data.violations
        );

        const axes = calculateTrendAxes(
            rawPenaltyMaximum,
            rawViolationMaximum
        );

        const points = data.months.map(
            (
                month,
                index
            ) => {
                const x = (
                    left
                    + stepX
                    * index
                );

                const penaltyY = (
                    top
                    + chartHeight
                    - (
                        data.penalties[
                            index
                        ]
                        / axes.penalties.maximum
                    )
                    * chartHeight
                );

                const violationY = (
                    top
                    + chartHeight
                    - (
                        data.violations[
                            index
                        ]
                        / axes.violations.maximum
                    )
                    * chartHeight
                );

                return {
                    key: String(
                        month.key
                        || month.axisLabel
                        || index
                    ),

                    month,
                    index,
                    x,
                    penaltyY,
                    violationY,

                    penalties: (
                        data.penalties[
                            index
                        ]
                    ),

                    violations: (
                        data.violations[
                            index
                        ]
                    ),

                    opacity: 1
                };
            }
        );

        const tickFractions = Array.from(
            {
                length: (
                    axes.intervals
                    + 1
                )
            },
            (
                _,
                index
            ) => (
                index
                / axes.intervals
            )
        );

        return {
            width,
            height,
            left,
            right,
            top,
            bottom,
            chartWidth,
            chartHeight,
            axisY,
            axes,
            points,
            tickFractions,
            forecastStartIndex: (
                data.forecastStartIndex
            )
        };
    }

    function interpolateTrendPoint(
        start,
        finish,
        progress
    ) {
        return {
            ...finish,

            x: lerp(
                start.x,
                finish.x,
                progress
            ),

            penaltyY: lerp(
                start.penaltyY,
                finish.penaltyY,
                progress
            ),

            violationY: lerp(
                start.violationY,
                finish.violationY,
                progress
            ),

            opacity: lerp(
                start.opacity ?? 1,
                finish.opacity ?? 1,
                progress
            )
        };
    }

    function interpolateTrendLayout(
        startLayout,
        finishLayout,
        progress
    ) {
        if (!startLayout) {
            return finishLayout;
        }

        const startByKey = new Map(
            startLayout.points.map(
                (point) => [
                    point.key,
                    point
                ]
            )
        );

        const firstStartPoint = (
            startLayout.points[0]
            || finishLayout.points[0]
        );

        const lastStartPoint = (
            startLayout.points[
                startLayout.points.length - 1
            ]
            || finishLayout.points[
                finishLayout.points.length - 1
            ]
        );

        const points = finishLayout.points.map(
            (
                finishPoint,
                index
            ) => {
                let startPoint = (
                    startByKey.get(
                        finishPoint.key
                    )
                );

                if (!startPoint) {
                    const useFirst = (
                        index
                        <= 0
                    );

                    const fallback = (
                        useFirst
                            ? firstStartPoint
                            : lastStartPoint
                    );

                    startPoint = {
                        ...finishPoint,

                        x: (
                            fallback?.x
                            ?? finishPoint.x
                        ),

                        penaltyY: (
                            fallback?.penaltyY
                            ?? finishPoint.penaltyY
                        ),

                        violationY: (
                            fallback?.violationY
                            ?? finishPoint.violationY
                        ),

                        opacity: 0
                    };
                }

                return interpolateTrendPoint(
                    startPoint,
                    finishPoint,
                    progress
                );
            }
        );

        return {
            ...finishLayout,
            points
        };
    }

    function interpolateTrendSegmentPoint(
        start,
        finish,
        progress
    ) {
        return {
            x: lerp(
                start.x,
                finish.x,
                progress
            ),

            penaltyY: lerp(
                start.penaltyY,
                finish.penaltyY,
                progress
            ),

            violationY: lerp(
                start.violationY,
                finish.violationY,
                progress
            )
        };
    }

    function buildTrendAreaMarkup(layout) {
        const actualPointCount = clamp(
            layout.forecastStartIndex,
            0,
            layout.points.length
        );

        if (actualPointCount < 2) {
            return {
                definitions: "",
                areas: ""
            };
        }

        const definitions = [];
        const areas = [];

        const colorBySeries = {
            penalties: PENALTY_COLORS[0],
            violations: VIOLATION_COLORS[0]
        };

        let gradientIndex = 0;

        function addGradient(
            series,
            startY,
            finishY,
            startOpacity
        ) {
            const id = (
                "trend-area-gradient-"
                + trendState.renderAnimationToken
                + "-"
                + gradientIndex
            );

            gradientIndex += 1;

            definitions.push(`
                <linearGradient
                    id="${id}"
                    gradientUnits="userSpaceOnUse"
                    x1="0"
                    y1="${startY}"
                    x2="0"
                    y2="${Math.max(
                        startY + 1,
                        finishY
                    )}"
                >
                    <stop
                        offset="0%"
                        stop-color="${colorBySeries[series]}"
                        stop-opacity="${startOpacity}"
                    ></stop>

                    <stop
                        offset="100%"
                        stop-color="${colorBySeries[series]}"
                        stop-opacity="0"
                    ></stop>
                </linearGradient>
            `);

            return id;
        }

        function addSubsegment(
            start,
            finish
        ) {
            const middlePenaltyY = (
                start.penaltyY
                + finish.penaltyY
            ) / 2;

            const middleViolationY = (
                start.violationY
                + finish.violationY
            ) / 2;

            const lowerSeries = (
                middlePenaltyY
                >= middleViolationY

                    ? "penalties"
                    : "violations"
            );

            const upperSeries = (
                lowerSeries
                === "penalties"

                    ? "violations"
                    : "penalties"
            );

            const lowerStartY = (
                lowerSeries
                === "penalties"

                    ? start.penaltyY
                    : start.violationY
            );

            const lowerFinishY = (
                lowerSeries
                === "penalties"

                    ? finish.penaltyY
                    : finish.violationY
            );

            const upperStartY = (
                upperSeries
                === "penalties"

                    ? start.penaltyY
                    : start.violationY
            );

            const upperFinishY = (
                upperSeries
                === "penalties"

                    ? finish.penaltyY
                    : finish.violationY
            );

            const lowerGradientId = addGradient(
                lowerSeries,
                (
                    lowerStartY
                    + lowerFinishY
                ) / 2,
                layout.axisY,
                0.34
            );

            const lowerPath = [
                "M",
                start.x,
                lowerStartY,

                "L",
                finish.x,
                lowerFinishY,

                "L",
                finish.x,
                layout.axisY,

                "L",
                start.x,
                layout.axisY,

                "Z"
            ].join(" ");

            areas.push(`
                <path
                    class="trend-area trend-area--${lowerSeries}"
                    d="${lowerPath}"
                    fill="url(#${lowerGradientId})"
                ></path>
            `);

            const upperHeight = Math.abs(
                (
                    upperStartY
                    + upperFinishY
                )
                - (
                    lowerStartY
                    + lowerFinishY
                )
            ) / 2;

            if (upperHeight > 0.5) {
                const upperGradientId = addGradient(
                    upperSeries,
                    (
                        upperStartY
                        + upperFinishY
                    ) / 2,
                    (
                        lowerStartY
                        + lowerFinishY
                    ) / 2,
                    0.3
                );

                const upperPath = [
                    "M",
                    start.x,
                    upperStartY,

                    "L",
                    finish.x,
                    upperFinishY,

                    "L",
                    finish.x,
                    lowerFinishY,

                    "L",
                    start.x,
                    lowerStartY,

                    "Z"
                ].join(" ");

                areas.push(`
                    <path
                        class="trend-area trend-area--${upperSeries}"
                        d="${upperPath}"
                        fill="url(#${upperGradientId})"
                    ></path>
                `);
            }
        }

        for (
            let index = 0;
            index < actualPointCount - 1;
            index += 1
        ) {
            const start = (
                layout.points[
                    index
                ]
            );

            const finish = (
                layout.points[
                    index + 1
                ]
            );

            const startDifference = (
                start.penaltyY
                - start.violationY
            );

            const finishDifference = (
                finish.penaltyY
                - finish.violationY
            );

            const linesCross = (
                startDifference
                * finishDifference
                < 0
            );

            if (!linesCross) {
                addSubsegment(
                    start,
                    finish
                );

                continue;
            }

            const crossingProgress = (
                Math.abs(
                    startDifference
                )
                / (
                    Math.abs(
                        startDifference
                    )
                    + Math.abs(
                        finishDifference
                    )
                )
            );

            const crossing = (
                interpolateTrendSegmentPoint(
                    start,
                    finish,
                    crossingProgress
                )
            );

            addSubsegment(
                start,
                crossing
            );

            addSubsegment(
                crossing,
                finish
            );
        }

        return {
            definitions: (
                definitions.join("")
            ),

            areas: (
                areas.join("")
            )
        };
    }

    function formatPenaltyAxisValue(value) {
        const prepared = Math.max(
            0,
            numericValue(value) || 0
        );

        if (prepared <= 0) {
            return "0 тыс.";
        }

        return (
            formatThousands(
                prepared
            )
            + " тыс."
        );
    }

    function fillTrendTooltip(
        container,
        payload
    ) {
        const title = document.createElement(
            "div"
        );

        title.className = (
            "dashboard-trend-tooltip__title"
        );

        title.textContent = (
            payload.month
            || "Период"
        );

        const list = document.createElement(
            "div"
        );

        list.className = (
            "dashboard-trend-tooltip__list"
        );

        const rows = [
            {
                label: "Штрафы",
                value: (
                    formatNumber(
                        payload.penalties,
                        0
                    )
                ),
                color: PENALTY_COLORS[0]
            },
            {
                label: "Отклонения",
                value: (
                    formatNumber(
                        payload.violations,
                        0
                    )
                ),
                color: VIOLATION_COLORS[0]
            }
        ];

        rows.forEach(
            (item) => {
                const row = document.createElement(
                    "div"
                );

                const swatch = document.createElement(
                    "span"
                );

                const label = document.createElement(
                    "span"
                );

                const value = document.createElement(
                    "strong"
                );

                row.className = (
                    "dashboard-trend-tooltip__row"
                );

                swatch.className = (
                    "dashboard-trend-tooltip__swatch"
                );

                label.className = (
                    "dashboard-trend-tooltip__label"
                );

                value.className = (
                    "dashboard-trend-tooltip__value"
                );

                swatch.style.backgroundColor = (
                    item.color
                );

                label.textContent = item.label;
                value.textContent = item.value;

                row.append(
                    swatch,
                    label,
                    value
                );

                list.appendChild(row);
            }
        );

        container.append(
            title,
            list
        );
    }

    function renderTrendLayout(
        target,
        layout,
        bindTooltips = true
    ) {
        const split = splitTrendIndexes(
            layout.points.length,
            layout.forecastStartIndex
        );

        const pointResolver = (
            series
        ) => (
            index
        ) => ({
            x: (
                layout.points[
                    index
                ].x
            ),

            y: (
                series
                === "penalties"

                    ? layout.points[
                        index
                    ].penaltyY

                    : layout.points[
                        index
                    ].violationY
            )
        });

        const penaltyResolver = (
            pointResolver(
                "penalties"
            )
        );

        const violationResolver = (
            pointResolver(
                "violations"
            )
        );

        const horizontalGridMarkup = (
            layout.tickFractions
                .map(
                    (
                        fraction,
                        index
                    ) => {
                        const y = (
                            layout.top
                            + layout.chartHeight
                            - fraction
                            * layout.chartHeight
                        );

                        return `
                            <line
                                class="trend-grid-line"
                                x1="${layout.left}"
                                y1="${y}"
                                x2="${layout.width - layout.right}"
                                y2="${y}"
                            ></line>
                        `;
                    }
                )
                .join("")
        );

        const verticalGridMarkup = (
            layout.points
                .map(
                    (point) => `
                        <line
                            class="trend-grid-line"
                            x1="${point.x}"
                            y1="${layout.top}"
                            x2="${point.x}"
                            y2="${layout.axisY}"
                        ></line>
                    `
                )
                .join("")
        );

        const leftLabelsMarkup = (
            layout.tickFractions
                .map(
                    (
                        fraction,
                        index
                    ) => {
                        const y = (
                            layout.top
                            + layout.chartHeight
                            - fraction
                            * layout.chartHeight
                        );

                        const penaltyValue = (
                            layout.axes
                                .penalties
                                .step
                            * index
                        );

                        const violationValue = (
                            layout.axes
                                .violations
                                .step
                            * index
                        );

                        return `
                            <text
                                class="trend-axis-label"
                                x="${layout.left - 12}"
                                y="${y + 4}"
                                text-anchor="end"
                            >
                                <tspan
                                    class="trend-axis-label--penalties"
                                >
                                    ${formatPenaltyAxisValue(
                                        penaltyValue
                                    )}
                                </tspan>

                                <tspan
                                    class="trend-axis-label-separator"
                                >
                                    /
                                </tspan>

                                <tspan
                                    class="trend-axis-label--violations"
                                >
                                    ${formatNumber(
                                        violationValue,
                                        0
                                    )} шт.
                                </tspan>
                            </text>
                        `;
                    }
                )
                .join("")
        );

        const axisCaptionMarkup = `
            <text
                class="trend-axis-caption"
                x="${layout.left - 12}"
                y="${layout.top - 7}"
                text-anchor="end"
            >
                тыс. / шт.
            </text>
        `;

        const bottomLabelsMarkup = (
            layout.points
                .map(
                    (point) => `
                        <text
                            class="trend-bottom-label"
                            x="${point.x}"
                            y="${layout.height - 12}"
                            text-anchor="middle"
                        >
                            ${point.month.axisLabel}
                        </text>
                    `
                )
                .join("")
        );

        const controlPointsMarkup = (
            layout.points
                .map(
                    (point) => {
                        const tooltipPayload = (
                            encodeURIComponent(
                                JSON.stringify(
                                    {
                                        month: (
                                            point.month.label
                                        ),

                                        penalties: (
                                            point.penalties
                                        ),

                                        violations: (
                                            point.violations
                                        )
                                    }
                                )
                            )
                        );

                        return `
                            <g
                                opacity="${point.opacity ?? 1}"
                            >
                                <circle
                                    class="trend-point"
                                    cx="${point.x}"
                                    cy="${point.penaltyY}"
                                    r="4.5"
                                    fill="${PENALTY_COLORS[0]}"
                                ></circle>

                                <circle
                                    class="trend-point"
                                    cx="${point.x}"
                                    cy="${point.violationY}"
                                    r="4.5"
                                    fill="${VIOLATION_COLORS[0]}"
                                ></circle>

                                <circle
                                    class="trend-point-hit"
                                    cx="${point.x}"
                                    cy="${point.penaltyY}"
                                    r="13"
                                    data-trend-tooltip="${tooltipPayload}"
                                ></circle>

                                <circle
                                    class="trend-point-hit"
                                    cx="${point.x}"
                                    cy="${point.violationY}"
                                    r="13"
                                    data-trend-tooltip="${tooltipPayload}"
                                ></circle>
                            </g>
                        `;
                    }
                )
                .join("")
        );

        const penaltiesActual = (
            buildTrendPathMarkup(
                "trend-line trend-line--penalties",
                split.actual,
                penaltyResolver
            )
        );

        const penaltiesForecast = (
            buildTrendPathMarkup(
                "trend-line trend-line--penalties trend-line--forecast",
                split.forecast,
                penaltyResolver
            )
        );

        const violationsActual = (
            buildTrendPathMarkup(
                "trend-line trend-line--violations",
                split.actual,
                violationResolver
            )
        );

        const violationsForecast = (
            buildTrendPathMarkup(
                "trend-line trend-line--violations trend-line--forecast",
                split.forecast,
                violationResolver
            )
        );

        const areaMarkup = buildTrendAreaMarkup(
            layout
        );

        target.innerHTML = `
            <svg
                viewBox="0 0 ${layout.width} ${layout.height}"
                role="img"
                aria-label="Тренды штрафов и отклонений"
                preserveAspectRatio="none"
            >
                <defs>
                    ${areaMarkup.definitions}
                </defs>

                <g class="trend-area-layer">
                    ${areaMarkup.areas}
                </g>

                <g class="trend-detail-layer">
                    ${horizontalGridMarkup}
                    ${verticalGridMarkup}
                </g>

                <line
                    class="trend-axis-line"
                    x1="${layout.left}"
                    y1="${layout.top}"
                    x2="${layout.left}"
                    y2="${layout.axisY}"
                ></line>

                <line
                    class="trend-axis-line"
                    x1="${layout.left}"
                    y1="${layout.axisY}"
                    x2="${layout.width - layout.right}"
                    y2="${layout.axisY}"
                ></line>

                ${penaltiesActual}
                ${penaltiesForecast}

                ${violationsActual}
                ${violationsForecast}

                <g class="trend-detail-layer">
                    ${controlPointsMarkup}
                    ${leftLabelsMarkup}
                    ${axisCaptionMarkup}
                    ${bottomLabelsMarkup}
                </g>
            </svg>
        `;

        if (!bindTooltips) {
            return;
        }

        target
            .querySelectorAll(
                "[data-trend-tooltip]"
            )
            .forEach(
                (node) => {
                    node.addEventListener(
                        "pointerenter",
                        () => {
                            try {
                                const payload = JSON.parse(
                                    decodeURIComponent(
                                        node.getAttribute(
                                            "data-trend-tooltip"
                                        ) || ""
                                    )
                                );

                                trendTooltip.show(
                                    node,

                                    (container) => {
                                        fillTrendTooltip(
                                            container,
                                            payload
                                        );
                                    },

                                    [
                                        "top",
                                        "right",
                                        "left",
                                        "bottom"
                                    ]
                                );
                            } catch {
                                trendTooltip.hide();
                            }
                        }
                    );

                    node.addEventListener(
                        "pointermove",
                        () => {
                            trendTooltip.position(
                                node,

                                [
                                    "top",
                                    "right",
                                    "left",
                                    "bottom"
                                ]
                            );
                        },
                        {
                            passive: true
                        }
                    );

                    node.addEventListener(
                        "pointerleave",
                        trendTooltip.hide
                    );

                    node.addEventListener(
                        "pointercancel",
                        trendTooltip.hide
                    );
                }
            );
    }

    function renderTrendFromState(
        options = {}
    ) {
        const target = byId(
            "dashboard-trend-chart"
        );

        const zoomIn = byId(
            "dashboard-trend-zoom-in"
        );

        const zoomOut = byId(
            "dashboard-trend-zoom-out"
        );

        if (
            !target
            || !trendState.raw
        ) {
            return;
        }

        const data = getTrendVisibleData();

        if (
            !data
            || data.months.length < 2
        ) {
            target.innerHTML = `
                <div class="dashboard-chart-placeholder">
                    Данных для тренда недостаточно.
                </div>
            `;

            trendState.currentLayout = null;

            return;
        }

        const targetLayout = buildTrendLayout(
            data
        );

        const animate = Boolean(
            options.animate
            && trendState.currentLayout
            && !magnetState.reducedMotion
        );

        if (
            trendState.renderAnimationFrame
            !== null
        ) {
            window.cancelAnimationFrame(
                trendState.renderAnimationFrame
            );

            trendState.renderAnimationFrame = null;
        }

        trendState.renderAnimationToken += 1;

        const animationToken = (
            trendState.renderAnimationToken
        );

        if (!animate) {
            trendState.currentLayout = (
                targetLayout
            );

            renderTrendLayout(
                target,
                targetLayout,
                true
            );
        } else {
            const startLayout = (
                trendState.currentLayout
            );

            const startedAt = performance.now();

            const renderFrame = (
                timestamp
            ) => {
                if (
                    animationToken
                    !== trendState.renderAnimationToken
                ) {
                    return;
                }

                const rawProgress = clamp(
                    (
                        timestamp
                        - startedAt
                    )
                    / trendState.renderAnimationDuration,
                    0,
                    1
                );

                const easedProgress = (
                    1
                    - Math.pow(
                        1
                        - rawProgress,
                        3
                    )
                );

                const interpolatedLayout = (
                    interpolateTrendLayout(
                        startLayout,
                        targetLayout,
                        easedProgress
                    )
                );

                trendState.currentLayout = (
                    interpolatedLayout
                );

                renderTrendLayout(
                    target,
                    interpolatedLayout,
                    false
                );

                if (rawProgress < 1) {
                    trendState.renderAnimationFrame = (
                        window.requestAnimationFrame(
                            renderFrame
                        )
                    );

                    return;
                }

                trendState.renderAnimationFrame = null;
                trendState.currentLayout = targetLayout;

                renderTrendLayout(
                    target,
                    targetLayout,
                    true
                );
            };

            trendState.renderAnimationFrame = (
                window.requestAnimationFrame(
                    renderFrame
                )
            );
        }

        const total = (
            trendState.raw.months.length
        );

        const minimum = Math.min(
            trendState.minVisibleCount,
            total
        );

        const maximum = Math.min(
            trendState.maxVisibleCount,
            total
        );

        if (zoomIn) {
            zoomIn.disabled = (
                trendState.visibleCount
                <= minimum
            );
        }

        if (zoomOut) {
            zoomOut.disabled = (
                trendState.visibleCount
                >= maximum
            );
        }
    }

    function getShapePhysicsKey(shape) {
        if (
            shape.classList.contains(
                "dashboard-shape--sales"
            )
        ) {
            return "sales";
        }

        if (
            shape.classList.contains(
                "dashboard-shape--violations"
            )
        ) {
            return "violations";
        }

        if (
            shape.classList.contains(
                "dashboard-shape--penalties"
            )
        ) {
            return "penalties";
        }

        return "documents";
    }

    function createMagnetItem(shape) {
        const physicsKey = (
            getShapePhysicsKey(shape)
        );

        return {
            shape,

            physicsKey,

            physics: (
                TREND_CIRCLE_PHYSICS[
                    physicsKey
                ]
            ),

            pie: (
                shape.querySelector(
                    ".analytics-pie"
                )
            ),

            orbitStates: [],

            baseCenterX: 0,
            baseCenterY: 0,

            diameter: 1,

            lastDirectionX: 0,
            lastDirectionY: 0,

            currentX: 0,
            currentY: 0,

            targetX: 0,
            targetY: 0,

            currentTiltX: 0,
            currentTiltY: 0,

            targetTiltX: 0,
            targetTiltY: 0,

            currentScale: 1,
            targetScale: 1,

            currentIntensity: 0,
            targetIntensity: 0,

            trendX: 0,
            trendY: 0,
            trendScale: 1,

            trendTargetX: 0,
            trendTargetY: 0,
            trendTargetScale: 1,

            trendVelocityX: 0,
            trendVelocityY: 0,
            trendVelocityScale: 0,

            trendStartAt: 0
        };
    }

    function refreshMagnetElements() {
        magnetState.zone = (
            document.querySelector(
                ".dashboard-circle-zone"
            )
        );

        magnetState.items = (
            Array.from(
                document.querySelectorAll(
                    ".dashboard-circle-zone "
                    + ".dashboard-shape"
                )
            )
                .map(
                    createMagnetItem
                )
        );
    }

    function updateMagnetGeometry() {
        if (!magnetState.zone) {
            return;
        }

        magnetState.zoneRect = (
            magnetState.zone
                .getBoundingClientRect()
        );

        magnetState.items.forEach(
            (item) => {
                const chart = (
                    item.shape
                        .querySelector(
                            ".dashboard-shape__chart"
                        )
                );

                item.pie = (
                    item.shape
                        .querySelector(
                            ".analytics-pie"
                        )
                );

                item.baseCenterX = (
                    magnetState.zoneRect.left
                    + item.shape.offsetLeft
                );

                item.baseCenterY = (
                    magnetState.zoneRect.top
                    + item.shape.offsetTop
                );

                item.diameter = Math.max(
                    1,

                    item.pie?.offsetWidth
                    || item.shape.offsetWidth
                    || 1
                );

                const chartWidth = Math.max(
                    1,

                    chart?.offsetWidth
                    || item.diameter
                );

                const chartHeight = Math.max(
                    1,

                    chart?.offsetHeight
                    || item.diameter
                );

                item.orbitStates = (
                    Array.from(
                        item.shape
                            .querySelectorAll(
                                ".dashboard-orbit-item"
                            )
                    )
                        .map(
                            (element) => ({
                                element,

                                relativeX: (
                                    element.offsetLeft
                                    - chartWidth / 2
                                ),

                                relativeY: (
                                    element.offsetTop
                                    - chartHeight / 2
                                ),

                                currentX: 0,
                                currentY: 0,

                                targetX: 0,
                                targetY: 0
                            })
                        )
                );
            }
        );
    }

    function resetMagnetTargets(
        resetDirection = false
    ) {
        magnetState.items.forEach(
            (item) => {
                item.targetX = 0;
                item.targetY = 0;

                item.targetTiltX = 0;
                item.targetTiltY = 0;

                item.targetScale = 1;
                item.targetIntensity = 0;

                item.orbitStates.forEach(
                    (state) => {
                        state.targetX = 0;
                        state.targetY = 0;
                    }
                );

                if (resetDirection) {
                    item.lastDirectionX = 0;
                    item.lastDirectionY = 0;
                }
            }
        );
    }

    function calculateMagnetTargets() {
        if (
            !magnetState.pointerInside
            || magnetState.reducedMotion
            || magnetState.coarsePointer
        ) {
            resetMagnetTargets();

            return;
        }

        magnetState.items.forEach(
            (item) => {
                const effectiveCenterX = (
                    item.baseCenterX
                    + item.trendX
                );

                const effectiveCenterY = (
                    item.baseCenterY
                    + item.trendY
                );

                const deltaX = (
                    magnetState.pointerX
                    - effectiveCenterX
                );

                const deltaY = (
                    magnetState.pointerY
                    - effectiveCenterY
                );

                const distance = Math.hypot(
                    deltaX,
                    deltaY
                );

                const influenceRadius = clamp(
                    item.diameter
                    * item.trendScale
                    * MAGNET_SETTINGS
                        .influenceMultiplier,

                    MAGNET_SETTINGS
                        .minimumInfluence,

                    MAGNET_SETTINGS
                        .maximumInfluence
                );

                if (
                    distance
                    >= influenceRadius
                ) {
                    item.targetX = 0;
                    item.targetY = 0;

                    item.targetTiltX = 0;
                    item.targetTiltY = 0;

                    item.targetScale = 1;
                    item.targetIntensity = 0;

                    return;
                }

                if (
                    distance
                    > MAGNET_SETTINGS
                        .circleDeadZone
                ) {
                    item.lastDirectionX = (
                        deltaX
                        / distance
                    );

                    item.lastDirectionY = (
                        deltaY
                        / distance
                    );
                }

                const proximity = (
                    1
                    - distance
                    / influenceRadius
                );

                const intensity = (
                    distance
                    <= MAGNET_SETTINGS
                        .circleDeadZone

                        ? 1

                        : smoothStep(
                            proximity
                        )
                );

                const maximumMove = clamp(
                    item.diameter
                    * item.trendScale
                    * MAGNET_SETTINGS
                        .maximumMoveRatio,

                    MAGNET_SETTINGS
                        .minimumMaximumMove,

                    MAGNET_SETTINGS
                        .maximumMaximumMove
                );

                item.targetX = (
                    item.lastDirectionX
                    * maximumMove
                    * intensity
                );

                item.targetY = (
                    item.lastDirectionY
                    * maximumMove
                    * intensity
                );

                item.targetTiltX = (
                    -item.lastDirectionY
                    * MAGNET_SETTINGS
                        .maximumTilt
                    * intensity
                );

                item.targetTiltY = (
                    item.lastDirectionX
                    * MAGNET_SETTINGS
                        .maximumTilt
                    * intensity
                );

                item.targetScale = (
                    1

                    + (
                        MAGNET_SETTINGS
                            .maximumScale
                        - 1
                    )
                    * intensity
                );

                item.targetIntensity = (
                    intensity
                );
            }
        );
    }

    function calculateOrbitValueShift(
        state,
        item
    ) {
        if (
            !magnetState.pointerInside
            || magnetState.reducedMotion
            || magnetState.coarsePointer
        ) {
            return {
                x: 0,
                y: 0
            };
        }

        const circleFollowX = (
            item.currentX
            * ORBIT_MAGNET_SETTINGS
                .circleFollowRatio
        );

        const circleFollowY = (
            item.currentY
            * ORBIT_MAGNET_SETTINGS
                .circleFollowRatio
        );

        const effectiveCenterX = (
            item.baseCenterX
            + item.trendX
            + state.relativeX
            * item.trendScale
            + circleFollowX
        );

        const effectiveCenterY = (
            item.baseCenterY
            + item.trendY
            + state.relativeY
            * item.trendScale
            + circleFollowY
        );

        const deltaX = (
            magnetState.pointerX
            - effectiveCenterX
        );

        const deltaY = (
            magnetState.pointerY
            - effectiveCenterY
        );

        const distance = Math.hypot(
            deltaX,
            deltaY
        );

        if (
            distance
            <= ORBIT_MAGNET_SETTINGS
                .deadZone

            || distance
            >= ORBIT_MAGNET_SETTINGS
                .influenceRadius
        ) {
            return {
                x: 0,
                y: 0
            };
        }

        const activeDistance = (
            distance
            - ORBIT_MAGNET_SETTINGS
                .deadZone
        );

        const activeRadius = (
            ORBIT_MAGNET_SETTINGS
                .influenceRadius

            - ORBIT_MAGNET_SETTINGS
                .deadZone
        );

        const proximity = (
            1
            - activeDistance
            / activeRadius
        );

        const intensity = smoothStep(
            proximity
        );

        return {
            x: (
                deltaX
                / distance

                * ORBIT_MAGNET_SETTINGS
                    .maximumShift

                * intensity
            ),

            y: (
                deltaY
                / distance

                * ORBIT_MAGNET_SETTINGS
                    .maximumShift

                * intensity
            )
        };
    }

    function springValue(
        value,
        velocity,
        target,
        stiffness,
        damping,
        frameFactor
    ) {
        let nextVelocity = (
            velocity

            + (
                target
                - value
            )
            * stiffness
            * frameFactor
        );

        nextVelocity *= Math.pow(
            damping,
            frameFactor
        );

        const nextValue = (
            value
            + nextVelocity
            * frameFactor
        );

        return {
            value: nextValue,
            velocity: nextVelocity
        };
    }

    function stepTrendPhysics(
        item,
        timestamp,
        frameFactor
    ) {
        if (
            timestamp
            < item.trendStartAt
        ) {
            return true;
        }

        const xResult = springValue(
            item.trendX,
            item.trendVelocityX,
            item.trendTargetX,
            item.physics.stiffness,
            item.physics.damping,
            frameFactor
        );

        const yResult = springValue(
            item.trendY,
            item.trendVelocityY,
            item.trendTargetY,
            item.physics.stiffness,
            item.physics.damping,
            frameFactor
        );

        const scaleResult = springValue(
            item.trendScale,
            item.trendVelocityScale,
            item.trendTargetScale,
            item.physics.scaleStiffness,
            item.physics.scaleDamping,
            frameFactor
        );

        item.trendX = xResult.value;
        item.trendVelocityX = xResult.velocity;

        item.trendY = yResult.value;
        item.trendVelocityY = yResult.velocity;

        item.trendScale = scaleResult.value;
        item.trendVelocityScale = scaleResult.velocity;

        const difference = (
            Math.abs(
                item.trendTargetX
                - item.trendX
            )

            + Math.abs(
                item.trendTargetY
                - item.trendY
            )

            + Math.abs(
                item.trendTargetScale
                - item.trendScale
            )
            * 100

            + Math.abs(
                item.trendVelocityX
            )

            + Math.abs(
                item.trendVelocityY
            )

            + Math.abs(
                item.trendVelocityScale
            )
            * 100
        );

        if (difference < 0.035) {
            item.trendX = item.trendTargetX;
            item.trendY = item.trendTargetY;

            item.trendScale = (
                item.trendTargetScale
            );

            item.trendVelocityX = 0;
            item.trendVelocityY = 0;
            item.trendVelocityScale = 0;

            return false;
        }

        return true;
    }

    function applyMagnetStyles(item) {
        item.shape.style.setProperty(
            "--magnet-x",

            `${
                item.currentX
                    .toFixed(3)
            }px`
        );

        item.shape.style.setProperty(
            "--magnet-y",

            `${
                item.currentY
                    .toFixed(3)
            }px`
        );

        item.shape.style.setProperty(
            "--trend-x",

            `${
                item.trendX
                    .toFixed(3)
            }px`
        );

        item.shape.style.setProperty(
            "--trend-y",

            `${
                item.trendY
                    .toFixed(3)
            }px`
        );

        item.shape.style.setProperty(
            "--trend-scale",

            item.trendScale
                .toFixed(5)
        );

        item.orbitStates.forEach(
            (state) => {
                const target = (
                    calculateOrbitValueShift(
                        state,
                        item
                    )
                );

                state.targetX = target.x;
                state.targetY = target.y;

                state.currentX = lerp(
                    state.currentX,
                    state.targetX,

                    ORBIT_MAGNET_SETTINGS
                        .movementEase
                );

                state.currentY = lerp(
                    state.currentY,
                    state.targetY,

                    ORBIT_MAGNET_SETTINGS
                        .movementEase
                );

                const totalX = (
                    item.currentX

                    * ORBIT_MAGNET_SETTINGS
                        .circleFollowRatio

                    + state.currentX
                );

                const totalY = (
                    item.currentY

                    * ORBIT_MAGNET_SETTINGS
                        .circleFollowRatio

                    + state.currentY
                );

                state.element.style.transform = (
                    "translate(-50%, -50%) "

                    + "translate3d("

                    + totalX.toFixed(3)
                    + "px, "

                    + totalY.toFixed(3)
                    + "px, 0)"
                );
            }
        );

        if (!item.pie) {
            return;
        }

        item.pie.style.setProperty(
            "--tilt-x",

            `${
                item.currentTiltX
                    .toFixed(3)
            }deg`
        );

        item.pie.style.setProperty(
            "--tilt-y",

            `${
                item.currentTiltY
                    .toFixed(3)
            }deg`
        );

        item.pie.style.setProperty(
            "--magnet-scale",

            item.currentScale
                .toFixed(4)
        );

        item.pie.style.setProperty(
            "--shadow-x",

            `${
                (
                    -item.currentX
                    * 0.2
                ).toFixed(2)
            }px`
        );

        item.pie.style.setProperty(
            "--shadow-y",

            `${
                (
                    8
                    - item.currentY
                    * 0.1
                ).toFixed(2)
            }px`
        );

        item.pie.style.setProperty(
            "--shadow-blur",

            `${
                (
                    14
                    + item.currentIntensity
                    * 9
                ).toFixed(2)
            }px`
        );

        item.pie.style.setProperty(
            "--shadow-opacity",

            (
                0.07
                + item.currentIntensity
                * 0.06
            ).toFixed(3)
        );
    }

    function animateMagnet(timestamp) {
        calculateMagnetTargets();

        const previousTime = (
            magnetState.lastAnimationTime
            ?? timestamp
        );

        const elapsed = clamp(
            timestamp
            - previousTime,
            0,
            40
        );

        const frameFactor = clamp(
            elapsed / 16.6667,
            0.35,
            2.4
        );

        magnetState.lastAnimationTime = timestamp;

        let hasMovement = false;

        magnetState.items.forEach(
            (item) => {
                const trendMoving = (
                    stepTrendPhysics(
                        item,
                        timestamp,
                        frameFactor
                    )
                );

                item.currentX = lerp(
                    item.currentX,
                    item.targetX,

                    MAGNET_SETTINGS
                        .movementEase
                );

                item.currentY = lerp(
                    item.currentY,
                    item.targetY,

                    MAGNET_SETTINGS
                        .movementEase
                );

                item.currentTiltX = lerp(
                    item.currentTiltX,
                    item.targetTiltX,

                    MAGNET_SETTINGS
                        .rotationEase
                );

                item.currentTiltY = lerp(
                    item.currentTiltY,
                    item.targetTiltY,

                    MAGNET_SETTINGS
                        .rotationEase
                );

                item.currentScale = lerp(
                    item.currentScale,
                    item.targetScale,

                    MAGNET_SETTINGS
                        .scaleEase
                );

                item.currentIntensity = lerp(
                    item.currentIntensity,
                    item.targetIntensity,

                    MAGNET_SETTINGS
                        .scaleEase
                );

                applyMagnetStyles(item);

                const orbitDifference = (
                    item.orbitStates.reduce(
                        (
                            sum,
                            state
                        ) => (
                            sum

                            + Math.abs(
                                state.currentX
                                - state.targetX
                            )

                            + Math.abs(
                                state.currentY
                                - state.targetY
                            )
                        ),
                        0
                    )
                );

                const magnetDifference = (
                    Math.abs(
                        item.currentX
                        - item.targetX
                    )

                    + Math.abs(
                        item.currentY
                        - item.targetY
                    )

                    + Math.abs(
                        item.currentTiltX
                        - item.targetTiltX
                    )

                    + Math.abs(
                        item.currentTiltY
                        - item.targetTiltY
                    )

                    + Math.abs(
                        item.currentScale
                        - item.targetScale
                    )

                    + orbitDifference
                );

                if (
                    trendMoving

                    || magnetDifference
                    > MAGNET_SETTINGS
                        .restThreshold
                ) {
                    hasMovement = true;
                }
            }
        );

        circleTooltip.reposition(
            [
                "right",
                "left",
                "bottom",
                "top"
            ]
        );

        trendTooltip.reposition(
            [
                "top",
                "right",
                "left",
                "bottom"
            ]
        );

        if (
            magnetState.pointerInside
            || hasMovement
        ) {
            magnetState.animationFrame = (
                window.requestAnimationFrame(
                    animateMagnet
                )
            );
        } else {
            magnetState.animationFrame = null;
            magnetState.lastAnimationTime = null;
        }
    }

    function ensureMagnetAnimation() {
        if (
            magnetState.animationFrame
            !== null
        ) {
            return;
        }

        magnetState.lastAnimationTime = null;

        magnetState.animationFrame = (
            window.requestAnimationFrame(
                animateMagnet
            )
        );
    }

    function setCircleTrendTargets(expanded) {
        const now = performance.now();

        magnetState.items.forEach(
            (item) => {
                const physics = item.physics;

                item.trendTargetX = (
                    expanded
                        ? physics.x
                        : 0
                );

                item.trendTargetY = (
                    expanded
                        ? physics.y
                        : 0
                );

                item.trendTargetScale = (
                    expanded
                        ? physics.scale
                        : 1
                );

                item.trendStartAt = (
                    now

                    + (
                        expanded
                            ? physics.delayIn
                            : physics.delayOut
                    )
                );

                const direction = (
                    expanded
                        ? 1
                        : -0.62
                );

                item.trendVelocityX += (
                    physics.impulseX
                    * direction
                );

                item.trendVelocityY += (
                    physics.impulseY
                    * direction
                );

                item.trendVelocityScale += (
                    physics.impulseScale
                    * direction
                );
            }
        );

        ensureMagnetAnimation();
    }

    function setTrendExpanded(expanded) {
        const zone = byId(
            "dashboard-trend-zone"
        );

        if (
            !zone
            || trendState.expanded
            === expanded
        ) {
            return;
        }

        trendState.expanded = expanded;

        zone.classList.toggle(
            "dashboard-trend-zone--expanded",
            expanded
        );

        document.body.classList.toggle(
            "dashboard-page--trend-expanded",
            expanded
        );

        setCircleTrendTargets(
            expanded
        );

        if (!expanded) {
            trendTooltip.hide();
        }
    }

    function scheduleTrendExpand() {
        if (
            trendState.collapseTimer
            !== null
        ) {
            window.clearTimeout(
                trendState.collapseTimer
            );

            trendState.collapseTimer = null;
        }

        if (
            trendState.expanded
            || trendState.expandTimer
            !== null
        ) {
            return;
        }

        trendState.expandTimer = (
            window.setTimeout(
                () => {
                    trendState.expandTimer = null;

                    setTrendExpanded(true);
                },
                trendState.hoverDelay
            )
        );
    }

    function scheduleTrendCollapse() {
        if (
            trendState.expandTimer
            !== null
        ) {
            window.clearTimeout(
                trendState.expandTimer
            );

            trendState.expandTimer = null;
        }

        if (
            !trendState.expanded
            || trendState.collapseTimer
            !== null
        ) {
            return;
        }

        trendState.collapseTimer = (
            window.setTimeout(
                () => {
                    trendState.collapseTimer = null;

                    setTrendExpanded(false);
                },
                trendState.hoverDelay
            )
        );
    }

    function initializeTrendInteractions() {
        if (trendState.initialized) {
            return;
        }

        const zone = byId(
            "dashboard-trend-zone"
        );

        const zoomIn = byId(
            "dashboard-trend-zoom-in"
        );

        const zoomOut = byId(
            "dashboard-trend-zoom-out"
        );

        if (!zone) {
            return;
        }

        zone.addEventListener(
            "pointerenter",
            scheduleTrendExpand
        );

        zone.addEventListener(
            "pointerleave",
            scheduleTrendCollapse
        );

        zoomIn?.addEventListener(
            "click",
            (event) => {
                event.stopPropagation();

                const total = (
                    trendState.raw
                        ?.months
                        ?.length

                    || 0
                );

                if (!total) {
                    return;
                }

                const minimum = Math.min(
                    trendState.minVisibleCount,
                    total
                );

                trendState.visibleCount = Math.max(
                    minimum,
                    trendState.visibleCount - 1
                );

                trendTooltip.hide();

                renderTrendFromState({
                    animate: true
                });
            }
        );

        zoomOut?.addEventListener(
            "click",
            (event) => {
                event.stopPropagation();

                const total = (
                    trendState.raw
                        ?.months
                        ?.length

                    || 0
                );

                if (!total) {
                    return;
                }

                const maximum = Math.min(
                    trendState.maxVisibleCount,
                    total
                );

                trendState.visibleCount = Math.min(
                    maximum,
                    trendState.visibleCount + 1
                );

                trendTooltip.hide();

                renderTrendFromState({
                    animate: true
                });
            }
        );

        trendState.initialized = true;
    }

    function renderTrend(trend) {
        trendState.raw = normalizeTrendPayload(
            trend
        );

        const total = (
            trendState.raw.months.length
        );

        if (total === 0) {
            const target = byId(
                "dashboard-trend-chart"
            );

            if (target) {
                target.innerHTML = `
                    <div class="dashboard-chart-placeholder">
                        Данных для тренда недостаточно.
                    </div>
                `;
            }

            return;
        }

        const minimum = Math.min(
            trendState.minVisibleCount,
            total
        );

        const maximum = Math.min(
            trendState.maxVisibleCount,
            total
        );

        trendState.visibleCount = clamp(
            Math.min(
                5,
                total
            ),
            minimum,
            maximum
        );

        renderTrendFromState();
    }

    function updateStaticFilters(payload) {
        const period = byId(
            "dashboard-period-value"
        );

        const tradePoint = byId(
            "dashboard-trade-point-value"
        );

        const organization = byId(
            "dashboard-organization-value"
        );

        if (period) {
            const nextPeriodLabel = (
                payload
                    ?.period
                    ?.label

                || "01.07.2026 — 04.08.2026"
            );

            if (!periodPickerState.userCommitted) {
                const parsed = parsePeriodLabelText(nextPeriodLabel);

                periodPickerState.appliedStart = parsed.start || periodPickerState.appliedStart;
                periodPickerState.appliedEnd = parsed.end || parsed.start || periodPickerState.appliedEnd;
                periodPickerState.draftStart = cloneDate(periodPickerState.appliedStart);
                periodPickerState.draftEnd = cloneDate(periodPickerState.appliedEnd);
                periodPickerState.viewMonth = startOfMonth(periodPickerState.appliedStart || new Date());
            }

            period.textContent = formatPeriodLabel(
                periodPickerState.appliedStart,
                periodPickerState.appliedEnd
            ) || nextPeriodLabel;
        }

        if (tradePoint) {
            tradePoint.textContent = (
                payload
                    ?.filters
                    ?.trade_point

                || "Все ТТ"
            );
        }

        if (organization) {
            organization.textContent = (
                payload
                    ?.filters
                    ?.organization

                || "Все организации"
            );
        }
    }

    async function renderDashboard(
        payload,
        options = {}
    ) {
        const previousPayload = dashboardExportPayload;
        const transition = options.transition || "initial";
        const changedTargets = CIRCLE_TARGET_IDS.filter(
            (targetId) => (
                transition === "initial"
                || circleDataChanged(
                    previousPayload,
                    payload,
                    targetId
                )
            )
        );

        updateStaticFilters(payload);

        if (
            transition === "filters"
            && previousPayload
            && changedTargets.length
        ) {
            await Promise.all(
                changedTargets.map(
                    animateCircleOut
                )
            );
        }

        CIRCLE_TARGET_IDS.forEach(
            (targetId) => {
                if (
                    transition === "filters"
                    && previousPayload
                    && !changedTargets.includes(targetId)
                ) {
                    return;
                }

                const config = CIRCLE_RENDER_CONFIG[targetId];

                renderCircle(
                    targetId,
                    getCircleSegmentsFromPayload(
                        payload,
                        targetId
                    ),
                    config.colors,
                    config.sizeClass
                );
            }
        );

        renderTrend(
            payload?.trend
            || {}
        );

        dashboardExportPayload = payload || {};

        refreshMagnetElements();

        window.requestAnimationFrame(
            updateMagnetGeometry
        );
    }

    function setLoadState(
        message,
        error = false
    ) {
        const element = byId(
            "dashboard-load-state"
        );

        if (!element) {
            return;
        }

        element.textContent = message;

        element.classList.toggle(
            "dashboard-load-state--error",
            error
        );
    }

    function handlePointerMove(event) {
        if (
            magnetState.reducedMotion
            || magnetState.coarsePointer
        ) {
            return;
        }

        magnetState.pointerX = event.clientX;
        magnetState.pointerY = event.clientY;

        magnetState.pointerInside = true;

        circleTooltip.reposition(
            [
                "right",
                "left",
                "bottom",
                "top"
            ]
        );

        ensureMagnetAnimation();
    }

    function handlePointerLeave() {
        magnetState.pointerInside = false;

        circleTooltip.hide();

        resetMagnetTargets(
            true
        );

        ensureMagnetAnimation();
    }

    function handleResize() {
        circleTooltip.hide();
        trendTooltip.hide();

        handlePointerLeave();

        window.requestAnimationFrame(
            () => {
                refreshMagnetElements();
                updateMagnetGeometry();
                renderTrendFromState();

                if (trendState.expanded) {
                    setCircleTrendTargets(true);
                }
            }
        );
    }

    function initializeMagnetEffect() {
        refreshMagnetElements();
        updateMagnetGeometry();

        if (
            !magnetState.zone
            || magnetState.reducedMotion
            || magnetState.coarsePointer
        ) {
            return;
        }

        magnetState.zone.addEventListener(
            "pointermove",
            handlePointerMove,
            {
                passive: true
            }
        );

        magnetState.zone.addEventListener(
            "pointerleave",
            handlePointerLeave,
            {
                passive: true
            }
        );

        window.addEventListener(
            "blur",
            handlePointerLeave
        );

        window.addEventListener(
            "resize",
            handleResize,
            {
                passive: true
            }
        );
    }

    function buildDashboardRequestUrl() {
        const requestUrl = new URL(
            API_URL,
            window.location.origin
        );

        if (periodPickerState.appliedStart) {
            requestUrl.searchParams.set(
                "date_from",
                formatDateForPeriod(periodPickerState.appliedStart)
            );
        }

        if (periodPickerState.appliedEnd) {
            requestUrl.searchParams.set(
                "date_to",
                formatDateForPeriod(periodPickerState.appliedEnd)
            );
        }

        return `${requestUrl.pathname}${requestUrl.search}`;
    }

    function initializeFilterApplyAction() {
        const applyButton = byId("dashboard-apply-filters");

        if (!applyButton) {
            return;
        }

        applyButton.addEventListener("click", function () {
            circleTooltip.hide();
            trendTooltip.hide();
            loadDashboard({
                transition: "filters"
            });
        });
    }

    async function loadDashboard(options = {}) {
        setLoadState(
            "Загрузка данных…"
        );

        try {
            const response = await fetch(
                buildDashboardRequestUrl(),
                {
                    method: "GET",

                    headers: {
                        "Accept": (
                            "application/json"
                        )
                    },

                    cache: "no-store"
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
                        "Не удалось получить "
                        + "данные дашборда."
                    )
                );
            }

            await renderDashboard(
                payload
                || {},
                {
                    transition: options.transition || (
                        dashboardExportPayload
                            ? "refresh"
                            : "initial"
                    )
                }
            );

            markCurrentFiltersAsConfirmed();

            setLoadState(
                "Данные загружены"
            );
        } catch (error) {
            setLoadState(
                error.message
                || "Ошибка загрузки",
                true
            );
        }
    }

    function getDashboardExportSnapshot() {
        const visibleTrend = getTrendVisibleData();

        return {
            payload: dashboardExportPayload || {},

            trend: visibleTrend
                ? {
                    months: visibleTrend.months.map(
                        (month) => ({ ...month })
                    ),
                    penalties: visibleTrend.penalties.slice(),
                    violations: visibleTrend.violations.slice(),
                    forecastStartIndex: visibleTrend.forecastStartIndex
                }
                : null,

            trendExpanded: Boolean(trendState.expanded),
            visibleTrendPoints: Number(trendState.visibleCount) || 0,

            colors: {
                sales: SALES_COLORS.slice(),
                violations: VIOLATION_COLORS.slice(),
                documents: DOCUMENT_COLORS.slice(),
                penalties: PENALTY_COLORS.slice()
            }
        };
    }

    window.dashboardExportBridge = {
        getSnapshot: getDashboardExportSnapshot
    };

    function initializeDashboard() {
        circleTooltip.ensure();
        trendTooltip.ensure();

        initializeMagnetEffect();
        initializeTrendInteractions();
        initializePeriodPicker();
        initializeFilterApplyAction();

        loadDashboard({
            transition: "initial"
        });
    }

    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initializeDashboard
        );
    } else {
        initializeDashboard();
    }
})();