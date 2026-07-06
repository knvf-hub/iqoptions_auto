const $ = (selector) => document.querySelector(selector);

const state = {
  month: "",
  data: null,
  rankMode: "pnl",
  theme: localStorage.getItem("iq-auto-theme") || "light",
};

async function api(path, options = {}) {
  const { timeoutMs = 20000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      ...fetchOptions,
    });
  } finally {
    window.clearTimeout(timer);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

function setBadge(element, text, variant) {
  element.textContent = text;
  element.className = `badge ${variant || ""}`.trim();
}

function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("iq-auto-theme", state.theme);
  const button = $("#pnlThemeToggleBtn");
  const isDark = state.theme === "dark";
  button.setAttribute("aria-pressed", isDark ? "true" : "false");
  button.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  button.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;
  if (window.lucide) window.lucide.createIcons();
}

function toggleTheme() {
  setTheme(state.theme === "dark" ? "light" : "dark");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function monthNow() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(month) {
  const [year, monthText] = month.split("-").map(Number);
  return new Date(year, monthText - 1, 1).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
  });
}

function moveMonth(delta) {
  const [year, monthText] = state.month.split("-").map(Number);
  const next = new Date(year, monthText - 1 + delta, 1);
  state.month = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
  $("#monthInput").value = state.month;
  loadPnl();
}

