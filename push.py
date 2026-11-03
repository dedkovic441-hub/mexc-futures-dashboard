#!/usr/bin/env python3
"""Pusher for the public MEXC futures PAPER dashboard (GitHub Pages).
Reads /workspace/mexc-futures status.json, ledger.json, config.json, futuresd.pid (and the local dash history at
127.0.0.1:8798/api/history). Never calls watchdog.py. Its ONLY write there: config.json strategy.take_profit_usdt /
stop_loss_usdt / tp_cooldown_minutes, via dash/server.py's validate()+save_settings() (atomic, locked, backup
config.json.bak-settings-last), when the repo's settings.json changes.
Every SAMPLE_EVERY_S: git fetch origin main + settings. Settings live on the dedicated branch 'settings' (file settings.json),
which this script NEVER force-pushes; it only reads it, and mirror writes are normal commits via the GitHub contents API
(gh api PUT with the current blob sha; a 409 means the user just edited it -> their edit wins next cycle).
main's settings.json is only a stub pointing to that branch. Settings sync (state in state/settings_sync.json):
  - origin/settings:settings.json hash != last processed hash -> user edit: validate (same rules as /api/settings, keys starting
    with '_' ignored); valid -> apply to config.json; invalid -> not applied, error shown on the page. GitHub wins.
  - else if config.json values != last synced values (local panel save) -> mirror them into settings.json (contents API commit).
Push (every PUSH_EVERY_S, or at once after a settings event): data lives in one 'data snapshot' commit by
mexc-futures-pusher on top of origin/main. If origin's tip is that commit it is replaced (parent = its parent),
otherwise (a user commit is on top) the new data commit goes on top of origin's tip. Pushed with
--force-with-lease=<fetched origin sha>, so a user commit made in between is never overwritten (push fails, retried).
Usage: python3 push.py [--once] [--no-push]"""
import json, os, sys, time, subprocess, urllib.request, traceback, hashlib, importlib.util
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
PUSHER_NAME = "mexc-futures-pusher"; PUSHER_EMAIL = "pusher@users.noreply.github.com"
SETTINGS = "settings.json"; SYNC_FILE = os.path.join(STATE, "settings_sync.json")
REPO = "dedkovic441-hub/mexc-futures-dashboard"; SET_BRANCH = "settings"
EDIT_URL = f"https://github.com/{REPO}/edit/{SET_BRANCH}/settings.json"
SET_HELP = ("Edit the 3 values below and commit: take_profit_usdt = net USDT profit that closes a trade (>0, <=1000); "
            "stop_loss_usdt = net USDT loss that closes a trade (null or 0 = off, max 1000); tp_cooldown_minutes = block "
            "re-entry in a coin for N minutes after it closed via take profit (0 = off, max 10080 = 7 days). "
            "Applied to the paper bot within ~1 min; invalid values are rejected and shown on the page.")

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

# ---------- settings sync ----------
_SRV = None
def srv():
    global _SRV
    if _SRV is None:
        sp = importlib.util.spec_from_file_location("mf_dash_server", os.path.join(BOT, "dash", "server.py"))
        m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); _SRV = m
    return _SRV
def wib_now(): return datetime.now(WIB).isoformat(timespec="seconds")
def sha(t): return hashlib.sha256(t.encode()).hexdigest()
def load_sync():
    try: return json.load(open(SYNC_FILE))
    except Exception: return {}
def save_sync(st):
    tmp = SYNC_FILE + ".tmp"
    with open(tmp, "w") as fh: json.dump(st, fh, indent=1)
    os.replace(tmp, SYNC_FILE)
def config_values():
    with open(os.path.join(BOT, "config.json")) as fh: return srv().current_settings(json.load(fh))
def settings_text(v):
    return json.dumps({"_help": SET_HELP, **{k: v.get(k) for k in ("take_profit_usdt", "stop_loss_usdt", "tp_cooldown_minutes")}}, indent=2) + "\n"
def fetch():
    git("fetch", "-q", "origin", "main", SET_BRANCH)
    return git("rev-parse", "refs/remotes/origin/main")
