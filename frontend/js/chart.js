// GoldScalper — Realtime Candlestick Chart using LightweightCharts.
// Handles historical candle fetching, live tick candle updates, position price lines,
// timeframe switching, crosshair telemetry, and responsive resize.

import { api, state } from "./ws.js";
import { esc, fmtPrice, icon } from "./components.js";

const TF_SECONDS = {
  M1: 60,
  M5: 300,
  M15: 900,
  M30: 1800,
  H1: 3600,
  H4: 14400,
  D1: 86400,
};

export class PriceChart {
  constructor(container, { onCrosshairMove } = {}) {
    this.container = container;
    this.onCrosshairMove = onCrosshairMove;
    this.chart = null;
    this.series = null;
    this.currentTf = "M1";
    this.currentBar = null;
    this.positionLines = [];
    this.resizeObserver = null;
    this.isLoading = false;
    this.hasData = false;
    this.bars = [];
    this.isFetchingOlder = false;
    this.hasMoreOlder = true;

    this.init();
  }

  init() {
    if (!window.LightweightCharts) {
      console.error("LightweightCharts is not loaded");
      this.renderError("Chart library failed to load");
      return;
    }

    this.container.innerHTML = "";
    const chartEl = document.createElement("div");
    chartEl.className = "lw-chart-canvas";
    chartEl.style.width = "100%";
    chartEl.style.height = "100%";
    this.container.appendChild(chartEl);

    this.chart = window.LightweightCharts.createChart(chartEl, {
      width: this.container.clientWidth || 600,
      height: this.container.clientHeight || 340,
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: "#8b93a1",
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.03)" },
        horzLines: { color: "rgba(255, 255, 255, 0.03)" },
      },
      crosshair: {
        vertLine: {
          color: "rgba(255, 255, 255, 0.25)",
          width: 1,
          style: 3,
          labelBackgroundColor: "#1e2227",
        },
        horzLine: {
          color: "rgba(255, 255, 255, 0.25)",
          width: 1,
          style: 3,
          labelBackgroundColor: "#1e2227",
        },
      },
      rightPriceScale: {
        borderColor: "rgba(255, 255, 255, 0.06)",
        scaleMargins: {
          top: 0.12,
          bottom: 0.12,
        },
        autoScale: true,
      },
      timeScale: {
        borderColor: "rgba(255, 255, 255, 0.06)",
        timeVisible: true,
        secondsVisible: false,
        shiftVisibleRangeOnNewBar: true,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    this.series = this.chart.addCandlestickSeries({
      upColor: "#3fb68b",
      downColor: "#e5534b",
      borderVisible: false,
      wickUpColor: "#3fb68b",
      wickDownColor: "#e5534b",
      priceFormat: {
        type: "price",
        precision: 2,
        minMove: 0.01,
      },
    });

    if (this.onCrosshairMove) {
      this.chart.subscribeCrosshairMove((param) => {
        if (!param || !param.time || !param.seriesData) {
          this.onCrosshairMove(null);
          return;
        }
        const data = param.seriesData.get(this.series);
        this.onCrosshairMove(data || null);
      });
    }

    // Subscribe to visible range changes for dynamic backward paging
    this.chart.timeScale().subscribeVisibleLogicalRangeChange((newRange) => {
      if (!newRange || this.isLoading || this.isFetchingOlder || !this.hasMoreOlder) return;
      // When scrolling near the left boundary of existing candles
      if (newRange.from < 20) {
        this.loadOlderCandles();
      }
    });

    this.resizeObserver = new ResizeObserver((entries) => {
      if (!entries || !entries.length || !this.chart) return;
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        this.chart.applyOptions({ width, height });
      }
    });
    this.resizeObserver.observe(this.container);
  }

  async load(timeframe = "M1") {
    this.currentTf = timeframe.toUpperCase();
    this.isLoading = true;
    this.isFetchingOlder = false;
    this.hasMoreOlder = true;
    this.bars = [];
    this.renderLoading(true);

    try {
      const data = await api(`/api/candles?tf=${encodeURIComponent(this.currentTf)}&limit=600`);
      this.renderLoading(false);
      if (!this.series || !this.chart) return;

      if (!data || !data.candles || !data.candles.length) {
        this.hasData = false;
        this.renderEmpty();
        return;
      }

      this.hasData = true;
      // Sort ascending by time (Unix timestamp in seconds)
      const formatted = data.candles
        .map((c) => ({
          time: Number(c.time),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        }))
        .sort((a, b) => a.time - b.time);

      // Deduplicate times if any
      const uniqueBars = [];
      let lastTime = 0;
      for (const b of formatted) {
        if (b.time > lastTime) {
          uniqueBars.push(b);
          lastTime = b.time;
        } else if (b.time === lastTime && uniqueBars.length) {
          uniqueBars[uniqueBars.length - 1] = b;
        }
      }

      this.bars = uniqueBars;
      this.series.setData(uniqueBars);
      this.currentBar = uniqueBars.length ? { ...uniqueBars[uniqueBars.length - 1] } : null;
      this.chart.timeScale().fitContent();

      // Update positions
      this.updatePositions();
    } catch (err) {
      console.warn("Failed to load candles:", err);
      this.renderLoading(false);
      this.renderError(err.message || "Failed to load candle history");
    } finally {
      this.isLoading = false;
    }
  }

