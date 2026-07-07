# TradingView-Indicators

Pine Script v6 indicators.

## Indicators

### MP_TD_Seq_V1.pine
Tom DeMark Sequential (Standard Sequential variant) — Setup 9 / Countdown 13
with Price Flip, Perfection, TDST, Recycle, and qualifier logic.

### consolidation_breakout_detector_v6.pine
Consolidation & Breakout Detector v6 — coil detection with confirmed-breakout
signals plus full trade management:

- **Frozen S/R zones** — the zone is captured at the raw-break bar, so breakout
  candles can never inflate the level being traded (v5 zones slid with the
  rolling window). Zones show touch-count strength (`R×n S×m`), shade their
  edge bands, extend right until decisively broken, and the broken level is
  projected forward as a role-flipped line (broken resistance → support).
- **Trade plan on every signal** — exact entry (the broken level), stop
  (zone midpoint / opposite edge / ATR), and two measured-move targets drawn
  on the chart with prices.
- **Retest entry** — fires when price pulls back to within an ATR band of the
  broken level and closes back in the breakout direction; fills far closer to
  the level than chasing the confirmation close.
- **Exit signals** — failed-breakout warning the moment a close falls back
  through the level, stop-hit, and T1/T2 target tags. v5 had no exits at all.
- **Close-confirmed, non-repainting** — all state changes are gated on
  `barstate.isconfirmed`; nothing prints or alerts intrabar.

`consolidation_breakout_detector_v5.pine` is the previous version, kept for
reference.

## Tests

`tests/` contains a Python port of the v5/v6 detector logic
(`pine_sim.py`) plus scenario tests with ground-truth synthetic OHLC data
(clean breakout, fakeout, chop, retest, confirmed-then-collapse):

```
cd tests
python3 test_v5.py   # characterizes v5 behavior
python3 test_v6.py   # compares v5 vs v6 signals side by side
```

The simulator mirrors the Pine semantics bar by bar (prior-bar window, RMA
ATR, SMA/na propagation, the confirmation state machine) so logic changes can
be validated off-platform before touching the chart.
