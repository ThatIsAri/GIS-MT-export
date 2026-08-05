(function () {
    "use strict";

    const API_URL = (
        "/api/analytics-dashboard"
    );

    const VIOLATION_COLORS = [
        "#1f5fd6",
        "#3f79de",
        "#6694e4",
        "#7faae8",
        "#a0c1ef",
        "#274f86",
        "#5c85c9",
        "#8aa7d5"
    ];

    const DOCUMENT_COLORS = [
        "#1d8b57",
        "#4aa06f",
        "#7abd8d"
    ];

    const PENALTY_COLORS = [
        "#f0d200",
        "#efd768"
    ];

    const SALES_COLORS = [
        "#e12626",
        "#f1a9a9"
    ];

    const MAGNET_SETTINGS = {
        influenceMultiplier: 1.7,

        minimumInfluence: 180,
        maximumInfluence: 330,

        deadZone: 14,

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


    function byId(id) {
        return document.getElementById(
            id
        );
    }


    function numericValue(value) {
        const prepared = Number(
            value
        );

        return Number.isFinite(
            prepared
        )
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


    function buildPieGradient(
        segments,
        colors
    ) {
        const prepared = (
            Array.isArray(
                segments
            )
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
                        )
                        || 0
                    ),

                    color: colors[
                        index
                        % colors.length
                    ]
                })
            )
            .filter(
                (segment) => (
                    segment.value
                    > 0
                )
            );

        const total = (
            prepared.reduce(
                (
                    sum,
                    segment
                ) => (
                    sum
                    + segment.value
                ),
                0
            )
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


    function renderCircle(
        targetId,
        segments,
        colors,
        sizeClass
    ) {
        const target = byId(
            targetId
        );

        if (!target) {
            return;
        }

        const gradient = (
            buildPieGradient(
                segments,
                colors
            )
        );

        target.innerHTML = (
            createPieMarkup(
                gradient,
                sizeClass
            )
        );
    }


    function normalizeSeries(
        values
    ) {
        const numeric = values.map(
            (value) => (
                Math.max(
                    0,
                    numericValue(
                        value
                    )
                    || 0
                )
            )
        );

        const maximum = Math.max(
            1,
            ...numeric
        );

        return numeric.map(
            (value) => (
                value
                / maximum
                * 100
            )
        );
    }


    function svgPath(
        indexes,
        pointResolver
    ) {
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


    function renderTrend(
        trend
    ) {
        const target = byId(
            "dashboard-trend-chart"
        );

        if (!target) {
            return;
        }

        const months = (
            Array.isArray(
                trend?.months
            )
                ? trend.months
                : []
        );

        const violations = (
            Array.isArray(
                trend?.violations
            )
                ? trend.violations
                : []
        );

        const penalties = (
            Array.isArray(
                trend?.penalties
            )
                ? trend.penalties
                : []
        );

        if (
            months.length < 3
            || violations.length
                !== months.length
            || penalties.length
                !== months.length
        ) {
            target.innerHTML = `
                <div class="dashboard-chart-placeholder">
                    Данных для тренда недостаточно.
                </div>
            `;

            return;
        }

        const width = 780;
        const height = 260;

        const left = 34;
        const right = 14;
        const top = 18;
        const bottom = 18;

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

        const stepX = (
            chartWidth
            / Math.max(
                1,
                months.length - 1
            )
        );

        const normalizedViolations = (
            normalizeSeries(
                violations
            )
        );

        const normalizedPenalties = (
            normalizeSeries(
                penalties
            )
        );

        const pointResolverViolations = (
            index
        ) => ({
            x: (
                left
                + stepX
                * index
            ),

            y: (
                top
                + chartHeight
                - (
                    normalizedViolations[
                        index
                    ]
                    / 100
                )
                * chartHeight
            )
        });

        const pointResolverPenalties = (
            index
        ) => ({
            x: (
                left
                + stepX
                * index
            ),

            y: (
                top
                + chartHeight
                - (
                    normalizedPenalties[
                        index
                    ]
                    / 100
                )
                * chartHeight
            )
        });

        const forecastStart = Math.max(
            1,
            Number(
                trend
                    ?.forecast_start_index
            )
            || 3
        );

        const actualIndexes = (
            Array.from(
                {
                    length: forecastStart
                },
                (
                    _,
                    index
                ) => index
            )
        );

        const forecastIndexes = (
            Array.from(
                {
                    length: (
                        months.length
                        - forecastStart
                        + 1
                    )
                },
                (
                    _,
                    index
                ) => (
                    forecastStart
                    - 1
                    + index
                )
            )
        );

        const axisY = (
            top
            + chartHeight
        );

        target.innerHTML = `
            <svg
                viewBox="0 0 ${width} ${height}"
                role="img"
                aria-label="Тренды"
                preserveAspectRatio="none"
            >
                <line
                    class="trend-axis-line"
                    x1="${left}"
                    y1="${top}"
                    x2="${left}"
                    y2="${axisY}"
                ></line>

                <line
                    class="trend-axis-line"
                    x1="${left}"
                    y1="${axisY}"
                    x2="${width - right}"
                    y2="${axisY}"
                ></line>

                <path
                    class="trend-line trend-line--penalties"
                    d="${svgPath(actualIndexes, pointResolverPenalties)}"
                ></path>

                <path
                    class="trend-line trend-line--penalties trend-line--forecast"
                    d="${svgPath(forecastIndexes, pointResolverPenalties)}"
                ></path>

                <path
                    class="trend-line trend-line--violations"
                    d="${svgPath(actualIndexes, pointResolverViolations)}"
                ></path>

                <path
                    class="trend-line trend-line--violations trend-line--forecast"
                    d="${svgPath(forecastIndexes, pointResolverViolations)}"
                ></path>
            </svg>
        `;
    }


    function updateStaticFilters(
        payload
    ) {
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
            period.textContent = (
                payload?.period?.label

                || (
                    "01.07.2026 "
                    + "— "
                    + "04.08.2026"
                )
            );
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


    function renderDashboard(
        payload
    ) {
        updateStaticFilters(
            payload
        );

        renderCircle(
            "sales-chart",
            payload
                ?.cards
                ?.sales
                ?.segments
                || [],
            SALES_COLORS,
            "analytics-pie--large"
        );

        renderCircle(
            "violations-chart",
            payload
                ?.cards
                ?.violations
                ?.segments
                || [],
            VIOLATION_COLORS,
            "analytics-pie--medium"
        );

        renderCircle(
            "penalties-chart",
            payload
                ?.cards
                ?.penalties
                ?.segments
                || [],
            PENALTY_COLORS,
            "analytics-pie--large"
        );

        renderCircle(
            "documents-chart",
            payload
                ?.cards
                ?.documents
                ?.segments
                || [],
            DOCUMENT_COLORS,
            "analytics-pie--small"
        );

        renderTrend(
            payload?.trend
            || {}
        );

        refreshMagnetElements();
        updateMagnetGeometry();
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


    const magnetState = {
        zone: null,
        zoneRect: null,

        items: [],

        pointerX: 0,
        pointerY: 0,

        pointerInside: false,

        animationFrame: null,

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


    function createMagnetItem(
        shape
    ) {
        return {
            shape,

            pie: (
                shape.querySelector(
                    ".analytics-pie"
                )
            ),

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
            targetIntensity: 0
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


    /*
     * Центр каждого круга вычисляется по его
     * неподвижной CSS-позиции, а не через
     * getBoundingClientRect движущегося элемента.
     *
     * Это устраняет обратную связь и дрожание.
     */

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
                item.pie = (
                    item.shape.querySelector(
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
                const deltaX = (
                    magnetState.pointerX
                    - item.baseCenterX
                );

                const deltaY = (
                    magnetState.pointerY
                    - item.baseCenterY
                );

                const distance = Math.hypot(
                    deltaX,
                    deltaY
                );

                const influenceRadius = clamp(
                    item.diameter
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

                /*
                 * В центральной мёртвой зоне
                 * направление фиксируется.
                 *
                 * Поэтому при минимальных движениях
                 * курсора вокруг центра направление
                 * не начинает переключаться туда-сюда.
                 */

                if (
                    distance
                    > MAGNET_SETTINGS.deadZone
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
                    <= MAGNET_SETTINGS.deadZone
                        ? 1
                        : smoothStep(
                            proximity
                        )
                );

                const maximumMove = clamp(
                    item.diameter
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


    function applyMagnetStyles(
        item
    ) {
        item.shape.style.setProperty(
            "--magnet-x",
            item.currentX.toFixed(3)
            + "px"
        );

        item.shape.style.setProperty(
            "--magnet-y",
            item.currentY.toFixed(3)
            + "px"
        );

        if (!item.pie) {
            return;
        }

        item.pie.style.setProperty(
            "--tilt-x",
            item.currentTiltX.toFixed(3)
            + "deg"
        );

        item.pie.style.setProperty(
            "--tilt-y",
            item.currentTiltY.toFixed(3)
            + "deg"
        );

        item.pie.style.setProperty(
            "--magnet-scale",
            item.currentScale.toFixed(4)
        );

        item.pie.style.setProperty(
            "--shadow-x",
            (
                -item.currentX
                * 0.2
            ).toFixed(2)
            + "px"
        );

        item.pie.style.setProperty(
            "--shadow-y",
            (
                8
                - item.currentY
                * 0.1
            ).toFixed(2)
            + "px"
        );

        item.pie.style.setProperty(
            "--shadow-blur",
            (
                14
                + item.currentIntensity
                * 9
            ).toFixed(2)
            + "px"
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


    function animateMagnet() {
        calculateMagnetTargets();

        let hasMovement = false;

        magnetState.items.forEach(
            (item) => {
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

                applyMagnetStyles(
                    item
                );

                const difference = (
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
                );

                if (
                    difference
                    > MAGNET_SETTINGS
                        .restThreshold
                ) {
                    hasMovement = true;
                }
            }
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
        }
    }


    function ensureMagnetAnimation() {
        if (
            magnetState.animationFrame
            !== null
        ) {
            return;
        }

        magnetState.animationFrame = (
            window.requestAnimationFrame(
                animateMagnet
            )
        );
    }


    function handlePointerMove(
        event
    ) {
        if (
            magnetState.reducedMotion
            || magnetState.coarsePointer
        ) {
            return;
        }

        magnetState.pointerX = event.clientX;
        magnetState.pointerY = event.clientY;

        magnetState.pointerInside = true;

        ensureMagnetAnimation();
    }


    function handlePointerLeave() {
        magnetState.pointerInside = false;

        resetMagnetTargets(
            true
        );

        ensureMagnetAnimation();
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
            () => {
                handlePointerLeave();

                window.requestAnimationFrame(
                    () => {
                        refreshMagnetElements();
                        updateMagnetGeometry();
                    }
                );
            },
            {
                passive: true
            }
        );
    }


    async function loadDashboard() {
        setLoadState(
            "Загрузка данных…"
        );

        try {
            const response = await fetch(
                API_URL,
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

            renderDashboard(
                payload
                || {}
            );

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


    function initializeDashboard() {
        initializeMagnetEffect();

        loadDashboard();
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