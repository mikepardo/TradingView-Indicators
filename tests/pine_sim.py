"""Bar-by-bar simulator of the Pine v5/v6 Consolidation & Breakout Detector logic.

Ports the exact Pine semantics (prior-bar window, RMA-based ATR, SMA baseline,
confirmation state machine) so signal behavior can be tested off-platform with
ground-truth synthetic data.
"""
import math
import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------- Pine helpers
class RollingWindow:
    def __init__(self, length):
        self.length = length
        self.buf = []

    def push(self, v):
        self.buf.append(v)
        if len(self.buf) > self.length:
            self.buf.pop(0)

    def highest(self):
        if len(self.buf) < self.length:
            return math.nan
        return max(self.buf)

    def lowest(self):
        if len(self.buf) < self.length:
            return math.nan
        return min(self.buf)

    def sma(self):
        vals = [v for v in self.buf]
        if len(vals) < self.length or any(math.isnan(v) for v in vals):
            return math.nan
        return sum(vals) / len(vals)


class RMA:
    """Pine ta.rma / ta.atr smoothing."""

    def __init__(self, length):
        self.length = length
        self.value = math.nan
        self.seed = []

    def push(self, v):
        if math.isnan(v):
            return self.value
        if math.isnan(self.value):
            self.seed.append(v)
            if len(self.seed) >= self.length:
                self.value = sum(self.seed) / len(self.seed)
        else:
            self.value = (self.value * (self.length - 1) + v) / self.length
        return self.value


@dataclass
class Bar:
    o: float
    h: float
    l: float
    c: float
    v: float = 1000.0


@dataclass
class Signal:
    bar: int
    kind: str          # 'up' | 'down' | 'retest_up' | 'retest_down' | 'exit'
    level: float       # the broken level
    close: float       # close at signal bar
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- v5 simulator
def simulate_v5(bars, lookback=20, confirm_bars=2, mode="adaptive",
                compression=0.6, baseline_len=100, fixed_thresh=5.0,
                atr_buf_mult=0.0, use_vol_filter=False, vol_ma_len=20):
    highs = RollingWindow(lookback)
    lows = RollingWindow(lookback)
    baseline = RollingWindow(baseline_len)
    vol_ma = RollingWindow(vol_ma_len)
    atr = RMA(14)

    hh_prev = ll_prev = math.nan     # hhRaw[1], llRaw[1]
    prev_close = math.nan
    dir_ = 0
    confirm_cnt = 0
    broken_level = math.nan
    armed = False
    was_consolidating = False

    signals = []
    consolidating_flags = []
    range_high_series = []
    range_low_series = []

    for i, b in enumerate(bars):
        # ta.* computed on current bar first (Pine evaluates on current bar's values)
        highs.push(b.h)
        lows.push(b.l)
        hh_raw = highs.highest()
        ll_raw = lows.lowest()

        range_high = hh_prev
        range_low = ll_prev

        if not math.isnan(prev_close):
            tr = max(b.h - b.l, abs(b.h - prev_close), abs(b.l - prev_close))
        else:
            tr = b.h - b.l
        atr_val = atr.push(tr)
        vol_ma.push(b.v)
        vma = vol_ma.sma()

        avg_price = (range_high + range_low) / 2 if not math.isnan(range_high) else math.nan
        if not math.isnan(avg_price) and avg_price != 0:
            range_pct = (range_high - range_low) / avg_price * 100
        else:
            range_pct = math.nan
        baseline.push(range_pct)

        if mode == "adaptive":
            base = baseline.sma()
            eff_thresh = base * compression if not math.isnan(base) else math.nan
        else:
            eff_thresh = fixed_thresh

        is_cons = (not math.isnan(range_pct) and not math.isnan(eff_thresh)
                   and range_pct <= eff_thresh)

        buffer = (atr_buf_mult * atr_val) if not math.isnan(atr_val) else math.nan
        if math.isnan(buffer):
            buffer = 0.0 if atr_buf_mult == 0 else math.nan
        vol_ok = (not use_vol_filter) or (not math.isnan(vma) and b.v > vma)

        raw_up = (is_cons and not math.isnan(range_high) and not math.isnan(buffer)
                  and b.c > range_high + buffer and vol_ok)
        raw_dn = (is_cons and not math.isnan(range_low) and not math.isnan(buffer)
                  and b.c < range_low - buffer and vol_ok)

        if is_cons and not was_consolidating:
            armed = True

        if dir_ == 0:
            if armed and raw_up:
                dir_, broken_level, confirm_cnt = 1, range_high, 1
            elif armed and raw_dn:
                dir_, broken_level, confirm_cnt = -1, range_low, 1
        elif dir_ == 1:
            if b.c > broken_level:
                confirm_cnt += 1
            else:
                dir_, confirm_cnt, broken_level = 0, 0, math.nan
        elif dir_ == -1:
            if b.c < broken_level:
                confirm_cnt += 1
            else:
                dir_, confirm_cnt, broken_level = 0, 0, math.nan

        conf_up = dir_ == 1 and confirm_cnt == confirm_bars
        conf_dn = dir_ == -1 and confirm_cnt == confirm_bars

        if conf_up:
            signals.append(Signal(i, 'up', broken_level, b.c))
        if conf_dn:
            signals.append(Signal(i, 'down', broken_level, b.c))
        if conf_up or conf_dn:
            dir_, confirm_cnt, armed = 0, 0, False
            broken_level = math.nan

        consolidating_flags.append(is_cons)
        range_high_series.append(range_high)
        range_low_series.append(range_low)

        hh_prev, ll_prev = hh_raw, ll_raw
        prev_close = b.c
        was_consolidating = is_cons

    return {
        'signals': signals,
        'consolidating': consolidating_flags,
        'range_high': range_high_series,
        'range_low': range_low_series,
    }


