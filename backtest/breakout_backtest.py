#!/usr/bin/env python3
"""Backtest of MP_Consolidation_Breakout_Long_Strategy_V1 (long-only).

A faithful Python port of the Pine strategy so results can be produced outside
TradingView. Semantics mirrored exactly:

- Detection identical to Consolidation & Breakout Detector v7: the high-low
  range is measured over the lookback window ending at the PRIOR bar; adaptive
  threshold = median (nearest-rank) or SMA of the range%-series times the
  compression factor, LOCKED at coil onset; coil boundaries expand-only; the
  zone freezes at the raw break; N total closes beyond the level confirm; a
  failed attempt cannot re-enter the same direction on its reset bar; one
  signal per coil (either direction consumes it); grace window after coil end.
- Entry: market fill at the CLOSE of the confirmation bar (process_orders_on_close),
  or at the close of the retest bar in retest mode.
- Exits, live from the bar after entry:
    T1 limit (partial), T2 limit (rest) fill intrabar at max(open, limit);
    stop (default) triggers only when a bar CLOSES through it, at that close;
    optional intrabar stop order at the level (max-style fill at min(open, stop));
    stop rises to the entry fill after T1 touch (optional);
    optional FAIL exit at the close back through the broken level.
  Same-bar sequence (matches TV order processing with process_orders_on_close):
  limits fill intrabar first, then the close-based exits act on the remainder.
- Sizing: qty = equity * risk% / (entry - stop), or equity% / close.
- Pine built-ins ported exactly: ta.sma / ta.highest / ta.lowest return na
  until their window is full; ta.percentile_nearest_rank uses the nearest-rank
  method (k = ceil(p/100*n)); ta.atr is an RMA of true range seeded with the
  SMA of the first `len` values.

Data: CSV with header date,open,high,low,close,volume (daily, split-adjusted).
Known idealizations (identical to the Pine strategy defaults): fills at the
close with no slippage, zero commission, dividends excluded.
"""

import csv
import math
import sys
from dataclasses import dataclass, field


NA = None


# ----------------------------- Pine built-ins -----------------------------

def highest(values, length, i):
    """ta.highest(values, length) at bar i; na until window full or any na."""
    if i < length - 1:
        return NA
    window = values[i - length + 1 : i + 1]
    if any(v is NA for v in window):
        return NA
    return max(window)


def lowest(values, length, i):
    if i < length - 1:
        return NA
    window = values[i - length + 1 : i + 1]
    if any(v is NA for v in window):
        return NA
    return min(window)


def sma(values, length, i):
    if i < length - 1:
        return NA
    window = values[i - length + 1 : i + 1]
    if any(v is NA for v in window):
        return NA
    return sum(window) / length


def percentile_nearest_rank(values, length, pct, i):
    """Pine nearest-rank percentile: k-th smallest with k = ceil(pct/100 * n)."""
    if i < length - 1:
        return NA
    window = values[i - length + 1 : i + 1]
    if any(v is NA for v in window):
        return NA
    k = math.ceil(pct / 100.0 * length)
    return sorted(window)[k - 1]


def atr_series(high, low, close, length):
    """ta.atr(length): RMA of true range, seeded with the SMA of the first
    `length` TR values (Pine's ta.rma seeding)."""
    n = len(close)
    tr = [NA] * n
    out = [NA] * n
    for i in range(n):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    alpha = 1.0 / length
    prev = NA
    for i in range(n):
        if i < length - 1:
            continue
        if prev is NA:
            prev = sum(tr[i - length + 1 : i + 1]) / length
        else:
            prev = alpha * tr[i] + (1 - alpha) * prev
        out[i] = prev
    return out


# ----------------------------- configuration -----------------------------

@dataclass
class Config:
    # detection (Detector v7 defaults)
    detection_adaptive: bool = True
    lookback: int = 20
    confirm_closes: int = 2
    min_coil_bars: int = 3
    grace_bars: int = 5
    use_close_basis: bool = False          # False = Wicks (conservative)
    compression: float = 0.6
    baseline_len: int = 100
    baseline_median: bool = True
    fixed_threshold: float = 5.0
    atr_len: int = 14
    atr_buffer_mult: float = 0.0
    use_vol_filter: bool = False
    vol_ma_len: int = 20
    # strategy
    retest_entry: bool = False
    risk_sizing: bool = True
    risk_pct: float = 1.0
    equity_pct: float = 10.0
    stop_mode: str = "midpoint"            # midpoint | opposite | atr
    stop_atr_mult: float = 1.5
    close_through_stop: bool = True
    t1_mult: float = 1.0
    t2_mult: float = 2.0
    t1_partial_pct: float = 50.0
    be_after_t1: bool = True
    fail_exit: bool = False
    retest_band_atr: float = 0.5
    retest_window: int = 20
    initial_capital: float = 100_000.0
    commission_pct: float = 0.0            # per fill, % of notional


