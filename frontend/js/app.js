// GoldScalper — app bootstrap: nav, router, topbar, symbol strip,
// collapsible sidebar, session popover, and service worker.

import { esc, fmtMoney, fmtPrice, hydrateIcons, icon, openModal, toast } from "./components.js?v=20261020_02";
import { COCKPIT_SUBTABS, VIEWS } from "./agents.js?v=20261020_02";
import {
  api,
  connectTelemetry,
  disconnectTelemetry,
  onConnectionChange,
  setState,
  setToken,
  state,
  subscribe,
} from "./ws.js?v=20261014_17";

const ORDER = ["cockpit", "agents", "divisions", "portfolio", "settings"];
let current = "cockpit";
let raf = null;
let refreshTimer = null;
let currentUser = null;

/* ------------------------------------------------------------- URL parameters */
export function getUrlParam(name, defaultVal = null) {
  try {
    const url = new URL(window.location.href);
    return url.searchParams.get(name) ?? defaultVal;
  } catch {
    return defaultVal;
  }
}

export function updateUrlParams(updates = {}, options = { replaceHash: true }) {
  try {
    const url = new URL(window.location.href);
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === undefined || v === "") {
        url.searchParams.delete(k);
      } else {
        url.searchParams.set(k, v);
      }
    }
    if (options.replaceHash && updates.tab) {
      url.hash = `#${updates.tab}`;
    }
    window.history.replaceState(null, "", url.toString());
  } catch (e) {
    console.debug("updateUrlParams error:", e);
  }
}

window.getUrlParam = getUrlParam;
window.updateUrlParams = updateUrlParams;

