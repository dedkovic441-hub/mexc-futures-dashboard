/* Open-position 15m candlestick charts for the MEXC futures paper dashboards. No deps. */
(function (global) {
  const CANDLE_S = 900;
  const NOTE = "No open trades";
  const cache = {}; // symbol|opened_at -> {bars, at}

  function ensureCss() {
    if (document.getElementById("mf-poscharts-css")) return;
    const s = document.createElement("style");
    s.id = "mf-poscharts-css";
    s.textContent = `
      .mf-poscharts{display:flex;flex-direction:column;gap:12px;margin-top:10px}
      .mf-pc{background:transparent;border:1px solid rgba(42,49,60,.9);border-radius:10px;padding:10px 10px 8px}
      .mf-pc-hd{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap}
      .mf-pc-hd a{color:inherit;font-weight:650;text-decoration:none}
      .mf-pc-hd a:hover{text-decoration:underline}
      .mf-pc-side{font-size:11px;font-weight:700;padding:1px 6px;border-radius:6px;margin-left:6px;letter-spacing:.02em}
      .mf-pc-side.short{background:rgba(248,81,73,.16);color:#f85149}
      .mf-pc-side.long{background:rgba(63,185,80,.16);color:#3fb950}
      .mf-pc-pnl{font-weight:650;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
      .mf-pc-pnl .pos{color:#3fb950}.mf-pc-pnl .neg{color:#f85149}
      .mf-pc-sub{color:#8b949e;font-size:12px;margin-top:2px;font-variant-numeric:tabular-nums}
      .mf-pc-lv{display:flex;flex-wrap:wrap;gap:2px 12px;color:#8b949e;font-size:11px;margin:6px 0 4px;font-variant-numeric:tabular-nums}
      .mf-pc-lv b{font-weight:600}
      .mf-pc-lv .ent{color:#58a6ff}.mf-pc-lv .tp{color:#3fb950}.mf-pc-lv .sl{color:#f85149}.mf-pc-lv .liq{color:#d2a8ff}.mf-pc-lv .mk{color:#e6edf3}
      .mf-pc canvas.mf-ohlc{width:100%;height:220px;display:block;margin:0;touch-action:none}
      .mf-pc-empty{color:#8b949e;padding:12px 0;text-align:center;font-size:13px}
      .mf-pc-wait{color:#8b949e;font-size:12px;padding:24px 0;text-align:center}
    `;
    document.head.appendChild(s);
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const base = (s) => String(s || "").replace(/_USDT$/, "");
  const href = (p) => p.url || ("https://futures.mexc.com/exchange/" + p.symbol);
  const n2 = (v, d) => (v == null || isNaN(v) ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const sg = (v, d) => (v == null ? "–" : (v > 0 ? "+" : "") + n2(v, d));
  function px(v) {
    if (v == null || isNaN(v)) return "–";
    const a = Math.abs(v);
    if (a >= 1000) return Number(v).toFixed(1);
    if (a >= 1) return Number(v).toFixed(4);
    if (a >= 0.01) return Number(v).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
    return Number(v).toPrecision(5).replace(/0+$/, "").replace(/\.$/, "");
  }
  function held(m, openedAt) {
    if (m == null && openedAt) m = (Date.now() / 1000 - openedAt) / 60;
    if (m == null || isNaN(m)) return "–";
    if (m < 60) return Math.max(0, Math.round(m)) + "m";
    if (m < 1440) return Math.floor(m / 60) + "h " + String(Math.round(m % 60)).padStart(2, "0") + "m";
    return (m / 1440).toFixed(1) + "d";
  }
  function wibParts(ts) {
    const d = new Date((ts + 7 * 3600) * 1000);
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    const day = d.getUTCDate();
    const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getUTCMonth()];
    return { hh, mm, day, mon, hm: hh + ":" + mm };
  }
  function wibHM(sOrTs) {
    if (sOrTs == null || sOrTs === "") return "–";
    const ts = typeof sOrTs === "number" ? sOrTs : Date.parse(sOrTs) / 1000;
    if (!ts) return "–";
    return wibParts(ts).hm;
  }
  function wibDT(sOrTs) {
    if (sOrTs == null || sOrTs === "") return "–";
    const ts = typeof sOrTs === "number" ? sOrTs : Date.parse(sOrTs) / 1000;
    if (!ts) return "–";
    const p = wibParts(ts);
    return p.day + " " + p.mon + " " + p.hm;
  }

  function applyMark(bars, mark, now) {
    if (!bars || !bars.length || mark == null || isNaN(mark)) return bars;
    const t0 = Math.floor((now || Date.now() / 1000) / CANDLE_S) * CANDLE_S;
    const last = bars[bars.length - 1];
    if (last.t === t0) {
      return bars.slice(0, -1).concat([{ t: last.t, o: last.o, h: Math.max(last.h, mark), l: Math.min(last.l, mark), c: mark }]);
    }
    if (t0 > last.t) {
      return bars.concat([{ t: t0, o: last.c, h: Math.max(last.c, mark), l: Math.min(last.c, mark), c: mark }]);
    }
    return bars;
  }
  function toBars(raw) {
    if (!raw || !raw.length) return [];
    return raw.map((r) => (Array.isArray(r) ? { t: +r[0], o: +r[1], h: +r[2], l: +r[3], c: +r[4] } : { t: +r.t, o: +r.o, h: +r.h, l: +r.l, c: +r.c }));
  }

  function yRange(bars, lines) {
    // Zoom to recent action plus Entry/TP/SL so a far-away liquidation line does not squash the trade.
    const use = bars.slice(-32);
    let lo = Infinity, hi = -Infinity;
    for (const b of use) { if (b.l < lo) lo = b.l; if (b.h > hi) hi = b.h; }
    const padAmt = (hi - lo) || Math.abs(hi) * 0.01 || 1e-9;
    const liqLo = lo - padAmt * 0.8, liqHi = hi + padAmt * 0.8;
    for (const ln of lines) {
      if (ln.price == null || isNaN(ln.price)) continue;
      if (ln.key === "liq" && (ln.price < liqLo || ln.price > liqHi)) { ln.off = true; continue; }
      if (ln.price < lo) lo = ln.price;
      if (ln.price > hi) hi = ln.price;
    }
    if (!isFinite(lo) || !isFinite(hi) || lo === hi) { const m = isFinite(lo) ? lo : 1; lo = m * 0.99; hi = m * 1.01; }
    const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.005;
    return { lo: lo - pad, hi: hi + pad };
  }

  function draw(canvas, bars, opt) {
    const dpr = window.devicePixelRatio || 1;
    const Wcss = canvas.clientWidth || 320, Hcss = canvas.clientHeight || 220;
    if (Wcss < 40) return;
    canvas.width = Math.round(Wcss * dpr);
    canvas.height = Math.round(Hcss * dpr);
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, Wcss, Hcss);
    const L = 52, R = 58, T = 8, B = 22;
    const W = Wcss - L - R, H = Hcss - T - B;
    if (W < 40 || H < 40) return;
    const lines = opt.lines || [];
    const yr = yRange(bars, lines);
    const t0 = bars[0].t, t1 = bars[bars.length - 1].t + CANDLE_S;
    const x = (t) => L + ((t - t0) / (t1 - t0 || 1)) * W;
    const y = (p) => T + (1 - (p - yr.lo) / (yr.hi - yr.lo || 1)) * H;
    const slot = W / Math.max(bars.length, 1);
    const cw = Math.max(1, Math.min(8, slot * 0.72));

    // grid
    g.strokeStyle = "rgba(42,49,60,.9)";
    g.lineWidth = 1;
    g.setLineDash([2, 3]);
    const ticks = 4;
    g.font = "10px ui-sans-serif,system-ui,sans-serif";
    g.fillStyle = "#8b949e";
    g.textAlign = "right";
    g.textBaseline = "middle";
    for (let i = 0; i <= ticks; i++) {
      const pv = yr.lo + (yr.hi - yr.lo) * (i / ticks);
      const yy = y(pv);
      g.beginPath(); g.moveTo(L, yy); g.lineTo(L + W, yy); g.stroke();
      g.fillText(px(pv), L - 4, yy);
    }
    g.setLineDash([]);

    // time labels
    g.textAlign = "center";
    g.textBaseline = "top";
    const nlab = Wcss < 400 ? 3 : 5;
    for (let i = 0; i < nlab; i++) {
      const t = t0 + ((t1 - t0) * i) / (nlab - 1 || 1);
      const ts = Math.floor(t / CANDLE_S) * CANDLE_S;
      g.fillText(wibParts(ts).hm, x(Math.min(Math.max(ts, t0), t1 - 1)), T + H + 4);
    }

    // candles
    for (const b of bars) {
      const xc = x(b.t + CANDLE_S / 2);
      const up = b.c >= b.o;
      g.strokeStyle = g.fillStyle = up ? "#3fb950" : "#f85149";
      g.beginPath();
      g.moveTo(xc, y(b.h));
      g.lineTo(xc, y(b.l));
      g.stroke();
      const y1 = y(b.o), y2 = y(b.c);
      const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
      g.fillRect(xc - cw / 2, top, cw, h);
    }

    // entry time marker
    if (opt.entryAt) {
      const et = Math.floor(opt.entryAt / CANDLE_S) * CANDLE_S;
      if (et >= t0 && et <= t1) {
        const xx = x(et + CANDLE_S / 2);
        g.strokeStyle = "rgba(88,166,255,.7)";
        g.lineWidth = 1;
        g.setLineDash([3, 3]);
        g.beginPath(); g.moveTo(xx, T); g.lineTo(xx, T + H); g.stroke();
        g.setLineDash([]);
        g.fillStyle = "#58a6ff";
        g.beginPath();
        g.moveTo(xx, T + H); g.lineTo(xx - 5, T + H + 6); g.lineTo(xx + 5, T + H + 6); g.closePath();
        g.fill();
      }
    }

    // price lines
    g.font = "10px ui-sans-serif,system-ui,sans-serif";
    g.textBaseline = "middle";
    const usedY = [];
    function placeY(yy) {
      let y0 = yy;
      for (let k = 0; k < 8; k++) {
        if (usedY.every((u) => Math.abs(u - y0) > 11)) { usedY.push(y0); return y0; }
        y0 = yy + (k % 2 === 0 ? 1 : -1) * (Math.floor(k / 2) + 1) * 11;
      }
      usedY.push(y0); return y0;
    }
    for (const ln of lines) {
      if (ln.price == null || ln.off) continue;
      const yy = y(ln.price);
      if (yy < T - 2 || yy > T + H + 2) continue;
      g.strokeStyle = ln.color;
      g.lineWidth = ln.key === "entry" ? 1.4 : 1;
      g.setLineDash(ln.dash || [5, 3]);
      g.beginPath(); g.moveTo(L, yy); g.lineTo(L + W, yy); g.stroke();
      g.setLineDash([]);
      const ly = placeY(Math.min(T + H, Math.max(T, yy)));
      g.fillStyle = ln.color;
      g.textAlign = "left";
      g.fillText(ln.label, L + W + 3, ly);
    }

    // last price tag
    const last = bars[bars.length - 1];
    if (last) {
      const yy = y(last.c);
      g.fillStyle = last.c >= last.o ? "#3fb950" : "#f85149";
      const label = px(last.c);
      g.font = "bold 10px ui-sans-serif,system-ui,sans-serif";
      const tw = g.measureText(label).width + 8;
      const ty = Math.min(T + H - 7, Math.max(T + 7, yy));
      g.fillRect(L + W - tw, ty - 7, tw, 14);
      g.fillStyle = "#0b0f14";
      g.textAlign = "right";
      g.fillText(label, L + W - 4, ty);
    }
  }

  function linesOf(p) {
    const entry = p.fill_px ?? p.entry;
    const out = [];
    if (entry != null) out.push({ key: "entry", price: +entry, color: "#58a6ff", label: "Entry", dash: [4, 3] });
    if (p.tp_px != null) out.push({ key: "tp", price: +p.tp_px, color: "#3fb950", label: "TP", dash: [6, 3] });
    if (p.sl_px != null) out.push({ key: "sl", price: +p.sl_px, color: "#f85149", label: "SL", dash: [6, 3] });
    if (p.liq_px != null) out.push({ key: "liq", price: +p.liq_px, color: "#d2a8ff", label: "Liq", dash: [2, 3] });
    return out;
  }

  function cardHtml(p) {
    const side = (p.side || "").toLowerCase();
    const opened = p.opened_wib || p.opened_at;
    const liqOff = (p._liqOff) ? " (off chart)" : "";
    return `<div class="mf-pc-hd">
      <div><a href="${esc(href(p))}" target="_blank" rel="noopener noreferrer">${esc(base(p.symbol))}</a>
        <span class="mf-pc-side ${esc(side)}">${side === "long" ? "LONG" : "SHORT"}</span>
        <div class="mf-pc-sub">Opened ${esc(wibDT(opened))} WIB · open ${esc(held(p.held_min, p.opened_at))}${p.leverage ? " · " + Number(p.leverage) + "×" : ""}</div>
      </div>
      <div class="mf-pc-pnl"><span class="${p.pnl_usdt > 0 ? "pos" : p.pnl_usdt < 0 ? "neg" : ""}">${sg(p.pnl_usdt, 2)} USDT</span>
        <div class="mf-pc-sub">${sg(p.pnl_pct, 2)}% on margin</div></div>
    </div>
    <div class="mf-pc-lv">
      <span class="ent">Entry <b>${px(p.fill_px ?? p.entry)}</b></span>
      <span class="mk">Mark <b>${px(p.mark)}</b></span>
      ${p.tp_px != null ? `<span class="tp">TP <b>${px(p.tp_px)}</b></span>` : `<span>TP <b>off</b></span>`}
      ${p.sl_px != null ? `<span class="sl">SL <b>${px(p.sl_px)}</b></span>` : `<span>SL <b>off</b></span>`}
      ${p.liq_px != null ? `<span class="liq">Liq <b>${px(p.liq_px)}</b>${liqOff}</span>` : ""}
    </div>
    <canvas class="mf-ohlc" height="220"></canvas>`;
  }

  function paintCard(el, p) {
    el._pos = p;
    if (!el._ro && typeof ResizeObserver !== "undefined") {
      el._ro = new ResizeObserver(() => { if (el._pos) paintCard(el, el._pos); });
      el._ro.observe(el);
    }
    const bars = applyMark(toBars(p.klines || p.bars || []), p.mark, Date.now() / 1000);
    const cv = el.querySelector("canvas.mf-ohlc");
    if (!cv) return;
    const Wcss = cv.clientWidth, Hcss = cv.clientHeight || 220, dpr = window.devicePixelRatio || 1;
    if (Wcss < 40) return; // layout not ready; ResizeObserver will retry
    const wantW = Math.round(Wcss * dpr), wantH = Math.round(Hcss * dpr);
    const sz = wantW + "x" + wantH + "x" + (p.mark || "") + "x" + (bars.length ? bars[bars.length-1].c : "") + "x" + (p._liqOff ? 1 : 0);
    if (sz === el._sz && cv.width === wantW && cv.height === wantH) return;
    if (!bars.length) {
      cv.width = wantW; cv.height = wantH;
      const g = cv.getContext("2d");
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, Wcss, Hcss);
      g.fillStyle = "#8b949e"; g.font = "12px sans-serif"; g.textAlign = "center";
      g.fillText(p._klineErr || "Loading 15m candles…", Wcss / 2, Hcss / 2);
      el._sz = sz;
      return;
    }
    const lns = linesOf(p);
    // pre-run range so we can flag liq off-chart in the caption
    yRange(bars, lns);
    const liq = lns.find((x) => x.key === "liq");
    if (liq && liq.off && !p._liqOff) {
      p._liqOff = true;
      el.innerHTML = cardHtml(p);
      return paintCard(el, p);
    }
    draw(el.querySelector("canvas.mf-ohlc"), bars, { lines: lns, entryAt: p.opened_at || (p.opened_wib ? Date.parse(p.opened_wib) / 1000 : null) });
    el._sz = sz;
  }

  async function loadKlines(p, loader) {
    const key = (p.symbol || "") + "|" + (p.opened_at || p.opened_wib || "");
    const hit = cache[key];
    const now = Date.now() / 1000;
    if (p.klines && p.klines.length && (!hit || now - hit.at < 120)) {
      cache[key] = { bars: p.klines, at: now };
      return p.klines;
    }
    if (hit && now - hit.at < 25) return hit.bars;
    if (!loader) return (hit && hit.bars) || p.klines || [];
    try {
      const bars = await loader(p.symbol, p);
      cache[key] = { bars: bars || [], at: Date.now() / 1000 };
      return bars || [];
    } catch (e) {
      p._klineErr = "Chart unavailable";
      return (hit && hit.bars) || [];
    }
  }

  function render(container, positions, opts) {
    ensureCss();
    const el = typeof container === "string" ? document.getElementById(container) : container;
    if (!el) return;
    const list = (positions || []).filter((p) => p && p.symbol);
    if (!list.length) {
      el.className = "mf-poscharts";
      el.innerHTML = `<div class="mf-pc-empty">${esc((opts && opts.emptyText) || NOTE)}</div>`;
      el._syms = "";
      return;
    }
    const sig = list.map((p) => p.symbol + ":" + (p.opened_at || p.opened_wib || "")).join(",");
    if (el._syms !== sig) {
      el.className = "mf-poscharts";
      el.innerHTML = list.map((p, i) => `<div class="mf-pc" data-i="${i}" data-sym="${esc(p.symbol)}">${cardHtml(p)}</div>`).join("");
      el._syms = sig;
    } else {
      list.forEach((p, i) => {
        const card = el.querySelector(`.mf-pc[data-i="${i}"]`);
        if (card) {
          const hd = card.querySelector(".mf-pc-hd");
          const lv = card.querySelector(".mf-pc-lv");
          const tmp = document.createElement("div");
          tmp.innerHTML = cardHtml(p);
          if (hd && tmp.querySelector(".mf-pc-hd")) hd.replaceWith(tmp.querySelector(".mf-pc-hd"));
          if (lv && tmp.querySelector(".mf-pc-lv")) lv.replaceWith(tmp.querySelector(".mf-pc-lv"));
        }
      });
    }
    list.forEach(async (p, i) => {
      const card = el.querySelector(`.mf-pc[data-i="${i}"]`);
      if (!card) return;
      if (!p.klines || !p.klines.length) p.klines = await loadKlines(p, opts && opts.loadKlines);
      const go = () => paintCard(card, p);
      go();
      requestAnimationFrame(go);
    });
  }

  global.MFPosCharts = { render, applyMark, toBars, px, held };
})(typeof window !== "undefined" ? window : globalThis);
