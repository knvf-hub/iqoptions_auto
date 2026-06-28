const $ = (selector) => document.querySelector(selector);

const state = {
  assets: [],
  history: [],
  currentJobId: "",
  pollTimer: null,
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
  const button = $("#exportThemeToggleBtn");
  if (!button) return;
  const isDark = state.theme === "dark";
  button.setAttribute("aria-pressed", isDark ? "true" : "false");
  button.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  button.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;
  if (window.lucide) window.lucide.createIcons();
}

function toggleTheme() {
  setTheme(state.theme === "dark" ? "light" : "dark");
}

function setSubmitLoading(loading) {
  const button = $("#exportSubmitBtn");
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  const label = button.querySelector("[data-label]");
  if (label) label.textContent = loading ? "Exporting..." : "Export CSV";
}

function timeframeLabel(value) {
  return Number(value) === 300 ? "5 minutes" : "1 minute";
}

function localTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const EXPORT_ASSET_CACHE_KEY = "iq-export-open-assets-cache";

function cachedAssets() {
  try {
    const cached = JSON.parse(localStorage.getItem(EXPORT_ASSET_CACHE_KEY) || "{}");
    return Array.isArray(cached.items) ? cached.items : [];
  } catch {
    return [];
  }
}

function saveAssetCache(items) {
  if (!Array.isArray(items) || !items.length) return;
  localStorage.setItem(
    EXPORT_ASSET_CACHE_KEY,
    JSON.stringify({
      saved_at: new Date().toISOString(),
      items,
    })
  );
}

function renderAssets(items, { label = "open assets" } = {}) {
  const select = $("#exportAssetInput");
  const previousValue = select.value;
  select.innerHTML = "";
  const seen = new Set();
  const assets = items
    .filter((item) => item.open !== false)
    .map((item) => String(item.name || "").trim())
    .filter((asset) => {
      if (!asset || seen.has(asset)) return false;
      seen.add(asset);
      return true;
    })
    .sort((left, right) => left.localeCompare(right));

  state.assets = assets;
  for (const asset of assets) {
    const option = document.createElement("option");
    option.value = asset;
    option.textContent = asset;
    select.appendChild(option);
  }
  if (previousValue && assets.includes(previousValue)) {
    select.value = previousValue;
  }

  if (!assets.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No open assets";
    select.appendChild(option);
  }
  $("#assetLoadState").textContent = `${assets.length} ${label}`;
}

async function loadBrokerAssetsWithRetry() {
  try {
    return await api("/api/broker/assets", { timeoutMs: 45000 });
  } catch (firstError) {
    $("#assetLoadState").textContent = "Retrying broker assets";
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    try {
      return await api("/api/broker/assets", { timeoutMs: 60000 });
    } catch {
      throw firstError;
    }
  }
}

async function loadAssets() {
  $("#assetLoadState").textContent = "Loading assets";
  const status = await api("/api/status").catch(() => null);
  setBadge(
    $("#exportConnectionBadge"),
    status?.broker?.connected ? "online" : "offline",
    status?.broker?.connected ? "success" : "danger"
  );
  try {
    const assets = await loadBrokerAssetsWithRetry();
    saveAssetCache(assets.items || []);
    renderAssets(assets.items || [], { label: "open assets" });
  } catch (error) {
    showToast(error.message);
    const cached = cachedAssets();
    if (cached.length) {
      renderAssets(cached, { label: "cached assets" });
      return;
    }
    const configuredAssets = status?.config?.trading?.assets || [];
    renderAssets(configuredAssets.map((name) => ({ name, open: true })), { label: "configured assets" });
  }
}

function renderHistory(items = []) {
  state.history = items;
  const body = $("#exportHistoryBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="reason-cell">No export files yet</td></tr>`;
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${localTime(item.updated_at)}</td>
      <td>${escapeHtml(item.asset || "-")}</td>
      <td>${escapeHtml(item.timeframe_label || timeframeLabel(item.timeframe_sec))}</td>
      <td>${Number(item.records_written || 0).toLocaleString()}</td>
      <td class="reason-cell">${escapeHtml(item.relative_path || item.error || "-")}</td>
      <td>
        ${
          item.status === "done" && item.download_url
            ? `<a class="mini-download" href="${escapeHtml(item.download_url)}">Download</a>`
            : `<span class="muted">${escapeHtml(item.status || "-")}</span>`
        }
      </td>
    `;
    body.appendChild(row);
  }
}

async function loadHistory() {
  try {
    const data = await api("/api/exports/market/history?limit=80");
    renderHistory(data.items || []);
  } catch (error) {
    showToast(error.message);
  }
}

function renderJob(job) {
  const status = job.status || "idle";
  const variant = status === "done" ? "success" : status === "error" ? "danger" : status === "running" ? "warning" : "neutral";
  setBadge($("#exportJobBadge"), status, variant);
  $("#exportStatusAsset").textContent = job.asset || "-";
  $("#exportStatusTimeframe").textContent = job.timeframe_label || timeframeLabel(job.timeframe_sec);
  $("#exportStatusRecords").textContent = job.records_written
    ? `${job.records_written} / ${job.records_requested}`
    : job.records_requested || "-";
  $("#exportStatusPath").textContent = job.relative_path || job.error || "-";

  const active = status === "queued" || status === "running";
  $("#exportProgress").hidden = !active;
  setSubmitLoading(active);

  const link = $("#exportDownloadLink");
  if (status === "done" && job.download_url) {
    link.href = job.download_url;
    link.hidden = false;
  } else {
    link.hidden = true;
  }
}

async function pollJob(jobId) {
  try {
    const job = await api(`/api/exports/market/${jobId}`);
    renderJob(job);
    if (job.status === "done") {
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
      showToast(`Saved to ${job.relative_path}`);
      await loadHistory();
    }
    if (job.status === "error") {
      window.clearInterval(state.pollTimer);
      state.pollTimer = null;
      showToast(job.error || "Export failed");
    }
  } catch (error) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
    setSubmitLoading(false);
    showToast(error.message);
  }
}

async function startExport(event) {
  event.preventDefault();
  const asset = $("#exportAssetInput").value;
  const timeframeSec = Number($("#exportTimeframeInput").value);
  const records = Number($("#exportRecordsInput").value);
  if (!asset) {
    showToast("Select an asset first");
    return;
  }
  if (!Number.isFinite(records) || records < 1 || records > 50000) {
    showToast("Records must be between 1 and 50000");
    return;
  }

  setSubmitLoading(true);
  $("#exportDownloadLink").hidden = true;
  try {
    const job = await api("/api/exports/market", {
      method: "POST",
      body: JSON.stringify({ asset, timeframe_sec: timeframeSec, records }),
      timeoutMs: 30000,
    });
    state.currentJobId = job.id;
    renderJob(job);
    window.clearInterval(state.pollTimer);
    state.pollTimer = window.setInterval(() => pollJob(job.id), 1200);
    await pollJob(job.id);
  } catch (error) {
    setSubmitLoading(false);
    showToast(error.message);
  }
}

function init() {
  setTheme(state.theme);
  $("#exportForm").addEventListener("submit", startExport);
  $("#exportThemeToggleBtn")?.addEventListener("click", toggleTheme);
  $("#refreshAssetsBtn").addEventListener("click", loadAssets);
  $("#refreshHistoryBtn").addEventListener("click", loadHistory);
  loadAssets();
  loadHistory();
  if (window.lucide) window.lucide.createIcons();
}

window.addEventListener("DOMContentLoaded", init);
