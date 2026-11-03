# MEXC Futures Paper Bot dashboard

Public live view of a **paper-trading** (simulated, no real money) MEXC futures bot.

Live page: https://dedkovic441-hub.github.io/mexc-futures-dashboard/

`data.json` is regenerated and pushed every ~2 minutes by `push.py`.
To keep history small, the data lives in one commit that is amended and force-pushed each time.

## Changing the bot's settings (phone-friendly)
Settings live on the separate **`settings` branch** (so the data pushes on `main` never get in the way of an edit):
[edit settings.json on the settings branch](https://github.com/dedkovic441-hub/mexc-futures-dashboard/edit/settings/settings.json)
(pencil icon → change the numbers → **Commit changes**, "commit directly to the settings branch").
Fields: `take_profit_usdt` (net USDT, >0, ≤1000), `stop_loss_usdt` (net USDT, `null` or `0` = off, ≤1000), `tp_cooldown_minutes` (0 = off, ≤10080).
`push.py` reads that branch every ~30 s, validates the file and applies it to the paper bot; invalid files are rejected (shown on the page) and not applied.
Changes made on the bot's local dashboard are added to the settings branch as normal commits (never force-pushed).
The `settings.json` on `main` is only a pointer to the settings branch and is ignored.