# ---------------------------------------------------------- scenario builders
def _flat_bars(n, center, half_range, seed, vol=1000.0):
    rng = random.Random(seed)
    bars = []
    for _ in range(n):
        c = center + rng.uniform(-half_range * 0.7, half_range * 0.7)
        o = center + rng.uniform(-half_range * 0.7, half_range * 0.7)
        h = min(center + half_range, max(o, c) + rng.uniform(0, half_range * 0.3))
        l = max(center - half_range, min(o, c) - rng.uniform(0, half_range * 0.3))
        bars.append(Bar(o, h, l, c, vol))
    return bars


def _trend_bars(n, start, step, noise, seed, vol=1500.0):
    rng = random.Random(seed)
    bars = []
    price = start
    for _ in range(n):
        o = price
        price += step + rng.uniform(-noise, noise)
        c = price
        h = max(o, c) + rng.uniform(0, noise)
        l = min(o, c) - rng.uniform(0, noise)
        bars.append(Bar(o, h, l, c, vol))
    return bars


def scenario_clean_breakout_up(seed=1):
    """150 volatile bars -> 40-bar tight coil at 100 (+/-1) -> strong up-trend."""
    bars = _trend_bars(75, 80, 0.4, 2.0, seed) + _trend_bars(75, 110, -0.15, 2.2, seed + 1)
    coil_start = len(bars)
    bars += _flat_bars(40, 100.0, 1.0, seed + 2)
    breakout_start = len(bars)
    bars += _trend_bars(40, 101.0, 0.9, 0.5, seed + 3, vol=2500.0)
    return bars, {'coil_start': coil_start, 'breakout_start': breakout_start,
                  'direction': 'up', 'coil_high': 101.0, 'coil_low': 99.0}


def scenario_false_break_then_down(seed=7):
    """Coil, 1-bar fakeout above, back inside, then real breakdown."""
    bars = _trend_bars(150, 90, 0.12, 1.8, seed)
    coil_start = len(bars)
    bars += _flat_bars(35, 100.0, 1.0, seed + 1)
    # fakeout: one close above the range, then back inside
    bars += [Bar(100.5, 102.6, 100.3, 102.2, 1200.0)]
    bars += [Bar(102.0, 102.1, 99.6, 100.0, 1100.0)]
    bars += _flat_bars(8, 100.0, 1.0, seed + 2)
    breakdown_start = len(bars)
    bars += _trend_bars(40, 98.8, -0.8, 0.5, seed + 3, vol=2600.0)
    return bars, {'coil_start': coil_start, 'fake_bar': coil_start + 35,
                  'breakdown_start': breakdown_start, 'direction': 'down'}


