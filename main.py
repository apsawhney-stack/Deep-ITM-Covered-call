import os
import yaml
import math
import numpy as np
import pandas as pd
import polars as pl
import matplotlib.pyplot as plt
from datetime import datetime, date, timedelta

import requests
import thetadata.client

# Monkeypatch requests to enforce a 15-second default timeout to prevent indefinite hangs
_original_get = requests.get
def _patched_get(*args, **kwargs):
    if 'timeout' not in kwargs:
        kwargs['timeout'] = 15.0
    return _original_get(*args, **kwargs)
requests.get = _patched_get
if hasattr(thetadata.client, 'requests'):
    thetadata.client.requests.get = _patched_get

from backtester.data_loader import DataLoader
from backtester.engine import BacktestEngine
from backtester.metrics import calculate_metrics, calculate_base_metrics

def run_buy_and_hold(stock_df: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    """
    Simulates Buy & Hold TSLA benchmark.
    Cash is used to buy shares on day 1 at Close.
    Accrues Treasury interest on fractional leftover cash.
    """
    df = stock_df.sort_values('Date').reset_index(drop=True)
    dates = df['Date'].tolist()
    closes = df['Close'].tolist()
    rates = df['Treasury_Yield_3M'].tolist()
    
    # Buy shares on day 1
    s0 = closes[0]
    shares = math.floor(starting_capital / s0)
    cash = starting_capital - (shares * s0)
    
    history = []
    prev_date = None
    
    for idx, row in df.iterrows():
        curr_date = row['Date']
        close_p = row['Close']
        rate = row['Treasury_Yield_3M']
        
        # Interest on cash
        if prev_date is not None:
            dt = (curr_date - prev_date).days
            interest = cash * (rate / 365.0) * dt
            cash += interest
            
        port_val = cash + (shares * close_p)
        history.append({
            'date': curr_date,
            'portfolio_value': port_val,
            'cash': cash,
            'shares': shares,
            'stock_close': close_p,
            'treasury_rate': rate
        })
        prev_date = curr_date
        
    return pd.DataFrame(history)

def run_treasury_cash(stock_df: pd.DataFrame, starting_capital: float) -> pd.DataFrame:
    """
    Simulates 100% Cash benchmark earning Treasury yield daily.
    """
    df = stock_df.sort_values('Date').reset_index(drop=True)
    cash = starting_capital
    history = []
    prev_date = None
    
    for idx, row in df.iterrows():
        curr_date = row['Date']
        rate = row['Treasury_Yield_3M']
        
        if prev_date is not None:
            dt = (curr_date - prev_date).days
            interest = cash * (rate / 365.0) * dt
            cash += interest
            
        history.append({
            'date': curr_date,
            'portfolio_value': cash,
            'cash': cash,
            'shares': 0,
            'stock_close': row['Close'],
            'treasury_rate': rate
        })
        prev_date = curr_date
        
    return pd.DataFrame(history)



def main():
    print("==============================================================")
    print("   DEEP ITM COVERED CALL BACKTESTER & PARAMETER OPTIMIZER     ")
    print("==============================================================")
    
    # 1. Load Configurations
    if not os.path.exists("config.yaml"):
        raise FileNotFoundError("config.yaml not found. Please create it in the workspace.")
        
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
        
    os.makedirs("results", exist_ok=True)
    
    # 2. Download Stock and Macro Data
    loader = DataLoader(creds_path="creds.txt")
    client = loader.get_client()
    
    print("Connecting to local Theta Terminal server...", flush=True)
    with client.connect():
        print(f"Loading/Downloading stock daily database...", flush=True)
        stock_pl = loader.download_stock_and_macro_data(
            ticker=config['asset'],
            start_str=config['start_date'],
            end_str=config['end_date']
        )
        stock_df = stock_pl.to_pandas()
        stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.date
        
        # Load existing results if file exists to allow resuming
        results_sweep = []
        completed_runs = set()
        if os.path.exists("results/backtest_results.csv"):
            try:
                existing_df = pd.read_csv("results/backtest_results.csv")
                if not existing_df.empty and "target_dte" in existing_df.columns and "target_delta" in existing_df.columns:
                    for idx, row in existing_df.iterrows():
                        dte_val = int(row['target_dte'])
                        delta_val = float(row['target_delta'])
                        # Allow resuming completed runs for DTE 15, 30, and 45.
                        if dte_val in [15, 30, 45]:
                            completed_runs.add((dte_val, delta_val))
                            results_sweep.append({
                                'target_dte': dte_val,
                                'target_delta': delta_val,
                                'cagr': float(row['cagr']),
                                'sharpe': float(row['sharpe']),
                                'sortino': float(row['sortino']),
                                'max_dd': float(row['max_dd']),
                                'win_rate': float(row['win_rate']),
                                'income_swept': float(row['income_swept'])
                            })
                    print(f"Loaded {len(completed_runs)} completed sweeps from results/backtest_results.csv.", flush=True)
            except Exception as e:
                print(f"Error loading existing results: {e}. Starting fresh.", flush=True)
                
        # Define Parameter Sweep Range
        dte_sweep = [15, 30, 45, 7]
        delta_sweep = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.93, 0.95]
        
        print("\nStarting Parameter Sweep Grid Search...", flush=True)
        print(f"DTEs to test: {dte_sweep}", flush=True)
        print(f"Deltas to test: {delta_sweep}", flush=True)
        print("--------------------------------------------------------------", flush=True)
        
        # Run Grid Search
        for dte in dte_sweep:
            for delta in delta_sweep:
                if (dte, delta) in completed_runs:
                    print(f"Skipping completed sweep: DTE = {dte}, Delta = {delta}", flush=True)
                    continue
                    
                print(f"Running sweep: DTE = {dte}, Delta = {delta}...", flush=True)
                
                # Setup configuration for this run
                run_config = config.copy()
                run_config['target_dte'] = dte
                run_config['baseline_delta'] = delta
                
                # Run simulation
                engine = BacktestEngine(run_config, loader)
                daily_history = engine.run_backtest()
                
                # Calculate metrics
                metrics = calculate_metrics(daily_history, engine.trade_log, run_config, stock_df)
                
                if metrics:
                    cagr = metrics['overall']['cagr']
                    sharpe = metrics['overall']['sharpe']
                    sortino = metrics['overall']['sortino']
                    max_dd = metrics['overall']['max_dd']
                    win_rate = metrics['overall']['win_rate']
                    
                    results_sweep.append({
                        'target_dte': dte,
                        'target_delta': delta,
                        'cagr': cagr,
                        'sharpe': sharpe,
                        'sortino': sortino,
                        'max_dd': max_dd,
                        'win_rate': win_rate,
                        'income_swept': daily_history['income_ledger'].iloc[-1],
                        'metrics_dict': metrics,
                        'history_df': daily_history,
                        'trade_log': engine.trade_log
                    })
                    print(f"  Result: CAGR = {cagr*100:.2f}%, Sortino = {sortino:.2f}, MaxDD = {max_dd*100:.2f}%", flush=True)
                    
                    # Save incremental sweep results to CSV
                    sweep_df_temp = pd.DataFrame([
                        {k: v for k, v in r.items() if k not in ['metrics_dict', 'history_df', 'trade_log']}
                        for r in results_sweep
                    ])
                    sweep_df_temp.to_csv("results/backtest_results.csv", index=False)
                    
        # Save sweep results to CSV
        sweep_df = pd.DataFrame([
            {k: v for k, v in r.items() if k not in ['metrics_dict', 'history_df', 'trade_log']}
            for r in results_sweep
        ])
        sweep_filepath = "results/backtest_results.csv"
        sweep_df.to_csv(sweep_filepath, index=False)
        print(f"\nSaved all grid search sweeps to {sweep_filepath}", flush=True)
        
        # 3. Robustness and Delta Band Stability Analytics
        # Clustered Delta Bands:
        # - Moderate Overwrite: 0.60 to 0.75
        # - Defensive Overwrite: 0.80 to 0.88
        # - Deep ITM Carry: 0.90 to 0.95
        bands = {
            'Moderate Overwrite (0.60-0.75)': [r for r in results_sweep if 0.60 <= r['target_delta'] <= 0.75],
            'Defensive Overwrite (0.80-0.88)': [r for r in results_sweep if 0.80 <= r['target_delta'] <= 0.88],
            'Deep ITM Carry (0.90-0.95)': [r for r in results_sweep if 0.90 <= r['target_delta'] <= 0.95]
        }
        
        print("\n==============================================================", flush=True)
        print("   INTRA-REGIME STABILITY COEFFICIENTS (VARIANCE ANALYSIS)    ", flush=True)
        print("==============================================================", flush=True)
        for band_name, band_runs in bands.items():
            if len(band_runs) > 1:
                sortinos = [r['sortino'] for r in band_runs]
                max_dds = [r['max_dd'] for r in band_runs]
                
                sortino_var = np.var(sortinos)
                max_dd_var = np.var(max_dds)
                
                print(f"{band_name}:", flush=True)
                print(f"  Sortino Ratio Variance: {sortino_var:.6f} (Std Dev: {np.std(sortinos):.4f})", flush=True)
                print(f"  Max Drawdown Variance:  {max_dd_var:.6f} (Std Dev: {np.std(max_dds):.4f})", flush=True)
            else:
                print(f"{band_name}: Insufficient runs to compute variance.", flush=True)
        print("--------------------------------------------------------------", flush=True)
        
        # Find Optimal settings (maximizing Sortino Ratio)
        optimal_run = max(results_sweep, key=lambda r: r['sortino'])
        opt_dte = optimal_run['target_dte']
        opt_delta = optimal_run['target_delta']
        
        # If the optimal run was loaded from checkpoint, re-run its simulation once to populate full logs/history
        if 'metrics_dict' not in optimal_run:
            print(f"\nRe-running optimal strategy configuration (DTE = {opt_dte}, Delta = {opt_delta}) to gather full logs...", flush=True)
            run_config = config.copy()
            run_config['target_dte'] = opt_dte
            run_config['baseline_delta'] = opt_delta
            engine = BacktestEngine(run_config, loader)
            opt_history = engine.run_backtest()
            opt_metrics = calculate_metrics(opt_history, engine.trade_log, run_config, stock_df)
            opt_trade_log = engine.trade_log
        else:
            opt_metrics = optimal_run['metrics_dict']
            opt_history = optimal_run['history_df']
            opt_trade_log = optimal_run['trade_log']
            
        strategy_metrics = opt_metrics['overall']
        
        print(f"\n>>> Optimal Parameters Identified: DTE = {opt_dte}, Delta = {opt_delta} (Sortino: {strategy_metrics['sortino']:.2f})", flush=True)
        
        # 4. Simulate Benchmarks
        print("\nSimulating Benchmark Strategies...", flush=True)
        starting_capital = config['starting_capital']
        
        # Benchmark A: Buy & Hold TSLA
        bh_history = run_buy_and_hold(stock_df, starting_capital)
        bh_history['daily_return'] = bh_history['portfolio_value'].pct_change()
        bh_history.loc[0, 'daily_return'] = 0.0
        bh_metrics = calculate_base_metrics(
            returns=bh_history['daily_return'].iloc[1:],
            values=bh_history['portfolio_value'],
            dates=bh_history['date'],
            treasury_rates=bh_history['treasury_rate']
        )
        
        # Benchmark B: Short-Duration Treasury cash
        cash_history = run_treasury_cash(stock_df, starting_capital)
        cash_history['daily_return'] = cash_history['portfolio_value'].pct_change()
        cash_history.loc[0, 'daily_return'] = 0.0
        cash_metrics = calculate_base_metrics(
            returns=cash_history['daily_return'].iloc[1:],
            values=cash_history['portfolio_value'],
            dates=cash_history['date'],
            treasury_rates=cash_history['treasury_rate']
        )
        
        # Benchmark C: Standard OTM Covered Call (30 Delta monthly overwrite, no EMA, no stop loss, no VRP gates)
        print("  Simulating Standard 30-Delta OTM Covered Call benchmark...", flush=True)
        otm_config = config.copy()
        otm_config['target_dte'] = 30
        otm_config['baseline_delta'] = 0.30
        otm_config['disable_stop_loss'] = True
        otm_config['disable_ema_filter'] = True
        otm_config['disable_vrp_filter'] = True
        
        otm_engine = BacktestEngine(otm_config, loader)
        otm_history = otm_engine.run_backtest()
        otm_history['daily_return'] = otm_history['portfolio_value'].pct_change()
        otm_history.loc[0, 'daily_return'] = 0.0
        otm_metrics = calculate_base_metrics(
            returns=otm_history['daily_return'].iloc[1:],
            values=otm_history['portfolio_value'],
            dates=otm_history['date'],
            treasury_rates=otm_history['treasury_rate']
        )
        
        # 5. Output Graphics
        print("\nGenerating Performance Charts...", flush=True)
        plt.figure(figsize=(12, 7))
        plt.plot(opt_history['date'], opt_history['portfolio_value'], label=f'Optimal ITM Covered Call (DTE {opt_dte}, $\\Delta$ {opt_delta})', color='#3b82f6', linewidth=2.0)
        plt.plot(bh_history['date'], bh_history['portfolio_value'], label='Buy & Hold TSLA', color='#ef4444', linewidth=1.5, alpha=0.8)
        plt.plot(otm_history['date'], otm_history['portfolio_value'], label='Standard 30-Delta OTM Covered Call', color='#10b981', linewidth=1.5, alpha=0.8)
        plt.plot(cash_history['date'], cash_history['portfolio_value'], label='3-Month US Treasury Cash', color='#6b7280', linewidth=1.2, linestyle='--')
        
        plt.title(f'{config["asset"]} Strategy Comparison (Starting capital: ${starting_capital:,.2f})', fontsize=14, fontweight='bold', pad=15)
        plt.xlabel('Date', fontsize=11, labelpad=10)
        plt.ylabel('Portfolio Value ($)', fontsize=11, labelpad=10)
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.legend(frameon=True, facecolor='#ffffff', edgecolor='#e2e8f0', loc='upper left')
        
        plt.tight_layout()
        plot_path = "results/equity_curves.png"
        plt.savefig(plot_path, dpi=300)
        plt.close()
        print(f"Performance chart saved to {plot_path}", flush=True)
        
        # 6. Print Comprehensive Summary Report
        print("\n==============================================================", flush=True)
        print("              FINAL STRATEGY PERFORMANCE COMPARISON           ", flush=True)
        print("==============================================================", flush=True)
        
        print(f"{'Metric':<25} | {'Active Strategy':<15} | {'Buy & Hold':<12} | {'OTM Overwrite':<14} | {'Treasury Proxy':<14}", flush=True)
        print("-" * 105, flush=True)
        
        print(f"{'Annualized CAGR':<25} | {strategy_metrics['cagr']*100:>13.2f}% | {bh_metrics['cagr']*100:>11.2f}% | {otm_metrics['cagr']*100:>12.2f}% | {cash_metrics['cagr']*100:>12.2f}%", flush=True)
        print(f"{'Sharpe Ratio':<25} | {strategy_metrics['sharpe']:>14.2f} | {bh_metrics['sharpe']:>12.2f} | {otm_metrics['sharpe']:>13.2f} | {cash_metrics['sharpe']:>13.2f}", flush=True)
        print(f"{'Sortino Ratio':<25} | {strategy_metrics['sortino']:>14.2f} | {bh_metrics['sortino']:>12.2f} | {otm_metrics['sortino']:>13.2f} | {cash_metrics['sortino']:>13.2f}", flush=True)
        print(f"{'Max Drawdown':<25} | {strategy_metrics['max_dd']*100:>13.2f}% | {bh_metrics['max_dd']*100:>11.2f}% | {otm_metrics['max_dd']*100:>12.2f}% | {cash_metrics['max_dd']*100:>12.2f}%", flush=True)
        print(f"{'Expected Shortfall (CVaR)':<25} | {strategy_metrics['cvar_95']*100:>13.2f}% | {'N/A':>12} | {'N/A':>13} | {'N/A':>13}", flush=True)
        print(f"{'Win Rate':<25} | {strategy_metrics['win_rate']*100:>13.2f}% | {bh_metrics['win_rate']*100:>11.2f}% | {otm_metrics['win_rate']*100:>12.2f}% | {cash_metrics['win_rate']*100:>12.2f}%", flush=True)
        print(f"{'Volatility (Annualized)':<25} | {strategy_metrics['volatility']*100:>13.2f}% | {bh_metrics['volatility']*100:>11.2f}% | {otm_metrics['volatility']*100:>12.2f}% | {cash_metrics['volatility']*100:>12.2f}%", flush=True)
        print("-" * 105, flush=True)
        print(f"{'Total Income Swept':<25} | ${opt_history['income_ledger'].iloc[-1]:>13,.2f} | {'N/A':>12} | {'N/A':>13} | {'N/A':>13}", flush=True)
        
        # 7. Print Event-Segregated Analytics
        print("\n==============================================================", flush=True)
        print("             EVENT-SEGREGATED PERFORMANCE ANALYSIS            ", flush=True)
        print("==============================================================", flush=True)
        seg_m = opt_metrics['segregated']
        print(f"{'Regime Segment':<25} | {'CAGR':<10} | {'Sortino':<10} | {'Max Drawdown':<12} | {'Win Rate':<10}", flush=True)
        print("-" * 75, flush=True)
        print(f"{'Earnings Weeks':<25} | {seg_m['earnings_weeks']['cagr']*100:>8.2f}% | {seg_m['earnings_weeks']['sortino']:>9.2f} | {seg_m['earnings_weeks']['max_dd']*100:>10.2f}% | {seg_m['earnings_weeks']['win_rate']*100:>8.2f}%", flush=True)
        print(f"{'FOMC Weeks':<25} | {seg_m['fomc_weeks']['cagr']*100:>8.2f}% | {seg_m['fomc_weeks']['sortino']:>9.2f} | {seg_m['fomc_weeks']['max_dd']*100:>10.2f}% | {seg_m['fomc_weeks']['win_rate']*100:>8.2f}%", flush=True)
        print(f"{'Crash Clusters':<25} | {seg_m['crash_clusters']['cagr']*100:>8.2f}% | {seg_m['crash_clusters']['sortino']:>9.2f} | {seg_m['crash_clusters']['max_dd']*100:>10.2f}% | {seg_m['crash_clusters']['win_rate']*100:>8.2f}%", flush=True)
        print(f"{'Non-Event Weeks':<25} | {seg_m['non_event_weeks']['cagr']*100:>8.2f}% | {seg_m['non_event_weeks']['sortino']:>9.2f} | {seg_m['non_event_weeks']['max_dd']*100:>10.2f}% | {seg_m['non_event_weeks']['win_rate']*100:>8.2f}%", flush=True)
        print("--------------------------------------------------------------", flush=True)
        
        # 8. Print VIX Regime Attribution Table
        print("\n==============================================================", flush=True)
        print("                  VIX REGIME ATTRIBUTION TABLE                ", flush=True)
        print("==============================================================", flush=True)
        vix_m = opt_metrics['vix_attribution']
        print(f"{'VIX Regime Bins':<25} | {'Ann. Return':<12} | {'Volatility':<12} | {'Sortino':<10} | {'Win Rate':<10}", flush=True)
        print("-" * 78, flush=True)
        print(f"{'Low VIX (< 15)':<25} | {vix_m['low_vix']['cagr']*100:>10.2f}% | {vix_m['low_vix']['volatility']*100:>10.2f}% | {vix_m['low_vix']['sortino']:>9.2f} | {vix_m['low_vix']['win_rate']*100:>8.2f}%", flush=True)
        print(f"{'Moderate VIX (15-30)':<25} | {vix_m['mod_vix']['cagr']*100:>10.2f}% | {vix_m['mod_vix']['volatility']*100:>10.2f}% | {vix_m['mod_vix']['sortino']:>9.2f} | {vix_m['mod_vix']['win_rate']*100:>8.2f}%", flush=True)
        print(f"{'Panic VIX (> 30)':<25} | {vix_m['panic_vix']['cagr']*100:>10.2f}% | {vix_m['panic_vix']['volatility']*100:>10.2f}% | {vix_m['panic_vix']['sortino']:>9.2f} | {vix_m['panic_vix']['win_rate']*100:>8.2f}%", flush=True)
        print("--------------------------------------------------------------", flush=True)
        
        # 9. Print Overnight Gap Matrix
        print("\n==============================================================", flush=True)
        print("                     OVERNIGHT GAP MATRIX                     ", flush=True)
        print("==============================================================", flush=True)
        print(f"{'Date':<12} | {'TSLA Overnight Gap':<20} | {'Portfolio Daily Return':<22} | {'Portfolio Drawdown':<20}", flush=True)
        print("-" * 83, flush=True)
        for row in opt_metrics['gap_matrix']:
            print(f"{row['date']:<12} | {row['stock_gap']*100:>18.2f}% | {row['portfolio_return']*100:>20.2f}% | {row['portfolio_drawdown']*100:>18.2f}%", flush=True)
        print("--------------------------------------------------------------", flush=True)
        
        # 10. Print Convexity, Vol-of-Vol, & Attributions
        print("\n==============================================================", flush=True)
        print("        CONVEXITY, HEDGING VELOCITY, & TAIL-RISK METRICS       ", flush=True)
        print("==============================================================", flush=True)
        print(f"Max Net Portfolio Delta Exposure:     {opt_metrics['delta_max']:.4f} (Underlying delta cushion collapse)", flush=True)
        print(f"Average Net Delta Exposure:           {opt_metrics['delta_avg']:.4f}", flush=True)
        print(f"Short-Gamma Crisis Indicator (Max):   {opt_metrics['gamma_stress_max']:.6f} (Delta change per 1% stock move)", flush=True)
        print(f"Short-Gamma Crisis Indicator (Avg):   {opt_metrics['gamma_stress_avg']:.6f}", flush=True)
        print(f"Vol-of-Vol Acceleration Index:        {opt_metrics['vol_of_vol']*100:.2f}% (Annualized std of daily ATM IV changes)", flush=True)
        print(f"Early Assignment Hazard Frequency:    {opt_metrics['assignment_freq']*100:.2f}% of trade cycles", flush=True)
        print(f"Average Volatility Risk Premium at Entry: {opt_metrics['avg_entry_vrp_z']:.4f} z-score", flush=True)
        print("--------------------------------------------------------------", flush=True)
        
        print("\n==============================================================", flush=True)
        print("                  PORTFOLIO P&L RETURN ATTRIBUTION            ", flush=True)
        print("==============================================================", flush=True)
        att = opt_metrics['attribution']
        tot_att = sum(att.values())
        print(f"Total Cumulative Return:     ${tot_att:>14,.2f}", flush=True)
        print(f"  - Theta Harvest (Time):    ${att['theta_harvest']:>14,.2f}", flush=True)
        print(f"  - Delta Drift (Direction): ${att['delta_drift']:>14,.2f}", flush=True)
        print(f"  - Gamma Drag (Convexity):  ${att['gamma_drag']:>14,.2f}", flush=True)
        print(f"  - Vega Impact (Volatility):${att['vega_impact']:>14,.2f}", flush=True)
        print(f"  - Slippage Cost (Friction):${-att['slippage_cost']:>14,.2f}", flush=True)
        print(f"  - Gap Loss (Overnight):    ${-att['gap_loss']:>14,.2f}", flush=True)
        print(f"  - Treasury Interest:       ${att['interest_earned']:>14,.2f}", flush=True)
        print("==============================================================", flush=True)

if __name__ == "__main__":
    main()
