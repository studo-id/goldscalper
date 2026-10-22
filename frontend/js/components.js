// GoldScalper — UI primitives: icons, toast, modal, select, canvas charts, formatters.
// Vanilla ES module. No external icon/CDN dependency (inline lucide-style SVG).

/* ----------------------------------------------------------------- icons */
const ICONS = {
  goldLogo:
    '<path d="M411 121 L407 121 L200 329 L191 353 L191 457 L193 459 L348 307 L357 307 L407 357 L411 357 Z"/><path d="M327 37 L321 38 L169 189 L161 188 L111 138 L107 139 L107 374 L110 375 L319 165 L327 145 Z"/>',
  hexagon:
    '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="7.5 13.5 10.5 10.5 13.5 12.5 16.5 8.5"/>',
  menu: '<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>',
  gauge:
    '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  cpu:
    '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  radar:
    '<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/><path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/><path d="M12 18h.01"/><path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/><circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/>',
  trending:
    '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  book:
    '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  sliders:
    '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  pause:
    '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  up: '<line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/>',
  down: '<line x1="7" y1="7" x2="17" y2="17"/><polyline points="17 7 17 17 7 17"/>',
  wifi:
    '<path d="M12 20h.01"/><path d="M2 8.82a15 15 0 0 1 20 0"/><path d="M5 12.859a10 10 0 0 1 14 0"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/>',
  wifioff:
    '<line x1="2" y1="2" x2="22" y2="22"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/><path d="M5 12.859a10 10 0 0 1 5.17-2.69"/><path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/><path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/><path d="M12 20h.01"/>',
  alert:
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  refresh:
    '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  chevron: '<polyline points="6 9 12 15 18 9"/>',
  lock:
    '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  wallet:
    '<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5"/><path d="M16 12h.01"/>',
  target:
    '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  shield:
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  chart:
    '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
  clock:
    '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>',
  inbox:
    '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
  search:
    '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  user:
    '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  logout:
    '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  sidebar:
    '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
  chevronLeft: '<polyline points="15 18 9 12 15 6"/>',
  chevronRight: '<polyline points="9 18 15 12 9 6"/>',
  arrowDown: '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
  loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
};

export function icon(name, size = 18, sw = 1.75) {
  if (name === "goldLogo") {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 500 500" fill="currentColor" aria-hidden="true">${ICONS.goldLogo}</svg>`;
  }
  const body = ICONS[name] || ICONS.dot;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    const size = el.dataset.size ? Number(el.dataset.size) : 18;
    el.innerHTML = icon(el.dataset.icon, size);
  });
}

/* -------------------------------------------------------------- escaping */
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

/* ----------------------------------------------------------- formatters */
export function fmtPrice(v, dp = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}
export function getCurrency() {
  if (typeof window !== "undefined") {
    if (window.GS_CURRENCY) return window.GS_CURRENCY;
    if (window.GS_STATE?.currency) return window.GS_STATE.currency;
    if (window.GS_STATE?.telemetry?.currency) return window.GS_STATE.telemetry.currency;
  }
  return "USC";
}