function resolveInitialTab() {
  try {
    const url = new URL(window.location.href);
    // 1. URL token auto-login support: ?token=...
    const tokenParam = url.searchParams.get("token");
    if (tokenParam) {
      localStorage.setItem("gs_token", tokenParam);
      state.token = tokenParam;
    }

    // 2. Cockpit Subtab direct access: ?tab=trades or ?tab=recent or ?subtab=trades
    const tabParam = (url.searchParams.get("tab") || url.searchParams.get("view") || "").toLowerCase();
    const subtabParam = (url.searchParams.get("subtab") || "").toLowerCase();

    if (tabParam && COCKPIT_SUBTABS && COCKPIT_SUBTABS[tabParam]) {
      if (VIEWS.cockpit) {
        VIEWS.cockpit.activeTab = COCKPIT_SUBTABS[tabParam];
      }
      return "cockpit";
    }

    if (subtabParam && COCKPIT_SUBTABS && COCKPIT_SUBTABS[subtabParam]) {
      if (VIEWS.cockpit) {
        VIEWS.cockpit.activeTab = COCKPIT_SUBTABS[subtabParam];
      }
      return "cockpit";
    }

    // 3. Main Views: ?tab=agents or ?view=portfolio
    if (tabParam && VIEWS[tabParam]) return tabParam;

    // 4. Hash support: #agents or #trades or #divisions
    const hash = window.location.hash.replace(/^#/, "").toLowerCase();
    if (hash && COCKPIT_SUBTABS && COCKPIT_SUBTABS[hash]) {
      if (VIEWS.cockpit) {
        VIEWS.cockpit.activeTab = COCKPIT_SUBTABS[hash];
      }
      return "cockpit";
    }
    if (hash && VIEWS[hash]) return hash;
  } catch (e) {
    console.debug("resolveInitialTab error:", e);
  }
  return "cockpit";
}

/* --------------------------------------------------------------- nav */
function buildNav() {
  const nav = document.getElementById("nav");
  const tab = document.getElementById("tabbar");
  if (!nav || !tab) return;
  nav.innerHTML = "";
  tab.innerHTML = "";
  for (const key of ORDER) {
    const v = VIEWS[key];
    if (!v) continue;
    const item = document.createElement("button");
    item.className = "nav-item";
    item.type = "button";
    item.dataset.key = key;
    item.title = v.title;
    item.innerHTML = `${icon(v.icon, 17)}<span>${esc(v.title)}</span>`;
    item.addEventListener("click", () => go(key));
    nav.appendChild(item);

    const tabItem = item.cloneNode(true);
    tabItem.addEventListener("click", () => go(key));
    tab.appendChild(tabItem);
  }
}

function markNav() {
  document.querySelectorAll("[data-key]").forEach((el) => {
    if (el.dataset.key === current) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
}

/* ------------------------------------------------------------- router */
async function go(key, syncUrl = true) {
  if (key === "performance" || key === "lessons") key = "portfolio";
  if (key === "control") key = "settings";
  if (!VIEWS[key]) key = "cockpit";
  if (current !== key && VIEWS[current]?.exit) {
    try {
      VIEWS[current].exit();
    } catch (e) {
      console.debug("view exit error:", e);
    }
  }
  current = key;
  window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  if (syncUrl) {
    if (key === "cockpit") {
      const curTab = getUrlParam("tab")?.toLowerCase();
      const curSubtab = getUrlParam("subtab")?.toLowerCase();
      const targetTab = (curTab && COCKPIT_SUBTABS?.[curTab])
        ? COCKPIT_SUBTABS[curTab]
        : (curSubtab && COCKPIT_SUBTABS?.[curSubtab])
          ? COCKPIT_SUBTABS[curSubtab]
          : (VIEWS.cockpit?.activeTab || "positions");
      updateUrlParams({ tab: targetTab, subtab: null });
    } else {
      updateUrlParams({ tab: key, subtab: null });
    }
  }
  markNav();
  closeMobileMenu();
  render();
  try {
    await VIEWS[key].enter?.();
  } catch (e) {
    console.warn("view enter failed", e);
  }
  scheduleRefresh();
}

function render() {
  const view = VIEWS[current];
  const titleEl = document.getElementById("view-title");
  const subEl = document.getElementById("view-sub");
  if (titleEl) titleEl.textContent = view.title;
  if (subEl) subEl.textContent = view.sub || "";

  // Show live symbol telemetry strip & cockpit ticker strictly on cockpit view only
  const symbolStrip = document.querySelector(".symbol-strip");
  if (symbolStrip) {
    symbolStrip.style.display = current === "cockpit" ? "flex" : "none";
  }
  const tickerEl = document.getElementById("cockpit-ticker");
  if (tickerEl) {
    tickerEl.style.display = current === "cockpit" ? "flex" : "none";
  }

  const root = document.getElementById("view");
  if (!root) return;
  try {
    view.render(root);
  } catch (e) {
    root.innerHTML = `<div class="panel"><div class="state error">${icon("alert", 28)}<div class="state-title">Render error</div><div class="state-text">${esc(e.message)}</div></div></div>`;
  }
  hydrateIcons(root);
  updateTopbar();
}

function scheduleRender() {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = null;
    const activeView = VIEWS[current];
    if (activeView && typeof activeView.patch === "function") {
      activeView.patch();
    }
    updateTopbar();
  });
}

function scheduleRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (document.hidden) return;
    if (current === "control" || current === "cockpit" || current === "performance") {
      VIEWS[current].enter?.();
    }
  }, 12000);
}