@dataclass
class Trade:
    entry_date: str = ""
    entry_price: float = 0.0
    qty: float = 0.0
    init_stop: float = 0.0
    level: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    kind: str = "BREAK"
    fills: list = field(default_factory=list)   # (date, qty, price, tag)
    pnl: float = 0.0

    @property
    def risk_dollars(self):
        return self.qty * (self.entry_price - self.init_stop)


# ----------------------------- engine -----------------------------

def run_backtest(dates, o, h, l, c, v, cfg: Config):
    n = len(c)
    atr = atr_series(h, l, c, cfg.atr_len)
    body_hi = [max(o[i], c[i]) for i in range(n)]
    body_lo = [min(o[i], c[i]) for i in range(n)]

    # range% series (window ending at prior bar via [1] shift)
    range_pct = [NA] * n
    range_hi = [NA] * n
    range_lo = [NA] * n
    b_hi = [NA] * n
    b_lo = [NA] * n
    for i in range(n):
        if i >= 1:
            range_hi[i] = highest(h, cfg.lookback, i - 1)
            range_lo[i] = lowest(l, cfg.lookback, i - 1)
            b_hi[i] = highest(body_hi, cfg.lookback, i - 1)
            b_lo[i] = lowest(body_lo, cfg.lookback, i - 1)
        if range_hi[i] is not NA and range_lo[i] is not NA:
            avg = (range_hi[i] + range_lo[i]) / 2
            if avg != 0:
                range_pct[i] = (range_hi[i] - range_lo[i]) / avg * 100

    # ---- persistent state (Pine `var`s)
    locked_threshold = NA
    in_coil = False
    coil_age = 0
    ended_coil_age = 0
    prev_consolidating = False
    dir_ = 0
    confirm_cnt = 0
    broken_level = NA
    armed = False
    coil_high = coil_low = coil_bh = coil_bl = NA
    coil_start_bar = coil_end_bar = NA
    pend_top = pend_bot = NA
    pend_break_bar = NA
    flip_dir = 0
    flip_level = NA
    flip_bar = NA
    retest_done = False
    plan_entry_lvl = plan_stop = plan_t1 = plan_t2 = NA
    plan_bar = NA
    t1_done = False

    cash = cfg.initial_capital
    pos_qty = 0.0
    pos_entry_qty = 0.0
    trade = None
    trades = []
    equity_curve = []

    def equity_at_close(i):
        return cash + pos_qty * c[i]

    def fill(i, qty, price, tag):
        nonlocal cash, pos_qty, trade
        cash += qty * price
        cash -= abs(qty * price) * cfg.commission_pct / 100.0
        pos_qty -= qty
        trade.fills.append((dates[i], qty, price, tag))
        if pos_qty <= 1e-9:
            entry_cost = trade.qty * trade.entry_price
            exit_proceeds = sum(q * p for (_, q, p, _) in trade.fills)
            comm = (entry_cost + exit_proceeds) * cfg.commission_pct / 100.0
            trade.pnl = exit_proceeds - entry_cost - comm
            trades.append(trade)
            trade = None

    for i in range(n):
        # ---------------- consolidation test (exact statement order) ----------------
        if cfg.detection_adaptive:
            if cfg.baseline_median:
                baseline = percentile_nearest_rank(range_pct, cfg.baseline_len, 50, i)
            else:
                baseline = sma(range_pct, cfg.baseline_len, i)
            raw_threshold = NA if baseline is NA else baseline * cfg.compression
        else:
            raw_threshold = cfg.fixed_threshold

        eff_threshold = locked_threshold if (in_coil and locked_threshold is not NA) else raw_threshold
        is_consolidating = (range_pct[i] is not NA and eff_threshold is not NA
                            and range_pct[i] <= eff_threshold)
        if is_consolidating and not in_coil:
            locked_threshold = raw_threshold
        if not is_consolidating:
            locked_threshold = NA
        in_coil = is_consolidating
        new_consolidation = is_consolidating and not prev_consolidating

        prev_coil_age = coil_age
        coil_age = (1 if new_consolidation else coil_age + 1) if is_consolidating else 0
        if not is_consolidating and prev_consolidating:
            ended_coil_age = prev_coil_age

        # ---------------- filters ----------------
        buffer_ = (cfg.atr_buffer_mult * atr[i]) if atr[i] is not NA else NA
        vol_ma = sma(v, cfg.vol_ma_len, i)
        vol_ok = (not cfg.use_vol_filter) or v[i] is NA or (vol_ma is not NA and v[i] > vol_ma)

        # ---------------- state machine (barstate.isconfirmed == every daily bar) ----------------
        confirm_fail_dir = 0
        if new_consolidation:
            armed = True
            coil_high, coil_low = range_hi[i], range_lo[i]
            coil_bh, coil_bl = b_hi[i], b_lo[i]
            coil_start_bar = i
            coil_end_bar = NA
            dir_ = 0
            confirm_cnt = 0
            broken_level = NA
        elif is_consolidating:
            coil_high = max(coil_high, range_hi[i])
            coil_low = min(coil_low, range_lo[i])
            coil_bh = max(coil_bh, b_hi[i])
            coil_bl = min(coil_bl, b_lo[i])
        if not is_consolidating and prev_consolidating:
            coil_end_bar = i - 1

        coil_top_lvl = coil_bh if cfg.use_close_basis else coil_high
        coil_bot_lvl = coil_bl if cfg.use_close_basis else coil_low

        in_break_window = is_consolidating or (coil_end_bar is not NA and i - coil_end_bar <= cfg.grace_bars)
        coil_age_ok = (coil_age >= cfg.min_coil_bars) if is_consolidating else (ended_coil_age >= cfg.min_coil_bars)
        raw_break_up = (in_break_window and coil_age_ok and coil_top_lvl is not NA
                        and buffer_ is not NA and c[i] > coil_top_lvl + buffer_ and vol_ok)
        raw_break_down = (in_break_window and coil_age_ok and coil_bot_lvl is not NA
                          and buffer_ is not NA and c[i] < coil_bot_lvl - buffer_ and vol_ok)

        if dir_ == 1:
            if c[i] > broken_level + buffer_:
                confirm_cnt += 1
            elif c[i] <= broken_level:
                confirm_fail_dir = 1
                dir_, confirm_cnt, broken_level = 0, 0, NA
        elif dir_ == -1:
            if c[i] < broken_level - buffer_:
                confirm_cnt += 1
            elif c[i] >= broken_level:
                confirm_fail_dir = -1
                dir_, confirm_cnt, broken_level = 0, 0, NA

        if dir_ == 0:
            if armed and raw_break_up and confirm_fail_dir != 1:
                dir_, broken_level, confirm_cnt = 1, coil_top_lvl, 1
                pend_top, pend_bot, pend_break_bar = coil_top_lvl, coil_bot_lvl, i
            elif armed and raw_break_down and confirm_fail_dir != -1:
                dir_, broken_level, confirm_cnt = -1, coil_bot_lvl, 1
                pend_top, pend_bot, pend_break_bar = coil_top_lvl, coil_bot_lvl, i

        confirmed_up = dir_ == 1 and confirm_cnt == cfg.confirm_closes
        confirmed_down = dir_ == -1 and confirm_cnt == cfg.confirm_closes

        # ---------------- position management (before any new signal fill this bar,
        # mirrors Pine script order: the management block sits after the signal block
        # in source, but a new entry this bar has plan_bar == i so `i > plan_bar`
        # gates it out; ordering here is therefore equivalent) ----------------
        if pos_qty > 1e-9 and plan_bar is not NA and i > plan_bar:
            # limit fills first (intrabar), lower limit first for a long
            if not t1_done and h[i] >= plan_t1:
                t1_done = True
                if cfg.t1_partial_pct > 0:
                    fill(i, pos_entry_qty * cfg.t1_partial_pct / 100.0, max(o[i], plan_t1), "T1")
                if cfg.be_after_t1:
                    plan_stop = max(plan_stop, trade.entry_price if trade else plan_stop)
            if pos_qty > 1e-9 and h[i] >= plan_t2:
                fill(i, pos_qty, max(o[i], plan_t2), "T2")
            # intrabar stop (optional mode)
            if pos_qty > 1e-9 and not cfg.close_through_stop and l[i] <= plan_stop:
                fill(i, pos_qty, min(o[i], plan_stop), "STOP")
            # close-based exits on the remainder
            if pos_qty > 1e-9:
                if cfg.fail_exit and c[i] < plan_entry_lvl:
                    fill(i, pos_qty, c[i], "FAIL")
                elif cfg.close_through_stop and c[i] < plan_stop:
                    fill(i, pos_qty, c[i], "STOP")

        # ---------------- signal handling ----------------
        if confirmed_up or confirmed_down:
            up = confirmed_up
            level = pend_top if up else pend_bot
            flip_dir = 1 if up else -1
            flip_level = level
            flip_bar = i
            retest_done = False

            # a new plan is only adopted while FLAT: an open trade keeps the
            # stop and targets it was entered with (mirrors the Pine strategy)
            if up and pos_qty <= 1e-9:
                zone_h = pend_top - pend_bot
                plan_entry_lvl = level
                if cfg.stop_mode == "midpoint":
                    plan_stop = (pend_top + pend_bot) / 2
                elif cfg.stop_mode == "opposite":
                    plan_stop = pend_bot
                else:
                    plan_stop = level - cfg.stop_atr_mult * atr[i]
                plan_t1 = level + cfg.t1_mult * zone_h
                plan_t2 = level + cfg.t2_mult * zone_h
                plan_bar = i
                t1_done = False

                if (not cfg.retest_entry) and plan_stop < c[i]:
                    eq = equity_at_close(i)
                    qty = (eq * cfg.risk_pct / 100.0) / (c[i] - plan_stop) if cfg.risk_sizing \
                        else (eq * cfg.equity_pct / 100.0) / c[i]
                    if qty > 0:
                        trade = Trade(entry_date=dates[i], entry_price=c[i], qty=qty,
                                      init_stop=plan_stop, level=level, t1=plan_t1,
                                      t2=plan_t2, kind="BREAK")
                        cash -= qty * c[i]
                        cash -= qty * c[i] * cfg.commission_pct / 100.0
                        pos_qty = qty
                        pos_entry_qty = qty

            # one signal per coil — both directions consume it
            dir_, confirm_cnt, broken_level, armed = 0, 0, NA, False
        else:
            if flip_dir == 1 and flip_bar is not NA and i > flip_bar:
                band = cfg.retest_band_atr * atr[i] if atr[i] is not NA else NA
                if (not retest_done and band is not NA and i - flip_bar <= cfg.retest_window
                        and l[i] <= flip_level + band and c[i] > flip_level):
                    retest_done = True
                    if (cfg.retest_entry and pos_qty <= 1e-9 and plan_stop is not NA
                            and plan_stop < c[i] and plan_bar is not NA
                            and i - plan_bar <= cfg.retest_window):
                        eq = equity_at_close(i)
                        qty = (eq * cfg.risk_pct / 100.0) / (c[i] - plan_stop) if cfg.risk_sizing \
                            else (eq * cfg.equity_pct / 100.0) / c[i]
                        if qty > 0:
                            trade = Trade(entry_date=dates[i], entry_price=c[i], qty=qty,
                                          init_stop=plan_stop, level=flip_level, t1=plan_t1,
                                          t2=plan_t2, kind="RETEST")
                            cash -= qty * c[i]
                            cash -= qty * c[i] * cfg.commission_pct / 100.0
                            pos_qty = qty
                            pos_entry_qty = qty
                            plan_bar = i
                            t1_done = False
                if c[i] < flip_level:
                    flip_dir = 0
                    # identical to the indicator: coil still intact → re-arm
                    if is_consolidating:
                        armed = True
            if flip_dir == -1 and flip_bar is not NA and i > flip_bar and c[i] > flip_level:
                flip_dir = 0
                if is_consolidating:
                    armed = True
            if new_consolidation:
                flip_dir = 0

        prev_consolidating = is_consolidating
        equity_curve.append(equity_at_close(i))

    # liquidate any open position at the final close so stats are complete
    open_note = None
    if pos_qty > 1e-9:
        open_note = f"open position marked to market on {dates[-1]}"
        fill(n - 1, pos_qty, c[n - 1], "EOD")

    return trades, equity_curve, open_note


