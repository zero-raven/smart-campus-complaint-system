/* Dashboard charts (Chart.js).
 *
 * Responsive notes:
 *  - maintainAspectRatio:false plus a fixed-height .chart-wrap parent. A
 *    canvas with Chart.js's default aspect ratio grows taller than a phone
 *    viewport and pushes the page into a long scroll.
 *  - Long category labels are truncated and angled; Chart.js otherwise draws
 *    them overlapping on a narrow canvas.
 *  - Charts are rebuilt on resize so they re-fit after an orientation change.
 */

const cards = document.getElementById("kpi-cards");
const hybridCards = document.getElementById("hybrid-cards");

// Design system palette - premium dark with teal primary
const PALETTE = [
  "#2ec4b6",  // Primary teal
  "#3b82f6",  // Accent blue
  "#10b981",  // Success green
  "#f59e0b",  // Warning amber
  "#ef4444",  // Danger red
  "#06b6d4",  // Info cyan
  "#8b5cf6",  // Purple
  "#ec4899",  // Pink
];

const CHART_TEXT_COLOR = "#e6e8eb"; // Light text for dark theme
const CHART_GRID_COLOR = "rgba(255, 255, 255, 0.05)";

function truncate(label, max = 18) {
  const text = String(label ?? "");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function chartFontSize() {
  // Chart.js defaults are tuned for desktop; shrink them on small screens.
  return window.innerWidth < 576 ? 10 : 12;
}

function makeBarChart(canvasId, rows, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !rows.length) return null;

  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((d) => truncate(d.label)),
      datasets: [
        {
          label: "Complaints",
          data: rows.map((d) => d.count),
          backgroundColor: color,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: window.innerWidth < 576 ? "y" : "x",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => rows[items[0].dataIndex].label,
          },
        },
      },
      scales: {
        x: {
          grid: { display: window.innerWidth >= 576, color: CHART_GRID_COLOR },
          ticks: { font: { size: chartFontSize(), color: CHART_TEXT_COLOR }, maxRotation: 45, minRotation: 0 },
        },
        y: {
          beginAtZero: true,
          grid: { display: window.innerWidth < 576, color: CHART_GRID_COLOR },
          ticks: { font: { size: chartFontSize(), color: CHART_TEXT_COLOR }, precision: 0 },
        },
      },
    },
  });
}

function makeDoughnut(canvasId, rows) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !rows.length) return null;

  return new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: rows.map((d) => d.label),
      datasets: [
        {
          data: rows.map((d) => d.count),
          backgroundColor: PALETTE,
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: window.innerWidth < 576 ? "bottom" : "right",
          labels: { font: { size: chartFontSize(), color: CHART_TEXT_COLOR }, boxWidth: 12 },
        },
      },
    },
  });
}

if (cards) {
  (async () => {
    try {
      const summary = await apiFetch("/dashboard/summary");
      const breakdown = await apiFetch("/dashboard/breakdown");

      const kpis = [
        { label: "Total", value: summary.total_complaints },
        { label: "Open", value: summary.open_complaints },
        { label: "Resolved", value: summary.resolved_complaints },
        { label: "Resolution rate", value: `${summary.resolution_rate}%` },
        {
          label: "Avg resolution",
          value: summary.avg_resolution_hours !== null
            ? `${Math.round(summary.avg_resolution_hours)}h`
            : "—",
        },
        { label: "Statuses", value: Object.keys(summary.by_status || {}).length },
      ];

      cards.innerHTML = kpis
        .map(
          (k, idx) => {
            const accentColors = ["#2ec4b6", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];
            const accent = accentColors[idx % accentColors.length];
            return `<div class="col-6 col-md-4 col-xl-2">
              <div class="card h-100" style="border-top: 3px solid ${accent};">
                <div class="card-body text-center py-4">
                  <div class="kpi-value" style="color: var(--text-primary); font-size: clamp(2rem, 4vw, 2.5rem); font-weight: 700; font-family: var(--font-display); line-height: 1.2; letter-spacing: -0.02em;">${k.value}</div>
                  <div class="kpi-label" style="color: var(--text-secondary); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; margin-top: 0.5rem;">${k.label}</div>
                </div>
              </div>
            </div>`;
          }
        )
        .join("");

      makeBarChart("chart-category", breakdown.by_category, "#2ec4b6");
      makeDoughnut("chart-status", breakdown.by_status);
      makeBarChart("chart-priority", breakdown.by_priority, "#f59e0b");
      makeBarChart("chart-department", breakdown.by_department, "#3b82f6");
    } catch (err) {
      cards.innerHTML = `<div class="col-12"><div class="alert alert-danger">${err.message}</div></div>`;
    }
  })();
}

if (hybridCards) {
  (async () => {
    try {
      const stats = await apiFetch("/dashboard/hybrid-stats");
      const entries = [
        { label: "Complaints (PostgreSQL)", value: stats.postgres_complaints },
        { label: "Activity events (MongoDB)", value: stats.mongo_events },
        { label: "Outbox pending", value: stats.outbox_pending },
      ];
      hybridCards.innerHTML = entries
        .map(
          (e) => `<div class="col-12 col-md-4">
            <div class="text-center">
              <div class="kpi-value" style="color: var(--text-primary); font-size: clamp(2rem, 4vw, 2.5rem); font-weight: 700; font-family: var(--font-display); line-height: 1.2; letter-spacing: -0.02em;">${e.value}</div>
              <div class="kpi-label" style="color: var(--text-secondary); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; margin-top: 0.5rem;">${e.label}</div>
            </div>
          </div>`
        )
        .join("");
    } catch (err) {
      hybridCards.innerHTML = `<div class="col-12"><div class="alert alert-secondary small">${
        err.message
      } <span class="text-muted">(requires STAFF or ADMIN)</span></div></div>`;
    }
  })();
}