def scenario_chop(seed=13):
    """Pure noisy random walk — a good detector should not fire often."""
    rng = random.Random(seed)
    bars = []
    price = 100.0
    for _ in range(400):
        o = price
        price *= 1 + rng.uniform(-0.02, 0.02)
        c = price
        h = max(o, c) * (1 + rng.uniform(0, 0.008))
        l = min(o, c) * (1 - rng.uniform(0, 0.008))
        bars.append(Bar(o, h, l, c, 1000 + rng.uniform(-300, 300)))
    return bars, {}


def scenario_retest_breakout(seed=21):
    """Coil -> breakout up -> pullback that retests the broken level -> resume up."""
    bars = _trend_bars(150, 85, 0.15, 1.6, seed)
    coil_start = len(bars)
    bars += _flat_bars(40, 100.0, 1.0, seed + 1)
    # breakout leg
    bars += _trend_bars(6, 101.2, 1.0, 0.4, seed + 2, vol=2500.0)
    # pullback to the broken level (~101) holding above it
    top = bars[-1].c
    pull = []
    price = top
    rng = random.Random(seed + 3)
    steps = 6
    for k in range(steps):
        o = price
        price = top - (top - 101.3) * (k + 1) / steps + rng.uniform(-0.15, 0.15)
        c = price
        pull.append(Bar(o, max(o, c) + 0.2, min(o, c) - 0.2, c, 900.0))
    bars += pull
    retest_end = len(bars)
    bars += _trend_bars(30, price, 0.9, 0.4, seed + 4, vol=2400.0)
    return bars, {'coil_start': coil_start, 'retest_end': retest_end,
                  'direction': 'up', 'level': 101.0}


