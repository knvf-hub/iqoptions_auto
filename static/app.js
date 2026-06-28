const $ = (selector) => document.querySelector(selector);

const state = {
  status: null,
  trades: [],
  openTrades: [],
  assetStats: [],
  events: [],
  equity: [],
  assets: [],
  telegram: null,
  telegramSignals: [],
  assetStatsRaw: [],
  summarySelectedAssets: new Set(),
  summarySearch: "",
  selectedAsset: "",
  lastAutoSignalAt: "",
  historyOffset: 0,
  historyLastCount: 0,
  eventsOffset: 0,
  eventsLimit: 20,
  eventsHasMore: true,
  eventsLoading: false,
  pendingAction: "",
  refreshing: false,
  refreshTimer: null,
  countdownTimer: null,
  clockTimer: null,
  settlePending: false,
  lastSettleAttemptAt: 0,
  equityHoverIndex: null,
  equityChartPoints: [],
  equityPlotArea: null,
  theme: localStorage.getItem("iq-auto-theme") || "light",
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
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
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

function shortTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function confirmDialog({
  title = "Confirm action",
  message = "",
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "primary",
} = {}) {
  return new Promise((resolve) => {
    document.querySelector(".confirm-backdrop")?.remove();
    const backdrop = document.createElement("div");
    backdrop.className = "confirm-backdrop";
    backdrop.innerHTML = `
      <section class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
        <div class="confirm-icon ${escapeHtml(variant)}">
          <i data-lucide="${variant === "danger" ? "alert-triangle" : "shield-check"}"></i>
        </div>
        <div class="confirm-copy">
          <h2 id="confirmTitle">${escapeHtml(title)}</h2>
          <p>${escapeHtml(message)}</p>
        </div>
        <div class="confirm-actions">
          <button class="btn confirm-cancel" type="button">${escapeHtml(cancelText)}</button>
          <button class="btn ${variant === "danger" ? "danger" : "primary"} confirm-ok" type="button">
            ${escapeHtml(confirmText)}
          </button>
        </div>
      </section>
    `;
    document.body.appendChild(backdrop);
    if (window.lucide) window.lucide.createIcons();

    const done = (value) => {
      document.removeEventListener("keydown", onKeyDown);
      backdrop.remove();
      resolve(value);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") done(false);
      if (event.key === "Enter") done(true);
    };
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) done(false);
    });
    backdrop.querySelector(".confirm-cancel").addEventListener("click", () => done(false));
    backdrop.querySelector(".confirm-ok").addEventListener("click", () => done(true));
    document.addEventListener("keydown", onKeyDown);
    backdrop.querySelector(".confirm-ok").focus();
  });
}