/* ------------------------------------------------------------ topbar & strip */
function updateTopbar() {
  const t = state.telemetry;
  const d = state.decision;
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };

  const price = t?.bid ?? t?.ask ?? null;
  set("s-symbol", t?.symbol || "XAUUSD");
  set("m-bid", t?.bid != null ? fmtPrice(t.bid) : "—");
  set("m-ask", t?.ask != null ? fmtPrice(t.ask) : "—");
  set("m-spread", t?.bid != null && t?.ask != null ? (t.ask - t.bid).toFixed(2) : "—");

  const action = d?.action || "—";
  const actionEl = document.getElementById("m-action");
  if (actionEl) {
    actionEl.textContent = action;
    actionEl.className = `val ${action === "BUY" ? "pos" : action === "SELL" ? "neg" : "muted"}`;
  }

  const eq = t?.equity != null ? t.equity : state.performance?.stats?.final_equity;
  set("m-equity", eq != null ? `$${Math.round(eq).toLocaleString("en-US")}` : "—");

  const conf = d?.confidence != null ? `${Math.round(d.confidence * 100)}%` : "—";
  set("m-conf", conf);

  // Run toggle pill
  const paused = t?.paused ?? false;
  const btn = document.getElementById("toggle-run");
  if (btn) {
    btn.dataset.state = paused ? "paused" : "running";
    const tx = btn.querySelector(".pill-text");
    if (tx) tx.textContent = paused ? "Paused" : "Running";
  }

  // MT5 Algo Trading Indicator
  const algoEl = document.getElementById("algo-indicator");
  if (algoEl) {
    const isAlgoOn = t?.mt5_trade_allowed ?? true;
    algoEl.dataset.state = isAlgoOn ? "on" : "off";
    const tx = algoEl.querySelector(".algo-text");
    if (tx) tx.textContent = isAlgoOn ? "Algo ON" : "Algo OFF";
    algoEl.title = isAlgoOn
      ? "MetaTrader 5 Algo Trading is Enabled (Terminal Allowed)"
      : "MetaTrader 5 Algo Trading is Disabled (Terminal Blocked - Press Ctrl+E in MT5)";
  }

  // Live Cockpit Telemetry Ticker
  updateCockpitTicker();
}

