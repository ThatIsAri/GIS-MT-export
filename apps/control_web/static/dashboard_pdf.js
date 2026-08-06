(function () {
    "use strict";

    const PAGE_WIDTH = 2480;
    const PAGE_HEIGHT = 1754;

    const PDF_PAGE_WIDTH = 842;
    const PDF_PAGE_HEIGHT = 595;

    const CARD_CONFIGS = [
        {
            key: "sales",
            containerId: "sales-chart",
            title: "Продажи"
        },
        {
            key: "violations",
            containerId: "violations-chart",
            title: "Отклонения"
        },
        {
            key: "penalties",
            containerId: "penalties-chart",
            title: "Штрафы"
        },
        {
            key: "documents",
            containerId: "documents-chart",
            title: "Документы"
        }
    ];

    const FALLBACK_COLORS = {
        sales: [
            "#3DB2D9",
            "#8DD5E8"
        ],

        violations: [
            "#A45CC5",
            "#B16DD0",
            "#BD7FDB",
            "#C991E4",
            "#D7ADEB",
            "#8E49B1",
            "#7C3D9E",
            "#E3C5F2"
        ],

        documents: [
            "#F2D23C",
            "#F6DF70",
            "#FAEBA2"
        ],

        penalties: [
            "#FF3D46",
            "#FF7A81"
        ]
    };

    const COLORS = {
        text: "#182431",
        muted: "#6C7886",
        border: "#D7DEE5",
        grid: "#E6EBF0",
        axis: "#9DA7B1",
        white: "#FFFFFF",
        tableBorder: "#1D2833"
    };

    const state = {
        busy: false,
        lastFocusedElement: null
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function clamp(value, minimum, maximum) {
        return Math.min(
            maximum,
            Math.max(minimum, value)
        );
    }

    function numericValue(value) {
        const prepared = Number(value);

        return Number.isFinite(prepared)
            ? prepared
            : 0;
    }

    function formatNumber(value, maximumFractionDigits = 2) {
        return new Intl.NumberFormat(
            "ru-RU",
            {
                maximumFractionDigits
            }
        ).format(numericValue(value));
    }

    function formatThousands(value) {
        const prepared = numericValue(value) / 1000;

        return new Intl.NumberFormat(
            "ru-RU",
            {
                maximumFractionDigits: prepared >= 100
                    ? 0
                    : 1
            }
        ).format(prepared);
    }

    function getDashboardTitle() {
        const title = byId("dashboard-current-title")
            ?.textContent
            ?.trim();

        return title || "Дашборд";
    }

    function sanitizeFileName(value) {
        const cleaned = String(value || "")
            .replace(/[\\/:*?"<>|]+/g, " ")
            .replace(/\s+/g, " ")
            .trim()
            .replace(/[. ]+$/g, "");

        return cleaned || "Дашборд";
    }

    function getPdfFileName() {
        const input = byId("dashboard-pdf-filename");
        const baseName = sanitizeFileName(
            input?.value || getDashboardTitle()
        );

        return baseName.toLowerCase().endsWith(".pdf")
            ? baseName
            : `${baseName}.pdf`;
    }

    function openModal() {
        const modal = byId("dashboard-pdf-modal");
        const input = byId("dashboard-pdf-filename");
        const status = byId("dashboard-pdf-status");

        if (!modal || !input) {
            return;
        }

        state.lastFocusedElement = document.activeElement;

        input.value = getDashboardTitle();

        if (status) {
            status.textContent = "";
        }

        modal.hidden = false;
        document.body.classList.add(
            "dashboard-pdf-modal-open"
        );

        window.requestAnimationFrame(
            () => {
                input.focus();
                input.select();
            }
        );
    }

    function closeModal() {
        if (state.busy) {
            return;
        }

        const modal = byId("dashboard-pdf-modal");

        if (!modal) {
            return;
        }

        modal.hidden = true;
        document.body.classList.remove(
            "dashboard-pdf-modal-open"
        );

        if (
            state.lastFocusedElement
            && typeof state.lastFocusedElement.focus === "function"
        ) {
            state.lastFocusedElement.focus();
        }
    }

    function setBusy(busy, message = "") {
        state.busy = busy;

        const dialog = document.querySelector(
            ".dashboard-pdf-dialog"
        );

        const confirm = byId("dashboard-pdf-confirm");
        const cancel = byId("dashboard-pdf-cancel");
        const input = byId("dashboard-pdf-filename");
        const status = byId("dashboard-pdf-status");

        dialog?.classList.toggle(
            "dashboard-pdf-dialog--busy",
            busy
        );

        if (confirm) {
            confirm.disabled = busy;
            confirm.textContent = busy
                ? "Формирование"
                : "Скачать";
        }

        if (cancel) {
            cancel.disabled = busy;
        }

        if (input) {
            input.disabled = busy;
        }

        if (status) {
            status.textContent = message;
        }
    }

    function isVisible(element) {
        if (!element) {
            return false;
        }

        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();

        return (
            style.display !== "none"
            && style.visibility !== "hidden"
            && Number(style.opacity || 1) > 0
            && rect.width > 0
            && rect.height > 0
        );
    }

    function getExportSnapshot() {
        const bridge = window.dashboardExportBridge;

        if (
            bridge
            && typeof bridge.getSnapshot === "function"
        ) {
            return bridge.getSnapshot();
        }

        return {
            payload: {},
            trend: null,
            colors: FALLBACK_COLORS
        };
    }

    function getVisibleCards(snapshot) {
        return CARD_CONFIGS
            .filter(
                (config) => {
                    const container = byId(config.containerId);
                    const shape = container?.closest(
                        ".dashboard-shape"
                    );

                    return isVisible(shape || container);
                }
            )
            .map(
                (config) => {
                    const card = snapshot
                        ?.payload
                        ?.cards
                        ?.[config.key]
                        || {};

                    const segments = Array.isArray(card.segments)
                        ? card.segments
                        : [];

                    const colors = snapshot
                        ?.colors
                        ?.[config.key]
                        || FALLBACK_COLORS[config.key]
                        || ["#D9E0E6"];

                    return {
                        ...config,
                        title: String(
                            card.title
                            || config.title
                        ),
                        segments: segments.map(
                            (segment, index) => ({
                                label: String(
                                    segment?.label
                                    || segment?.name
                                    || segment?.title
                                    || "Без названия"
                                ),
                                value: Math.max(
                                    0,
                                    numericValue(segment?.value)
                                ),
                                color: colors[
                                    index % colors.length
                                ]
                            })
                        )
                    };
                }
            );
    }

    function setFont(
        context,
        size,
        weight = 500
    ) {
        context.font = (
            `${weight} ${size}px `
            + 'Inter, "Segoe UI", Arial, sans-serif'
        );
    }

    function fitText(
        context,
        text,
        maximumWidth
    ) {
        const prepared = String(text || "");

        if (
            context.measureText(prepared).width
            <= maximumWidth
        ) {
            return prepared;
        }

        let result = prepared;

        while (
            result.length > 1
            && context.measureText(
                `${result}…`
            ).width > maximumWidth
        ) {
            result = result.slice(0, -1);
        }

        return `${result}…`;
    }

    function drawCenteredTitle(
        context,
        title
    ) {
        context.save();

        setFont(context, 52, 760);
        context.fillStyle = COLORS.text;
        context.textAlign = "center";
        context.textBaseline = "middle";

        context.fillText(
            fitText(
                context,
                title,
                1300
            ),
            PAGE_WIDTH / 2,
            82
        );

        context.restore();
    }

    function drawDate(context) {
        const date = new Intl.DateTimeFormat(
            "ru-RU",
            {
                day: "2-digit",
                month: "2-digit",
                year: "numeric"
            }
        ).format(new Date());

        context.save();

        setFont(context, 25, 650);
        context.fillStyle = COLORS.muted;
        context.textAlign = "left";
        context.textBaseline = "middle";

        context.fillText(
            date,
            72,
            82
        );

        context.restore();
    }

    function drawPie(
        context,
        card,
        centerX,
        centerY,
        radius
    ) {
        const nonZeroSegments = card.segments.filter(
            (segment) => segment.value > 0
        );

        const total = nonZeroSegments.reduce(
            (sum, segment) => sum + segment.value,
            0
        );

        context.save();

        context.shadowColor = "rgba(31, 49, 68, 0.10)";
        context.shadowBlur = 30;
        context.shadowOffsetY = 14;

        if (total <= 0) {
            context.beginPath();
            context.arc(
                centerX,
                centerY,
                radius,
                0,
                Math.PI * 2
            );
            context.fillStyle = "#E9EEF2";
            context.fill();
            context.restore();
            return;
        }

        let startAngle = -Math.PI / 2;

        nonZeroSegments.forEach(
            (segment) => {
                const angle = (
                    segment.value / total
                ) * Math.PI * 2;

                context.beginPath();
                context.moveTo(centerX, centerY);
                context.arc(
                    centerX,
                    centerY,
                    radius,
                    startAngle,
                    startAngle + angle
                );
                context.closePath();
                context.fillStyle = segment.color;
                context.fill();

                startAngle += angle;
            }
        );

        context.restore();
    }

    function drawCardLegend(
        context,
        card,
        x,
        y,
        width,
        maximumLines
    ) {
        const segments = card.segments.filter(
            (segment) => segment.value > 0
        );

        const preparedSegments = segments.length
            ? segments
            : [
                {
                    label: "Нет данных",
                    value: 0,
                    color: "#D9E0E6"
                }
            ];

        const fontSize = preparedSegments.length > 5
            ? 18
            : 21;

        const lineHeight = fontSize + 13;
        const rows = preparedSegments.slice(
            0,
            maximumLines
        );

        rows.forEach(
            (segment, index) => {
                const lineY = y + index * lineHeight;

                context.beginPath();
                context.arc(
                    x + 10,
                    lineY,
                    8,
                    0,
                    Math.PI * 2
                );
                context.fillStyle = segment.color;
                context.fill();

                setFont(context, fontSize, 560);
                context.fillStyle = COLORS.muted;
                context.textAlign = "left";
                context.textBaseline = "middle";

                const valueText = formatNumber(
                    segment.value,
                    2
                );

                setFont(context, fontSize, 730);
                const valueWidth = context.measureText(
                    valueText
                ).width;

                context.fillStyle = COLORS.text;
                context.textAlign = "right";
                context.fillText(
                    valueText,
                    x + width,
                    lineY
                );

                setFont(context, fontSize, 560);
                context.fillStyle = COLORS.muted;
                context.textAlign = "left";

                const labelWidth = Math.max(
                    80,
                    width - valueWidth - 55
                );

                context.fillText(
                    fitText(
                        context,
                        segment.label,
                        labelWidth
                    ),
                    x + 30,
                    lineY
                );
            }
        );

        if (preparedSegments.length > maximumLines) {
            setFont(context, 17, 650);
            context.fillStyle = COLORS.muted;
            context.textAlign = "left";
            context.fillText(
                `Ещё: ${preparedSegments.length - maximumLines}`,
                x + 30,
                y + maximumLines * lineHeight
            );
        }
    }

    function drawCircleGrid(
        context,
        cards
    ) {
        if (!cards.length) {
            return;
        }

        const area = {
            x: 36,
            y: 155,
            width: 1290,
            height: 1530
        };

        const columns = cards.length === 1
            ? 1
            : Math.ceil(Math.sqrt(cards.length));

        const rows = Math.ceil(
            cards.length / columns
        );

        const cellWidth = area.width / columns;
        const cellHeight = area.height / rows;

        cards.forEach(
            (card, index) => {
                const column = index % columns;
                const row = Math.floor(index / columns);

                const cellX = area.x + column * cellWidth;
                const cellY = area.y + row * cellHeight;

                const radius = clamp(
                    Math.min(
                        cellWidth * 0.195,
                        cellHeight * 0.175
                    ),
                    82,
                    132
                );

                const centerX = cellX + cellWidth / 2;
                const centerY = cellY + radius + 82;

                context.save();

                setFont(context, 31, 750);
                context.fillStyle = COLORS.text;
                context.textAlign = "center";
                context.textBaseline = "middle";

                context.fillText(
                    fitText(
                        context,
                        card.title,
                        cellWidth - 50
                    ),
                    centerX,
                    cellY + 28
                );

                drawPie(
                    context,
                    card,
                    centerX,
                    centerY,
                    radius
                );

                drawCardLegend(
                    context,
                    card,
                    cellX + 50,
                    centerY + radius + 42,
                    cellWidth - 100,
                    rows > 2 ? 4 : 6
                );

                context.restore();
            }
        );
    }

    function readTableData() {
        const table = document.querySelector(
            ".dashboard-programmable-table"
        );

        if (!table) {
            return Array.from(
                { length: 5 },
                () => Array(4).fill("")
            );
        }

        const rows = Array.from(
            table.querySelectorAll("tr")
        );

        return rows.map(
            (row) => Array.from(
                row.querySelectorAll("th, td")
            ).map(
                (cell) => cell.textContent.trim()
            )
        );
    }

    function drawTable(context) {
        const x = 1390;
        const y = 175;
        const width = 1020;
        const height = 500;

        context.save();

        setFont(context, 29, 750);
        context.fillStyle = COLORS.text;
        context.textAlign = "left";
        context.textBaseline = "middle";
        context.fillText(
            "Таблица",
            x,
            y - 38
        );

        const rows = readTableData();
        const rowCount = Math.max(1, rows.length);
        const columnCount = Math.max(
            1,
            ...rows.map((row) => row.length)
        );

        const rowHeight = height / rowCount;
        const columnWidth = width / columnCount;

        context.strokeStyle = COLORS.tableBorder;
        context.lineWidth = 2;

        for (
            let rowIndex = 0;
            rowIndex <= rowCount;
            rowIndex += 1
        ) {
            const lineY = y + rowIndex * rowHeight;

            context.beginPath();
            context.moveTo(x, lineY);
            context.lineTo(x + width, lineY);
            context.stroke();
        }

        for (
            let columnIndex = 0;
            columnIndex <= columnCount;
            columnIndex += 1
        ) {
            const lineX = x + columnIndex * columnWidth;

            context.beginPath();
            context.moveTo(lineX, y);
            context.lineTo(lineX, y + height);
            context.stroke();
        }

        setFont(context, 18, 550);
        context.fillStyle = COLORS.text;
        context.textAlign = "center";
        context.textBaseline = "middle";

        rows.forEach(
            (row, rowIndex) => {
                row.forEach(
                    (value, columnIndex) => {
                        if (!value) {
                            return;
                        }

                        context.fillText(
                            fitText(
                                context,
                                value,
                                columnWidth - 18
                            ),
                            x + columnWidth * (
                                columnIndex + 0.5
                            ),
                            y + rowHeight * (
                                rowIndex + 0.5
                            )
                        );
                    }
                );
            }
        );

        context.restore();
    }

    function getNiceMaximum(value) {
        const maximum = Math.max(
            1,
            numericValue(value)
        );

        const exponent = Math.floor(
            Math.log10(maximum)
        );

        const magnitude = Math.pow(10, exponent);
        const fraction = maximum / magnitude;

        let niceFraction;

        if (fraction <= 1) {
            niceFraction = 1;
        } else if (fraction <= 2) {
            niceFraction = 2;
        } else if (fraction <= 5) {
            niceFraction = 5;
        } else {
            niceFraction = 10;
        }

        return niceFraction * magnitude;
    }

    function getMonthLabel(month, index) {
        if (
            month
            && typeof month === "object"
        ) {
            return String(
                month.axisLabel
                || month.label
                || month.name
                || month.key
                || index + 1
            );
        }

        return String(month ?? index + 1);
    }

    function drawTrendArea(
        context,
        points,
        baseY,
        color,
        topOpacity
    ) {
        if (points.length < 2) {
            return;
        }

        const minimumY = Math.min(
            ...points.map((point) => point.y)
        );

        const gradient = context.createLinearGradient(
            0,
            minimumY,
            0,
            baseY
        );

        gradient.addColorStop(
            0,
            color.replace("#", "#")
        );

        gradient.addColorStop(
            1,
            "rgba(255, 255, 255, 0)"
        );

        context.save();
        context.globalAlpha = topOpacity;

        context.beginPath();
        context.moveTo(points[0].x, baseY);
        context.lineTo(points[0].x, points[0].y);

        points.slice(1).forEach(
            (point) => context.lineTo(
                point.x,
                point.y
            )
        );

        context.lineTo(
            points[points.length - 1].x,
            baseY
        );
        context.closePath();
        context.fillStyle = gradient;
        context.fill();

        context.restore();
    }

    function drawPolyline(
        context,
        points,
        color,
        dashed = false
    ) {
        if (points.length < 2) {
            return;
        }

        context.save();

        context.strokeStyle = color;
        context.lineWidth = 5;
        context.lineCap = "round";
        context.lineJoin = "round";
        context.setLineDash(
            dashed
                ? [16, 12]
                : []
        );

        context.beginPath();
        context.moveTo(
            points[0].x,
            points[0].y
        );

        points.slice(1).forEach(
            (point) => context.lineTo(
                point.x,
                point.y
            )
        );

        context.stroke();
        context.restore();
    }

    function drawTrend(
        context,
        trend,
        colors
    ) {
        const x = 1390;
        const y = 795;
        const width = 1020;
        const height = 855;

        context.save();

        setFont(context, 29, 750);
        context.fillStyle = COLORS.text;
        context.textAlign = "left";
        context.textBaseline = "middle";
        context.fillText(
            "Тренды",
            x,
            y - 38
        );

        if (
            !trend
            || !Array.isArray(trend.months)
            || trend.months.length < 2
        ) {
            setFont(context, 21, 560);
            context.fillStyle = COLORS.muted;
            context.fillText(
                "Недостаточно данных",
                x,
                y + 40
            );
            context.restore();
            return;
        }

        const months = trend.months;
        const penalties = trend.penalties.map(numericValue);
        const violations = trend.violations.map(numericValue);

        const plot = {
            x: x + 115,
            y: y + 35,
            width: width - 145,
            height: height - 115
        };

        const baseY = plot.y + plot.height;
        const penaltyMaximum = getNiceMaximum(
            Math.max(...penalties, 1)
        );
        const violationMaximum = getNiceMaximum(
            Math.max(...violations, 1)
        );

        const stepX = plot.width / Math.max(
            1,
            months.length - 1
        );

        const penaltyPoints = months.map(
            (_, index) => ({
                x: plot.x + stepX * index,
                y: baseY - (
                    penalties[index] / penaltyMaximum
                ) * plot.height
            })
        );

        const violationPoints = months.map(
            (_, index) => ({
                x: plot.x + stepX * index,
                y: baseY - (
                    violations[index] / violationMaximum
                ) * plot.height
            })
        );

        const tickCount = 5;

        context.strokeStyle = COLORS.grid;
        context.lineWidth = 2;

        for (
            let tick = 0;
            tick <= tickCount;
            tick += 1
        ) {
            const ratio = tick / tickCount;
            const lineY = baseY - ratio * plot.height;

            context.beginPath();
            context.moveTo(plot.x, lineY);
            context.lineTo(plot.x + plot.width, lineY);
            context.stroke();

            setFont(context, 16, 620);
            context.textAlign = "right";
            context.textBaseline = "middle";

            const penaltyValue = penaltyMaximum * ratio;
            const violationValue = violationMaximum * ratio;

            context.fillStyle = colors.penalties[0];
            context.fillText(
                `${formatThousands(penaltyValue)} тыс.`,
                plot.x - 42,
                lineY - 8
            );

            context.fillStyle = colors.violations[0];
            context.fillText(
                `${formatNumber(violationValue, 0)} шт.`,
                plot.x - 42,
                lineY + 12
            );
        }

        months.forEach(
            (month, index) => {
                const pointX = plot.x + stepX * index;

                context.beginPath();
                context.moveTo(pointX, plot.y);
                context.lineTo(pointX, baseY);
                context.strokeStyle = COLORS.grid;
                context.stroke();

                setFont(context, 18, 650);
                context.fillStyle = COLORS.muted;
                context.textAlign = "center";
                context.textBaseline = "top";
                context.fillText(
                    getMonthLabel(month, index),
                    pointX,
                    baseY + 18
                );
            }
        );

        context.strokeStyle = COLORS.axis;
        context.lineWidth = 3;
        context.beginPath();
        context.moveTo(plot.x, plot.y);
        context.lineTo(plot.x, baseY);
        context.lineTo(plot.x + plot.width, baseY);
        context.stroke();

        const forecastStart = clamp(
            Number(trend.forecastStartIndex),
            0,
            months.length
        );

        const actualLength = forecastStart <= 0
            ? 0
            : Math.min(
                months.length,
                forecastStart
            );

        if (actualLength >= 2) {
            drawTrendArea(
                context,
                penaltyPoints.slice(0, actualLength),
                baseY,
                colors.penalties[0],
                0.28
            );

            drawTrendArea(
                context,
                violationPoints.slice(0, actualLength),
                baseY,
                colors.violations[0],
                0.22
            );
        }

        if (forecastStart >= months.length) {
            drawPolyline(
                context,
                penaltyPoints,
                colors.penalties[0]
            );
            drawPolyline(
                context,
                violationPoints,
                colors.violations[0]
            );
        } else if (forecastStart <= 0) {
            drawPolyline(
                context,
                penaltyPoints,
                colors.penalties[0],
                true
            );
            drawPolyline(
                context,
                violationPoints,
                colors.violations[0],
                true
            );
        } else {
            drawPolyline(
                context,
                penaltyPoints.slice(0, forecastStart),
                colors.penalties[0]
            );
            drawPolyline(
                context,
                violationPoints.slice(0, forecastStart),
                colors.violations[0]
            );

            drawPolyline(
                context,
                penaltyPoints.slice(
                    Math.max(0, forecastStart - 1)
                ),
                colors.penalties[0],
                true
            );
            drawPolyline(
                context,
                violationPoints.slice(
                    Math.max(0, forecastStart - 1)
                ),
                colors.violations[0],
                true
            );
        }

        penaltyPoints.forEach(
            (point) => {
                context.beginPath();
                context.arc(
                    point.x,
                    point.y,
                    6,
                    0,
                    Math.PI * 2
                );
                context.fillStyle = colors.penalties[0];
                context.fill();
                context.strokeStyle = COLORS.white;
                context.lineWidth = 2;
                context.stroke();
            }
        );

        violationPoints.forEach(
            (point) => {
                context.beginPath();
                context.arc(
                    point.x,
                    point.y,
                    6,
                    0,
                    Math.PI * 2
                );
                context.fillStyle = colors.violations[0];
                context.fill();
                context.strokeStyle = COLORS.white;
                context.lineWidth = 2;
                context.stroke();
            }
        );

        context.restore();
    }

    async function buildDashboardCanvas() {
        if (document.fonts?.ready) {
            await document.fonts.ready;
        }

        const snapshot = getExportSnapshot();
        const cards = getVisibleCards(snapshot);

        const canvas = document.createElement("canvas");
        canvas.width = PAGE_WIDTH;
        canvas.height = PAGE_HEIGHT;

        const context = canvas.getContext("2d", {
            alpha: false
        });

        context.fillStyle = COLORS.white;
        context.fillRect(
            0,
            0,
            PAGE_WIDTH,
            PAGE_HEIGHT
        );

        drawDate(context);
        drawCenteredTitle(
            context,
            getDashboardTitle()
        );

        context.strokeStyle = "#D8EAF6";
        context.lineWidth = 8;
        context.beginPath();
        context.moveTo(0, 4);
        context.lineTo(PAGE_WIDTH, 4);
        context.stroke();

        drawCircleGrid(context, cards);
        drawTable(context);

        drawTrend(
            context,
            snapshot.trend,
            {
                penalties: snapshot
                    ?.colors
                    ?.penalties
                    || FALLBACK_COLORS.penalties,
                violations: snapshot
                    ?.colors
                    ?.violations
                    || FALLBACK_COLORS.violations
            }
        );

        return canvas;
    }

    function canvasToJpegBlob(canvas) {
        return new Promise(
            (resolve, reject) => {
                canvas.toBlob(
                    (blob) => {
                        if (blob) {
                            resolve(blob);
                        } else {
                            reject(
                                new Error(
                                    "Не удалось подготовить изображение PDF."
                                )
                            );
                        }
                    },
                    "image/jpeg",
                    0.94
                );
            }
        );
    }

    function createPdfBlobFromJpeg(
        jpegBytes,
        imageWidth,
        imageHeight
    ) {
        const encoder = new TextEncoder();
        const chunks = [];
        const offsets = [0];
        let length = 0;

        function appendBytes(bytes) {
            chunks.push(bytes);
            length += bytes.length;
        }

        function appendText(text) {
            appendBytes(encoder.encode(text));
        }

        function startObject(number) {
            offsets[number] = length;
            appendText(`${number} 0 obj\n`);
        }

        appendText("%PDF-1.4\n%DashboardExport\n");

        startObject(1);
        appendText(
            "<< /Type /Catalog /Pages 2 0 R >>\n"
            + "endobj\n"
        );

        startObject(2);
        appendText(
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
            + "endobj\n"
        );

        startObject(3);
        appendText(
            "<< /Type /Page /Parent 2 0 R "
            + `/MediaBox [0 0 ${PDF_PAGE_WIDTH} ${PDF_PAGE_HEIGHT}] `
            + "/Resources << /XObject << /Im0 5 0 R >> >> "
            + "/Contents 4 0 R >>\n"
            + "endobj\n"
        );

        const content = (
            "q\n"
            + `${PDF_PAGE_WIDTH} 0 0 ${PDF_PAGE_HEIGHT} 0 0 cm\n`
            + "/Im0 Do\n"
            + "Q\n"
        );

        const contentBytes = encoder.encode(content);

        startObject(4);
        appendText(
            `<< /Length ${contentBytes.length} >>\nstream\n`
        );
        appendBytes(contentBytes);
        appendText("endstream\nendobj\n");

        startObject(5);
        appendText(
            "<< /Type /XObject /Subtype /Image "
            + `/Width ${imageWidth} /Height ${imageHeight} `
            + "/ColorSpace /DeviceRGB /BitsPerComponent 8 "
            + "/Filter /DCTDecode "
            + `/Length ${jpegBytes.length} >>\nstream\n`
        );
        appendBytes(jpegBytes);
        appendText("\nendstream\nendobj\n");

        const xrefOffset = length;

        appendText("xref\n0 6\n");
        appendText("0000000000 65535 f \n");

        for (
            let objectNumber = 1;
            objectNumber <= 5;
            objectNumber += 1
        ) {
            appendText(
                String(offsets[objectNumber])
                    .padStart(10, "0")
                + " 00000 n \n"
            );
        }

        appendText(
            "trailer\n"
            + "<< /Size 6 /Root 1 0 R >>\n"
            + "startxref\n"
            + `${xrefOffset}\n`
            + "%%EOF"
        );

        return new Blob(
            chunks,
            {
                type: "application/pdf"
            }
        );
    }

    function downloadBlob(blob, fileName) {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");

        anchor.href = url;
        anchor.download = fileName;
        anchor.style.display = "none";

        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();

        window.setTimeout(
            () => URL.revokeObjectURL(url),
            1000
        );
    }

    async function generateAndDownloadPdf() {
        const fileName = getPdfFileName();

        setBusy(
            true,
            "Формируется PDF-файл…"
        );

        try {
            const canvas = await buildDashboardCanvas();
            const jpegBlob = await canvasToJpegBlob(canvas);
            const jpegBytes = new Uint8Array(
                await jpegBlob.arrayBuffer()
            );

            const pdfBlob = createPdfBlobFromJpeg(
                jpegBytes,
                canvas.width,
                canvas.height
            );

            downloadBlob(pdfBlob, fileName);

            setBusy(false, "");
            closeModal();
        } catch (error) {
            console.error(
                "Dashboard PDF export failed:",
                error
            );

            setBusy(
                false,
                error?.message
                || "Не удалось сформировать PDF-файл."
            );
        }
    }

    function initializePdfExport() {
        const downloadButton = byId(
            "dashboard-download-pdf"
        );
        const shareButton = byId(
            "dashboard-share-link"
        );
        const cancelButton = byId(
            "dashboard-pdf-cancel"
        );
        const confirmButton = byId(
            "dashboard-pdf-confirm"
        );
        const input = byId(
            "dashboard-pdf-filename"
        );

        downloadButton?.addEventListener(
            "click",
            openModal
        );

        shareButton?.addEventListener(
            "click",
            () => {
                // Функциональность кнопки «Поделиться» будет добавлена отдельно.
            }
        );

        cancelButton?.addEventListener(
            "click",
            closeModal
        );

        confirmButton?.addEventListener(
            "click",
            generateAndDownloadPdf
        );

        input?.addEventListener(
            "keydown",
            (event) => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    generateAndDownloadPdf();
                }
            }
        );

        document.querySelectorAll(
            "[data-pdf-modal-close]"
        ).forEach(
            (element) => element.addEventListener(
                "click",
                closeModal
            )
        );

        document.addEventListener(
            "keydown",
            (event) => {
                if (
                    event.key === "Escape"
                    && !byId("dashboard-pdf-modal")?.hidden
                ) {
                    closeModal();
                }
            }
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializePdfExport
        );
    } else {
        initializePdfExport();
    }
})();
