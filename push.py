#!/usr/bin/env python3
"""Pusher for the public MEXC futures PAPER dashboard (GitHub Pages).
READ-ONLY on /workspace/mexc-futures: reads status.json, ledger.json, config.json, futuresd.pid
(and, optionally, the local dash history at 127.0.0.1:8798/api/history). Never calls watchdog.py.
Builds data.json and pushes it every PUSH_EVERY_S seconds. Repo history stays small: the data
lives in a single 'data snapshot' commit on top of the site commit, amended + force-pushed.
Usage: python3 push.py [--once] [--no-push]"""
import json, os, sys, time, subprocess, urllib.request, traceback
from datetime import datetime, timezone, timedelta

BOT = "/workspace/mexc-futures"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")            # gitignored, local only
HIST_FILE = os.path.join(STATE, "history.json")
WIB = timezone(timedelta(hours=7))
PUSH_EVERY_S = 120
SAMPLE_EVERY_S = 30
DATA_MSG = "data snapshot"
DASH_HIST = "http://127.0.0.1:8798/api/history"

def log(*a):
    print(datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB"), *a, flush=True)

def rj(name):
    with open(os.path.join(BOT, name)) as fh:
        return json.load(fh)

def iso_ts(s):
    try: return datetime.fromisoformat(s).timestamp()
    except Exception: return None

def daemon_alive():
    pid = None
    try:
        pid = int(open(os.path.join(BOT, "futuresd.pid")).read().strip())
        os.kill(pid, 0)
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="ignore")
        return pid, "futuresd.py" in cmd
    except Exception:
        return pid, False

# ---------- equity history (local, persisted in state/) ----------
def load_hist():
    try: return {float(k): v for k, v in json.load(open(HIST_FILE)).items()}
    except Exception: return {}

