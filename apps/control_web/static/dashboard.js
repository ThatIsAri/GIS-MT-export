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

    const ORBIT_VALUE_LAYOUTS = {
        "sales-chart": [
            { left: "-8%", top: "18%" },
            { left: "-10%", top: "86%" }
        ],

        "violations-chart": [
            { left: "-8%", top: "36%" },
            { left: "14%", top: "-4%" },
            { left: "48%", top: "-10%" },
            { left: "116%", top: "18%" },
            { left: "126%", top: "74%" },
            { left: "110%", top: "104%" },
            { left: "50%", top: "118%" },
            { left: "-12%", top: "94%" }
        ],

        "documents-chart": [
            { left: "-20%", top: "92%" },
            { left: "10%", top: "118%" },
            { left: "116%", top: "102%" }
        ],

        "penalties-chart": [
            { left: "120%", top: "44%" },
            { left: "80%", top: "112%" }
        ]
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

    const tooltipState = {
        element: null,
        hideTimer: null,
        anchor: null,
        side: "right"
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function numericValue(value) {
        const prepared = Number(value);

        return Number.isFinite(prepared)
            ? prepared
            : null;
    }

    function clamp(value, minimum, maximum) {
        return Math.min(
            maximum,
            Math.max(minimum, value)
        );
    }

    function lerp(current, target, factor) {
        return current + (target - current) * factor;
    }

    function smoothStep(value) {
        const prepared = clamp(value, 0, 1);

        return prepared * prepared * (3 - 2 * prepared);
    }

    function formatLegendValue(value) {
        const prepared = numericValue(value);

        if (prepared === null) {
            return "—";
        }

        return new Intl.NumberFormat("ru-RU", {
            maximumFractionDigits: 2
        }).format(prepared);
    }

    function normalizeLegendSegments(segments, colors) {
        return (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map((segment, index) => ({
                label: String(
                    segment?.label
                    || segment?.name
                    || segment?.title
                    || "Без названия"
                ),
                value: Math.max(
                    0,
                    numericValue(segment?.value) || 0
                ),
                color: colors[index % colors.length]
            }))
            .filter((segment) => segment.value > 0);
    }

    function ensureTooltip() {
        if (tooltipState.element) {
            return tooltipState.element;
        }

        const tooltip = document.createElement("div");

        tooltip.id = "dashboard-circle-tooltip";
        tooltip.className = "dashboard-circle-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.dataset.side = "right";
        tooltip.hidden = true;

        document.body.appendChild(tooltip);

        tooltipState.element = tooltip;

        return tooltip;
    }

    function fillTooltip(segments) {
        const tooltip = ensureTooltip();

        tooltip.replaceChildren();

        if (!segments.length) {
            const empty = document.createElement("div");

            empty.className = "dashboard-circle-tooltip__empty";
            empty.textContent = "Нет данных";

            tooltip.appendChild(empty);
            return;
        }

        const list = document.createElement("div");
        list.className = "dashboard-circle-tooltip__list";

        segments.forEach((segment) => {
            const row = document.createElement("div");
            const swatch = document.createElement("span");
            const label = document.createElement("span");
            const value = document.createElement("strong");

            row.className = "dashboard-circle-tooltip__row";
            swatch.className = "dashboard-circle-tooltip__swatch";
            label.className = "dashboard-circle-tooltip__label";
            value.className = "dashboard-circle-tooltip__value";

            swatch.style.backgroundColor = segment.color;
            label.textContent = segment.label;
            value.textContent = formatLegendValue(segment.value);

            row.append(swatch, label, value);
            list.appendChild(row);
        });

        tooltip.appendChild(list);
    }

    function positionTooltip(anchorElement) {
        const tooltip = ensureTooltip();

        if (tooltip.hidden || !anchorElement) {
            return;
        }

        const viewportPadding = 12;
        const anchorGap = 18;
        const anchorRect = anchorElement.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();

        const candidates = [
            {
                side: "right",
                left: anchorRect.right + anchorGap,
                top: (
                    anchorRect.top
                    + anchorRect.height / 2
                    - tooltipRect.height / 2
                )
            },
            {
                side: "left",
                left: (
                    anchorRect.left
                    - tooltipRect.width
                    - anchorGap
                ),
                top: (
                    anchorRect.top
                    + anchorRect.height / 2
                    - tooltipRect.height / 2
                )
            },
            {
                side: "bottom",
                left: (
                    anchorRect.left
                    + anchorRect.width / 2
                    - tooltipRect.width / 2
                ),
                top: anchorRect.bottom + anchorGap
            },
            {
                side: "top",
                left: (
                    anchorRect.left
                    + anchorRect.width / 2
                    - tooltipRect.width / 2
                ),
                top: (
                    anchorRect.top
                    - tooltipRect.height
                    - anchorGap
                )
            }
        ];

        const fitsViewport = (candidate) => (
            candidate.left >= viewportPadding
            && candidate.top >= viewportPadding
            && (
                candidate.left + tooltipRect.width
                <= window.innerWidth - viewportPadding
            )
            && (
                candidate.top + tooltipRect.height
                <= window.innerHeight - viewportPadding
            )
        );

        const selected = (
            candidates.find(fitsViewport)
            || candidates[0]
        );

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

        tooltip.dataset.side = selected.side;
        tooltipState.side = selected.side;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    }

    function showTooltip(segments, anchorElement) {
        const tooltip = ensureTooltip();

        if (tooltipState.hideTimer !== null) {
            window.clearTimeout(tooltipState.hideTimer);
            tooltipState.hideTimer = null;
        }

        tooltipState.anchor = anchorElement || null;

        fillTooltip(segments);

        tooltip.hidden = false;
        tooltip.classList.add(
            "dashboard-circle-tooltip--visible"
        );

        positionTooltip(tooltipState.anchor);
    }

    function hideTooltip() {
        const tooltip = tooltipState.element;

        tooltipState.anchor = null;

        if (!tooltip) {
            return;
        }

        tooltip.classList.remove(
            "dashboard-circle-tooltip--visible"
        );

        if (tooltipState.hideTimer !== null) {
            window.clearTimeout(tooltipState.hideTimer);
        }

        tooltipState.hideTimer = window.setTimeout(
            () => {
                tooltip.hidden = true;
                tooltipState.hideTimer = null;
            },
            90
        );
    }

    function registerCircleTooltip(pie, segments, colors) {
        if (!pie) {
            return;
        }

        const legendSegments = normalizeLegendSegments(
            segments,
            colors
        );

        pie.addEventListener(
            "pointerenter",
            () => {
                showTooltip(legendSegments, pie);
            }
        );

        pie.addEventListener(
            "pointermove",
            () => {
                positionTooltip(pie);
            },
            { passive: true }
        );

        pie.addEventListener("pointerleave", hideTooltip);
        pie.addEventListener("pointercancel", hideTooltip);
    }

    function buildPieGradient(segments, colors) {
        const prepared = (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map((segment, index) => ({
                value: Math.max(
                    0,
                    numericValue(segment?.value) || 0
                ),
                color: colors[index % colors.length]
            }))
            .filter((segment) => segment.value > 0);

        const total = prepared.reduce(
            (sum, segment) => sum + segment.value,
            0
        );

        if (total <= 0) {
            return null;
        }

        let cursor = 0;
        const parts = [];

        prepared.forEach((segment) => {
            const start = cursor;
            const finish = (
                cursor
                + segment.value / total * 100
            );

            parts.push(
                `${segment.color} ${start}% ${finish}%`
            );

            cursor = finish;
        });

        return `conic-gradient(${parts.join(", ")})`;
    }

    function createPieMarkup(gradient, sizeClass) {
        const classes = [
            "analytics-pie",
            sizeClass
        ];

        if (!gradient) {
            classes.push("analytics-pie--empty");
        }

        return `
            <div
                class="${classes.join(" ")}"
                ${gradient ? `style="background:${gradient}"` : ""}
            ></div>
        `;
    }

    function buildOrbitValuesMarkup(targetId, segments) {
        const layout = ORBIT_VALUE_LAYOUTS[targetId] || [];

        const preparedSegments = (
            Array.isArray(segments)
                ? segments
                : []
        )
            .map((segment, originalIndex) => ({
                originalIndex,
                value: Math.max(
                    0,
                    numericValue(segment?.value) || 0
                )
            }))
            .filter((segment) => segment.value > 0);

        return preparedSegments
            .map((segment, visibleIndex) => {
                const point = (
                    layout[segment.originalIndex]
                    || {
                        left: "110%",
                        top: `${20 + visibleIndex * 18}%`
                    }
                );

                return `
                    <span
                        class="dashboard-orbit-value"
                        style="
                            left:${point.left};
                            top:${point.top};
                        "
                        aria-hidden="true"
                    >
                        ${segment.value}
                    </span>
                `;
            })
            .join("");
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

        const gradient = buildPieGradient(
            segments,
            colors
        );

        target.innerHTML = (
            createPieMarkup(gradient, sizeClass)
            + buildOrbitValuesMarkup(targetId, segments)
        );

        registerCircleTooltip(
            target.querySelector(".analytics-pie"),
            segments,
            colors
        );
    }

    function normalizeSeries(values) {
        const numeric = values.map((value) => (
            Math.max(0, numericValue(value) || 0)
        ));

        const maximum = Math.max(1, ...numeric);

        return numeric.map((value) => (
            value / maximum * 100
        ));
    }

    function svgPath(indexes, pointResolver) {
        return indexes
            .map((index, position) => {
                const point = pointResolver(index);

                return (
                    (position === 0 ? "M" : "L")
                    + " "
                    + point.x
                    + " "
                    + point.y
                );
            })
            .join(" ");
    }

    function renderTrend(trend) {
        const target = byId("dashboard-trend-chart");

        if (!target) {
            return;
        }

        const months = Array.isArray(trend?.months)
            ? trend.months
            : [];

        const violations = Array.isArray(trend?.violations)
            ? trend.violations
            : [];

        const penalties = Array.isArray(trend?.penalties)
            ? trend.penalties
            : [];

        if (
            months.length < 3
            || violations.length !== months.length
            || penalties.length !== months.length
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

        const chartWidth = width - left - right;
        const chartHeight = height - top - bottom;

        const stepX = (
            chartWidth
            / Math.max(1, months.length - 1)
        );

        const normalizedViolations = normalizeSeries(
            violations
        );

        const normalizedPenalties = normalizeSeries(
            penalties
        );

        const pointResolverViolations = (index) => ({
            x: left + stepX * index,
            y: (
                top
                + chartHeight
                - normalizedViolations[index]
                / 100
                * chartHeight
            )
        });

        const pointResolverPenalties = (index) => ({
            x: left + stepX * index,
            y: (
                top
                + chartHeight
                - normalizedPenalties[index]
                / 100
                * chartHeight
            )
        });

        const forecastStart = Math.max(
            1,
            Number(trend?.forecast_start_index) || 3
        );

        const actualIndexes = Array.from(
            { length: forecastStart },
            (_, index) => index
        );

        const forecastIndexes = Array.from(
            {
                length: (
                    months.length
                    - forecastStart
                    + 1
                )
            },
            (_, index) => forecastStart - 1 + index
        );

        const axisY = top + chartHeight;

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
                    d="${svgPath(
                        actualIndexes,
                        pointResolverPenalties
                    )}"
                ></path>

                <path
                    class="trend-line trend-line--penalties trend-line--forecast"
                    d="${svgPath(
                        forecastIndexes,
                        pointResolverPenalties
                    )}"
                ></path>

                <path
                    class="trend-line trend-line--violations"
                    d="${svgPath(
                        actualIndexes,
                        pointResolverViolations
                    )}"
                ></path>

                <path
                    class="trend-line trend-line--violations trend-line--forecast"
                    d="${svgPath(
                        forecastIndexes,
                        pointResolverViolations
                    )}"
                ></path>
            </svg>
        `;
    }

    function updateStaticFilters(payload) {
        const period = byId("dashboard-period-value");
        const tradePoint = byId(
            "dashboard-trade-point-value"
        );
        const organization = byId(
            "dashboard-organization-value"
        );

        if (period) {
            period.textContent = (
                payload?.period?.label
                || "01.07.2026 — 04.08.2026"
            );
        }

        if (tradePoint) {
            tradePoint.textContent = (
                payload?.filters?.trade_point
                || "Все ТТ"
            );
        }

        if (organization) {
            organization.textContent = (
                payload?.filters?.organization
                || "Все организации"
            );
        }
    }

    function renderDashboard(payload) {
        updateStaticFilters(payload);

        renderCircle(
            "sales-chart",
            payload?.cards?.sales?.segments || [],
            SALES_COLORS,
            "analytics-pie--large"
        );

        renderCircle(
            "violations-chart",
            payload?.cards?.violations?.segments || [],
            VIOLATION_COLORS,
            "analytics-pie--medium"
        );

        renderCircle(
            "penalties-chart",
            payload?.cards?.penalties?.segments || [],
            PENALTY_COLORS,
            "analytics-pie--large"
        );

        renderCircle(
            "documents-chart",
            payload?.cards?.documents?.segments || [],
            DOCUMENT_COLORS,
            "analytics-pie--small"
        );

        renderTrend(payload?.trend || {});

        refreshMagnetElements();

        window.requestAnimationFrame(
            updateMagnetGeometry
        );
    }

    function setLoadState(message, error = false) {
        const element = byId("dashboard-load-state");

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
        reducedMotion: window.matchMedia(
            "(prefers-reduced-motion: reduce)"
        ).matches,
        coarsePointer: window.matchMedia(
            "(pointer: coarse)"
        ).matches
    };

    function createMagnetItem(shape) {
        return {
            shape,
            pie: shape.querySelector(".analytics-pie"),
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
            targetIntensity: 0
        };
    }

    function refreshMagnetElements() {
        magnetState.zone = document.querySelector(
            ".dashboard-circle-zone"
        );

        magnetState.items = Array.from(
            document.querySelectorAll(
                ".dashboard-circle-zone .dashboard-shape"
            )
        ).map(createMagnetItem);
    }

    function updateMagnetGeometry() {
        if (!magnetState.zone) {
            return;
        }

        magnetState.zoneRect = (
            magnetState.zone.getBoundingClientRect()
        );

        magnetState.items.forEach((item) => {
            const chart = item.shape.querySelector(
                ".dashboard-shape__chart"
            );

            item.pie = item.shape.querySelector(
                ".analytics-pie"
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
                chart?.offsetWidth || item.diameter
            );

            const chartHeight = Math.max(
                1,
                chart?.offsetHeight || item.diameter
            );

            item.orbitStates = Array.from(
                item.shape.querySelectorAll(
                    ".dashboard-orbit-value"
                )
            ).map((element) => ({
                element,
                baseCenterX: (
                    item.baseCenterX
                    + element.offsetLeft
                    - chartWidth / 2
                ),
                baseCenterY: (
                    item.baseCenterY
                    + element.offsetTop
                    - chartHeight / 2
                ),
                currentX: 0,
                currentY: 0,
                targetX: 0,
                targetY: 0
            }));
        });
    }

    function resetMagnetTargets(
        resetDirection = false
    ) {
        magnetState.items.forEach((item) => {
            item.targetX = 0;
            item.targetY = 0;
            item.targetTiltX = 0;
            item.targetTiltY = 0;
            item.targetScale = 1;
            item.targetIntensity = 0;

            item.orbitStates.forEach((state) => {
                state.targetX = 0;
                state.targetY = 0;
            });

            if (resetDirection) {
                item.lastDirectionX = 0;
                item.lastDirectionY = 0;
            }
        });
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

        magnetState.items.forEach((item) => {
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
                * MAGNET_SETTINGS.influenceMultiplier,
                MAGNET_SETTINGS.minimumInfluence,
                MAGNET_SETTINGS.maximumInfluence
            );

            if (distance >= influenceRadius) {
                item.targetX = 0;
                item.targetY = 0;
                item.targetTiltX = 0;
                item.targetTiltY = 0;
                item.targetScale = 1;
                item.targetIntensity = 0;
                return;
            }

            if (distance > MAGNET_SETTINGS.circleDeadZone) {
                item.lastDirectionX = deltaX / distance;
                item.lastDirectionY = deltaY / distance;
            }

            const proximity = (
                1 - distance / influenceRadius
            );

            const intensity = (
                distance <= MAGNET_SETTINGS.circleDeadZone
                    ? 1
                    : smoothStep(proximity)
            );

            const maximumMove = clamp(
                item.diameter
                * MAGNET_SETTINGS.maximumMoveRatio,
                MAGNET_SETTINGS.minimumMaximumMove,
                MAGNET_SETTINGS.maximumMaximumMove
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
                * MAGNET_SETTINGS.maximumTilt
                * intensity
            );

            item.targetTiltY = (
                item.lastDirectionX
                * MAGNET_SETTINGS.maximumTilt
                * intensity
            );

            item.targetScale = (
                1
                + (
                    MAGNET_SETTINGS.maximumScale - 1
                )
                * intensity
            );

            item.targetIntensity = intensity;
        });
    }

    function calculateOrbitValueShift(state, item) {
        if (
            !magnetState.pointerInside
            || magnetState.reducedMotion
            || magnetState.coarsePointer
        ) {
            return { x: 0, y: 0 };
        }

        const circleFollowX = (
            item.currentX
            * ORBIT_MAGNET_SETTINGS.circleFollowRatio
        );

        const circleFollowY = (
            item.currentY
            * ORBIT_MAGNET_SETTINGS.circleFollowRatio
        );

        const effectiveCenterX = (
            state.baseCenterX + circleFollowX
        );

        const effectiveCenterY = (
            state.baseCenterY + circleFollowY
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
            distance <= ORBIT_MAGNET_SETTINGS.deadZone
            || distance >= ORBIT_MAGNET_SETTINGS.influenceRadius
        ) {
            return { x: 0, y: 0 };
        }

        const activeDistance = (
            distance
            - ORBIT_MAGNET_SETTINGS.deadZone
        );

        const activeRadius = (
            ORBIT_MAGNET_SETTINGS.influenceRadius
            - ORBIT_MAGNET_SETTINGS.deadZone
        );

        const proximity = (
            1 - activeDistance / activeRadius
        );

        const intensity = smoothStep(proximity);

        return {
            x: (
                deltaX / distance
                * ORBIT_MAGNET_SETTINGS.maximumShift
                * intensity
            ),
            y: (
                deltaY / distance
                * ORBIT_MAGNET_SETTINGS.maximumShift
                * intensity
            )
        };
    }

    function applyMagnetStyles(item) {
        item.shape.style.setProperty(
            "--magnet-x",
            `${item.currentX.toFixed(3)}px`
        );

        item.shape.style.setProperty(
            "--magnet-y",
            `${item.currentY.toFixed(3)}px`
        );

        item.orbitStates.forEach((state) => {
            const target = calculateOrbitValueShift(
                state,
                item
            );

            state.targetX = target.x;
            state.targetY = target.y;

            state.currentX = lerp(
                state.currentX,
                state.targetX,
                ORBIT_MAGNET_SETTINGS.movementEase
            );

            state.currentY = lerp(
                state.currentY,
                state.targetY,
                ORBIT_MAGNET_SETTINGS.movementEase
            );

            const totalX = (
                item.currentX
                * ORBIT_MAGNET_SETTINGS.circleFollowRatio
                + state.currentX
            );

            const totalY = (
                item.currentY
                * ORBIT_MAGNET_SETTINGS.circleFollowRatio
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
        });

        if (!item.pie) {
            return;
        }

        item.pie.style.setProperty(
            "--tilt-x",
            `${item.currentTiltX.toFixed(3)}deg`
        );

        item.pie.style.setProperty(
            "--tilt-y",
            `${item.currentTiltY.toFixed(3)}deg`
        );

        item.pie.style.setProperty(
            "--magnet-scale",
            item.currentScale.toFixed(4)
        );

        item.pie.style.setProperty(
            "--shadow-x",
            `${(-item.currentX * 0.2).toFixed(2)}px`
        );

        item.pie.style.setProperty(
            "--shadow-y",
            `${(8 - item.currentY * 0.1).toFixed(2)}px`
        );

        item.pie.style.setProperty(
            "--shadow-blur",
            `${
                (
                    14
                    + item.currentIntensity * 9
                ).toFixed(2)
            }px`
        );

        item.pie.style.setProperty(
            "--shadow-opacity",
            (
                0.07
                + item.currentIntensity * 0.06
            ).toFixed(3)
        );
    }

    function animateMagnet() {
        calculateMagnetTargets();

        let hasMovement = false;

        magnetState.items.forEach((item) => {
            item.currentX = lerp(
                item.currentX,
                item.targetX,
                MAGNET_SETTINGS.movementEase
            );

            item.currentY = lerp(
                item.currentY,
                item.targetY,
                MAGNET_SETTINGS.movementEase
            );

            item.currentTiltX = lerp(
                item.currentTiltX,
                item.targetTiltX,
                MAGNET_SETTINGS.rotationEase
            );

            item.currentTiltY = lerp(
                item.currentTiltY,
                item.targetTiltY,
                MAGNET_SETTINGS.rotationEase
            );

            item.currentScale = lerp(
                item.currentScale,
                item.targetScale,
                MAGNET_SETTINGS.scaleEase
            );

            item.currentIntensity = lerp(
                item.currentIntensity,
                item.targetIntensity,
                MAGNET_SETTINGS.scaleEase
            );

            applyMagnetStyles(item);

            const orbitDifference = (
                item.orbitStates.reduce(
                    (sum, state) => (
                        sum
                        + Math.abs(
                            state.currentX - state.targetX
                        )
                        + Math.abs(
                            state.currentY - state.targetY
                        )
                    ),
                    0
                )
            );

            const difference = (
                Math.abs(item.currentX - item.targetX)
                + Math.abs(item.currentY - item.targetY)
                + Math.abs(
                    item.currentTiltX - item.targetTiltX
                )
                + Math.abs(
                    item.currentTiltY - item.targetTiltY
                )
                + Math.abs(
                    item.currentScale - item.targetScale
                )
                + orbitDifference
            );

            if (difference > MAGNET_SETTINGS.restThreshold) {
                hasMovement = true;
            }
        });

        if (magnetState.pointerInside || hasMovement) {
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
        if (magnetState.animationFrame !== null) {
            return;
        }

        magnetState.animationFrame = (
            window.requestAnimationFrame(
                animateMagnet
            )
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

        if (tooltipState.anchor) {
            positionTooltip(tooltipState.anchor);
        }

        ensureMagnetAnimation();
    }

    function handlePointerLeave() {
        magnetState.pointerInside = false;

        hideTooltip();
        resetMagnetTargets(true);
        ensureMagnetAnimation();
    }

    function handleResize() {
        hideTooltip();
        handlePointerLeave();

        window.requestAnimationFrame(() => {
            refreshMagnetElements();
            updateMagnetGeometry();
        });
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
            { passive: true }
        );

        magnetState.zone.addEventListener(
            "pointerleave",
            handlePointerLeave,
            { passive: true }
        );

        window.addEventListener(
            "blur",
            handlePointerLeave
        );

        window.addEventListener(
            "resize",
            handleResize,
            { passive: true }
        );
    }

    async function loadDashboard() {
        setLoadState("Загрузка данных…");

        try {
            const response = await fetch(API_URL, {
                method: "GET",
                headers: {
                    "Accept": "application/json"
                },
                cache: "no-store"
            });

            let payload = null;

            try {
                payload = await response.json();
            } catch {
                payload = null;
            }

            if (!response.ok) {
                throw new Error(
                    payload?.error
                    || "Не удалось получить данные дашборда."
                );
            }

            renderDashboard(payload || {});
            setLoadState("Данные загружены");
        } catch (error) {
            setLoadState(
                error.message || "Ошибка загрузки",
                true
            );
        }
    }

    function initializeDashboard() {
        ensureTooltip();
        initializeMagnetEffect();
        loadDashboard();
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeDashboard
        );
    } else {
        initializeDashboard();
    }
})();