# ---------------------------------------------------------------- v6 simulator
def simulate_v6(bars, lookback=20, confirm_bars=2, mode="adaptive",
                compression=0.6, baseline_len=100, fixed_thresh=5.0,
                atr_buf_mult=0.0, use_vol_filter=False, vol_ma_len=20,
                stop_mode="midpoint", retest_band_atr=0.25, retest_window=20,
                t1_mult=1.0, t2_mult=2.0, min_coil_bars=3, grace_bars=5):
    """v6: identical detection core + frozen zone levels captured at the raw
    break, retest entry signals, failed-breakout exit, stop/target tracking."""
    highs = RollingWindow(lookback)
    lows = RollingWindow(lookback)
    baseline = RollingWindow(baseline_len)
    vol_ma = RollingWindow(vol_ma_len)
    atr = RMA(14)

    hh_prev = ll_prev = math.nan
    prev_close = math.nan
    dir_ = 0
    confirm_cnt = 0
    broken_level = math.nan
    saved_high = saved_low = math.nan     # zone frozen at the raw-break bar
    armed = False
    was_consolidating = False
    coil_age = 0
    coil_age_prev = 0
    ended_coil_age = 0
    coil_high = coil_low = math.nan   # expand-only coil-extent levels
    coil_end = None

    # trade plan state (stop/target tracking)
    plan_dir = 0
    plan_entry = plan_stop = plan_t1 = plan_t2 = math.nan
    plan_bar = -1
    t1_hit = False
    # flip-level state (retest / failed-break tracking; outlives the plan)
    flip_dir = 0
    flip_level = math.nan
    flip_bar = -1
    retest_done = False

    signals = []
    zone_tops_at_signal = {}   # bar -> drawn zone top (to compare v5 sliding vs v6 frozen)

    for i, b in enumerate(bars):
        highs.push(b.h)
        lows.push(b.l)
        hh_raw = highs.highest()
        ll_raw = lows.lowest()
        range_high, range_low = hh_prev, ll_prev

        if not math.isnan(prev_close):
            tr = max(b.h - b.l, abs(b.h - prev_close), abs(b.l - prev_close))
        else:
            tr = b.h - b.l
        atr_val = atr.push(tr)
        vol_ma.push(b.v)
        vma = vol_ma.sma()

        avg_price = (range_high + range_low) / 2 if not math.isnan(range_high) else math.nan
        range_pct = ((range_high - range_low) / avg_price * 100
                     if not math.isnan(avg_price) and avg_price != 0 else math.nan)
        baseline.push(range_pct)
        if mode == "adaptive":
            base = baseline.sma()
            eff_thresh = base * compression if not math.isnan(base) else math.nan
        else:
            eff_thresh = fixed_thresh
        is_cons = (not math.isnan(range_pct) and not math.isnan(eff_thresh)
                   and range_pct <= eff_thresh)
        coil_age = (coil_age + 1) if is_cons and was_consolidating else (1 if is_cons else 0)
        if not is_cons and was_consolidating:
            ended_coil_age = coil_age_prev
            coil_end = i
        coil_age_prev = coil_age

        # expand-only coil-extent levels (frozen once the coil ends)
        if is_cons and not was_consolidating:
            coil_high, coil_low = range_high, range_low
            coil_end = None
        elif is_cons:
            coil_high = max(coil_high, range_high)
            coil_low = min(coil_low, range_low)

        buffer = (atr_buf_mult * atr_val) if not math.isnan(atr_val) else 0.0
        vol_ok = (not use_vol_filter) or (not math.isnan(vma) and b.v > vma)
        in_break_window = is_cons or (coil_end is not None and i - coil_end <= grace_bars)
        age_ok = (coil_age >= min_coil_bars) if is_cons else (ended_coil_age >= min_coil_bars)
        raw_up = (in_break_window and age_ok and
                  not math.isnan(coil_high) and b.c > coil_high + buffer and vol_ok)
        raw_dn = (in_break_window and age_ok and
                  not math.isnan(coil_low) and b.c < coil_low - buffer and vol_ok)

        if is_cons and not was_consolidating:
            armed = True

        # hold/reset: confirmation closes held to the same buffered standard as
        # the break; a close between level and level+buffer stalls the count.
        reset_from = 0
        if dir_ == 1:
            if b.c > broken_level + buffer:
                confirm_cnt += 1
            elif b.c <= broken_level:
                reset_from = 1
                dir_, confirm_cnt, broken_level = 0, 0, math.nan
        elif dir_ == -1:
            if b.c < broken_level - buffer:
                confirm_cnt += 1
            elif b.c >= broken_level:
                reset_from = -1
                dir_, confirm_cnt, broken_level = 0, 0, math.nan

        # entry — may run on the same bar as a reset (fakeout reversal capture),
        # but never re-enters the direction that just failed.
        if dir_ == 0:
            if armed and raw_up and reset_from != 1:
                dir_, broken_level, confirm_cnt = 1, coil_high, 1
                saved_high, saved_low = coil_high, coil_low
            elif armed and raw_dn and reset_from != -1:
                dir_, broken_level, confirm_cnt = -1, coil_low, 1
                saved_high, saved_low = coil_high, coil_low

        conf_up = dir_ == 1 and confirm_cnt == confirm_bars
        conf_dn = dir_ == -1 and confirm_cnt == confirm_bars

        if conf_up or conf_dn:
            zone_h = saved_high - saved_low
            plan_dir = 1 if conf_up else -1
            plan_entry = saved_high if conf_up else saved_low
            if stop_mode == "midpoint":
                plan_stop = (saved_high + saved_low) / 2
            elif stop_mode == "opposite":
                plan_stop = saved_low if conf_up else saved_high
            else:  # atr
                plan_stop = plan_entry - 1.5 * atr_val * plan_dir
            plan_t1 = plan_entry + plan_dir * t1_mult * zone_h
            plan_t2 = plan_entry + plan_dir * t2_mult * zone_h
            plan_bar = i
            t1_hit = False
            flip_dir, flip_level, flip_bar = plan_dir, plan_entry, i
            retest_done = False
            kind = 'up' if conf_up else 'down'
            signals.append(Signal(i, kind, plan_entry, b.c,
                                  {'stop': plan_stop, 't1': plan_t1, 't2': plan_t2,
                                   'zone_top_frozen': saved_high,
                                   'zone_top_sliding': range_high}))
            dir_, confirm_cnt, armed = 0, 0, False
            broken_level = math.nan

        else:
            # ---- flip-level tracking (retest entries + failed-break warning);
            # independent of the stop/target plan so a retest can fire even
            # after targets are tagged.
            if flip_dir != 0:
                band = retest_band_atr * (atr_val if not math.isnan(atr_val) else 0)
                if flip_dir == 1:
                    if not retest_done and i - flip_bar <= retest_window and \
                            b.l <= flip_level + band and b.c > flip_level:
                        signals.append(Signal(i, 'retest_up', flip_level, b.c))
                        retest_done = True
                    if b.c < flip_level:
                        signals.append(Signal(i, 'exit_fail', flip_level, b.c))
                        flip_dir = 0
                        if is_cons:
                            armed = True
                else:
                    if not retest_done and i - flip_bar <= retest_window and \
                            b.h >= flip_level - band and b.c < flip_level:
                        signals.append(Signal(i, 'retest_down', flip_level, b.c))
                        retest_done = True
                    if b.c > flip_level:
                        signals.append(Signal(i, 'exit_fail', flip_level, b.c))
                        flip_dir = 0
                        if is_cons:
                            armed = True

            # ---- stop/target plan tracking
            if plan_dir == 1:
                if b.c < plan_stop:
                    signals.append(Signal(i, 'exit_stop', plan_stop, b.c))
                    plan_dir = 0
                elif not t1_hit and b.h >= plan_t1:
                    signals.append(Signal(i, 't1_hit', plan_t1, b.c))
                    t1_hit = True
                elif t1_hit and b.h >= plan_t2:
                    signals.append(Signal(i, 't2_hit', plan_t2, b.c))
                    plan_dir = 0
            elif plan_dir == -1:
                if b.c > plan_stop:
                    signals.append(Signal(i, 'exit_stop', plan_stop, b.c))
                    plan_dir = 0
                elif not t1_hit and b.l <= plan_t1:
                    signals.append(Signal(i, 't1_hit', plan_t1, b.c))
                    t1_hit = True
                elif t1_hit and b.l <= plan_t2:
                    signals.append(Signal(i, 't2_hit', plan_t2, b.c))
                    plan_dir = 0

            # a fresh coil supersedes previous tracking
            if is_cons and not was_consolidating:
                plan_dir = 0
                flip_dir = 0

        hh_prev, ll_prev = hh_raw, ll_raw
        prev_close = b.c
        was_consolidating = is_cons

    return {'signals': signals}