def save_hist(h):
    # compact: keep raw (<=30s) for last 6h, 5-min buckets older, max 30 days
    now = time.time(); out = {}
    for t in sorted(h):
        if t < now - 30 * 86400: continue
        key = t if t >= now - 6 * 3600 else (t // 300) * 300
        out[key] = h[t]
    tmp = HIST_FILE + ".tmp"
    with open(tmp, "w") as fh: json.dump({str(k): v for k, v in out.items()}, fh)
    os.replace(tmp, HIST_FILE)
    return out

def merge_dash_hist(h):
    try:
        for x in json.load(urllib.request.urlopen(DASH_HIST, timeout=5)):
            if x.get("eq") is not None: h.setdefault(float(x["t"]), [x["eq"], x.get("bal")])
    except Exception:
        pass

def sample(h):
    try:
        st = rj("status.json"); t = iso_ts(st.get("heartbeat_wib") or "")
        if t and st.get("equity_usdt") is not None:
            h[float(t)] = [st["equity_usdt"], st.get("balance_usdt")]
    except Exception:
        pass

def downsample(h, since):
    now = time.time(); bk = {}
    for t in sorted(h):
        if t < since: continue
        step = 60 if t >= now - 3 * 3600 else 900  # 1-min for last 3h, 15-min older
        bk[(t // step) * step] = (t, h[t])
    return [[int(t), round(v[0], 4), round(v[1], 4) if v[1] is not None else None] for t, v in (bk[k] for k in sorted(bk))]

# ---------- snapshot ----------
def build(h):
    st = rj("status.json"); led = rj("ledger.json")
    try: cfg = rj("config.json")
    except Exception: cfg = {}
    pid, alive = daemon_alive()
    now = time.time(); hb = iso_ts(st.get("heartbeat_wib") or "")
    led_open = led.get("open") or {}
    opn = []
    for p in st.get("open_positions") or led.get("open_positions") or []:
        lo = led_open.get(p["symbol"], {})
        opn.append({
            "symbol": p["symbol"], "side": p.get("side"), "entry": p.get("fill_px"), "mark": p.get("mark"),
            "pnl_usdt": p.get("pnl_usdt"), "pnl_pct": p.get("pnl_pct"), "liq_px": p.get("liq_px") or p.get("stop_px"),
            "leverage": p.get("leverage"), "notional_usdt": p.get("notional_usdt"), "held_min": p.get("held_min"),
            "opened_wib": lo.get("opened_wib") or p.get("opened_wib"), "opened_at": lo.get("opened_at") or p.get("opened_at"),
        })
    closed_all = led.get("closed") or []
    closed = [{
        "symbol": c["symbol"], "side": c.get("side"), "entry": c.get("entry_fill_px"), "exit": c.get("exit_fill_px"),
        "pnl_usdt": c.get("pnl_usdt"), "pnl_pct": c.get("pnl_pct"), "reason": c.get("reason"),
        "opened_wib": c.get("opened_wib"), "closed_wib": c.get("closed_wib"), "closed_at": c.get("closed_at"),
        "held_min": c.get("held_min"), "funding_usdt": c.get("funding_usdt"),
    } for c in closed_all[-100:]][::-1]
    wins = sum(1 for c in closed_all if (c.get("pnl_usdt") or 0) > 0)
    port = cfg.get("portfolio", {})
    r0 = iso_ts(led.get("created") or "") or 0
    return {
        "generated_at": datetime.now(WIB).isoformat(timespec="seconds"), "generated_ts": int(now),
        "paper_only": True, "push_every_s": PUSH_EVERY_S,
        "daemon": {"alive": alive, "pid": pid, "heartbeat_wib": st.get("heartbeat_wib"),
                   "heartbeat_age_s": round(now - hb, 1) if hb else None, "uptime_s": st.get("uptime_s"),
                   "last_eval_wib": st.get("last_eval_wib"), "errors": st.get("errors"), "http_errors": st.get("http_errors")},
        "snapshot": {
            "equity_usdt": st.get("equity_usdt"), "balance_usdt": st.get("balance_usdt"),
            "realized_usdt": st.get("realized_usdt"), "unrealized_usdt": st.get("unrealized_usdt"),
            "today_wib": st.get("today_wib"), "today_pnl_usdt": st.get("today_pnl_usdt"),
            "today_realized_usdt": st.get("today_realized_usdt"),
            "open_count": st.get("open_count", len(opn)), "max_open": port.get("max_concurrent"),
            "starting_balance_usdt": led.get("starting_balance_usdt"), "margin_used_usdt": led.get("margin_used_usdt"),
            "ledger_created_wib": led.get("created"), "ledger_updated_wib": led.get("updated"),
            "strategy": st.get("strategy"), "leverage": port.get("leverage"), "stake_usdt": port.get("stake_usdt"),
        },
        "stats": {"closed_trades": len(closed_all), "wins": wins,
                  "win_rate": round(100 * wins / len(closed_all), 1) if closed_all else None,
                  "closed_pnl_usdt": round(sum(c.get("pnl_usdt") or 0 for c in closed_all), 4)},
        "daily_realized": {k: round(v, 4) for k, v in (led.get("daily_realized") or {}).items()},
        "open": opn, "closed": closed,
        "history": downsample(h, r0),
    }

# ---------- git ----------
def git(*a, check=True):
    r = subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True, timeout=120)
    if check and r.returncode: raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()[:400]}")
    return r.stdout.strip()

def push():
    if git("log", "-1", "--format=%s") == DATA_MSG:
        git("reset", "--soft", "HEAD~1")          # drop previous data commit, keep site commit(s)
    git("add", "data.json")
    git("-c", "user.name=mexc-futures-pusher", "-c", "user.email=pusher@users.noreply.github.com",
        "commit", "-q", "-m", DATA_MSG, "--", "data.json")
    git("push", "-q", "--force", "origin", "HEAD:main")

def write_data(h):
    d = build(h)
    tmp = os.path.join(HERE, "data.json.tmp")
    with open(tmp, "w") as fh: json.dump(d, fh, separators=(",", ":"))
    os.replace(tmp, os.path.join(HERE, "data.json"))
    return d

def main():
    os.makedirs(STATE, exist_ok=True)
    once = "--once" in sys.argv; nopush = "--no-push" in sys.argv
    h = load_hist(); merge_dash_hist(h); sample(h); h = save_hist(h)
    last_push = 0; fails = 0
    while True:
        try:
            sample(h)
            if time.time() - last_push >= PUSH_EVERY_S or once:
                merge_dash_hist(h); h = save_hist(h)
                d = write_data(h)
                if not nopush: push()
                last_push = time.time(); fails = 0
                log(f"pushed eq={d['snapshot']['equity_usdt']} open={d['snapshot']['open_count']} alive={d['daemon']['alive']} hist={len(d['history'])}")
        except Exception as e:
            fails += 1; last_push = time.time() - PUSH_EVERY_S + 30 * min(fails, 4)  # retry sooner
            log("ERROR", repr(e)); traceback.print_exc()
        if once: break
        time.sleep(SAMPLE_EVERY_S)

if __name__ == "__main__":
    main()