# ----------------------------- statistics -----------------------------

def stats(trades, equity_curve, dates, closes, cfg):
    s = {}
    s["trades"] = len(trades)
    if not trades:
        return s
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    s["win_rate"] = len(wins) / len(trades) * 100
    s["profit_factor"] = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    s["net_profit"] = equity_curve[-1] - cfg.initial_capital
    s["net_profit_pct"] = s["net_profit"] / cfg.initial_capital * 100
    s["avg_trade_pnl"] = sum(t.pnl for t in trades) / len(trades)
    rs = [t.pnl / t.risk_dollars for t in trades if t.risk_dollars > 0]
    s["avg_R"] = sum(rs) / len(rs) if rs else float("nan")
    peak = -1e18
    max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak * 100 if peak > 0 else 0)
    s["max_dd_pct"] = max_dd
    years = max((len(dates) / 252.0), 1e-9)
    s["cagr_pct"] = ((equity_curve[-1] / cfg.initial_capital) ** (1 / years) - 1) * 100
    s["bh_return_pct"] = (closes[-1] / closes[0] - 1) * 100
    tags = {}
    for t in trades:
        final_tag = t.fills[-1][3] if t.fills else "?"
        tags[final_tag] = tags.get(final_tag, 0) + 1
    s["exit_breakdown"] = tags
    in_market_bars = 0
    # exposure: count bars between entry date and last fill date per trade
    idx = {d: k for k, d in enumerate(dates)}
    for t in trades:
        if t.fills:
            in_market_bars += idx[t.fills[-1][0]] - idx[t.entry_date] + 1
    s["exposure_pct"] = in_market_bars / len(dates) * 100
    return s