def gh_put_settings(text):
    """normal (fast-forward) commit of settings.json on the settings branch via the contents API; never forces."""
    import base64
    blob = git("rev-parse", f"refs/remotes/origin/{SET_BRANCH}:{SETTINGS}", check=False) or None
    msg = "settings: init from bot config" if load_sync().get("pending_reason") == "init" else "settings: sync from bot config (local panel)"
    args = ["gh", "api", "-X", "PUT", f"repos/{REPO}/contents/{SETTINGS}", "-f", f"message={msg}", "-f", f"branch={SET_BRANCH}",
            "-f", "content=" + base64.b64encode(text.encode()).decode(), "--jq", ".commit.sha"]
    if blob: args += ["-f", f"sha={blob}"]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if r.returncode: raise RuntimeError(f"settings mirror via contents API failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()
def sync_settings(R):
    """-> (urgent, mirror_text or None). Never raises for a bad user file."""
    S = srv(); st = load_sync(); urgent = False; mirror = None
    r = subprocess.run(["git", "-C", HERE, "show", f"refs/remotes/origin/{SET_BRANCH}:{SETTINGS}"], capture_output=True, text=True)
    txt = r.stdout if r.returncode == 0 else None
    cur = config_values()
    if txt is None:
        mirror = settings_text(cur); st["pending_reason"] = "init"
    elif sha(txt) != st.get("remote_hash"):
        st["remote_hash"] = sha(txt); st["remote_seen_wib"] = wib_now(); urgent = True
        try:
            body = json.loads(txt)
            if not isinstance(body, dict): raise ValueError("settings.json must be a JSON object")
            new = S.validate({k: v for k, v in body.items() if not str(k).startswith("_")})
        except ValueError as e:  # includes json.JSONDecodeError
            st.update(status="rejected", error=str(e)[:300], rejected_wib=wib_now())
            log("settings.json rejected:", st["error"])
        else:
            vals, changed = S.save_settings(new)
            st.update(status="ok", error=None, last_applied=vals, last_applied_wib=wib_now(), source="github settings.json")
            if changed: st["last_change_wib"] = st["last_applied_wib"]; st["last_change_keys"] = changed
            log("settings.json applied:", vals, "changed:", changed or "none")
    elif st.get("last_applied") is not None and cur != st["last_applied"]:
        mirror = settings_text(cur); st["pending_reason"] = "local panel"
    elif st.get("last_applied") is None:
        st["last_applied"] = cur
    save_sync(st)
    return urgent or mirror is not None, mirror
def mirror_done(text):
    st = load_sync(); v = json.loads(text); v.pop("_help", None)
    reason = st.pop("pending_reason", "local panel")
    st.update(remote_hash=sha(text), last_applied=v, last_applied_wib=wib_now(), status="ok", error=None,
              source="local panel (mirrored to settings.json)" if reason != "init" else "initialized from config.json")
    if reason != "init": st["last_change_wib"] = st["last_applied_wib"]
    save_sync(st); log("settings.json mirrored from config.json:", v, f"({reason})")

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
    port = cfg.get("portfolio", {}); sync = load_sync()
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
        "settings": {k: (cfg.get("strategy") or {}).get(k, 0 if k == "tp_cooldown_minutes" else None)
                     for k in ("take_profit_usdt", "stop_loss_usdt", "tp_cooldown_minutes")},  # read-only display
        "cooldowns": [{"symbol": c.get("symbol"), "until_wib": c.get("until_wib"), "left_s": c.get("left_s")}
                      for c in (st.get("cooldowns") or []) if isinstance(c, dict)][:30],
        "stats": {"closed_trades": len(closed_all), "wins": wins,
                  "win_rate": round(100 * wins / len(closed_all), 1) if closed_all else None,
                  "closed_pnl_usdt": round(sum(c.get("pnl_usdt") or 0 for c in closed_all), 4)},
        "daily_realized": {k: round(v, 4) for k, v in (led.get("daily_realized") or {}).items()},
        "settings_sync": {k: sync.get(k) for k in ("status", "error", "rejected_wib", "last_applied_wib", "last_change_wib",
                                                    "last_change_keys", "source", "remote_seen_wib")} | {"edit_url": EDIT_URL},
        "open": opn, "closed": closed,
        "history": downsample(h, r0),
    }

# ---------- git ----------
def git(*a, check=True):
    r = subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True, timeout=120)
    if check and r.returncode: raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()[:400]}")
    return r.stdout.strip()

def is_data_commit(rev):
    return git("log", "-1", "--format=%s%x1f%an", rev) == f"{DATA_MSG}\x1f{PUSHER_NAME}"
def commit(msg, path):
    git("add", path)
    git("-c", f"user.name={PUSHER_NAME}", "-c", f"user.email={PUSHER_EMAIL}", "commit", "-q", "--allow-empty", "-m", msg, "--", path)
def push(R):
    """main only: rebuild on top of the fetched origin tip R; never drops a commit that is not our own data snapshot."""
    base = git("rev-parse", f"{R}~1") if is_data_commit(R) else R
    git("reset", "-q", "--mixed", base)           # move HEAD+index only; working tree untouched
    commit(DATA_MSG, "data.json")
    git("push", "-q", f"--force-with-lease=refs/heads/main:{R}", "origin", "HEAD:main")

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
            R = fetch(); urgent, mirror = sync_settings(R)
            if time.time() - last_push >= PUSH_EVERY_S or once or urgent:
                if mirror is not None and not nopush:
                    gh_put_settings(mirror); mirror_done(mirror)   # settings branch, normal commit
                merge_dash_hist(h); h = save_hist(h)
                d = write_data(h)
                if not nopush: push(R)
                last_push = time.time(); fails = 0
                log(f"pushed eq={d['snapshot']['equity_usdt']} open={d['snapshot']['open_count']} alive={d['daemon']['alive']} hist={len(d['history'])}")
        except Exception as e:
            fails += 1; last_push = time.time() - PUSH_EVERY_S + 30 * min(fails, 4)  # retry sooner
            log("ERROR", repr(e)); traceback.print_exc()
        if once: break
        time.sleep(SAMPLE_EVERY_S)

if __name__ == "__main__":
    main()