def scenario_confirmed_then_collapse(seed=31):
    """Coil -> genuine 2-close confirmed breakout up -> full collapse back through
    the zone. v5 gives the trader nothing after the entry; v6 must warn."""
    bars = _trend_bars(150, 90, 0.12, 1.8, seed)
    coil_start = len(bars)
    bars += _flat_bars(35, 100.0, 1.0, seed + 1)
    # two solid closes above the range -> confirmed signal
    bars += [Bar(100.6, 102.4, 100.4, 102.1, 2000.0),
             Bar(102.1, 103.0, 101.6, 102.7, 1900.0)]
    # collapse
    bars += _trend_bars(25, 102.0, -0.9, 0.4, seed + 2, vol=2200.0)
    return bars, {'coil_start': coil_start, 'confirm_bar': coil_start + 36}


def scenario_decaying_coil(seed=41):
    """Long coil with an early spike to ~103 that ages out of the 20-bar rolling
    window. v5's decayed level fires 'inside the real zone'; v6's expand-only
    coil boundary waits for the structural break."""
    bars = _trend_bars(150, 90, 0.12, 1.8, seed)
    coil_start = len(bars)
    bars += _flat_bars(4, 100.0, 1.0, seed + 2)
    bars += [Bar(100.5, 103.0, 100.2, 100.8, 1400.0)]      # early spike
    bars += _flat_bars(45, 100.0, 1.0, seed + 3)           # spike ages out
    bars += _trend_bars(15, 100.8, 0.45, 0.3, seed + 4, vol=2200.0)
    return bars, {'coil_start': coil_start, 'spike_top': 103.0,
                  'direction': 'up'}