export function fmtMoney(v, curr = null) {
  if (v == null || Number.isNaN(v)) return "—";
  const num = Number(v);
  const sign = num < 0 ? "-" : "";
  const cur = curr || getCurrency();
  const formatted = Math.abs(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (cur === "USC") {
    return `${sign}${formatted} USC`;
  }
  return `${sign}$${formatted}`;
}

export function fmtPnl(v, curr = null) {
  if (v == null || Number.isNaN(v)) return "—";
  const num = Number(v);
  const sign = num > 0 ? "+" : num < 0 ? "-" : "";
  const cur = curr || getCurrency();
  const formatted = Math.abs(num).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (cur === "USC") {
    return `${sign}${formatted} USC`;
  }
  return `${sign}$${formatted}`;
}
export function fmtPct(v, dp = 0) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(dp)}%`;
}
export function fmtNum(v, dp = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toFixed(dp);
}
export function pnlClass(v) {
  if (v == null || Number.isNaN(v)) return "zero";
  const num = Number(v);
  if (num > 0) return "pos";
  if (num < 0) return "neg";
  return "zero";
}
export function voteLabel(v) {
  if (v === 1 || v === "BUY" || v === "buy") return "BUY";
  if (v === -1 || v === "SELL" || v === "sell") return "SELL";
  return "HOLD";
}
export function voteClass(v) {
  const l = voteLabel(v);
  return l === "BUY" ? "buy" : l === "SELL" ? "sell" : "hold";
}
export function relTime(ts) {
  if (!ts) return "—";
  const t = typeof ts === "number" ? ts : Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function formatStreamingDuration(ts) {
  if (!ts) return "—";
  const t = typeof ts === "number" ? ts : Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  const totalSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  if (h > 0) {
    return `${h}h ${pad(m)}m ${pad(s)}s`;
  }
  if (m > 0) {
    return `${m}m ${pad(s)}s`;
  }
  return `${s}s`;
}

export function formatWIB(ts, includeSeconds = true) {
  if (!ts) return "—";
  const t = typeof ts === "number" ? ts : Date.parse(ts);
  if (Number.isNaN(t)) return "—";
  const d = new Date(t);
  const opt = {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  };
  if (includeSeconds) opt.second = "2-digit";
  return d.toLocaleString("id-ID", opt).replace(/\./g, ":") + " WIB";
}

/* -------------------------------------------------- Indonesian Veto Translator */
export function formatVetoReasonID(raw) {
  if (!raw) return "Ditolak Veto: Aturan manajemen risiko aktif (Standby)";
  let r = String(raw).trim();
  r = r.replace(/^Vetoed:\s*/i, "").replace(/^HARD VETO:\s*/i, "").trim();
  const lower = r.toLowerCase();

  // 1. TREND_ALIGNED_PING_PONG
  if (lower.includes("trend_aligned_ping_pong")) {
    if (lower.includes("buy") && lower.includes("bearish")) {
      const match = r.match(/\((\d+)\s+htf scouts opposing(?::\s*([^)]+))?\)/i);
      const scouts = match ? (match[2] ? ` (${match[2]})` : ` (${match[1]} analis HTF)`) : " (M15/M30/H4/D1)";
      return `Ditolak Veto: TREND_ALIGNED_PING_PONG · Order BUY melawan tren diblokir di area sideway karena tren makro HTF sedang BEARISH kuat${scouts}. Hanya diizinkan order SELL di resisten!`;
    }
    if (lower.includes("sell") && lower.includes("bullish")) {
      const match = r.match(/\((\d+)\s+htf scouts opposing(?::\s*([^)]+))?\)/i);
      const scouts = match ? (match[2] ? ` (${match[2]})` : ` (${match[1]} analis HTF)`) : "";
      return `Ditolak Veto: TREND_ALIGNED_PING_PONG · Order SELL melawan tren diblokir di area sideway karena tren makro HTF sedang BULLISH kuat${scouts}. Hanya diizinkan order BUY di support!`;
    }
    return `Ditolak Veto: TREND_ALIGNED_PING_PONG · Order melawan tren dilarang di area sideway. Hanya eksekusi searah tren besar yang diizinkan!`;
  }

  // 2. COUNTER_TREND_DEFENSE
  if (lower.includes("counter_trend_defense")) {
    if (lower.includes("buy") && lower.includes("bearish")) {
      return "Ditolak Veto (Mode Defense): Dilarang membuka order BUY melawan tren BEARISH H1/D1 demi melindungi modal!";
    }
    if (lower.includes("sell") && lower.includes("bullish")) {
      return "Ditolak Veto (Mode Defense): Dilarang membuka order SELL melawan tren BULLISH H1/D1 demi melindungi modal!";
    }
    return "Ditolak Veto (Mode Defense): Posisi melawan tren dilarang saat drawdown aktif!";
  }

  // 3. DYNAMIC DATA GATE / S/R Floor/Ceiling block
  if (lower.includes("dynamic data gate") || lower.includes("near support floor") || lower.includes("near resistance ceiling") || lower.includes("probing below support") || lower.includes("probing above resistance")) {
    if (lower.includes("support")) {
      const distMatch = r.match(/dist=([\d.]+)/i);
      const distInfo = distMatch ? ` (jarak ${distMatch[1]} USD)` : "";
      return `Ditolak Veto: S/R Dinamis · Dilarang SELL terlalu dekat dengan lantai support${distInfo} tanpa konfirmasi candle breakdown M5!`;
    }
    if (lower.includes("resistance")) {
      const distMatch = r.match(/dist=([\d.]+)/i);
      const distInfo = distMatch ? ` (jarak ${distMatch[1]} USD)` : "";
      return `Ditolak Veto: S/R Dinamis · Dilarang BUY terlalu dekat dengan atap resisten${distInfo} tanpa konfirmasi candle breakout M5!`;
    }
    return `Ditolak Veto: S/R Dinamis · Harga berada di zona batas kritis support/resisten tanpa konfirmasi tembus!`;
  }

  // 4. DAILY_PROFIT_LOCKED
  if (lower.includes("daily_profit_locked") || lower.includes("profit locked") || lower.includes("target achieved") || lower.includes("remaining target <= $0")) {
    return "Ditolak Veto: Target profit harian telah terkunci disiplin. Semua order spekulatif ditahan untuk mengamankan keuntungan!";
  }

  // 5. DAILY_LOSS_LIMIT / Circuit Breaker
  if (lower.includes("daily_loss") || lower.includes("max daily loss") || lower.includes("circuit breaker") || lower.includes("hard_loss_clamp")) {
    return "Ditolak Veto (Circuit Breaker): Batas toleransi kerugian harian tercapai. Trading ditangguhkan otomatis untuk melindungi modal!";
  }

  // 6. WAVE ENGINE COOLDOWN
  if (lower.includes("broken wave") || lower.includes("veto_wave") || lower.includes("wave cooldown")) {
    const sMatch = r.match(/(\d+)s remaining/i);
    const sRem = sMatch ? ` (${sMatch[1]} detik tersisa)` : "";
    return `Ditolak Veto: Wave Cooldown Aktif${sRem} · Gelombang tren terputus, menunggu struktur harga kembali stabil.`;
  }

  // 7. LOW CONFIDENCE
  if (lower.includes("low confidence") || lower.includes("consensus too weak") || lower.includes("conflicted")) {
    const confMatch = r.match(/([\d.]+)\s*<\s*([\d.]+)/i);
    const confDetail = confMatch ? ` (${confMatch[1]} < Syarat ${confMatch[2]})` : "";
    return `Ditolak Veto: Konsensus Terlalu Lemah${confDetail} · Petugas analis belum sepakat atau sinyal masih terbelah.`;
  }

  // 8. WIDE SPREAD
  if (lower.includes("wide spread") || lower.includes("spread_points") || lower.includes("spread too high")) {
    return "Ditolak Veto: Spread Broker Melebar · Biaya transaksi terlalu tinggi, menunggu spread kembali normal.";
  }

  // 9. NEWS BLACKOUT
  if (lower.includes("news blackout") || lower.includes("high impact news")) {
    return "Ditolak Veto: News Blackout · Berita ekonomi berdampak tinggi (High-Impact), order ditahan untuk menghindari lonjakan liar.";
  }

  // 10. D1 MACRO
  if (lower.includes("d1 macro") || lower.includes("d1_macro")) {
    return `Ditolak Veto: Tren Makro D1 · Sinyal harian berlawanan arah dengan arah trading yang diajukan.`;
  }

  // 11. Generic sentence replacement for anything else
  let translated = r
    .replace(/Blocked counter-trend BUY in range/gi, "Order BUY melawan tren diblokir di area sideway")
    .replace(/Blocked counter-trend SELL in range/gi, "Order SELL melawan tren diblokir di area sideway")
    .replace(/while macro HTF is strongly BEARISH/gi, "karena tren makro HTF sedang BEARISH kuat")
    .replace(/while macro HTF is strongly BULLISH/gi, "karena tren makro HTF sedang BULLISH kuat")
    .replace(/HTF scouts opposing/gi, "petugas HTF menolak")
    .replace(/Only SELL allowed at resistance!?/gi, "Hanya diizinkan order SELL di resisten!")
    .replace(/Only BUY allowed at support!?/gi, "Hanya diizinkan order BUY di support!")
    .replace(/Strictly prohibited from opening counter-trend/gi, "Dilarang keras membuka posisi melawan tren")
    .replace(/in Defense Mode/gi, "dalam Mode Defense")
    .replace(/against confirmed/gi, "melawan konfirmasi tren");

  return `Ditolak Veto: ${translated}`;
}


/* --------------------------------------------------------------- toast */
export function toast({ title, text = "", type = "info", timeout = 4200 }) {
  const root = document.getElementById("toast-root");
  if (!root) return;
  const iconName =
    type === "ok" ? "check" : type === "err" ? "alert" : type === "warn" ? "alert" : "zap";
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(iconName, 18)}<div class="toast-body"><div class="toast-title">${esc(title)}</div>${
    text ? `<div class="toast-text">${esc(text)}</div>` : ""
  }</div>`;
  root.appendChild(el);
  const kill = () => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 200);
  };
  const timer = setTimeout(kill, timeout);
  el.addEventListener("click", () => {
    clearTimeout(timer);
    kill();
  });
}