function buildDailyPerformanceTickerHtml(t) {
  const j = t?.juggler;
  const b = t?.bizdev;

  // Extract base numbers with resilient fallbacks from live telemetry
  const targetPct = Number(j?.daily_target_pct ?? 35).toFixed(1);
  const sodBalance = Number(j?.sod_balance || t?.balance || t?.equity || 8873.73);
  const targetUsd = fmtMoney((sodBalance * Number(targetPct)) / 100).replace("$", "");

  const realizedPnl = Number(j?.daily_realized_pnl ?? 0);
  const pnlClass = realizedPnl > 0 ? "perf-win" : realizedPnl < 0 ? "perf-loss" : "";
  const signBadge = realizedPnl > 0 ? "(+)" : realizedPnl < 0 ? "(-)" : "(±)";
  const realizedPnlText = (realizedPnl >= 0 ? "+$" : "-$") + Math.abs(realizedPnl).toFixed(2);

  const pnlPct = Number(j?.daily_pnl_pct ?? (sodBalance > 0 ? (realizedPnl / sodBalance) * 100 : 0));
  const pnlPctClass = pnlPct > 0 ? "perf-win" : pnlPct < 0 ? "perf-loss" : "";
  const pnlPctText = (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(2) + "%";

  const progressPct = Number(j?.progress_pct ?? Math.max(0, (pnlPct / Number(targetPct)) * 100)).toFixed(1);
  const remUsd = Number(j?.remaining_usd ?? Math.max(0, (sodBalance * Number(targetPct)) / 100 - realizedPnl));
  const remText = remUsd > 0 ? `Sisa: $${remUsd.toFixed(2)}` : "Tercapai";

  let itemsHtml = "";
  if (j?.profit_locked || j?.status === "LOCKED") {
    itemsHtml = `
      <span class="ticker-perf-item"><b class="perf-accent">TARGET HARIAN +${targetPct}% LOCKED</b></span>
      <span class="ticker-bullet">·</span>
      <span class="ticker-perf-item">Target Nilai: <b class="perf-accent">+$${targetUsd}</b></span>
      <span class="ticker-bullet">·</span>
      <span class="ticker-perf-item">Pencapaian (+/-): <b class="${pnlClass}">${signBadge} ${realizedPnlText} (<span class="${pnlPctClass}">${pnlPctText}</span>)</b></span>
      <span class="ticker-bullet">·</span>
      <span class="ticker-perf-item">Status: <b class="perf-win">TERCAPAI 100%</b></span>
    `;
  } else {
    itemsHtml = `
      <span class="ticker-perf-item">Target: <b class="perf-accent">+${targetPct}% (+$${targetUsd})</b></span>
      <span class="ticker-bullet">·</span>
      <span class="ticker-perf-item">Pencapaian (+/-): <b class="${pnlClass}">${signBadge} ${realizedPnlText} (<span class="${pnlPctClass}">${pnlPctText}</span>)</b></span>
      <span class="ticker-bullet">·</span>
      <span class="ticker-perf-item">Progress: <b class="perf-accent">${progressPct}%</b> (${remText})</span>
    `;
  }

  if (b?.enabled) {
    const lots = Number(b.total_lots_today ?? 0).toFixed(2);
    const rebate = Number(b.estimated_rebate_usd ?? 0).toFixed(2);
    itemsHtml += `
      <span class="ticker-bullet">·</span>
      <span class="ticker-perf-item">Volume: <b>${lots} L</b> (Rebate <b class="perf-win">+$${rebate}</b>)</span>
    `;
  }

  return `
    <span class="ticker-divider">―</span>
    <span class="ticker-perf-badge">TARGET & PENCAPAIAN</span>
    ${itemsHtml}
  `;
}

function updateCockpitTicker() {
  const tickerEl = document.getElementById("cockpit-ticker");
  if (!tickerEl) return;
  if (current !== "cockpit") {
    tickerEl.style.display = "none";
    return;
  }
  tickerEl.style.display = "flex";

  const t = state.telemetry;
  const d = state.decision;
  const tagEl = document.getElementById("ticker-tag");
  const msgEl = document.getElementById("ticker-msg");
  const trackEl = document.getElementById("ticker-track");

  let level = "";
  let tag = "SCANNING";
  let msg = "SPK Engine Active · 37 Agents Online · Market Normal · Standby Monitoring M1 Trigger";

  const vetoReason = d?.veto_reason || "";
  const isNewsBlackout = t?.news_blackout || vetoReason.toLowerCase().includes("news blackout");

  if (isNewsBlackout) {
    level = "danger";
    tag = "NEWS VETO";
    const newsTitle = t?.current_news?.title || t?.current_news || "High Impact Economic Event";
    msg = `HARD VETO: News Blackout — ${newsTitle} · Entry Ditahan Demi Keamanan Modal`;
  } else if (d?.hard_veto && vetoReason) {
    level = "danger";
    if (vetoReason.toLowerCase().includes("loss") || vetoReason.toLowerCase().includes("drawdown")) {
      tag = "CIRCUIT BREAKER";
      msg = `HARD VETO: ${vetoReason} · Proteksi Max Daily Loss Aktif`;
    } else {
      tag = "HARD VETO";
      msg = `HARD VETO: ${vetoReason}`;
    }
  } else if (t?.cooldown_remaining_s > 0) {
    level = "warning";
    tag = "COOLDOWN";
    const cdReason = t.cooldown_reason || "Post-Trade Cooldown";
    msg = `COOLDOWN ACTIVE: ${cdReason} (${t.cooldown_remaining_s}s tersisa) · Menstabilkan Volatilitas Pasar`;
  } else if (t?.paused) {
    level = "warning";
    tag = "PAUSED";
    msg = "BOT PAUSED: Engine ditangguhkan oleh Operator · Monitoring pasar tetap berjalan";
  } else if (t?.mt5_trade_allowed === false) {
    level = "warning";
    tag = "ALGO OFF";
    msg = "ALGO TRADING OFF: MT5 Terminal menolak order otomatis · Tekan Ctrl+E di terminal MT5";
  } else if (t?.bid != null && t?.ask != null && (t.ask - t.bid) >= 0.45) {
    level = "warning";
    tag = "WIDE SPREAD";
    msg = `SPREAD MELEBAR: ${(t.ask - t.bid).toFixed(2)} pts · Menunggu spread kembali normal (<0.35 pts)`;
  } else if (t?.positions?.length > 0 || (t?.open_trades > 0)) {
    level = "success";
    tag = "IN TRADE";
    if (t?.positions?.length > 0) {
      const pos = t.positions[0];
      const pnl = Number(pos.pnl ?? pos.last_profit ?? pos.profit) || 0;
      const pnlText = (pnl >= 0 ? "+$" : "-$") + Math.abs(pnl).toFixed(2);
      const dir = (pos.direction || pos.side || pos.type || "BUY").toUpperCase();
      const rawVol = Number(pos.volume ?? pos.size ?? pos.lots) || 0.01;
      const vol = rawVol.toFixed(2);
      const rawEntry = Number(pos.entry ?? pos.open_price ?? pos.entry_price ?? pos.price_open);
      const op = Number.isFinite(rawEntry) && rawEntry > 0 ? fmtPrice(rawEntry) : "—";

      if (t.positions.length > 1) {
        const totalPnl = t.positions.reduce((acc, p) => acc + (Number(p.pnl ?? p.last_profit ?? p.profit) || 0), 0);
        const totalPnlText = (totalPnl >= 0 ? "+$" : "-$") + Math.abs(totalPnl).toFixed(2);
        const totalLots = t.positions.reduce((acc, p) => acc + (Number(p.volume ?? p.size ?? p.lots) || 0), 0).toFixed(2);
        msg = `ACTIVE POSITIONS (${t.positions.length}): ${totalLots} Lots Total · Combined PnL ${totalPnlText} · Trailing Dynamic Guard Active`;
      } else {
        msg = `ACTIVE POSITION: ${dir} ${vol} Lots @ ${op} · PnL ${pnlText} · Trailing Dynamic Guard Active`;
      }
    } else {
      msg = `ACTIVE POSITION: ${t.open_trades} Posisi Terbuka · Trailing Dynamic Guard Active`;
    }
  } else if (d?.action && d.action !== "HOLD" && Math.abs(d.score || 0) >= 1.5) {
    level = "info";
    tag = "CONFLUENCE";
    const scoreStr = (d.score > 0 ? "+" : "") + d.score.toFixed(2);
    const confStr = Math.round((d.confidence || 0) * 100);
    msg = `HIGH CONFLUENCE: Setup ${d.action} (Score ${scoreStr}, Conf ${confStr}%) · Menunggu Validasi M1 Trigger`;
  }

  const perfHtml = buildDailyPerformanceTickerHtml(t);
  const fullHtml = `<span class="ticker-lead">${msg}</span>${perfHtml}`;

  // Update DOM attributes and text only when changed
  if (level) {
    if (tickerEl.dataset.level !== level) tickerEl.dataset.level = level;
  } else {
    if (tickerEl.dataset.level) delete tickerEl.dataset.level;
  }

  if (tagEl && tagEl.textContent !== tag) {
    tagEl.textContent = tag;
  }
  if (msgEl && msgEl.dataset.content !== fullHtml) {
    msgEl.dataset.content = fullHtml;
    msgEl.innerHTML = fullHtml;
  }
}

function setConn(stateName, label) {
  const dot = document.querySelector("#conn .dot");
  const lbl = document.querySelector("#conn .conn-label");
  if (dot) dot.dataset.state = stateName;
  if (lbl) lbl.textContent = label;
}

/* ------------------------------------------------------- sidebar collapse */
function toggleSidebar(forceState) {
  const shell = document.getElementById("app-shell");
  const btn = document.getElementById("sidebar-toggle");
  if (!shell) return;

  if (window.innerWidth <= 760) {
    const sidebar = document.querySelector(".sidebar");
    if (sidebar?.classList.contains("nav-drawer")) {
      closeMobileMenu();
    } else {
      openMobileMenu();
    }
    return;
  }

  const willCollapse = typeof forceState === "boolean"
    ? forceState
    : !shell.classList.contains("sidebar-collapsed");

  if (willCollapse) {
    shell.classList.add("sidebar-collapsed");
    localStorage.setItem("gs_sidebar_collapsed", "true");
    if (btn) {
      btn.innerHTML = icon("sidebar", 16);
      btn.title = "Expand Sidebar ([)";
      btn.setAttribute("aria-expanded", "false");
    }
  } else {
    shell.classList.remove("sidebar-collapsed");
    localStorage.setItem("gs_sidebar_collapsed", "false");
    if (btn) {
      btn.innerHTML = icon("sidebar", 16);
      btn.title = "Collapse Sidebar ([)";
      btn.setAttribute("aria-expanded", "true");
    }
  }
  // Dispatch resize event so LightweightCharts recalibrates width
  window.dispatchEvent(new Event("resize"));
}

function initSidebarState() {
  const collapsed = localStorage.getItem("gs_sidebar_collapsed") === "true";
  if (collapsed) toggleSidebar(true);

  document.getElementById("sidebar-toggle")?.addEventListener("click", () => toggleSidebar());
  document.getElementById("brand-header")?.addEventListener("click", () => toggleSidebar());

  window.addEventListener("keydown", (e) => {
    if (e.key === "[" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
      e.preventDefault();
      toggleSidebar();
    }
  });
}

/* ------------------------------------------------------------ user menu */
function setupUserMenu() {
  const chipBtn = document.getElementById("user-chip-btn");
  const menu = document.getElementById("user-menu");
  const accBtn = document.getElementById("menu-open-acc");
  const logoutBtn = document.getElementById("menu-logout");

  chipBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    menu?.classList.toggle("open");
  });

  document.addEventListener("click", (e) => {
    if (menu && !menu.contains(e.target) && !chipBtn?.contains(e.target)) {
      menu.classList.remove("open");
    }
  });

  accBtn?.addEventListener("click", () => {
    menu?.classList.remove("open");
    openAccountModal();
  });

  logoutBtn?.addEventListener("click", () => {
    menu?.classList.remove("open");
    logout();
  });
}