def load_csv(path):
    dates, o, h, l, c, v = [], [], [], [], [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            dates.append(row["date"])
            o.append(float(row["open"]))
            h.append(float(row["high"]))
            l.append(float(row["low"]))
            c.append(float(row["close"]))
            v.append(float(row["volume"]))
    return dates, o, h, l, c, v


def fmt(s, note):
    if s.get("trades", 0) == 0:
        return "  no trades"
    pf = s["profit_factor"]
    lines = [
        f"  trades {s['trades']:>3}   win rate {s['win_rate']:5.1f}%   profit factor {pf if pf != float('inf') else 999:5.2f}   avg R {s['avg_R']:+5.2f}",
        f"  net P&L {s['net_profit_pct']:+7.2f}%   CAGR {s['cagr_pct']:+6.2f}%   max DD {s['max_dd_pct']:5.2f}%   exposure {s['exposure_pct']:5.1f}%",
        f"  buy & hold same period {s['bh_return_pct']:+9.1f}%   exits: " + ", ".join(f"{k}×{n}" for k, n in sorted(s["exit_breakdown"].items())),
    ]
    if note:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    symbols = sys.argv[2].split(",") if len(sys.argv) > 2 else ["RIO", "NVDA", "INTC", "OKTA"]
    variants = {
        "A · defaults (breakout entry, stop/T1/T2, BE after T1)": Config(),
        "B · retest entry": Config(retest_entry=True),
        "C · fail-exit on": Config(fail_exit=True),
    }
    for name, cfg in variants.items():
        print(f"\n=== Variant {name} ===")
        for sym in symbols:
            dates, o, h, l, c, v = load_csv(f"{data_dir}/{sym}.csv")
            trades, curve, note = run_backtest(dates, o, h, l, c, v, cfg)
            s = stats(trades, curve, dates, c, cfg)
            print(f"\n{sym}  ({dates[0]} → {dates[-1]}, {len(dates)} bars)")
            print(fmt(s, note))
            with open(f"{data_dir}/trades_{sym}_{name.split(' ')[0]}.csv", "w") as f:
                w = csv.writer(f)
                w.writerow(["entry_date", "kind", "entry", "init_stop", "t1", "t2", "qty", "exit_fills", "pnl", "R"])
                for t in trades:
                    r = t.pnl / t.risk_dollars if t.risk_dollars > 0 else ""
                    w.writerow([t.entry_date, t.kind, f"{t.entry_price:.4f}", f"{t.init_stop:.4f}",
                                f"{t.t1:.4f}", f"{t.t2:.4f}", f"{t.qty:.4f}",
                                " | ".join(f"{d}:{tag}@{p:.4f}" for (d, q, p, tag) in t.fills),
                                f"{t.pnl:.2f}", f"{r:.3f}" if r != "" else ""])


if __name__ == "__main__":
    main()