function money(value, { compact = false } = {}) {
  const number = Number(value || 0);
  const prefix = number > 0 ? "+" : number < 0 ? "-" : "";
  const absolute = Math.abs(number);
  if (compact && absolute >= 1000) {
    return `${prefix}${(absolute / 1000).toFixed(absolute >= 10000 ? 1 : 2)}K`;
  }
  return `${prefix}${absolute.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function percent(value) {
  return `${Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

function applyProfitClass(element, value) {
  element.classList.toggle("metric-win", Number(value) > 0);
  element.classList.toggle("metric-loss", Number(value) < 0);
}

function renderSummary(summary) {
  $("#monthTitle").textContent = monthLabel(state.month);
  const profit = $("#monthProfitValue");
  const roi = $("#monthRoiValue");
  profit.textContent = money(summary.profit);
  roi.textContent = percent(summary.roi);
  applyProfitClass(profit, summary.profit);
  applyProfitClass(roi, summary.roi);
  $("#monthWinRateValue").textContent = percent(summary.win_rate);
  $("#monthPositionsValue").textContent = Number(summary.positions || 0).toLocaleString();
  $("#monthBreakdownValue").innerHTML = `<span class="summary-win">${Number(summary.wins || 0)}</span> / <span class="summary-loss">${Number(summary.losses || 0)}</span> / ${Number(summary.draws || 0)}`;
}

function renderCalendar(days) {
  const grid = $("#calendarGrid");
  grid.innerHTML = "";
  const byDate = new Map(days.map((item) => [item.date, item]));
  const [year, monthText] = state.month.split("-").map(Number);
  const first = new Date(year, monthText - 1, 1);
  const last = new Date(year, monthText, 0);
  const leading = first.getDay();
  const totalCells = Math.ceil((leading + last.getDate()) / 7) * 7;

  for (let cellIndex = 0; cellIndex < totalCells; cellIndex += 1) {
    const dayNumber = cellIndex - leading + 1;
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "calendar-cell";
    if (dayNumber < 1 || dayNumber > last.getDate()) {
      cell.classList.add("empty");
      cell.disabled = true;
      grid.appendChild(cell);
      continue;
    }

    const dateKey = `${year}-${String(monthText).padStart(2, "0")}-${String(dayNumber).padStart(2, "0")}`;
    const item = byDate.get(dateKey);
    const profit = Number(item?.profit || 0);
    cell.classList.add(profit > 0 ? "positive" : profit < 0 ? "negative" : "flat");
    cell.title = item
      ? `${dateKey}: ${money(profit)} · ${item.positions} positions · WR ${percent(item.win_rate)}`
      : `${dateKey}: No closed trades`;
    cell.innerHTML = `
      <span class="calendar-day">${dayNumber}</span>
      <strong>${item ? money(profit, { compact: true }) : "-"}</strong>
      <small>${item ? `${item.positions} trades` : "No trades"}</small>
    `;
    grid.appendChild(cell);
  }
}

function renderRanking(items) {
  const list = $("#rankingList");
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = `<div class="ranking-empty">No closed trades for this month yet</div>`;
    return;
  }

  const metricKey = state.rankMode === "roi" ? "roi" : "profit";
  const sorted = [...items].sort((left, right) => Math.abs(Number(right[metricKey] || 0)) - Math.abs(Number(left[metricKey] || 0)));
  const maxValue = Math.max(...sorted.map((item) => Math.abs(Number(item[metricKey] || 0))), 1);

  for (const item of sorted.slice(0, 12)) {
    const value = Number(item[metricKey] || 0);
    const row = document.createElement("div");
    row.className = "ranking-row";
    row.innerHTML = `
      <div class="ranking-contract">
        <strong>${escapeHtml(item.label || `${item.asset} ${item.direction}`)}</strong>
        <span>${Number(item.positions || 0)} positions · WR ${percent(item.win_rate)}</span>
      </div>
      <div class="bar-track" aria-hidden="true">
        <span class="${value >= 0 ? "positive" : "negative"}" style="width: ${Math.max(8, Math.round((Math.abs(value) / maxValue) * 100))}%"></span>
      </div>
      <strong class="${value >= 0 ? "metric-win" : "metric-loss"}">${metricKey === "roi" ? percent(value) : money(value)}</strong>
    `;
    list.appendChild(row);
  }
}

function render(data) {
  renderSummary(data.summary || {});
  renderCalendar(data.days || []);
  renderRanking(data.ranking || []);
}

async function loadStatus() {
  const status = await api("/api/status").catch(() => null);
  setBadge(
    $("#pnlConnectionBadge"),
    status?.broker?.connected ? "online" : "offline",
    status?.broker?.connected ? "success" : "danger"
  );
}

async function loadPnl() {
  setBadge($("#pnlStatusBadge"), "loading", "neutral");
  try {
    const data = await api(`/api/pnl/month?month=${encodeURIComponent(state.month)}`);
    state.data = data;
    render(data);
    setBadge($("#pnlStatusBadge"), "ready", "success");
  } catch (error) {
    setBadge($("#pnlStatusBadge"), "error", "danger");
    showToast(error.message);
  }
}

function setRankMode(mode) {
  state.rankMode = mode === "roi" ? "roi" : "pnl";
  $("#rankPnlBtn").classList.toggle("active", state.rankMode === "pnl");
  $("#rankRoiBtn").classList.toggle("active", state.rankMode === "roi");
  renderRanking(state.data?.ranking || []);
}

function init() {
  const params = new URLSearchParams(window.location.search);
  state.month = params.get("month") || monthNow();
  $("#monthInput").value = state.month;
  $("#monthInput").addEventListener("change", (event) => {
    state.month = event.target.value || monthNow();
    loadPnl();
  });
  $("#prevMonthBtn").addEventListener("click", () => moveMonth(-1));
  $("#nextMonthBtn").addEventListener("click", () => moveMonth(1));
  $("#refreshPnlBtn").addEventListener("click", () => {
    loadStatus();
    loadPnl();
  });
  $("#rankPnlBtn").addEventListener("click", () => setRankMode("pnl"));
  $("#rankRoiBtn").addEventListener("click", () => setRankMode("roi"));
  $("#pnlThemeToggleBtn").addEventListener("click", toggleTheme);
  setTheme(state.theme);
  loadStatus();
  loadPnl();
  if (window.lucide) window.lucide.createIcons();
}

document.addEventListener("DOMContentLoaded", init);