const REASON_TH = {
  waiting: "รอสัญญาณ",
  entry_window_wait: "รอเข้าเฉพาะวินาที 59-00",
  entry_window_missed: "พลาดช่วงเข้าออเดอร์",
  telegram_follow_mode: "เปิดโหมดตามสัญญาณ Telegram",
  no_eligible_candidate: "ยังไม่มีคู่เงินที่ผ่านเงื่อนไข",
  no_candidate_above_threshold: "คะแนนสัญญาณยังไม่ถึงขั้นต่ำ",
  confidence_below_minimum: "ความมั่นใจต่ำกว่าที่ตั้งไว้",
  confidence_below_asset_rule: "ความมั่นใจต่ำกว่าค่าของคู่นี้",
  strategy_loss_cooldown: "พัก 1 แท่งหลังแพ้",
  asset_rule_disabled: "คู่นี้ถูกปิดไว้",
  direction_not_allowed_for_asset: "ฝั่ง CALL/PUT นี้ถูกปิดไว้",
  blocked_asset_direction: "ฝั่งนี้ถูกบล็อกไว้",
  asset_direction_loss_cooldown: "พักฝั่งนี้ชั่วคราวหลังแพ้ติดกัน",
  not_enough_candles: "ข้อมูลแท่งย้อนหลังยังไม่พอ",
  zero_range_candle: "แท่งนี้ไม่มีระยะราคา",
  atr_unavailable: "คำนวณ ATR ไม่ได้",
  indicator_unavailable: "คำนวณอินดิเคเตอร์ไม่ครบ",
  signal_scan_timeout: "สแกนสัญญาณนานเกินเวลา",
  asset_strategy_not_configured: "คู่นี้ยังไม่ได้ตั้งสูตร",
  asset_disabled: "คู่นี้ถูกปิดไว้",
  asset_direction_disabled: "ฝั่ง CALL/PUT นี้ถูกปิดไว้",
  daily_loss_limit_reached: "ถึงขีดจำกัดขาดทุนวันนี้",
  daily_loss_would_be_exceeded: "ไม้ถัดไปเสี่ยงเกิน Max Loss",
  take_profit_reached: "ถึงเป้ากำไรวันนี้แล้ว",
  max_trades_reached: "ถึงจำนวนออเดอร์สูงสุดวันนี้",
  order_sent: "ส่งคำสั่งแล้ว",
  order_not_placed: "ยังเข้าออเดอร์ไม่ได้",
  broker_open_binary: "พบใน Binary และพร้อมใช้",
  broker_open_turbo: "พบใน Turbo และพร้อมใช้",
  runtime_open_symbols: "เทียบชื่อจากรายการเปิดของโบรกเกอร์",
  telegram_signal: "สัญญาณจาก Telegram",
  telegram_martingale: "เข้าไม้แก้ตาม Telegram MTG",
  telegram_martingale_draw_retry: "เสมอ จึงคงไม้ MTG เดิม",
  waiting_for_entry_time: "รอถึงเวลาเข้าออเดอร์",
  latest_signal_entry_time_passed: "สัญญาณล่าสุดเลยเวลาเข้าแล้ว",
  entry_time_already_passed: "เลยเวลาเข้าออเดอร์แล้ว",
  duplicate_signal_already_scheduled: "สัญญาณนี้ถูกตั้งรอไว้แล้ว",
  bot_is_stopped: "บอทยังไม่ได้ Start",
  telegram_disabled_before_wait: "Telegram ถูกปิดก่อนถึงเวลาเข้า",
  telegram_disabled_before_order: "Telegram ถูกปิดก่อนส่งออเดอร์",
  sending_order: "กำลังส่งออเดอร์",
  follow_signals_disabled: "เปิด Listen อย่างเดียว ยังไม่ Follow",
  strategy_martingale_wait: "รอเข้าไม้ MTG 3-step",
  strategy_martingale_3step: "เข้าไม้ MTG 3-step",
  manual: "กดเข้าออเดอร์เอง",
  openai_call_selective_momentum: "OpenAI CALL: โมเมนตัมขาขึ้นผ่าน EMA/ATR",
  openai_put_selective_momentum: "OpenAI PUT: โมเมนตัมขาลงผ่าน EMA/ATR",
  openai_selective_momentum_not_met: "OpenAI: ยังไม่ครบเงื่อนไขโมเมนตัม",
  openai_rsi20_mean_reversion: "OpenAI: สูตร RSI mean reversion เดิม",
  audjpy_call_momentum_continuation: "AUDJPY CALL: ขาขึ้นต่อเนื่องผ่าน EMA/ATR",
  audjpy_put_resistance_wick_rejection: "AUDJPY PUT: ปฏิเสธแนวต้านด้วยไส้บน",
  audjpy_hybrid_condition_not_met: "AUDJPY: ยังไม่ครบเงื่อนไขสูตร Hybrid",
  alibaba_call_support_wick_rejection: "ALIBABA CALL: เด้งจากแนวรับด้วยไส้ล่าง",
  alibaba_put_resistance_wick_rejection: "ALIBABA PUT: ปฏิเสธแนวต้านด้วยไส้บน",
  alibaba_sr_wick_condition_not_met: "ALIBABA: ยังไม่ครบเงื่อนไขแนวรับ/แนวต้าน",
  gbpusd_call_support_wick_rejection_with_opposite_block: "GBPUSD CALL: เด้งแนวรับและผ่านตัวกรองฝั่งตรงข้าม",
  gbpusd_put_resistance_wick_rejection: "GBPUSD PUT: ปฏิเสธแนวต้านด้วยไส้บน",
  gbpusd_no_support_resistance_rejection: "GBPUSD: ยังไม่ชนแนวรับ/แนวต้านตามสูตร",
  gbpusd_call_opposite_block_score_below_min: "GBPUSD CALL: คะแนนยืนยันฝั่งกลับตัวยังไม่พอ",
  eurjpy_bearish_streak_exhaustion_call: "EURJPY CALL: ลงต่อเนื่องจนเริ่มหมดแรง",
  eurjpy_bullish_streak_exhaustion_put: "EURJPY PUT: ขึ้นต่อเนื่องจนเริ่มหมดแรง",
  eurjpy_streak_condition_not_met: "EURJPY: จำนวนแท่งต่อเนื่องยังไม่ครบ",
  usdjpy_call_bearish_streak_exhaustion: "USDJPY CALL: ลงต่อเนื่องหลายแท่ง คาดหวังแรงกลับตัว",
  usdjpy_put_bullish_streak_body_exhaustion: "USDJPY PUT: ขึ้นต่อเนื่องและแท่งล่าสุดมี body ถึงเกณฑ์",
  usdjpy_streak_exhaustion_not_met: "USDJPY: จำนวนแท่งต่อเนื่อง/ขนาดแท่งยังไม่ครบ",
  casinos_put_resistance_wick_rejection: "CASINOS PUT: แตะแนวต้านและมีไส้บนปฏิเสธราคา",
  casinos_put_rejection_not_met: "CASINOS: ยังไม่แตะแนวต้านหรือไส้บนยังไม่เข้าเงื่อนไข",
  eth_call_support_wick_rejection: "ETH CALL: แตะแนวรับและมีไส้ล่างปฏิเสธราคา",
  eth_put_resistance_wick_rejection: "ETH PUT: แตะแนวต้านและมีไส้บนปฏิเสธราคา",
  eth_sr_wick_rejection_not_met: "ETH: ยังไม่เข้าเงื่อนไขแนวรับ/แนวต้าน",
  eth_put_bb_bullish_exhaustion: "ETH PUT: แตะ BB บนหลังขึ้นต่อเนื่อง",
  eth_accurate_condition_not_met: "ETH Accurate: เงื่อนไขยังไม่ครบ",
  sp500_call_support_wick_rejection: "SP500 CALL: แตะแนวรับสั้นและมีไส้ล่าง",
  sp500_put_bb_bullish_exhaustion: "SP500 PUT: ราคาแตะโซน BB บนหลังขึ้นต่อเนื่อง",
  sp500_sr_bb_condition_not_met: "SP500: ยังไม่เข้าเงื่อนไขแนวรับหรือ BB exhaustion",
  sp500_accurate_put_bullish_streak: "SP500 Accurate PUT: ขึ้นต่อเนื่องครบ 7 แท่ง",
  sp500_accurate_condition_not_met: "SP500 Accurate: ยังขึ้นต่อเนื่องไม่ครบ",
  ondo_bearish_body_high_close_rejection_call: "ONDO CALL: แท่งแดงแต่ปิดใกล้ไฮ",
  ondo_bullish_body_low_close_rejection_put: "ONDO PUT: แท่งเขียวแต่ปิดใกล้โลว์",
  ondo_opposite_body_rejection_not_met: "ONDO: ยังไม่เข้าเงื่อนไขแท่ง rejection",
};

function reasonText(reason) {
  const raw = String(reason || "-");
  if (!raw || raw === "-") return "-";
  const parts = raw.split(":");
  const key = parts.length > 1 ? parts.at(-1) : raw;
  const prefix = parts.length > 1 ? `${parts.slice(0, -1).join(":")}: ` : "";
  if (REASON_TH[key]) return `${prefix}${REASON_TH[key]}`;
  if (key.startsWith("not_open_for_")) return `${prefix}สินทรัพย์นี้ยังไม่เปิดสำหรับ ${key.replace("not_open_for_", "")}`;
  if (key.startsWith("asset_not_open_or_mapped")) return `${prefix}จับคู่ชื่อสินทรัพย์ไม่ได้หรือยังไม่เปิด`;
  if (key.includes("HOLD")) return raw.replaceAll("HOLD", "พัก").replaceAll("_", " ");
  return raw.replaceAll("_", " ");
}

