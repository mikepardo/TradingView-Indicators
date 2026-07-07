"""Characterize v5 behavior on ground-truth scenarios: signal timing, entry quality."""
import math
from pine_sim import (simulate_v5, scenario_clean_breakout_up,
                      scenario_false_break_then_down, scenario_chop,
                      scenario_retest_breakout)


def report(name, bars, truth, res):
    print(f"\n=== {name} ===  ({len(bars)} bars)")
    sigs = res['signals']
    cons_spans = []
    start = None
    for i, f in enumerate(res['consolidating']):
        if f and start is None:
            start = i
        elif not f and start is not None:
            cons_spans.append((start, i - 1))
            start = None
    if start is not None:
        cons_spans.append((start, len(bars) - 1))
    print(f"consolidation spans: {cons_spans}")
    for s in sigs:
        # entry-quality metrics: distance of signal close from the broken level
        zone_h = None
        rh, rl = res['range_high'][s.bar], res['range_low'][s.bar]
        slip = abs(s.close - s.level)
        slip_pct = slip / s.level * 100
        print(f"signal {s.kind:5s} @bar {s.bar}  level={s.level:.2f}  close={s.close:.2f}  "
              f"slippage={slip:.2f} ({slip_pct:.2f}% of level)")
    if truth:
        print(f"ground truth: {truth}")
    if not sigs:
        print("no signals")
    return sigs


def main():
    for maker, name in [(scenario_clean_breakout_up, "clean up-breakout"),
                        (scenario_false_break_then_down, "false break then breakdown"),
                        (scenario_chop, "pure chop"),
                        (scenario_retest_breakout, "breakout + retest + resume")]:
        bars, truth = maker()
        res = simulate_v5(bars)
        sigs = report(name, bars, truth, res)

        # extra diagnostics on the clean scenario: how late is the signal?
        if name == "clean up-breakout" and sigs:
            s = sigs[0]
            bo = truth['breakout_start']
            print(f"breakout leg starts @bar {bo}; signal fired {s.bar - bo} bars later; "
                  f"price ran {s.close - s.level:.2f} past the level before the trader "
                  f"got a signal (zone height was ~2.0)")


if __name__ == "__main__":
    main()
