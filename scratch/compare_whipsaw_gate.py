"""
Improvement 1 Backtest Comparison: Anti-Whipsaw Entry Gate
-----------------------------------------------------------
Runs DTE=45 / Delta=0.70 with:
  A) Baseline       (cooling=0, ema_confirm=0)
  B) Cooling only   (cooling=7, ema_confirm=0)
  C) EMA only       (cooling=0, ema_confirm=3)
  D) Combined       (cooling=7, ema_confirm=3)  ← recommended
  E) Aggressive     (cooling=14, ema_confirm=5)

Prints a side-by-side comparison table.
"""

import os
import sys
import yaml
import math
import numpy as np
import pandas as pd
from datetime import date
from backtester.data_loader import DataLoader
from backtester.engine import BacktestEngine
from backtester.metrics import calculate_metrics

# ── Config ─────────────────────────────────────────────────────────────────

CONFIGS = [
    {"label": "A) Baseline",         "cooling_days": 0,  "ema_confirm_days": 0},
    {"label": "B) Cooling only",     "cooling_days": 7,  "ema_confirm_days": 0},
    {"label": "C) EMA only",         "cooling_days": 0,  "ema_confirm_days": 3},
    {"label": "D) Combined ★",       "cooling_days": 7,  "ema_confirm_days": 3},
    {"label": "E) Aggressive",       "cooling_days": 14, "ema_confirm_days": 5},
]

# ── Helpers ─────────────────────────────────────────────────────────────────

def _sharpe(returns, rf=0.045):
    """Annualised Sharpe from daily return series."""
    excess = returns - rf / 252
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(252))

def _sortino(returns, rf=0.045):
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float((returns.mean() - rf / 252) / downside.std() * np.sqrt(252))

def _max_drawdown(equity):
    roll_max = np.maximum.accumulate(equity)
    dd = (equity - roll_max) / roll_max
    return float(dd.min())

def _cagr(equity, n_days):
    if equity[0] == 0 or n_days == 0:
        return 0.0
    years = n_days / 252
    return float((equity[-1] / equity[0]) ** (1 / years) - 1)

def run_one(base_config, extra_params, loader, stock_df):
    cfg = dict(base_config)
    cfg.update(extra_params)
    
    engine = BacktestEngine(cfg, loader)
    daily_pl = engine.run_backtest()
    daily_df = daily_pl.to_pandas()
    daily_df['date'] = pd.to_datetime(daily_df['date']).dt.date

    metrics = calculate_metrics(daily_df, engine.trade_log, cfg, stock_df)

    equity = daily_df['portfolio_value'].values
    returns = pd.Series(equity).pct_change().dropna().values

    # Cycle stats
    entries  = [e for e in engine.trade_log if e['event'] == 'ENTRY']
    exits    = [e for e in engine.trade_log if e['event'] in ('TREND_EXIT', 'CASH_OVERRIDE_LIQ', 'EXPIRATION', 'ASSIGNMENT')]
    pnls     = [e['net_return'] for e in exits]
    winners  = [p for p in pnls if p > 0]
    losers   = [p for p in pnls if p <= 0]

    return {
        'cagr':           _cagr(equity, len(equity)),
        'sharpe':         _sharpe(returns),
        'sortino':        _sortino(returns),
        'max_dd':         _max_drawdown(equity),
        'final_equity':   equity[-1],
        'n_entries':      len(entries),
        'n_exits':        len(exits),
        'win_rate':       len(winners) / len(pnls) if pnls else 0.0,
        'avg_win':        np.mean(winners) if winners else 0.0,
        'avg_loss':       np.mean(losers) if losers else 0.0,
        'total_pnl':      sum(pnls),
        'whipsaw_blocks': engine.whipsaw_blocks_count,
        'trade_log':      engine.trade_log,
    }

# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  IMPROVEMENT 1 BACKTEST: Anti-Whipsaw Gate Parameter Sweep")
    print("=" * 70)

    if not os.path.exists("config.yaml"):
        print("Error: config.yaml not found. Run from project root.")
        sys.exit(1)

    with open("config.yaml", "r") as f:
        base_config = yaml.safe_load(f)

    base_config['target_dte']      = 45
    base_config['baseline_delta']  = 0.70

    loader = DataLoader(creds_path="creds.txt")
    loader.is_mock = True

    stock_path = os.path.join("data", "TSLA_daily.parquet")
    stock_df = pd.read_parquet(stock_path)
    stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.date

    results = []
    for cfg_extra in CONFIGS:
        label = cfg_extra['label']
        params = {k: v for k, v in cfg_extra.items() if k != 'label'}
        print(f"\nRunning {label} (cooling={params['cooling_days']}d, ema_confirm={params['ema_confirm_days']}d)...")
        r = run_one(base_config, params, loader, stock_df)
        r['label'] = label
        results.append(r)
        print(f"  → Entries={r['n_entries']}, Exits={r['n_exits']}, "
              f"Win%={r['win_rate']*100:.0f}%, CAGR={r['cagr']*100:.1f}%, "
              f"Sharpe={r['sharpe']:.2f}, Blocks={r['whipsaw_blocks']}")

    baseline = results[0]

    # ── Pretty comparison table ─────────────────────────────────────────────
    print("\n")
    print("=" * 100)
    print(f"{'':32} {'Baseline':>10}  " + "  ".join(f"{r['label']:>16}" for r in results[1:]))
    print("=" * 100)

    metrics_display = [
        ("Final Equity ($)",      'final_equity',   "${:,.0f}",    True),
        ("CAGR (%)",              'cagr',           "{:.2%}",      True),
        ("Sharpe",                'sharpe',         "{:.3f}",      True),
        ("Sortino",               'sortino',        "{:.3f}",      True),
        ("Max Drawdown (%)",      'max_dd',         "{:.2%}",      False),  # less negative = better
        ("Win Rate (%)",          'win_rate',       "{:.1%}",      True),
        ("Avg Win ($)",           'avg_win',        "${:,.0f}",    True),
        ("Avg Loss ($)",          'avg_loss',       "${:,.0f}",    False),
        ("# Trade Cycles",        'n_entries',      "{:d}",        None),
        ("# Exits",               'n_exits',        "{:d}",        None),
        ("Days Blocked",          'whipsaw_blocks', "{:d}",        None),
    ]

    for display_name, key, fmt, higher_is_better in metrics_display:
        base_val = baseline[key]
        row = f"  {display_name:30}"
        
        # Baseline value
        base_str = fmt.format(base_val) if not isinstance(base_val, float) or key != 'n_entries' else fmt.format(int(base_val))
        row += f"  {base_str:>10}"
        
        for r in results[1:]:
            val = r[key]
            val_str = fmt.format(val)
            
            if higher_is_better is not None:
                delta = val - base_val
                if higher_is_better:
                    marker = "✅" if delta > 0 else ("⚠️ " if abs(delta) < 0.001 else "❌")
                else:
                    marker = "✅" if delta < 0 else ("⚠️ " if abs(delta) < 0.001 else "❌")
            else:
                marker = "  "
            
            row += f"  {val_str:>14} {marker}"
        
        print(row)

    print("=" * 100)

    # ── Cycle-level analysis: show what changed ─────────────────────────────
    print("\n── Trade Cycle Changes vs Baseline ────────────────────────────────────")
    base_entries = [e for e in baseline['trade_log'] if e['event'] == 'ENTRY']
    best = results[3]  # D) Combined ★
    best_entries = [e for e in best['trade_log'] if e['event'] == 'ENTRY']

    base_dates = set(e['date'] for e in base_entries)
    best_dates  = set(e['date'] for e in best_entries)

    blocked = sorted(base_dates - best_dates)
    new     = sorted(best_dates - base_dates)

    if blocked:
        print(f"\n  ❌ Entries BLOCKED by gate (Combined ★ vs Baseline):")
        for d in blocked:
            ev = next(e for e in base_entries if e['date'] == d)
            print(f"     {d}  stock=${ev['stock_price']:.2f}")

    if new:
        print(f"\n  ✅ New/Shifted Entries in Combined ★:")
        for d in new:
            ev = next(e for e in best_entries if e['date'] == d)
            print(f"     {d}  stock=${ev['stock_price']:.2f}")

    if not blocked and not new:
        print("  No change in entry dates.")

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