function formatCountdown(expiresAt) {
  if (!expiresAt) return "--:--";
  const expiresMs = Date.parse(expiresAt);
  if (Number.isNaN(expiresMs)) return "--:--";
  const totalSeconds = Math.max(0, Math.ceil((expiresMs - Date.now()) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function isExpired(expiresAt) {
  if (!expiresAt) return false;
  const expiresMs = Date.parse(expiresAt);
  return !Number.isNaN(expiresMs) && expiresMs <= Date.now();
}

function updateCountdowns() {
  document.querySelectorAll("[data-countdown-expires]").forEach((element) => {
    const text = formatCountdown(element.dataset.countdownExpires);
    element.textContent = text === "00:00" && element.dataset.expiredText ? element.dataset.expiredText : text;
    element.classList.toggle("is-expired", text === "00:00");
  });
}

function setBadge(element, text, variant) {
  element.textContent = text;
  element.className = `badge ${variant || ""}`.trim();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("iq-auto-theme", state.theme);

  const button = $("#themeToggleBtn");
  if (!button) return;
  const isDark = state.theme === "dark";
  button.setAttribute("aria-pressed", isDark ? "true" : "false");
  button.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  button.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;
  if (window.lucide) {
    window.lucide.createIcons();
  }
  drawEquity(state.equity);
}

function toggleTheme() {
  setTheme(state.theme === "dark" ? "light" : "dark");
}

function setButtonLabel(button, label) {
  const labelElement = button?.querySelector("[data-label]");
  if (labelElement) labelElement.textContent = label;
}

function renderBotControls(status = state.status) {
  const running = Boolean(status?.running);
  const pending = state.pendingAction;
  const startBtn = $("#startBtn");
  const stopBtn = $("#stopBtn");
  if (!startBtn || !stopBtn) return;

  const starting = pending === "start";
  const stopping = pending === "stop";

  startBtn.classList.toggle("is-loading", starting);
  startBtn.classList.toggle("is-running", !starting && running);
  startBtn.disabled = starting || stopping || running;
  startBtn.setAttribute("aria-busy", starting ? "true" : "false");
  startBtn.title = starting ? "Starting bot" : running ? "Bot running" : "Start bot";
  setButtonLabel(startBtn, starting ? "Starting..." : running ? "Running" : "Start");

  stopBtn.classList.toggle("is-loading", stopping);
  stopBtn.disabled = stopping || starting || !running;
  stopBtn.setAttribute("aria-busy", stopping ? "true" : "false");
  stopBtn.title = stopping ? "Stopping bot" : "Stop bot";
  setButtonLabel(stopBtn, stopping ? "Stopping..." : "Stop");
}

function uniqueAssets(primary, assets = []) {
  const seen = new Set();
  const ordered = [primary, ...assets].filter(Boolean);
  return ordered
    .map((asset) => String(asset).trim())
    .filter((asset) => {
      if (!asset || seen.has(asset)) return false;
      seen.add(asset);
      return true;
    });
}

function setSelectedAsset(asset, { auto = false } = {}) {
  if (!asset) return;
  if (!state.assets.includes(asset)) {
    state.assets = [...state.assets, asset];
  }
  state.selectedAsset = asset;
  if (auto) state.autoAsset = asset;
  $("#assetSelectedText").textContent = asset;
  renderAssetOptions($("#assetSearchInput")?.value || "");
}

function ensureDurationOption(value) {
  const select = $("#durationInput");
  if (!select || value === null || value === undefined) return;
  const textValue = String(value);
  if ([...select.options].some((option) => option.value === textValue)) return;
  const option = document.createElement("option");
  option.value = textValue;
  option.textContent = `${textValue} minutes`;
  select.appendChild(option);
}

function closeAssetMenu() {
  $("#assetMenu").hidden = true;
  $("#assetSelectButton").setAttribute("aria-expanded", "false");
}

function openAssetMenu() {
  $("#assetMenu").hidden = false;
  $("#assetSelectButton").setAttribute("aria-expanded", "true");
  $("#assetSearchInput").value = "";
  renderAssetOptions("");
  $("#assetSearchInput").focus();
}

function renderAssetOptions(filter = "") {
  const options = $("#assetOptions");
  if (!options) return;
  const needle = filter.trim().toUpperCase();
  const assets = state.assets.filter((asset) => asset.toUpperCase().includes(needle));
  options.innerHTML = "";

  if (!assets.length) {
    const empty = document.createElement("div");
    empty.className = "combo-empty";
    empty.textContent = "No match";
    options.appendChild(empty);
    return;
  }

  for (const asset of assets) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `combo-option${asset === state.selectedAsset ? " selected" : ""}`;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", asset === state.selectedAsset ? "true" : "false");
    const name = document.createElement("span");
    name.textContent = asset;
    button.appendChild(name);
    button.addEventListener("click", () => {
      setSelectedAsset(asset);
      closeAssetMenu();
    });
    options.appendChild(button);
  }
}

function syncInputs(config) {
  if (!config) return;
  state.assets = uniqueAssets(config.trading.asset, config.trading.assets || []);
  if (!state.selectedAsset || !state.assets.includes(state.selectedAsset)) {
    setSelectedAsset(config.trading.asset);
  } else {
    renderAssetOptions("");
  }
  $("#instrumentInput").value = config.trading.instrument;
  $("#amountInput").value = config.trading.amount;
  ensureDurationOption(config.trading.duration_minutes);
  $("#durationInput").value = String(config.trading.duration_minutes);
  $("#takeProfitInput").value = config.risk?.take_profit ?? 0;
  $("#maxDailyLossInput").value = config.risk?.max_daily_loss ?? 1000;
  $("#martingaleInput").checked = Boolean(config.trading.martingale_enabled);
  $("#martingale3StepInput").checked = Boolean(config.trading.martingale_3step_enabled);
  renderMartingaleInput();
}

function renderMartingaleInput() {
  const input = $("#martingaleInput");
  const text = $("#martingaleInputText");
  const input3 = $("#martingale3StepInput");
  const text3 = $("#martingale3StepInputText");
  if (input && text) text.textContent = input.checked ? "On" : "Off";
  if (input3 && text3) text3.textContent = input3.checked ? "On" : "Off";
}

function renderSwitchText(inputSelector, textSelector) {
  const input = $(inputSelector);
  const text = $(textSelector);
  if (!input || !text) return;
  text.textContent = input.checked ? "On" : "Off";
}

function renderStatus(status) {
  state.status = status;
  const broker = status.broker || {};
  const stats = status.stats || {};
  const signal = status.last_signal || {};

  setBadge($("#modeBadge"), (broker.mode || "demo").toUpperCase(), broker.mode === "iqoption" ? "warning" : "neutral");
  setBadge($("#accountBadge"), broker.account_type || "PRACTICE", broker.account_type === "REAL" ? "danger" : "success");
  setBadge($("#connectionBadge"), broker.connected ? "online" : "offline", broker.connected ? "success" : "danger");
  const accountTypeSelect = $("#accountTypeSelect");
  if (accountTypeSelect && broker.account_type && accountTypeSelect.value !== broker.account_type) {
    accountTypeSelect.value = broker.account_type;
  }

  const runningState = $("#runningState");
  runningState.textContent = status.running ? "running" : "stopped";
  runningState.className = `state-dot ${status.running ? "running" : "stopped"}`;
  renderBotControls(status);

  $("#balanceValue").textContent = money(broker.balance);
  const todayProfit = Number(
    stats.today_profit ??
    stats.daily_profit ??
    stats.profit_today ??
    0
  );

  const sessionProfit = Number(stats.profit || 0);

  $("#todayProfitValue").textContent = money(todayProfit);
  $("#todayProfitValue").style.color = todayProfit >= 0 ? "var(--green)" : "var(--red)";

  $("#profitValue").textContent = money(sessionProfit);
  $("#profitValue").style.color = sessionProfit >= 0 ? "var(--green)" : "var(--red)";
  $("#winRateValue").textContent = pct(stats.win_rate);
  $("#winsValue").textContent = stats.wins || 0;
  $("#lossesValue").textContent = stats.losses || 0;
  $("#openTradesValue").textContent = stats.open_trades || 0;
  $("#tradeCountValue").textContent = stats.trades || 0;
  $("#lossStreakValue").textContent = stats.consecutive_losses || 0;
  const martingale = status.martingale || {};
  $("#nextAmountValue").textContent = money(martingale.next_amount ?? status.config?.trading?.amount);
  $("#nextAmountValue").style.color = martingale.will_apply ? "var(--amber)" : "var(--text)";
  $("#nextAmountValue").title = Array.isArray(martingale.sequence_preview)
    ? `MTG: ${martingale.sequence_preview.map(money).join(" -> ")}`
    : "";
  $("#lastTickValue").textContent = status.last_tick_at ? `Last tick ${localTime(status.last_tick_at)}` : "-";
  $("#brokerMessage").textContent = broker.message || "-";
  renderTelegram(status.telegram || state.telegram || {});

  const isRejectedScan = signal.tradable === false;
  $("#signalAction").textContent = isRejectedScan ? "SKIP" : (signal.action || "hold").toUpperCase();
  $("#signalAsset").textContent = isRejectedScan
    ? "No eligible"
    : signal.asset
      ? `${signal.asset} ${signal.label || ""}`.trim()
      : "-";
  $("#signalConfidence").textContent = isRejectedScan ? "-" : pct((signal.confidence || 0) * 100);
  if (isRejectedScan) {
    const rejections = signal.rejections || [];
    const summary = rejections
      .slice(0, 3)
      .map((item) => `${item.asset} ${String(item.action || "").toUpperCase()}: ${reasonText(item.reason)}`)
      .join(" | ");
    $("#signalReason").textContent = summary || reasonText(signal.reject_reason || "no_eligible_candidate");
  } else {
    $("#signalReason").textContent = reasonText(signal.reason || "waiting");
  }

  if (
    status.config?.trading?.auto_select_asset &&
    signal.tradable !== false &&
    signal.asset &&
    signal.created_at &&
    signal.created_at !== state.lastAutoSignalAt
  ) {
    state.lastAutoSignalAt = signal.created_at;
    setSelectedAsset(signal.asset, { auto: true });
  }
}

function renderTelegram(telegram = {}) {
  state.telegram = telegram;
  const enabledInput = $("#telegramEnabledInput");
  const followInput = $("#telegramFollowInput");
  if (enabledInput) enabledInput.checked = Boolean(telegram.enabled);
  if (followInput) {
    followInput.checked = Boolean(telegram.follow_signals);
    followInput.disabled = !Boolean(telegram.enabled);
  }
  renderSwitchText("#telegramEnabledInput", "#telegramEnabledText");
  renderSwitchText("#telegramFollowInput", "#telegramFollowText");

  const stateBadge = $("#telegramState");
  if (stateBadge) {
    const active = Boolean(telegram.running);
    stateBadge.textContent = active ? "listening" : telegram.enabled ? "starting" : "off";
    stateBadge.className = `state-dot ${active ? "running" : "stopped"}`;
  }

  const latest = telegram.latest_signal || {};
  $("#telegramChannel").textContent = telegram.channel || "-";
  $("#telegramSignal").textContent = latest.symbol
    ? `${latest.symbol} ${String(latest.direction || "").toUpperCase()}`
    : "-";
  $("#telegramEntry").textContent = latest.entry_time || latest.signal_time || "-";
  $("#telegramHistory").textContent = `${telegram.mapped || 0}/${telegram.imported || 0} mapped`;
  $("#telegramMtg").textContent = telegram.follow_signals ? "Fixed 1x / 2x / 4x" : "Fixed when Follow is on";
  $("#telegramError").textContent =
    reasonText(
      latest.order_message ||
        latest.mapped_reason ||
        telegram.last_error ||
        (telegram.running ? "listening" : "idle")
    );

  const mode = $("#assetSummaryMode");
  if (mode) {
    mode.textContent = telegram.follow_signals
      ? "Telegram mode: mapped history by asset and side"
      : "Session by asset and side";
  }
}

function renderTelegramFeed(items = []) {
  state.telegramSignals = items;
  const feed = $("#telegramFeed");
  if (!feed) return;
  feed.innerHTML = "";
  if (!items.length) {
    feed.innerHTML = `<div class="telegram-empty">No Telegram signals yet</div>`;
    return;
  }

  for (const item of items) {
    const payload = item.payload || {};
    const statusText = payload.order_status || item.status || (item.mapped ? "mapped" : "unmapped");
    const statusClass = telegramStatusClass(statusText, item.mapped);
    const symbol = payload.symbol || item.symbol || "-";
    const direction = String(payload.direction || item.direction || "").toUpperCase();
    const reason =
      payload.order_message ||
      payload.mapped_reason ||
      (item.mapped ? "mapped" : "asset_not_open_or_mapped");
    const active = payload.active_raw || item.active_raw || symbol;
    const card = document.createElement("article");
    card.className = "telegram-card";
    card.innerHTML = `
      <div class="telegram-card-top">
        <strong>${escapeHtml(active)}</strong>
        <span class="telegram-status ${statusClass}">${escapeHtml(statusText)}</span>
      </div>
      <div class="telegram-card-main">
        <span>${escapeHtml(symbol)}</span>
        <b>${escapeHtml(direction)}</b>
        <span>${escapeHtml(payload.expiration || item.expiration || "M1")}</span>
        <time>${escapeHtml(payload.signal_time || item.signal_time || "-")}</time>
      </div>
      <div class="telegram-card-reason" title="${escapeHtml(reason)}">${escapeHtml(reasonText(reason))}</div>
    `;
    feed.appendChild(card);
  }
}

function telegramStatusClass(status, mapped) {
  const value = String(status || "").toLowerCase();
  if (!mapped || value.includes("skip") || value.includes("cancel") || value.includes("unmapped") || value.includes("fail")) {
    return "bad";
  }
  if (value.includes("wait") || value.includes("open")) {
    return "warn";
  }
  return "good";
}

function renderTrades(items) {
  state.trades = items;
  state.historyLastCount = items.length;
  const body = $("#tradesBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="7" class="reason-cell">No trades yet</td></tr>`;
    renderHistoryPagination();
    return;
  }

  for (const trade of items) {
    const isOpen = trade.status === "open";
    const row = document.createElement("tr");
    if (isOpen) row.className = "open-trade-row";
    row.innerHTML = `
      <td>${localTime(trade.created_at)}</td>
      <td>${escapeHtml(trade.asset)}</td>
      <td>${String(trade.direction || "").toUpperCase()}</td>
      <td>${money(trade.amount)}</td>
      <td>${renderTradeStatus(trade)}</td>
      <td>${trade.profit === null || trade.profit === undefined ? "-" : money(trade.profit)}</td>
      <td class="reason-cell" title="${escapeHtml(trade.reason || trade.error || "-")}">${escapeHtml(reasonText(trade.reason || trade.error || "-"))}</td>
    `;
    body.appendChild(row);
  }
  updateCountdowns();
  renderHistoryPagination();
}

function renderHistoryPagination() {
  const limit = Number($("#historyLimit")?.value || 50);
  const page = Math.floor(state.historyOffset / limit) + 1;
  const prev = $("#historyPrevBtn");
  const next = $("#historyNextBtn");
  const label = $("#historyPageLabel");
  if (label) label.textContent = `Page ${page}`;
  if (prev) prev.disabled = state.historyOffset <= 0;
  if (next) next.disabled = state.historyLastCount < limit;
}

function changeHistoryPage(delta) {
  const limit = Number($("#historyLimit")?.value || 50);
  state.historyOffset = Math.max(0, state.historyOffset + delta * limit);
  refreshAll({ force: true });
}

function resetHistoryPage() {
  state.historyOffset = 0;
  refreshAll({ force: true });
}

function renderSummaryFilter(allRows = []) {
  const assets = [...new Set(allRows.map((item) => String(item.asset || "").trim()).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right));
  for (const selected of [...state.summarySelectedAssets]) {
    if (!assets.includes(selected)) state.summarySelectedAssets.delete(selected);
  }
  const text = $("#summaryFilterText");
  if (text) {
    const count = state.summarySelectedAssets.size;
    text.textContent = count ? `${count} selected` : "All assets";
  }
  const options = $("#summaryFilterOptions");
  if (!options) return;
  const search = state.summarySearch.trim().toLowerCase();
  const visibleAssets = assets.filter((asset) => asset.toLowerCase().includes(search));
  options.innerHTML = "";
  if (!visibleAssets.length) {
    options.innerHTML = `<div class="combo-empty">No assets</div>`;
    return;
  }
  for (const asset of visibleAssets) {
    const label = document.createElement("label");
    label.className = "summary-filter-option";
    label.innerHTML = `
      <input type="checkbox" value="${escapeHtml(asset)}" ${state.summarySelectedAssets.has(asset) ? "checked" : ""} />
      <span>${escapeHtml(asset)}</span>
    `;
    label.querySelector("input").addEventListener("change", (event) => {
      if (event.target.checked) state.summarySelectedAssets.add(asset);
      else state.summarySelectedAssets.delete(asset);
      renderAssetStats(state.assetStatsRaw, state.status?.config || {});
    });
    options.appendChild(label);
  }
}

function renderAssetStats(items = [], config = {}) {
  const directionOrder = { call: 0, put: 1 };
  const rules = config.trading?.asset_rules || {};
  const configuredAssets = uniqueAssets(config.trading?.asset, config.trading?.assets || []);
  const telegramMode = Boolean(state.telegram?.follow_signals || config.telegram?.follow_signals);
  const rowsByPair = new Map();

  if (!telegramMode) {
    for (const asset of configuredAssets) {
      for (const direction of ["call", "put"]) {
        const key = `${asset}:${String(direction).toLowerCase()}`;
        rowsByPair.set(key, {
          asset,
          direction: String(direction).toLowerCase(),
          trades: 0,
          wins: 0,
          losses: 0,
          draws: 0,
          open_trades: 0,
          profit: 0,
          win_rate: 0,
          avg_confidence: 0,
        });
      }
    }
  }

  for (const item of items) {
    const asset = String(item.asset || "").trim();
    const direction = String(item.direction || "").toLowerCase();
    if (!asset || !direction) continue;
    rowsByPair.set(`${asset}:${direction}`, { ...item, asset, direction });
  }

  const sortedItems = [...rowsByPair.values()].sort((left, right) => {
    const assetCompare = String(left.asset || "").localeCompare(String(right.asset || ""));
    if (assetCompare !== 0) return assetCompare;
    const leftDirection = directionOrder[String(left.direction || "").toLowerCase()] ?? 99;
    const rightDirection = directionOrder[String(right.direction || "").toLowerCase()] ?? 99;
    if (leftDirection !== rightDirection) return leftDirection - rightDirection;
    return String(left.direction || "").localeCompare(String(right.direction || ""));
  });
  state.assetStatsRaw = sortedItems;
  renderSummaryFilter(sortedItems);
  const filteredItems = state.summarySelectedAssets.size
    ? sortedItems.filter((item) => state.summarySelectedAssets.has(String(item.asset || "")))
    : sortedItems;
  state.assetStats = filteredItems;
  const body = $("#assetStatsBody");
  if (!body) return;
  body.innerHTML = "";
  if (!filteredItems.length) {
    body.innerHTML = `<tr><td colspan="8" class="reason-cell">No pair stats yet</td></tr>`;
    return;
  }

  for (const item of filteredItems) {
    const direction = String(item.direction || "").toLowerCase();
    const enabled = isAssetDirectionEnabled(rules[item.asset], direction);
    const profit = Number(item.profit || 0);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.asset)}</td>
      <td>${direction.toUpperCase()}</td>
      <td>${item.trades || 0}</td>
      <td><span class="summary-win">${item.wins || 0}</span>/<span class="summary-loss">${item.losses || 0}</span></td>
      <td>${pct(item.win_rate)}</td>
      <td class="${profit >= 0 ? "summary-win" : "summary-loss"}">${money(profit)}</td>
      <td>${pct((item.avg_confidence || 0) * 100)}</td>
      <td>
        <button
          class="mini-toggle ${enabled ? "is-on" : "is-off"}"
          type="button"
          data-asset-toggle="${escapeHtml(item.asset)}"
          data-direction-toggle="${escapeHtml(direction)}"
          title="${escapeHtml(`${item.asset} ${direction.toUpperCase()}`)}"
        >
          ${enabled ? "On" : "Off"}
        </button>
      </td>
    `;
    body.appendChild(row);
  }

  body.querySelectorAll("[data-asset-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleAssetDirection(button.dataset.assetToggle, button.dataset.directionToggle));
  });
}

function isAssetDirectionEnabled(rule, direction) {
  if (rule?.enabled === false) return false;
  const allowed = Array.isArray(rule?.allow_directions) ? rule.allow_directions.map((item) => String(item).toLowerCase()) : [];
  return !allowed.length || allowed.includes(direction);
}

function renderTradeStatus(trade) {
  if (trade.status === "open") {
    const expired = isExpired(trade.expires_at);
    return `
      <span class="status open active-order-status">
        <span class="pulse-dot"></span>
        <span>${expired ? "settling" : "open"}</span>
        <span class="status-countdown" data-countdown-expires="${escapeHtml(trade.expires_at || "")}">${formatCountdown(trade.expires_at)}</span>
      </span>
    `;
  }
  return `<span class="status ${trade.status}">${trade.status}</span>`;
}

function renderActiveOrder(openTrades = []) {
  state.openTrades = openTrades;
  const badge = $("#activeOrderBadge");
  if (!badge) return;
  const label = badge.querySelector("[data-label]");

  if (!openTrades.length) {
    badge.hidden = true;
    if (label) label.textContent = "No active order";
    return;
  }

  const trade = openTrades[0];
  const side = String(trade.direction || "").toUpperCase();
  const duration = trade.duration_minutes ? `${trade.duration_minutes}m` : "";
  const extra = openTrades.length > 1 ? ` +${openTrades.length - 1}` : "";
  if (label) {
    label.textContent = "";
    const prefix = isExpired(trade.expires_at) ? "Settling" : "Active";
    label.append(document.createTextNode(`${prefix}: ${trade.asset} ${side} ${duration}`.trim()));
    const countdown = document.createElement("span");
    countdown.className = "badge-countdown";
    countdown.dataset.countdownExpires = trade.expires_at || "";
    countdown.dataset.expiredText = "00:00";
    countdown.textContent = formatCountdown(trade.expires_at);
    label.appendChild(countdown);
    if (extra) label.append(document.createTextNode(extra));
  }
  badge.hidden = false;
  updateCountdowns();
}

function hasExpiredOpenTrade(openTrades = []) {
  return openTrades.some((trade) => trade.status === "open" && isExpired(trade.expires_at));
}

async function settleExpiredTrades() {
  const now = Date.now();
  if (state.settlePending || now - state.lastSettleAttemptAt < 5000) return;
  state.settlePending = true;
  state.lastSettleAttemptAt = now;
  try {
    await api("/api/trades/settle", { method: "POST", timeoutMs: 25000 });
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
  } catch (error) {
    showToast(error.message);
  } finally {
    state.settlePending = false;
  }
}

function renderEvents(items, { append = false } = {}) {
  state.events = append ? [...state.events, ...items] : items;
  const list = $("#eventsList");
  if (!append) list.innerHTML = "";
  if (!state.events.length) {
    const item = document.createElement("li");
    item.innerHTML = `<strong>System ready</strong><time>-</time>`;
    list.appendChild(item);
    return;
  }
  for (const event of items) {
    const item = document.createElement("li");
    item.innerHTML = `
      <strong>${event.category}: ${event.message}</strong>
      <time>${localTime(event.created_at)} · ${event.level}</time>
    `;
    list.appendChild(item);
  }
}

function updateEventsLoader(text = "") {
  const loader = $("#eventsLoader");
  if (!loader) return;
  if (text) {
    loader.textContent = text;
    loader.hidden = false;
    return;
  }
  loader.hidden = !state.eventsHasMore;
  loader.textContent = state.eventsHasMore ? "Scroll to load more" : "End of events";
}

async function loadEvents({ reset = false } = {}) {
  if (state.eventsLoading) return;
  state.eventsLoading = true;
  if (reset) {
    state.eventsOffset = 0;
    state.eventsHasMore = true;
    state.events = [];
  }
  updateEventsLoader("Loading");
  try {
    const data = await api(`/api/events?limit=${state.eventsLimit}&offset=${state.eventsOffset}`);
    const items = data.items || [];
    renderEvents(items, { append: !reset });
    state.eventsOffset += items.length;
    state.eventsHasMore = items.length === state.eventsLimit;
    updateEventsLoader();
  } catch (error) {
    updateEventsLoader("Load failed");
    showToast(error.message);
  } finally {
    state.eventsLoading = false;
  }
}

function drawEquity(items) {
  state.equity = items;
  const canvas = $("#equityCanvas");
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(rect.width * ratio);
  canvas.height = Math.floor(rect.height * ratio);
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, rect.width, rect.height);

  ctx.fillStyle = cssVar("--panel-soft") || "#fafbfc";
  ctx.fillRect(0, 0, rect.width, rect.height);
  ctx.font = "11px Inter, system-ui, sans-serif";
  ctx.textBaseline = "middle";

  if (!items.length) {
    ctx.fillStyle = cssVar("--muted") || "#69758a";
    ctx.fillText("Equity will appear after closed trades", 14, 28);
    state.equityChartPoints = [];
    state.equityPlotArea = null;
    hideEquityTooltip();
    return;
  }

  const values = items.map((item) => Number(item.equity || 0));
  const rawMin = Math.min(...values, 0);
  const rawMax = Math.max(...values, 0);
  const rawRange = rawMax - rawMin || 1;
  const yPad = Math.max(0.5, rawRange * 0.12);
  const min = Math.floor((rawMin - yPad) * 100) / 100;
  const max = Math.ceil((rawMax + yPad) * 100) / 100;
  const range = max - min || 1;
  const plot = {
    left: 58,
    right: Math.max(68, rect.width - 18),
    top: 24,
    bottom: Math.max(70, rect.height - 30),
  };
  const width = Math.max(1, plot.right - plot.left);
  const height = Math.max(1, plot.bottom - plot.top);
  state.equityPlotArea = plot;

  ctx.strokeStyle = cssVar("--line") || "#d9dee8";
  ctx.fillStyle = cssVar("--muted") || "#69758a";
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  const tickCount = 4;
  for (let i = 0; i <= tickCount; i += 1) {
    const value = min + (range * i) / tickCount;
    const y = plot.bottom - ((value - min) / range) * height;
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.fillText(money(value), plot.left - 8, y);
  }

  if (min < 0 && max > 0) {
    const zeroY = plot.bottom - ((0 - min) / range) * height;
    ctx.save();
    ctx.strokeStyle = cssVar("--muted") || "#69758a";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(plot.left, zeroY);
    ctx.lineTo(plot.right, zeroY);
    ctx.stroke();
    ctx.restore();
  }

  ctx.textAlign = "left";
  ctx.fillStyle = cssVar("--muted") || "#69758a";
  ctx.fillText(shortTime(items[0]?.time), plot.left, plot.bottom + 18);
  ctx.textAlign = "right";
  ctx.fillText(shortTime(items[items.length - 1]?.time), plot.right, plot.bottom + 18);

  ctx.strokeStyle = values[values.length - 1] >= 0 ? cssVar("--green") || "#0f8b6f" : cssVar("--red") || "#b42318";
  ctx.lineWidth = 2;
  ctx.beginPath();
  const points = values.map((value, index) => {
    const x = plot.left + (items.length === 1 ? width : (width * index) / (items.length - 1));
    const y = plot.bottom - ((value - min) / range) * height;
    return {
      x,
      y,
      value,
      time: items[index]?.time,
      delta: index === 0 ? value : value - values[index - 1],
    };
  });
  state.equityChartPoints = points;
  points.forEach((point, index) => {
    const { x, y } = point;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  for (const point of points) {
    ctx.fillStyle = point.value >= 0 ? cssVar("--green") || "#0f8b6f" : cssVar("--red") || "#b42318";
    ctx.beginPath();
    ctx.arc(point.x, point.y, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  const hoverIndex = state.equityHoverIndex;
  if (hoverIndex !== null && points[hoverIndex]) {
    const point = points[hoverIndex];
    ctx.save();
    ctx.strokeStyle = cssVar("--text") || "#172033";
    ctx.globalAlpha = 0.45;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(point.x, plot.top);
    ctx.lineTo(point.x, plot.bottom);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(plot.left, point.y);
    ctx.lineTo(plot.right, point.y);
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = cssVar("--panel") || "#ffffff";
    ctx.strokeStyle = cssVar("--text") || "#172033";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  ctx.textAlign = "left";
  ctx.fillStyle = cssVar("--text") || "#172033";
  ctx.fillText(`P/L ${money(values[values.length - 1])}`, plot.left, plot.top - 8);
}

function hideEquityTooltip() {
  const tooltip = $("#equityTooltip");
  if (tooltip) tooltip.hidden = true;
}

function updateEquityTooltip(event) {
  const canvas = $("#equityCanvas");
  const tooltip = $("#equityTooltip");
  if (!canvas || !tooltip || !state.equityChartPoints.length) return;
  const rect = canvas.getBoundingClientRect();
  const clientX = event.touches?.[0]?.clientX ?? event.clientX;
  const clientY = event.touches?.[0]?.clientY ?? event.clientY;
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  const plot = state.equityPlotArea;
  if (!plot || x < plot.left - 14 || x > plot.right + 14 || y < plot.top - 18 || y > plot.bottom + 28) {
    state.equityHoverIndex = null;
    hideEquityTooltip();
    drawEquity(state.equity);
    return;
  }

  let nearestIndex = 0;
  let nearestDistance = Infinity;
  state.equityChartPoints.forEach((point, index) => {
    const distance = Math.abs(point.x - x);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  state.equityHoverIndex = nearestIndex;
  drawEquity(state.equity);
  const point = state.equityChartPoints[nearestIndex];
  const deltaText = `${point.delta >= 0 ? "+" : ""}${money(point.delta)}`;
  tooltip.innerHTML = `
    <strong>P/L ${escapeHtml(money(point.value))}</strong>
    <span>${escapeHtml(localTime(point.time))}</span><br />
    <span>Change ${escapeHtml(deltaText)}</span>
  `;
  const left = Math.min(Math.max(point.x, 82), rect.width - 82);
  const top = Math.max(point.y, 42);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  tooltip.hidden = false;
}

function clearEquityHover() {
  state.equityHoverIndex = null;
  hideEquityTooltip();
  drawEquity(state.equity);
}

function tradingControlsPayload() {
  return {
    asset: state.selectedAsset || $("#assetSelectedText")?.textContent || "",
    instrument: $("#instrumentInput").value,
    amount: Number($("#amountInput").value),
    duration_minutes: Number($("#durationInput").value),
    take_profit: Number($("#takeProfitInput")?.value || 0),
    max_daily_loss: Number($("#maxDailyLossInput")?.value || 1000),
    martingale_enabled: Boolean($("#martingaleInput")?.checked),
    martingale_3step_enabled: Boolean($("#martingale3StepInput")?.checked),
  };
}

async function syncTradingControls() {
  const status = await api("/api/config/trading", {
    method: "POST",
    body: JSON.stringify(tradingControlsPayload()),
  });
  renderStatus(status);
}

async function refreshAll({ keepInputs = true, force = false } = {}) {
  if (state.refreshing && !force) return;
  state.refreshing = true;
  const statusFilter = $("#statusFilter").value;
  const historyLimit = $("#historyLimit")?.value || "50";
  try {
    const status = await api("/api/status");
    const summarySource = status.telegram?.follow_signals ? "&source=telegram" : "";
    const [trades, openTrades, equity, assetStats, telegramSignals] = await Promise.all([
      api(`/api/trades?limit=${encodeURIComponent(historyLimit)}&offset=${encodeURIComponent(state.historyOffset)}${statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ""}`),
      api("/api/trades?limit=5&status=open"),
      api("/api/equity?limit=500&scope=session"),
      api(`/api/stats/assets?scope=session${summarySource}`),
      api("/api/telegram/signals?limit=8"),
    ]);
    renderStatus(status);
    if (!keepInputs) syncInputs(status.config);
    renderTrades(trades.items || []);
    renderAssetStats(assetStats.items || [], status.config || {});
    renderTelegramFeed(telegramSignals.items || []);
    renderActiveOrder(openTrades.items || []);
    drawEquity(equity.items || []);
    if (hasExpiredOpenTrade(openTrades.items || [])) {
      settleExpiredTrades();
    }
  } finally {
    state.refreshing = false;
  }
}

async function syncTelegramControls() {
  const payload = {
    enabled: Boolean($("#telegramEnabledInput")?.checked),
    follow_signals: Boolean($("#telegramFollowInput")?.checked),
  };
  if (!payload.enabled) payload.follow_signals = false;
  const telegram = await api("/api/telegram/controls", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 20000,
  });
  renderTelegram(telegram);
  await refreshAll({ force: true });
  await loadEvents({ reset: true });
  showToast(`Telegram ${payload.enabled ? "enabled" : "disabled"}`);
}

async function postAction(path, label, action = "") {
  if (state.pendingAction) return;
  state.pendingAction = action;
  renderBotControls();
  try {
    if (action === "start" || action === "tick") {
      await syncTradingControls();
    }
    const result = await api(path, { method: "POST", timeoutMs: action === "stop" ? 6000 : 15000 });
    if (action === "start" || action === "stop") {
      renderStatus(result);
    }
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    showToast(label);
  } catch (error) {
    showToast(error.message);
  } finally {
    state.pendingAction = "";
    renderBotControls();
  }
}

async function manualTrade(direction) {
  try {
    await syncTradingControls();
    const payload = {
      asset: state.selectedAsset,
      instrument: $("#instrumentInput").value,
      direction,
      amount: Number($("#amountInput").value),
      duration_minutes: Number($("#durationInput").value),
    };
    await api("/api/trades/manual", { method: "POST", body: JSON.stringify(payload) });
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    showToast(`${direction.toUpperCase()} opened`);
  } catch (error) {
    showToast(error.message);
  }
}

async function toggleAssetDirection(asset, direction) {
  if (!asset || !direction) return;
  const rules = state.status?.config?.trading?.asset_rules || {};
  const enabled = isAssetDirectionEnabled(rules[asset], direction);
  const nextEnabled = !enabled;
  document
    .querySelectorAll(`[data-asset-toggle="${CSS.escape(asset)}"][data-direction-toggle="${CSS.escape(direction)}"]`)
    .forEach((button) => {
    button.disabled = true;
  });
  try {
    const status = await api("/api/config/asset-rule", {
      method: "POST",
      body: JSON.stringify({ asset, direction, enabled: nextEnabled }),
    });
    renderStatus(status);
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    showToast(`${asset} ${direction.toUpperCase()} ${nextEnabled ? "enabled" : "disabled"}`);
  } catch (error) {
    showToast(error.message);
  }
}

async function clearHistory() {
  const confirmed = await confirmDialog({
    title: "Clear history?",
    message: "Trade history, signals, events, and dashboard stats will be cleared.",
    confirmText: "Clear",
    variant: "danger",
  });
  if (!confirmed) return;
  try {
    const result = await api("/api/history/clear", { method: "POST", timeoutMs: 10000 });
    const cleared = result.cleared || {};
    state.lastAutoSignalAt = "";
    state.eventsOffset = 0;
    state.eventsHasMore = true;
    renderStatus(result.status || state.status || {});
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    showToast(`Cleared ${cleared.trades || 0} trades`);
  } catch (error) {
    showToast(error.message);
  }
}

async function resetStats() {
  const confirmed = await confirmDialog({
    title: "Reset stats?",
    message: "Dashboard stats will restart from now. Trade history will stay.",
    confirmText: "Reset",
  });
  if (!confirmed) return;
  try {
    const status = await api("/api/stats/reset", { method: "POST", timeoutMs: 10000 });
    renderStatus(status || state.status || {});
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    showToast("Stats reset");
  } catch (error) {
    showToast(error.message);
  }
}

async function switchAccountType() {
  const select = $("#accountTypeSelect");
  if (!select) return;
  const previous = state.status?.broker?.account_type || "PRACTICE";
  const next = select.value;
  if (next === previous) return;
  if (next === "REAL") {
    const confirmed = await confirmDialog({
      title: "Switch to REAL?",
      message: "Orders will use the real IQ Option balance after switching.",
      confirmText: "Switch",
      variant: "danger",
    });
    if (!confirmed) {
      select.value = previous;
      return;
    }
  }
  try {
    const status = await api("/api/broker/account-type", {
      method: "POST",
      body: JSON.stringify({ account_type: next }),
      timeoutMs: 20000,
    });
    renderStatus(status);
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    showToast(`Switched to ${next}`);
  } catch (error) {
    select.value = previous;
    showToast(error.message);
  }
}

async function logout() {
  const confirmed = await confirmDialog({
    title: "Logout?",
    message: "The bot will stop and broker credentials will be cleared from memory.",
    confirmText: "Logout",
    variant: "danger",
  });
  if (!confirmed) return;
  try {
    await api("/api/auth/logout", { method: "POST", timeoutMs: 15000 });
    window.location.href = "/login";
  } catch (error) {
    showToast(error.message);
  }
}

async function syncMartingaleMode(changedMode) {
  const classic = $("#martingaleInput");
  const threeStep = $("#martingale3StepInput");
  if (changedMode === "classic" && classic?.checked && threeStep) {
    threeStep.checked = false;
  }
  if (changedMode === "three_step" && threeStep?.checked && classic) {
    classic.checked = false;
  }
  renderMartingaleInput();
  try {
    await syncTradingControls();
    await refreshAll({ force: true });
    await loadEvents({ reset: true });
    const label = changedMode === "three_step" ? "MTG 3-step" : "Martingale x2";
    const enabled = changedMode === "three_step" ? Boolean(threeStep?.checked) : Boolean(classic?.checked);
    showToast(`${label} ${enabled ? "enabled" : "disabled"}`);
  } catch (error) {
    showToast(error.message);
  }
}

function bindEvents() {
  $("#assetSelectButton").addEventListener("click", (event) => {
    event.stopPropagation();
    if ($("#assetMenu").hidden) openAssetMenu();
    else closeAssetMenu();
  });
  $("#assetSearchInput").addEventListener("input", (event) => renderAssetOptions(event.target.value));
  $("#assetSearchInput").addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAssetMenu();
  });
  document.addEventListener("click", (event) => {
    if (!$("#assetCombo").contains(event.target)) closeAssetMenu();
  });
  $("#startBtn").addEventListener("click", () => postAction("/api/bot/start", "Bot started", "start"));
  $("#stopBtn").addEventListener("click", () => postAction("/api/bot/stop", "Bot stopped", "stop"));
  $("#tickBtn").addEventListener("click", () => postAction("/api/bot/tick", "Tick complete", "tick"));
  $("#reloadBtn").addEventListener("click", () => postAction("/api/config/reload", "Config reloaded"));
  $("#themeToggleBtn")?.addEventListener("click", toggleTheme);
  $("#accountTypeSelect")?.addEventListener("change", switchAccountType);
  $("#logoutBtn")?.addEventListener("click", logout);
  $("#resetStatsBtn")?.addEventListener("click", resetStats);
  $("#callBtn").addEventListener("click", () => manualTrade("call"));
  $("#putBtn").addEventListener("click", () => manualTrade("put"));
  $("#clearHistoryBtn").addEventListener("click", clearHistory);
  $("#martingaleInput").addEventListener("change", () => syncMartingaleMode("classic"));
  $("#martingale3StepInput").addEventListener("change", () => syncMartingaleMode("three_step"));
  $("#telegramEnabledInput").addEventListener("change", syncTelegramControls);
  $("#telegramFollowInput").addEventListener("change", syncTelegramControls);
  $("#statusFilter").addEventListener("change", resetHistoryPage);
  $("#historyLimit").addEventListener("change", resetHistoryPage);
  $("#historyPrevBtn")?.addEventListener("click", () => changeHistoryPage(-1));
  $("#historyNextBtn")?.addEventListener("click", () => changeHistoryPage(1));
  $("#summaryFilterButton")?.addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = $("#summaryFilterMenu");
    if (menu) menu.hidden = !menu.hidden;
  });
  $("#summarySearchInput")?.addEventListener("input", (event) => {
    state.summarySearch = event.target.value;
    renderSummaryFilter(state.assetStatsRaw);
  });
  $("#summarySelectAllBtn")?.addEventListener("click", () => {
    state.summarySelectedAssets.clear();
    renderAssetStats(state.assetStatsRaw, state.status?.config || {});
  });
  $("#summaryClearBtn")?.addEventListener("click", () => {
    state.summarySelectedAssets.clear();
    renderAssetStats(state.assetStatsRaw, state.status?.config || {});
  });
  document.addEventListener("click", (event) => {
    const filter = $("#summaryFilter");
    const menu = $("#summaryFilterMenu");
    if (filter && menu && !filter.contains(event.target)) menu.hidden = true;
  });
  $("#eventsScroller").addEventListener("scroll", () => {
    const scroller = $("#eventsScroller");
    const nearBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 80;
    if (nearBottom && state.eventsHasMore && !state.eventsLoading) {
      loadEvents();
    }
  });
  const equityCanvas = $("#equityCanvas");
  equityCanvas?.addEventListener("mousemove", updateEquityTooltip);
  equityCanvas?.addEventListener("mouseleave", clearEquityHover);
  equityCanvas?.addEventListener(
    "touchstart",
    (event) => {
      event.preventDefault();
      updateEquityTooltip(event);
    },
    { passive: false }
  );
  equityCanvas?.addEventListener(
    "touchmove",
    (event) => {
      event.preventDefault();
      updateEquityTooltip(event);
    },
    { passive: false }
  );
  equityCanvas?.addEventListener("touchend", clearEquityHover);
  window.addEventListener("resize", () => drawEquity(state.equity));
}

function initLocalClock() {
  const clock = $("#localClock");
  if (!clock) return;

  const pad = (value) => String(value).padStart(2, "0");

  const updateClock = () => {
    const now = new Date();
    clock.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  };

  updateClock();

  window.clearInterval(state.clockTimer);
  state.clockTimer = window.setInterval(updateClock, 1000);
}

document.addEventListener("DOMContentLoaded", async () => {
  setTheme(state.theme);
  initLocalClock();
  bindEvents();
  await refreshAll({ keepInputs: false }).catch((error) => showToast(error.message));
  await loadEvents({ reset: true });
  state.refreshTimer = window.setInterval(() => {
    refreshAll().catch((error) => showToast(error.message));
  }, 3000);
  state.countdownTimer = window.setInterval(updateCountdowns, 1000);
  updateCountdowns();
  if (window.lucide) {
    window.lucide.createIcons();
  }
});
