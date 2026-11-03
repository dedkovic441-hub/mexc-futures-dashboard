# settings branch (user-editable)

This branch holds only `settings.json` for the MEXC futures **paper** bot. Edit it here:
https://github.com/dedkovic441-hub/mexc-futures-dashboard/edit/settings/settings.json

- `take_profit_usdt`: net USDT profit that closes a trade (> 0, <= 1000)
- `stop_loss_usdt`: net USDT loss that closes a trade (`null` or `0` = off, <= 1000)
- `tp_cooldown_minutes`: block re-entry in a coin for N minutes after a take-profit close (0 = off, <= 10080)

The bot's pusher only *reads* this branch (every ~30 s) and never force-pushes it. Local-panel changes are added as normal
commits via the GitHub API. Invalid files are rejected (shown on the live page) and not applied.
Live page: https://dedkovic441-hub.github.io/mexc-futures-dashboard/
