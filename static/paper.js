const $ = (selector) => document.querySelector(selector);

const state = {
  theme: localStorage.getItem("iq-auto-theme") || "light",
  loadingImport: false,
  loadingToggle: false,
  enabled: false,
  timer: null,
};

async function api(path, options = {}) {
  const { timeoutMs = 15000, ...fetchOptions } = options;
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
  if (!response.ok) throw new Error(data.detail || response.statusText);
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function localTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function setBadge(element, text, variant = "neutral") {
  if (!element) return;
  element.textContent = text;
  element.className = `badge ${variant}`;
}

function statusBadge(status) {
  const value = String(status || "").toLowerCase();
  const variant = value === "won" ? "success" : value === "lost" ? "danger" : value === "filtered" ? "warning" : "neutral";
  return `<span class="badge ${variant}">${escapeHtml(value || "-")}</span>`;
}

function renderStatus(data) {
  const stats = data.stats || {};
  state.enabled = Boolean(data.enabled);
  setBadge($("#paperStateBadge"), data.enabled ? (data.running ? "running" : "enabled") : "off", data.enabled ? "success" : "danger");
  $("#paperChannel").textContent = data.channel_keyword ? `Channel contains: ${data.channel_keyword}` : "-";
  $("#paperEnabledText").textContent = data.enabled ? "On" : "Off";
  $("#paperSignals").textContent = stats.signals || 0;
  $("#paperWins").textContent = stats.wins || 0;
  $("#paperLosses").textContent = stats.losses || 0;
  $("#paperWinRate").textContent = pct(stats.win_rate);
  $("#paperPending").textContent = stats.pending || 0;
  $("#paperFiltered").textContent = stats.filtered || 0;
  renderSummary(stats.by_asset || []);
  renderToggleButton();
}

function renderSummary(items) {
  const body = $("#paperSummaryBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="reason-cell">No paper signals in this window</td></tr>`;
    return;
  }
  for (const item of items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.symbol)}</td>
      <td>${escapeHtml(String(item.direction || "").toUpperCase())}</td>
      <td>${item.signals || 0}</td>
      <td><span class="positive">${item.wins || 0}</span>/<span class="negative">${item.losses || 0}</span></td>
      <td>${pct(item.win_rate)}</td>
      <td>${item.pending || 0}</td>
    `;
    body.appendChild(row);
  }
}

function renderSignals(items) {
  const body = $("#paperSignalsBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="7" class="reason-cell">No paper signals</td></tr>`;
    return;
  }
  for (const item of items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${localTime(item.received_at)}</td>
      <td>${escapeHtml(item.symbol || item.active_raw || "-")}</td>
      <td>${escapeHtml(String(item.direction || "").toUpperCase())}</td>
      <td>${escapeHtml(item.signal_time || "-")}</td>
      <td>${statusBadge(item.status)}</td>
      <td class="reason-cell" title="${escapeHtml(item.filter_reason || "-")}">${escapeHtml(item.filter_reason || "-")}</td>
      <td>${escapeHtml(item.result_text || "-")}</td>
    `;
    body.appendChild(row);
  }
}

async function refreshAll() {
  const status = $("#paperStatusFilter")?.value || "";
  const query = status ? `&status=${encodeURIComponent(status)}` : "";
  const [statusData, signalData] = await Promise.all([
    api("/api/telegram-paper/status?hours=24"),
    api(`/api/telegram-paper/signals?hours=24&limit=200${query}`),
  ]);
  renderStatus(statusData);
  renderSignals(signalData.items || []);
}

async function importHistory() {
  if (state.loadingImport) return;
  state.loadingImport = true;
  renderImportButton();
  try {
    await api("/api/telegram-paper/import-history", { method: "POST", timeoutMs: 45000 });
    await refreshAll();
    showToast("Paper history imported");
  } catch (error) {
    showToast(error.message || "Import failed");
  } finally {
    state.loadingImport = false;
    renderImportButton();
  }
}

function renderImportButton() {
  const button = $("#paperImportBtn");
  if (!button) return;
  button.disabled = state.loadingImport;
  button.classList.toggle("is-loading", state.loadingImport);
  const label = button.querySelector("[data-label]");
  if (label) label.textContent = state.loadingImport ? "Importing..." : "Import 24h";
}

function renderToggleButton() {
  const button = $("#paperToggleBtn");
  if (!button) return;
  button.disabled = state.loadingToggle;
  button.classList.toggle("is-loading", state.loadingToggle);
  button.classList.toggle("primary", !state.enabled);
  button.classList.toggle("danger-outline", state.enabled);
  const label = button.querySelector("[data-label]");
  if (label) {
    label.textContent = state.loadingToggle ? "Updating..." : state.enabled ? "Disable" : "Enable";
  }
}

async function togglePaperMonitor() {
  if (state.loadingToggle) return;
  state.loadingToggle = true;
  renderToggleButton();
  try {
    const data = await api("/api/telegram-paper/controls", {
      method: "POST",
      body: JSON.stringify({ enabled: !state.enabled }),
      timeoutMs: 60000,
    });
    renderStatus(data);
    await refreshAll();
    showToast(`Paper monitor ${data.enabled ? "enabled" : "disabled"}`);
  } catch (error) {
    showToast(error.message || "Update failed");
  } finally {
    state.loadingToggle = false;
    renderToggleButton();
  }
}

function showToast(message) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2200);
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("iq-auto-theme", state.theme);
  const button = $("#paperThemeToggleBtn");
  if (button) button.innerHTML = state.theme === "dark" ? '<i data-lucide="sun"></i>' : '<i data-lucide="moon"></i>';
  window.lucide?.createIcons();
}

function toggleTheme() {
  state.theme = state.theme === "dark" ? "light" : "dark";
  applyTheme();
}

function init() {
  applyTheme();
  $("#paperThemeToggleBtn")?.addEventListener("click", toggleTheme);
  $("#paperRefreshBtn")?.addEventListener("click", refreshAll);
  $("#paperImportBtn")?.addEventListener("click", importHistory);
  $("#paperToggleBtn")?.addEventListener("click", togglePaperMonitor);
  $("#paperStatusFilter")?.addEventListener("change", refreshAll);
  refreshAll().catch((error) => showToast(error.message || "Refresh failed"));
  state.timer = window.setInterval(() => refreshAll().catch(() => {}), 5000);
  window.lucide?.createIcons();
}

document.addEventListener("DOMContentLoaded", init);