  async loadOlderCandles() {
    if (this.isFetchingOlder || !this.hasMoreOlder || !this.bars || !this.bars.length) return;
    this.isFetchingOlder = true;
    const reqTf = this.currentTf;

    try {
      const earliestTime = this.bars[0].time;
      const data = await api(
        `/api/candles?tf=${encodeURIComponent(reqTf)}&limit=500&before=${earliestTime}`
      );
      if (this.currentTf !== reqTf || !this.series || !this.chart) return;

      if (!data || !data.candles || !data.candles.length) {
        this.hasMoreOlder = false;
        return;
      }

      const formatted = data.candles
        .map((c) => ({
          time: Number(c.time),
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        }))
        .filter((c) => c.time < earliestTime)
        .sort((a, b) => a.time - b.time);

      if (!formatted.length) {
        this.hasMoreOlder = false;
        return;
      }

      // Deduplicate ascending
      const newBars = [];
      let lastTime = 0;
      for (const b of formatted) {
        if (b.time > lastTime && b.time < earliestTime) {
          newBars.push(b);
          lastTime = b.time;
        }
      }

      if (!newBars.length) {
        this.hasMoreOlder = false;
        return;
      }

      const addedCount = newBars.length;
      const merged = [...newBars, ...this.bars];
      this.bars = merged;

      // Preserve visible logical range so user's scrolling view remains smooth without jumping
      const currentRange = this.chart.timeScale().getVisibleLogicalRange();
      this.series.setData(merged);
      if (currentRange) {
        this.chart.timeScale().setVisibleLogicalRange({
          from: currentRange.from + addedCount,
          to: currentRange.to + addedCount,
        });
      }

      if (addedCount < 15) {
        this.hasMoreOlder = false;
      }
    } catch (err) {
      console.warn("Failed to load older candles:", err);
    } finally {
      this.isFetchingOlder = false;
    }
  }

  pushTick(bid, ask, ts) {
    if (!this.series || !bid) return;
    const price = Number(bid.toFixed(2));
    const tfSec = TF_SECONDS[this.currentTf] || 60;
    const nowSec = ts ? Math.floor(new Date(ts).getTime() / 1000) : Math.floor(Date.now() / 1000);
    const barTime = nowSec - (nowSec % tfSec);

    if (!this.currentBar) {
      this.currentBar = {
        time: barTime,
        open: price,
        high: price,
        low: price,
        close: price,
      };
      this.bars.push(this.currentBar);
      this.series.update(this.currentBar);
      return;
    }

    if (barTime > this.currentBar.time) {
      // New bar
      this.currentBar = {
        time: barTime,
        open: price,
        high: price,
        low: price,
        close: price,
      };
      this.bars.push(this.currentBar);
    } else {
      // Update existing bar
      this.currentBar.high = Math.max(this.currentBar.high, price);
      this.currentBar.low = Math.min(this.currentBar.low, price);
      this.currentBar.close = price;
      if (this.bars.length) {
        this.bars[this.bars.length - 1] = { ...this.currentBar };
      }
    }

    try {
      this.series.update(this.currentBar);
    } catch (e) {
      // Time ordering guard
      console.debug("chart update skipped:", e);
    }
  }

  setPositions(positions = []) {
    this._positions = positions;
    this.updatePositions();
  }

  updatePositions() {
    if (!this.series) return;
    // Clear existing price lines
    for (const line of this.positionLines) {
      try {
        this.series.removePriceLine(line);
      } catch {
        /* ignore */
      }
    }
    this.positionLines = [];

    const list = this._positions || state.trades?.open || [];
    for (const p of list) {
      const entry = p.entry ?? p.open_price;
      if (entry == null) continue;
      const side = (p.direction || p.side || "BUY").toUpperCase();
      const isBuy = side === "BUY";
      const vol = p.size ?? p.volume ?? "0.10";

      const line = this.series.createPriceLine({
        price: Number(entry),
        color: isBuy ? "#3fb68b" : "#e5534b",
        lineWidth: 1,
        lineStyle: 2, // LineStyle.Dashed
        axisLabelVisible: true,
        title: `${side} ${vol}`,
      });
      this.positionLines.push(line);
    }
  }

  renderLoading(show) {
    let el = this.container.querySelector(".chart-loading-overlay");
    if (show) {
      if (!el) {
        el = document.createElement("div");
        el.className = "chart-loading-overlay";
        el.innerHTML = `<div class="chart-shimmer"></div>`;
        this.container.appendChild(el);
      }
    } else if (el) {
      el.remove();
    }
  }

  renderEmpty() {
    let el = this.container.querySelector(".chart-empty-overlay");
    if (!el) {
      el = document.createElement("div");
      el.className = "chart-empty-overlay";
      el.innerHTML = `
        <div class="state">
          ${icon("chart", 28)}
          <div class="state-title">No candle data</div>
          <div class="state-text">Waiting for market data stream to populate historical rates.</div>
        </div>
      `;
      this.container.appendChild(el);
    }
  }

  renderError(msg) {
    let el = this.container.querySelector(".chart-error-overlay");
    if (!el) {
      el = document.createElement("div");
      el.className = "chart-error-overlay";
      el.innerHTML = `
        <div class="state error">
          ${icon("alert", 28)}
          <div class="state-title">Chart unavailable</div>
          <div class="state-text">${esc(msg)}</div>
          <button class="btn" id="chart-retry-btn" type="button">
            ${icon("refresh", 14)}
            <span>Retry</span>
          </button>
        </div>
      `;
      this.container.appendChild(el);
      el.querySelector("#chart-retry-btn")?.addEventListener("click", () => {
        el.remove();
        this.load(this.currentTf);
      });
    }
  }

  destroy() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.chart) {
      this.chart.remove();
      this.chart = null;
      this.series = null;
    }
    this.container.innerHTML = "";
  }
}