/* --------------------------------------------------------------- modal */
export function openModal({ title, body, actions = [], onClose }) {
  const root = document.getElementById("modal-root");
  root.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.style.display = "contents";
  wrap.innerHTML = `
    <div class="modal-backdrop" data-close></div>
    <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head">
        <h3>${esc(title)}</h3>
        <button class="modal-close" type="button" data-close aria-label="Close">${icon("x", 18)}</button>
      </div>
      <div class="modal-body"></div>
      ${actions.length ? '<div class="modal-foot"></div>' : ""}
    </div>`;
  const bodyEl = wrap.querySelector(".modal-body");
  if (typeof body === "string") bodyEl.innerHTML = body;
  else if (body instanceof Node) bodyEl.appendChild(body);

  const foot = wrap.querySelector(".modal-foot");
  const close = () => {
    root.classList.remove("open");
    root.innerHTML = "";
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose();
  };
  const onKey = (e) => e.key === "Escape" && close();

  actions.forEach((a) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `btn ${a.kind || ""}`;
    b.textContent = a.label;
    b.addEventListener("click", async () => {
      if (a.onClick) {
        const keep = await a.onClick(bodyEl);
        if (keep === false) return;
      }
      if (a.close !== false) close();
    });
    foot?.appendChild(b);
  });

  wrap.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  document.addEventListener("keydown", onKey);
  root.appendChild(wrap);
  root.classList.add("open");
  return { close, body: bodyEl };
}

