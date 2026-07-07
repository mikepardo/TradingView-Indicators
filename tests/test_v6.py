"""Compare v5 vs v6 behavior: entry precision, exit protection, zone freezing."""
from pine_sim import (simulate_v5, simulate_v6, scenario_clean_breakout_up,
                      scenario_false_break_then_down, scenario_chop,
                      scenario_retest_breakout, scenario_confirmed_then_collapse,
                      scenario_decaying_coil)


def show(name, res):
    print(f"  [{name}]")
    for s in res['signals']:
        line = (f"    {s.kind:11s} @bar {s.bar:3d}  level={s.level:8.2f}  close={s.close:8.2f}")
        if s.extra:
            line += (f"  stop={s.extra['stop']:.2f} t1={s.extra['t1']:.2f} "
                     f"t2={s.extra['t2']:.2f}")
            if abs(s.extra['zone_top_frozen'] - s.extra['zone_top_sliding']) > 1e-9:
                line += (f"  [zone top: frozen {s.extra['zone_top_frozen']:.2f} vs "
                         f"sliding {s.extra['zone_top_sliding']:.2f} <- v5 box would inflate]")
        print(line)
    if not res['signals']:
        print("    (no signals)")


def main():
    scenarios = [
        ("clean up-breakout", scenario_clean_breakout_up),
        ("false break then breakdown", scenario_false_break_then_down),
        ("pure chop", scenario_chop),
        ("breakout + retest + resume", scenario_retest_breakout),
        ("confirmed breakout then collapse", scenario_confirmed_then_collapse),
        ("decaying coil (early spike ages out)", scenario_decaying_coil),
    ]
    for name, maker in scenarios:
        bars, truth = maker()
        print(f"\n=== {name} ===")
        show("v5", simulate_v5(bars))
        show("v6", simulate_v6(bars))

        # quantify the headline improvements
        v6 = simulate_v6(bars)
        bo = next((s for s in v6['signals'] if s.kind in ('up', 'down')), None)
        rt = next((s for s in v6['signals'] if s.kind.startswith('retest')), None)
        if bo and rt:
            chase = abs(bo.close - bo.level)
            retest_entry = abs(rt.close - rt.level)
            print(f"    >>> entry improvement: chasing at signal costs {chase:.2f} above level;"
                  f" retest entry gets filled {retest_entry:.2f} from level"
                  f" ({(1 - retest_entry / chase) * 100:.0f}% tighter)")
        fail = next((s for s in v6['signals'] if s.kind == 'exit_fail'), None)
        if bo and fail:
            last_close = bars[-1].c
            loss_with_exit = (fail.close - bo.close) * (1 if bo.kind == 'up' else -1)
            loss_without = (last_close - bo.close) * (1 if bo.kind == 'up' else -1)
            print(f"    >>> exit protection: fail-warn at bar {fail.bar} close {fail.close:.2f}"
                  f" (P&L {loss_with_exit:+.2f}); holding to end of data: {loss_without:+.2f}")


if __name__ == "__main__":
    main()
