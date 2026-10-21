// GoldScalper — state store, REST client, telemetry websocket.

const TOKEN_KEY = "gs_token";

export const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  currency: localStorage.getItem("gs_currency") || "USC",
  connected: false,
  telemetry: null,
  decision: null,
  priceHistory: [],
  agentHealth: null,
  divisions: null,
  trades: null,
  performance: null,
  lessons: null,
};
if (typeof window !== "undefined") {
  window.GS_STATE = state;
  window.GS_CURRENCY = state.currency;
}

const listeners = new Set();
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function emit() {
  for (const fn of listeners) fn(state);
}
export function setState(patch) {
  Object.assign(state, patch);
  emit();
}
export function setToken(token) {
  state.token = token || "";
  if (state.token) localStorage.setItem(TOKEN_KEY, state.token);
  else localStorage.removeItem(TOKEN_KEY);
  emit();
}

/* ------------------------------------------------------------------ REST */
export async function api(path, { method = "GET", body, query } = {}) {
  const url = new URL(path, location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v != null) url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${state.token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    const e = new Error("unauthorized");
    e.code = 401;
    throw e;
  }
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j.detail || "";
    } catch {
      /* ignore */
    }
    const e = new Error(detail || `HTTP ${res.status}`);
    e.code = res.status;
    throw e;
  }
  if (res.status === 204) return null;
  return res.json();
}

/* ------------------------------------------------------------- telemetry */
let socket = null;
let retryTimer = null;
let pingTimer = null;
let statusListener = null;

export function onConnectionChange(fn) {
  statusListener = fn;
}
function setConnected(v) {
  if (state.connected !== v) {
    state.connected = v;
    emit();
  }
  statusListener && statusListener(v);
}

function ingest(d) {
  const patch = { telemetry: d };
  if (d.currency) {
    patch.currency = d.currency;
    if (typeof window !== "undefined") {
      window.GS_CURRENCY = d.currency;
    }
    localStorage.setItem("gs_currency", d.currency);
  }
  // telemetry carries a light decision; merge so the full record (votes/tradable)
  // fetched from /api/spk/latest is preserved field-by-field.
  if (d.decision) patch.decision = Object.assign({}, state.decision, d.decision);

  if (Array.isArray(d.positions)) {
    patch.trades = Object.assign({}, state.trades, { open: d.positions });
  } else if (state.trades?.open?.length && d.bid != null && d.ask != null) {
    // Ultra-responsive client-side tick interpolation for instant live streaming
    const updated = state.trades.open.map((pos) => {
      const isBuy = (pos.direction || pos.side || "BUY").toUpperCase() === "BUY";
      const curPrice = isBuy ? d.bid : d.ask;
      const entry = pos.entry ?? pos.open_price;
      const vol = pos.volume ?? pos.size ?? 0.01;
      let pnl = pos.pnl ?? pos.last_profit;
      if (entry && curPrice) {
        const diff = isBuy ? (curPrice - entry) : (entry - curPrice);
        // Standard Gold (XAUUSD) contract: 100 oz per 1.0 lot
        pnl = Number((diff * vol * 100).toFixed(2));
      }
      return Object.assign({}, pos, {
        price_current: curPrice,
        pnl: pnl,
      });
    });
    patch.trades = Object.assign({}, state.trades, { open: updated });
  }

  const price = d.bid ?? d.ask ?? null;
  if (price != null) {
    const hist = state.priceHistory.slice(-239);
    hist.push(price);
    patch.priceHistory = hist;
  }
  setState(patch);
}

function scheduleRetry() {
  clearTimeout(retryTimer);
  if (!state.token) return;
  retryTimer = setTimeout(connectTelemetry, 2000);
}

export function connectTelemetry() {
  if (!state.token) return;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/telemetry?token=${encodeURIComponent(state.token)}`;
  try {
    socket = new WebSocket(url);
  } catch {
    scheduleRetry();
    return;
  }
  socket.onopen = () => {
    setConnected(true);
    clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        try {
          socket.send("ping");
        } catch {
          /* ignore */
        }
      }
    }, 10000);
  };
  socket.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (!msg) return;
      if (msg.type === "telemetry") {
        ingest(msg.data);
      } else if (msg.type === "spk_decision") {
        setState({ decision: msg.data });
      }
    } catch {
      /* ignore malformed frame */
    }
  };
  socket.onclose = () => {
    clearInterval(pingTimer);
    setConnected(false);
    socket = null;
    scheduleRetry();
  };
  socket.onerror = () => {
    try {
      socket && socket.close();
    } catch {
      /* ignore */
    }
  };
}

export function disconnectTelemetry() {
  clearTimeout(retryTimer);
  clearInterval(pingTimer);
  if (socket) {
    socket.onclose = null;
    try {
      socket.close();
    } catch {
      /* ignore */
    }
    socket = null;
  }
  setConnected(false);
}

/* --------------------------------------------------------------- actions */
export async function pause() {
  return api("/api/control/pause", { method: "POST" });
}
export async function resume() {
  return api("/api/control/resume", { method: "POST" });
}
export async function panic() {
  return api("/api/control/panic", { method: "POST" });
}
export async function manualOrder(payload) {
  return api("/api/control/manual", { method: "POST", body: payload });
}
export async function closePosition(ticket) {
  return api(`/api/control/close?ticket=${encodeURIComponent(ticket)}`, { method: "POST" });
}
