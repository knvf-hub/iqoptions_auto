const $ = (selector) => document.querySelector(selector);

const state = {
  theme: localStorage.getItem("iq-auto-theme") || "light",
};

async function api(path, options = {}) {
  const { timeoutMs = 30000, ...fetchOptions } = options;
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

function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("iq-auto-theme", state.theme);
  const button = $("#loginThemeToggleBtn");
  if (!button) return;
  const isDark = state.theme === "dark";
  button.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  button.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;
  if (window.lucide) window.lucide.createIcons();
}

function setLoading(loading) {
  const button = $("#loginSubmitBtn");
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  const label = button.querySelector("[data-label]");
  if (label) label.textContent = loading ? "Connecting..." : "Login";
}

function showError(message) {
  const error = $("#loginError");
  error.textContent = message;
  error.hidden = !message;
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
        <div class="confirm-icon ${variant}">
          <i data-lucide="${variant === "danger" ? "alert-triangle" : "shield-check"}"></i>
        </div>
        <div class="confirm-copy">
          <h2 id="confirmTitle">${title}</h2>
          <p>${message}</p>
        </div>
        <div class="confirm-actions">
          <button class="btn confirm-cancel" type="button">${cancelText}</button>
          <button class="btn ${variant === "danger" ? "danger" : "primary"} confirm-ok" type="button">${confirmText}</button>
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

async function submitLogin(event) {
  event.preventDefault();
  showError("");
  const accountType = $("#accountTypeInput").value;
  if (accountType === "REAL") {
    const confirmed = await confirmDialog({
      title: "Login with REAL?",
      message: "Orders can use the real IQ Option balance after login.",
      confirmText: "Login REAL",
      variant: "danger",
    });
    if (!confirmed) return;
  }
  setLoading(true);
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("#emailInput").value.trim(),
        password: $("#passwordInput").value,
        account_type: accountType,
        two_factor_code: $("#twoFactorInput").value.trim(),
      }),
    });
    window.location.href = "/";
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setTheme(state.theme);
  $("#loginThemeToggleBtn")?.addEventListener("click", () => setTheme(state.theme === "dark" ? "light" : "dark"));
  $("#loginForm")?.addEventListener("submit", submitLogin);
  if (window.lucide) window.lucide.createIcons();
});