function updateUserDisplay(user) {
  currentUser = user;
  const emailEl = document.getElementById("user-display-email");
  const avatarEl = document.getElementById("user-avatar-initial");

  const email = user?.email || "Operator";
  if (emailEl) emailEl.textContent = email;
  if (avatarEl) {
    const initials = email.split("@")[0].substring(0, 2).toUpperCase();
    avatarEl.textContent = initials || "OP";
  }
}

/* ------------------------------------------------------------ auth portal */
let authMode = "login";

export function requireToken() {
  setToken("");
  localStorage.removeItem("gs_user");
  setConn("off", "no session");
  showAuthPortal();
}

function showAuthPortal() {
  const portal = document.getElementById("auth-portal");
  if (portal) {
    portal.style.display = "flex";
    setTimeout(() => document.getElementById("auth-email")?.focus(), 50);
  }
}

function hideAuthPortal() {
  const portal = document.getElementById("auth-portal");
  if (portal) portal.style.display = "none";
}

function setAuthMode(mode) {
  authMode = mode;
  const tabLogin = document.getElementById("tab-login");
  const tabReg = document.getElementById("tab-register");
  const fullNameField = document.getElementById("field-fullname");
  const submitBtn = document.getElementById("auth-submit-btn");
  const msgEl = document.getElementById("auth-msg");

  if (msgEl) msgEl.style.display = "none";

  if (mode === "register") {
    tabLogin?.classList.remove("active");
    tabReg?.classList.add("active");
    if (fullNameField) fullNameField.style.display = "flex";
    if (submitBtn) submitBtn.querySelector(".btn-text").textContent = "Create Account";
  } else {
    tabReg?.classList.remove("active");
    tabLogin?.classList.add("active");
    if (fullNameField) fullNameField.style.display = "none";
    if (submitBtn) submitBtn.querySelector(".btn-text").textContent = "Sign In";
  }
}

