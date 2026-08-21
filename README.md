# TradingView-Indicators

Pine Script v6 indicators.

## MP_TD_Seq_V1 — TD Sequential (Standard variant)

`MP_TD_Seq_V1.pine` is an independent Pine v6 implementation of Tom DeMark's
Sequential:

- **Setup** — Bearish/Bullish Price Flip, then a 9-bar count of closes beyond
  the close 4 bars earlier. Completion prints "9" and sets the TDST level.
- **Perfection** — forward-looking check of bar 8/9 (or any later bar while the
  Setup remains the most recent) against the lows/highs of bars 6 and 7,
  marked with a dot.
- **TDST** — support/resistance from the completed Setup (bar-1 true high/low,
  canonical, or the full Setup extreme — selectable).
- **Countdown** — non-consecutive 13-count (close vs. low/high 2 bars earlier),
  armed by a completed Setup, with the 13-vs-8 qualifier ("+" = deferred).
- **Cancellations** — TDST violation, opposing Setup completion, size-based
  recycle (default 100–161.8%), and the 22-bar Setup extension recycle.
- **Outputs** — Risk Level, optional risk-zone shading, 12-bar reversal window
  box, a full alert set, a diagnostic table, and hidden `display.none` series
  for downstream strategies/screeners.

Display toggles only affect drawing — they never change the signal logic.

### "About this script" on TradingView

TradingView's **About this script** section comes from the description you type
in the *Publish script* dialog — it is not settable from Pine code. The file
header of `MP_TD_Seq_V1.pine` contains a ready-to-paste description block
(marked `ABOUT THIS SCRIPT`): copy it into the description box when publishing
and it becomes the About text shown on the script's page and drop-down.

Inside the app, the indicator also ships an **ℹ️ About** panel at the top of
its Settings dialog with the same summary, so the description is visible even
for unpublished, private copies of the script.

### Disclaimer

"TD Sequential", "TDST", and "Risk Level" are trademarks of DeMARK Analytics,
LLC. This is an independent implementation of publicly available
documentation; not affiliated with or endorsed by DeMARK Analytics. For
education and research only — not financial advice.
