# TradingView-Indicators

Pine Script v6 indicators.

## Indicators

- **MP_TD_Seq_V1.pine** — TD Sequential (Setup + Countdown).
- **MP_Consolidation_Breakout_V7.pine** — Consolidation & Breakout Detector v7: coil detection with adaptive or fixed-percent engines, close-confirmed breakouts, trade plans (entry / stop / T1 / T2), retest entries, failed-break and stop exits, and frozen S/R zones that flip roles when broken.
- **MP_Consolidation_Breakout_Long_Strategy_V1.pine** — long-only strategy on the Detector v7 engine: entries at the confirmed-break (or retest) close, risk-based sizing, T1 partial / T2 completion, close-through stop with optional break-even after T1 and optional failed-breakout exit. A faithful Python port with a backtest runner lives in `backtest/breakout_backtest.py`.