/* ---------------------------------------------------- custom select */
export function createSelect({ options, value, onChange, ariaLabel = "Select" }) {
  const sel = document.createElement("div");
  sel.className = "select";
  const current = () => options.find((o) => o.value === value) || options[0];
  const render = () => {
    const c = current();
    sel.innerHTML = `
      <button class="select-btn" type="button" aria-haspopup="listbox" aria-label="${esc(ariaLabel)}">
        <span>${esc(c ? c.label : "")}</span>${icon("chevron", 16)}
      </button>
      <div class="select-list" role="listbox">
        ${options
          .map(
            (o) =>
              `<div class="select-opt" role="option" data-value="${esc(o.value)}" aria-selected="${
                o.value === value
              }">${esc(o.label)}</div>`,
          )
          .join("")}
      </div>`;
    sel.querySelector(".select-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      sel.classList.toggle("open");
    });
    sel.querySelector(".select-list")?.addEventListener("click", (e) => {
      e.stopPropagation();
    });
    sel.querySelectorAll(".select-opt").forEach((opt) =>
      opt.addEventListener("click", (e) => {
        e.stopPropagation();
        value = opt.dataset.value;
        sel.classList.remove("open");
        render();
        onChange && onChange(value);
      }),
    );
  };
  render();
  const onDoc = (e) => {
    if (!sel.contains(e.target)) sel.classList.remove("open");
  };
  document.addEventListener("click", onDoc);
  sel.destroy = () => document.removeEventListener("click", onDoc);
  return sel;
}

/* ------------------------------------------------------------ charts */
function setup(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 300;
  const h = canvas.clientHeight || 160;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

const COL = {
  line: "rgba(255,255,255,0.10)",
  text: "#8b93a1",
  accent: "#d9a441",
  up: "#36c98d",
  down: "#ef5f6b",
};

export function drawLine(canvas, values, { color = COL.accent, fill = true, pad = 6 } = {}) {
  const { ctx, w, h } = setup(canvas);
  if (!values || values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i) => pad + (i / (values.length - 1)) * (w - pad * 2);
  const y = (v) => h - pad - ((v - min) / span) * (h - pad * 2);

  // grid
  ctx.strokeStyle = COL.line;
  ctx.lineWidth = 1;
  for (let r = 0; r <= 3; r++) {
    const yy = Math.round(pad + (r / 3) * (h - pad * 2)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(pad, yy);
    ctx.lineTo(w - pad, yy);
    ctx.stroke();
  }

  // fill
  if (fill) {
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(217,164,65,0.18)");
    grad.addColorStop(1, "rgba(217,164,65,0)");
    ctx.beginPath();
    ctx.moveTo(x(0), y(values[0]));
    values.forEach((v, i) => ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(values.length - 1), h - pad);
    ctx.lineTo(x(0), h - pad);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // line
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();

  // last dot
  const lx = x(values.length - 1);
  const ly = y(values[values.length - 1]);
  ctx.beginPath();
  ctx.arc(lx, ly, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(lx, ly, 6.5, 0, Math.PI * 2);
  ctx.strokeStyle = color.replace(")", ", 0.35)").replace("rgb", "rgba");
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

export function drawEquity(canvas, points, { color = COL.accent, showEquity = true, showPnl = true } = {}) {
  if (canvas._cleanUpEquity) {
    canvas._cleanUpEquity();
    canvas._cleanUpEquity = null;
  }

  // Ensure at least one metric is enabled
  if (!showEquity && !showPnl) {
    showEquity = true;
  }

  if (!points || points.length < 2) {
    drawLine(canvas, [0, 0], { color });
    return;
  }
  const vals = points.map((p) => (typeof p === "object" && p !== null ? p.equity : p));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;

  // Max absolute trade PnL for scaling the histogram
  const maxAbsPnl = Math.max(...points.map((p) => Math.abs((p && p.pnl) || 0)), 1);

  // Layout Paddings for Axis Labels (Left for Y-Labels, Bottom for X-Time/Date)
  const padL = 64;
  const padR = 14;
  const padT = 16;
  const padB = 26;

  let cachedW = canvas.clientWidth || 300;
  let cachedH = canvas.clientHeight || 240;

  // Layout boundaries depending on active toggles
  const getEquityBottom = (h) => {
    if (showEquity && !showPnl) {
      return h - padB; // Full canvas height for equity
    }
    return padT + (h - padT - padB) * 0.67; // Split top zone
  };

  const getHistoTop = (h) => {
    if (!showEquity && showPnl) {
      return padT + 8; // Full canvas height for PnL
    }
    return padT + (h - padT - padB) * 0.73; // Split bottom zone
  };

  const getHistoBottom = (h) => h - padB - 2;

  const getX = (i, w = cachedW) => padL + (i / Math.max(1, vals.length - 1)) * (w - padL - padR);
  const getY = (v, h = cachedH) => {
    const eqBottom = getEquityBottom(h);
    const eqHeight = eqBottom - padT;
    return eqBottom - ((v - min) / span) * eqHeight;
  };

  const renderScene = (hoverIdx = -1) => {
    const { ctx, w, h } = setup(canvas);
    cachedW = w;
    cachedH = h;
    const x = (i) => getX(i, w);
    const y = (v) => getY(v, h);

    const eqBottom = getEquityBottom(h);
    const histoTop = getHistoTop(h);
    const histoBottom = getHistoBottom(h);
    const histoH = histoBottom - histoTop;
    const zeroY = Math.round(histoTop + histoH / 2) + 0.5;
    const halfH = Math.max(4, histoH / 2 - 3);

    // 1. Upper Zone: Equity Grid Lines & Currency Labels (if showEquity is on)
    if (showEquity) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
      ctx.lineWidth = 1;
      ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";

      const numYGrid = showPnl ? 3 : 4;
      for (let r = 0; r <= numYGrid; r++) {
        const ratio = r / numYGrid;
        const yy = Math.round(padT + ratio * (eqBottom - padT)) + 0.5;
        const yVal = max - ratio * span;

        ctx.beginPath();
        ctx.moveTo(padL, yy);
        ctx.lineTo(w - padR, yy);
        ctx.stroke();

        const cur = getCurrency();
        const isUSC = cur === "USC";
        ctx.fillStyle = "rgba(139, 147, 161, 0.75)";
        const yText = isUSC
          ? `${Math.round(yVal).toLocaleString("en-US")} USC`
          : (span < 10 ? `$${yVal.toFixed(2)}` : `$${Math.round(yVal).toLocaleString("en-US")}`);
        ctx.fillText(yText, padL - 8, yy);
      }
    }

    // 2. Zone Separator (Dotted Hairline between Equity and PnL Histogram)
    if (showEquity && showPnl) {
      ctx.save();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.07)";
      ctx.setLineDash([3, 4]);
      ctx.beginPath();
      ctx.moveTo(padL, Math.round(histoTop - 4) + 0.5);
      ctx.lineTo(w - padR, Math.round(histoTop - 4) + 0.5);
      ctx.stroke();
      ctx.restore();
    }

    // 3. Lower Zone: Trade PnL Histogram (if showPnl is on)
    if (showPnl) {
      // Zero baseline
      ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padL, zeroY);
      ctx.lineTo(w - padR, zeroY);
      ctx.stroke();

      // PnL Axis side labels & extra grid lines if in full PnL mode
      const cur = getCurrency();
      const isUSC = cur === "USC";
      ctx.font = "9px 'JetBrains Mono', ui-monospace, monospace";
      ctx.fillStyle = "rgba(139, 147, 161, 0.55)";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(isUSC ? "±0" : "±$0", padL - 8, zeroY);
      ctx.fillText(`+${Math.round(maxAbsPnl)}`, padL - 8, histoTop + 2);
      ctx.fillText(`-${Math.round(maxAbsPnl)}`, padL - 8, histoBottom - 1);

      if (!showEquity) {
        // Grid lines for full PnL view
        ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
        ctx.beginPath();
        ctx.moveTo(padL, histoTop + 2);
        ctx.lineTo(w - padR, histoTop + 2);
        ctx.moveTo(padL, histoBottom - 1);
        ctx.lineTo(w - padR, histoBottom - 1);
        ctx.stroke();
      }

      // Draw PnL Bars
      const stepX = (w - padL - padR) / Math.max(1, vals.length - 1);
      const barW = Math.max(2, Math.min(8, stepX * 0.65));

      points.forEach((pt, i) => {
        const pnl = typeof pt === "object" && pt !== null ? (pt.pnl || 0) : 0;
        const bx = x(i) - barW / 2;
        const barH = (Math.abs(pnl) / maxAbsPnl) * halfH;
        const isHover = hoverIdx === i;

        if (pnl >= 0) {
          ctx.fillStyle = isHover ? "#48cf9f" : "rgba(63, 182, 139, 0.70)";
          const by = zeroY - barH;
          ctx.fillRect(bx, by, barW, Math.max(1.5, barH));
        } else {
          ctx.fillStyle = isHover ? "#f06159" : "rgba(229, 83, 75, 0.70)";
          ctx.fillRect(bx, zeroY, barW, Math.max(1.5, barH));
        }
      });
    }

    // 4. X-Axis Time / Date Labels (Bottom)
    const numXTicks = w > 640 ? 5 : 3;
    ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
    ctx.textBaseline = "top";
    ctx.fillStyle = "rgba(139, 147, 161, 0.65)";

    for (let k = 0; k < numXTicks; k++) {
      const idx = Math.round((k / (numXTicks - 1)) * (vals.length - 1));
      const pt = points[idx];
      const xx = Math.round(x(idx));
      let label = "";
      if (typeof pt === "object" && pt !== null && pt.t) {
        try {
          const d = new Date(pt.t);
          if (!isNaN(d.getTime())) {
            label = d.toLocaleString("id-ID", {
              timeZone: "Asia/Jakarta",
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            }).replace(/\./g, ":");
          }
        } catch {}
      }
      if (!label) {
        label = `#${idx + 1}`;
      }

      if (k === 0) {
        ctx.textAlign = "left";
      } else if (k === numXTicks - 1) {
        ctx.textAlign = "right";
      } else {
        ctx.textAlign = "center";
      }

      ctx.fillText(label, xx, h - padB + 8);
    }

    // 5. Equity Curve Gradient Area Fill & Line (if showEquity is on)
    if (showEquity) {
      const grad = ctx.createLinearGradient(0, padT, 0, eqBottom);
      grad.addColorStop(0, "rgba(217,164,65,0.22)");
      grad.addColorStop(1, "rgba(217,164,65,0)");
      ctx.beginPath();
      ctx.moveTo(x(0), y(vals[0]));
      vals.forEach((v, i) => ctx.lineTo(x(i), y(v)));
      ctx.lineTo(x(vals.length - 1), eqBottom);
      ctx.lineTo(x(0), eqBottom);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      // Equity Line
      ctx.beginPath();
      vals.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.stroke();
    }

    // 6. Active / Hover Point or Last Point & Crosshair
    const activeIdx = hoverIdx >= 0 ? hoverIdx : vals.length - 1;
    const px = x(activeIdx);
    let py = padT;
    let dotColor = color;

    if (showEquity) {
      py = y(vals[activeIdx]);
      dotColor = color;
    } else if (showPnl) {
      const pnl = points[activeIdx]?.pnl || 0;
      const barH = (Math.abs(pnl) / maxAbsPnl) * halfH;
      py = pnl >= 0 ? zeroY - barH : zeroY + barH;
      dotColor = pnl >= 0 ? "#3fb68b" : "#e5534b";
    }

    const crosshairBottom = showPnl ? histoBottom : eqBottom;

    if (hoverIdx >= 0) {
      // vertical crosshair guide traversing through active charts
      ctx.save();
      ctx.beginPath();
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
      ctx.lineWidth = 1;
      ctx.moveTo(px, padT);
      ctx.lineTo(px, crosshairBottom);
      ctx.stroke();
      ctx.restore();

      // outer halo
      ctx.beginPath();
      ctx.arc(px, py, 7.5, 0, Math.PI * 2);
      ctx.fillStyle = dotColor === color ? "rgba(217, 164, 65, 0.30)" : "rgba(255, 255, 255, 0.15)";
      ctx.fill();

      // white ring
      ctx.beginPath();
      ctx.arc(px, py, 4.5, 0, Math.PI * 2);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // center dot
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = dotColor;
      ctx.fill();
    } else {
      // subtle pulse on the very last point
      ctx.beginPath();
      ctx.arc(px, py, 5.5, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(217, 164, 65, 0.35)";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fillStyle = dotColor;
      ctx.fill();
    }
  };

  // initial draw
  renderScene(-1);

  // setup interactive tooltip
  const wrap = canvas.parentElement;
  if (!wrap) return;

  let tooltip = wrap.querySelector(".equity-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "equity-tooltip";
    wrap.appendChild(tooltip);
  }

  const formatChartTime = (t) => {
    if (!t) return "";
    try {
      const d = new Date(t);
      if (isNaN(d.getTime())) return String(t);
      return (
        d.toLocaleString("id-ID", {
          timeZone: "Asia/Jakarta",
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }).replace(/\./g, ":") + " WIB"
      );
    } catch {
      return String(t);
    }
  };

  const handlePointer = (clientX) => {
    const rect = canvas.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const wrapWidth = wrapRect.width || canvas.clientWidth || 300;
    const wrapHeight = wrapRect.height || canvas.clientHeight || 240;

    const mx = clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, (mx - padL) / (wrapWidth - padL - padR)));
    const idx = Math.round(ratio * (vals.length - 1));
    const pt = points[idx];
    const val = vals[idx];

    renderScene(idx);

    if (tooltip) {
      const timeStr = typeof pt === "object" && pt !== null ? formatChartTime(pt.t) : "";
      const pnl = typeof pt === "object" && pt !== null ? pt.pnl : null;
      const cur = getCurrency();
      const isUSC = cur === "USC";
      const pnlText = pnl != null
        ? (pnl >= 0
            ? (isUSC ? `+${pnl.toFixed(2)} USC` : `+$${pnl.toFixed(2)}`)
            : (isUSC ? `-${Math.abs(pnl).toFixed(2)} USC` : `-$${Math.abs(pnl).toFixed(2)}`))
        : null;
      const pnlClass = pnl != null ? (pnl >= 0 ? "pos" : "neg") : "";

      let lines = `
        <div class="equity-tooltip-header">
          <span style="font-weight: 700; color: #fff;">#${idx + 1}</span>
          <span>${timeStr || `Point ${idx + 1}`}</span>
        </div>
      `;

      if (showEquity) {
        const eqStr = isUSC
          ? `${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USC`
          : `$${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        lines += `<div class="equity-tooltip-equity mono">${eqStr}</div>`;
      }

      if (showPnl && pnlText) {
        lines += `
          <div class="equity-tooltip-sub" style="${!showEquity ? 'margin-top: 4px;' : ''}">
            <span style="color: var(--fg-muted);">Trade PnL</span>
            <span class="mono ${pnlClass}" style="font-weight: 700; font-size: ${showEquity ? '12px' : '14px'};">${pnlText}</span>
          </div>
        `;
      }

      tooltip.innerHTML = lines;
      tooltip.classList.add("visible");

      const tooltipWidth = tooltip.offsetWidth || 155;
      const tooltipHeight = tooltip.offsetHeight || 72;

      const ptX = getX(idx, wrapWidth);
      let ptY = wrapHeight / 2;
      if (showEquity) {
        ptY = getY(val, wrapHeight);
      } else if (showPnl) {
        const histoH = getHistoBottom(wrapHeight) - getHistoTop(wrapHeight);
        const zeroY = Math.round(getHistoTop(wrapHeight) + histoH / 2) + 0.5;
        const halfH = Math.max(4, histoH / 2 - 3);
        const barH = (Math.abs(pnl || 0) / maxAbsPnl) * halfH;
        ptY = (pnl || 0) >= 0 ? zeroY - barH : zeroY + barH;
      }

      let left = ptX - tooltipWidth / 2;
      if (left < padL) left = padL;
      if (left + tooltipWidth > wrapWidth - padR) {
        left = wrapWidth - tooltipWidth - padR;
      }

      let top = ptY - tooltipHeight - 12;
      if (top < padT) {
        top = ptY + 14;
      }
      if (top + tooltipHeight > wrapHeight - padB) {
        top = wrapHeight - tooltipHeight - padB;
      }

      tooltip.style.left = `${Math.round(left)}px`;
      tooltip.style.top = `${Math.round(top)}px`;
    }
  };

  const onMouseMove = (e) => handlePointer(e.clientX);
  const onTouchMove = (e) => {
    if (e.touches && e.touches.length > 0) {
      handlePointer(e.touches[0].clientX);
    }
  };

  const onLeave = () => {
    renderScene(-1);
    if (tooltip) tooltip.classList.remove("visible");
  };

  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("mouseleave", onLeave);
  canvas.addEventListener("touchmove", onTouchMove, { passive: true });
  canvas.addEventListener("touchend", onLeave);
  canvas.addEventListener("touchcancel", onLeave);

  canvas._cleanUpEquity = () => {
    canvas.removeEventListener("mousemove", onMouseMove);
    canvas.removeEventListener("mouseleave", onLeave);
    canvas.removeEventListener("touchmove", onTouchMove);
    canvas.removeEventListener("touchend", onLeave);
    canvas.removeEventListener("touchcancel", onLeave);
    if (tooltip && tooltip.parentElement) {
      tooltip.remove();
    }
  };
}

export function drawRadar(canvas, { labels, values, max = 1 }) {
  const size = Math.min(canvas.clientWidth || 320, 360);
  canvas.style.height = `${size}px`;
  const { ctx, w, h } = setup(canvas);
  const cx = w / 2;
  const cy = h / 2;
  // Reserve generous horizontal margin so long axis labels (e.g. STRUCTURE, TECHNICAL) never clip
  const radius = Math.min(w / 2 - 76, h / 2 - 28);
  const n = labels.length;
  const angle = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pt = (i, r) => [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r];

  // rings
  ctx.strokeStyle = COL.line;
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring++) {
    const r = (radius * ring) / 4;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const [px, py] = pt(i % n, r);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.stroke();
  }
  // spokes
  for (let i = 0; i < n; i++) {
    const [px, py] = pt(i, radius);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(px, py);
    ctx.stroke();
  }

  // data polygon
  ctx.beginPath();
  values.forEach((v, i) => {
    const r = (Math.max(0, v) / max) * radius;
    const [px, py] = pt(i, r);
    i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
  });
  ctx.closePath();
  ctx.fillStyle = "rgba(217,164,65,0.16)";
  ctx.fill();
  ctx.strokeStyle = COL.accent;
  ctx.lineWidth = 2;
  ctx.stroke();

  // vertices
  values.forEach((v, i) => {
    const r = (Math.max(0, v) / max) * radius;
    const [px, py] = pt(i, r);
    ctx.beginPath();
    ctx.arc(px, py, 3, 0, Math.PI * 2);
    ctx.fillStyle = COL.accent;
    ctx.fill();
  });

  // labels
  ctx.fillStyle = COL.text;
  ctx.font = "600 9.5px 'Plus Jakarta Sans', sans-serif";
  labels.forEach((label, i) => {
    const [px, py] = pt(i, radius + 10);
    ctx.textAlign = Math.abs(px - cx) < 8 ? "center" : px > cx ? "left" : "right";
    ctx.textBaseline = Math.abs(py - cy) < 8 ? "middle" : py < cy ? "bottom" : "top";
    ctx.fillText(label.toUpperCase(), px, py);
  });
}

/* ------------------------------------------------------- state helpers */
export function loadingState(lines = 3) {
  let s = '<div class="panel">';
  for (let i = 0; i < lines; i++) s += '<div class="skeleton sk-line"></div>';
  return s + "</div>";
}
export function emptyState(title, text, iconName = "inbox") {
  return `<div class="state">${icon(iconName, 30)}<div class="state-title">${esc(
    title,
  )}</div><div class="state-text">${esc(text)}</div></div>`;
}
export function errorState(title, text, retryId = "") {
  return `<div class="state error">${icon("alert", 30)}<div class="state-title">${esc(
    title,
  )}</div><div class="state-text">${esc(text)}</div>${
    retryId ? `<button class="btn" id="${retryId}">${icon("refresh", 16)}Retry</button>` : ""
  }</div>`;
}
