# MEXC Futures Paper Bot dashboard

Public live view of a **paper-trading** (simulated, no real money) MEXC futures bot.

Live page: https://dedkovic441-hub.github.io/mexc-futures-dashboard/

`data.json` is regenerated and pushed every ~2 minutes by `push.py`.
To keep history small, the data lives in one commit that is amended and force-pushed each time.

## Changing the bot's settings (phone-friendly)
Edit [`settings.json`](https://github.com/dedkovic441-hub/mexc-futures-dashboard/edit/main/settings.json) (pencil icon → change the numbers → **Commit changes**).
Fields: `take_profit_usdt` (net USDT, >0, ≤1000), `stop_loss_usdt` (net USDT, `null` or `0` = off, ≤1000), `tp_cooldown_minutes` (0 = off, ≤10080).
`push.py` checks the file every ~30 s, validates it and applies it to the paper bot; invalid files are rejected (shown on the page) and not applied.
Changes made on the bot's local dashboard are written back here. Your commits are never overwritten: the data snapshot commit is rebuilt on top of them.