function setupAuthPortal() {
  const tabLogin = document.getElementById("tab-login");
  const tabReg = document.getElementById("tab-register");
  const form = document.getElementById("auth-form");
  const msgEl = document.getElementById("auth-msg");

  tabLogin?.addEventListener("click", () => setAuthMode("login"));
  tabReg?.addEventListener("click", () => setAuthMode("register"));

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("auth-email")?.value.trim();
    const password = document.getElementById("auth-password")?.value;
    const fullName = document.getElementById("auth-fullname")?.value.trim() || "";

    if (!email || !password) return;

    const submitBtn = document.getElementById("auth-submit-btn");
    if (submitBtn) submitBtn.disabled = true;
    if (msgEl) msgEl.style.display = "none";

    try {
      const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
      const payload = authMode === "register"
        ? { email, password, full_name: fullName }
        : { email, password };

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Authentication failed");
      }

      setToken(data.token);
      localStorage.setItem("gs_user", JSON.stringify(data.user));
      updateUserDisplay(data.user);
      hideAuthPortal();
      connectTelemetry();
      go("cockpit");
      primeStats();
      toast({
        title: authMode === "register" ? "Account created" : "Welcome back",
        text: `Logged in as ${data.user.email}`,
        type: "ok",
      });
    } catch (err) {
      if (msgEl) {
        msgEl.className = "auth-msg error";
        msgEl.textContent = err.message;
        msgEl.style.display = "block";
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

function logout() {
  setToken("");
  localStorage.removeItem("gs_user");
  currentUser = null;
  disconnectTelemetry();
  setConn("off", "no session");
  updateUserDisplay(null);
  showAuthPortal();
  toast({ title: "Signed out", type: "info" });
}

/* ------------------------------------------------------- account modal */
export async function openAccountModal() {
  let acc = null;
  try {
    const me = await api("/api/auth/me");
    acc = me.trading_account;
  } catch {
    /* ignore */
  }

  const body = document.createElement("div");
  body.style.display = "flex";
  body.style.flexDirection = "column";
  body.style.gap = "10px";
  body.innerHTML = `
    <p class="dim" style="font-size:12px;">Connect your personal Exness MT5 account. Consensus trades will execute on this account.</p>
    <div class="field">
      <label>Exness MT5 Login / Account #</label>
      <input class="input mono" id="acc-login" type="number" placeholder="434366152" value="${acc?.mt5_login || ""}" required />
    </div>
    <div class="field">
      <label>MT5 Trading Password</label>
      <input class="input mono" id="acc-pass" type="password" placeholder="${acc ? "•••••••• (leave blank to keep)" : "Trading password"}" />
    </div>
    <div class="field">
      <label>Exness Server</label>
      <input class="input mono" id="acc-server" type="text" placeholder="Exness-MT5Trial7" value="${esc(acc?.mt5_server || "Exness-MT5Trial7")}" required />
    </div>
    <div class="field">
      <label>Trading Lot Size</label>
      <input class="input mono" id="acc-lot" type="number" step="0.01" min="0.01" max="10" value="${acc?.lot_size || "0.01"}" required />
    </div>
    <div class="field" style="display:flex;align-items:center;gap:8px;margin-top:2px;">
      <input type="checkbox" id="acc-active" ${acc?.is_active !== false ? "checked" : ""} style="width:15px;height:15px;accent-color:var(--accent);" />
      <label for="acc-active" style="cursor:pointer;font-size:12px;user-select:none;">Enable bot execution on this account</label>
    </div>
  `;

  openModal({
    title: "Exness MT5 Account Configuration",
    body,
    actions: [
      { label: "Cancel" },
      {
        label: "Save Account",
        kind: "primary",
        onClick: async () => {
          const loginVal = parseInt(body.querySelector("#acc-login").value, 10);
          const passVal = body.querySelector("#acc-pass").value;
          const serverVal = body.querySelector("#acc-server").value.trim();
          const lotVal = parseFloat(body.querySelector("#acc-lot").value);
          const activeVal = body.querySelector("#acc-active").checked;

          if (!loginVal || !serverVal || Number.isNaN(lotVal)) {
            toast({ title: "Incomplete details", text: "Please enter account number and server.", type: "err" });
            return false;
          }

          try {
            await api("/api/auth/trading-account", {
              method: "POST",
              body: {
                mt5_login: loginVal,
                mt5_password: passVal,
                mt5_server: serverVal,
                risk_lot_mode: "fixed",
                lot_size: lotVal,
                is_active: activeVal,
              },
            });
            toast({ title: "Trading Account Configured", text: `Account #${loginVal} active.`, type: "ok" });
            return true;
          } catch (e) {
            toast({ title: "Save failed", text: e.message, type: "err" });
            return false;
          }
        },
      },
    ],
  });
}

/* --------------------------------------------------------- mobile menu */
function openMobileMenu() {
  const nav = document.querySelector(".sidebar");
  if (!nav) return;
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.style.zIndex = "55";
  document.body.appendChild(backdrop);
  nav.classList.add("nav-drawer");
  const close = () => {
    nav.classList.remove("nav-drawer");
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (e) => e.key === "Escape" && close();
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", onKey);
}
function closeMobileMenu() {
  document.querySelector(".sidebar")?.classList.remove("nav-drawer");
  document.querySelectorAll("body > .modal-backdrop").forEach((b) => b.remove());
}

/* ------------------------------------------------------------- wiring */
function wire() {
  document.getElementById("menu-btn")?.addEventListener("click", openMobileMenu);
  document.getElementById("toggle-run")?.addEventListener("click", async () => {
    const paused = state.telemetry?.paused ?? false;
    try {
      await api(paused ? "/api/control/resume" : "/api/control/pause", { method: "POST" });
      toast({ title: paused ? "Bot resumed" : "Bot paused", type: "ok" });
    } catch (e) {
      toast({ title: "Control failed", text: e.message, type: "err" });
    }
  });

  document.getElementById("algo-indicator")?.addEventListener("click", () => {
    const isAlgoOn = state.telemetry?.mt5_trade_allowed ?? true;
    toast({
      title: isAlgoOn ? "MT5 Algo Trading: ON" : "MT5 Algo Trading: OFF",
      text: isAlgoOn
        ? "Automated trading is active and permitted by MetaTrader 5 terminal."
        : "Automated trading is blocked in MT5 terminal. Press Ctrl+E in MT5 terminal.",
      type: isAlgoOn ? "ok" : "warn",
    });
  });

  onConnectionChange((ok) => {
    if (ok) setConn("on", "live");
    else if (!state.token) setConn("off", "no session");
    else setConn("off", "reconnecting");
  });

  subscribe(() => scheduleRender());

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) disconnectTelemetry();
    else if (state.token) connectTelemetry();
  });

  window.addEventListener("resize", () => updateCockpitTicker());

  window.addEventListener("popstate", () => {
    const target = resolveInitialTab();
    if (target !== current) {
      go(target, false);
    } else if (target === "cockpit") {
      const tabParam = (getUrlParam("tab") || getUrlParam("subtab") || "").toLowerCase();
      const mapped = COCKPIT_SUBTABS?.[tabParam];
      if (mapped && mapped !== VIEWS.cockpit?.activeTab) {
        VIEWS.cockpit.activeTab = mapped;
        const root = document.getElementById("view");
        if (root) VIEWS.cockpit.render(root);
      }
    }
  });

  window.addEventListener("hashchange", () => {
    const target = resolveInitialTab();
    if (target !== current) {
      go(target, false);
    } else if (target === "cockpit") {
      const tabParam = (getUrlParam("tab") || getUrlParam("subtab") || "").toLowerCase();
      const mapped = COCKPIT_SUBTABS?.[tabParam];
      if (mapped && mapped !== VIEWS.cockpit?.activeTab) {
        VIEWS.cockpit.activeTab = mapped;
        const root = document.getElementById("view");
        if (root) VIEWS.cockpit.render(root);
      }
    }
  });
}

/* --------------------------------------------------------- service worker */
function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("SW registration failed", e));
  });
}

/* ------------------------------------------------------------------ boot */
async function primeStats() {
  try {
    const r = await api("/api/performance");
    setState({ performance: r });
  } catch {
    /* fallback */
  }
}

async function verifyAndBoot() {
  if (!state.token) {
    setConn("off", "no session");
    showAuthPortal();
    return;
  }

  try {
    const me = await api("/api/auth/me");
    hideAuthPortal();
    updateUserDisplay(me.user);
    connectTelemetry();
    const initTab = resolveInitialTab();
    go(initTab, true);
    primeStats();
  } catch (err) {
    console.warn("Session verification failed", err);
    requireToken();
  }
}

function boot() {
  hydrateIcons(document);
  buildNav();
  initSidebarState();
  setupUserMenu();
  setupAuthPortal();
  wire();
  markNav();
  subscribe(scheduleRender);
  render();
  registerSW();
  verifyAndBoot();
}

boot();
