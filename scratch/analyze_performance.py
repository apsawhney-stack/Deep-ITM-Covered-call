import os
import yaml
import pandas as pd
import numpy as np
from datetime import datetime
from backtester.engine import BacktestEngine
from backtester.data_loader import DataLoader
from backtester.metrics import calculate_metrics

def main():
    # Load configuration
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        print("config.yaml not found.")
        return
        
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    # Initialize DataLoader
    loader = DataLoader(creds_path="creds.txt", data_dir="data", cache_dir="data/cache")
    
    # Load daily stock data
    stock_path = os.path.join("data", "TSLA_daily.parquet")
    if not os.path.exists(stock_path):
        print(f"{stock_path} not found.")
        return
    stock_df = pd.read_parquet(stock_path)
    
    deltas = [0.60, 0.65, 0.70, 0.75, 0.80]
    results = []
    
    print("Running diagnostic backtests offline (cached)...")
    print(f"{'Delta':<6} | {'CAGR':<8} | {'Sharpe':<7} | {'MaxDD':<8} | {'Cycles':<6} | {'Stops':<5} | {'Exits':<5} | {'Assign':<6} | {'Rolls':<5}")
    print("-" * 75)
    
    for delta in deltas:
        run_config = config.copy()
        run_config['target_dte'] = 45
        run_config['baseline_delta'] = delta
        
        # Run engine
        engine = BacktestEngine(run_config, loader)
        daily_history = engine.run_backtest()
        
        # Calculate metrics
        metrics = calculate_metrics(daily_history, engine.trade_log, run_config, stock_df)
        
        # Parse trade log
        log = engine.trade_log
        stops = sum(1 for t in log if t['event'] == 'STOP_LOSS')
        trend_exits = sum(1 for t in log if t['event'] == 'TREND_EXIT')
        assignments = sum(1 for t in log if t['event'] == 'ASSIGNMENT')
        expirations = sum(1 for t in log if t['event'] == 'EXPIRATION')
        rolls = sum(1 for t in log if 'ROLL' in t['event'])
        entries = sum(1 for t in log if t['event'] == 'ENTRY')
        
        # Extract attribution
        # Since metrics might have them in a sub-dict, let's sum them directly from daily_history
        theta_sum = daily_history['theta_harvest'].sum() if 'theta_harvest' in daily_history.columns else 0.0
        delta_sum = daily_history['delta_drift'].sum() if 'delta_drift' in daily_history.columns else 0.0
        gamma_sum = daily_history['gamma_drag'].sum() if 'gamma_drag' in daily_history.columns else 0.0
        vega_sum = daily_history['vega_impact'].sum() if 'vega_impact' in daily_history.columns else 0.0
        slippage_sum = daily_history['slippage_cost'].sum() if 'slippage_cost' in daily_history.columns else 0.0
        gap_sum = daily_history['gap_loss'].sum() if 'gap_loss' in daily_history.columns else 0.0
        interest_sum = daily_history['interest_earned'].sum() if 'interest_earned' in daily_history.columns else 0.0
        
        cagr = metrics['overall']['cagr']
        sharpe = metrics['overall']['sharpe']
        max_dd = metrics['overall']['max_dd']
        
        print(f"{delta:<6.2f} | {cagr*100:<7.2f}% | {sharpe:<7.3f} | {max_dd*100:<7.2f}% | {entries:<6} | {stops:<5} | {trend_exits:<5} | {assignments:<6} | {rolls:<5}")
        
        results.append({
            'delta': delta,
            'cagr': cagr,
            'sharpe': sharpe,
            'max_dd': max_dd,
            'entries': entries,
            'stops': stops,
            'trend_exits': trend_exits,
            'assignments': assignments,
            'expirations': expirations,
            'rolls': rolls,
            'theta_sum': theta_sum,
            'delta_sum': delta_sum,
            'gamma_sum': gamma_sum,
            'vega_sum': vega_sum,
            'slippage_sum': slippage_sum,
            'gap_sum': gap_sum,
            'interest_sum': interest_sum
        })
        
    print("\nAttribution Breakdown ($):")
    print(f"{'Delta':<6} | {'Theta':<9} | {'DeltaDrift':<11} | {'GammaDrag':<10} | {'Vega':<9} | {'Slippage':<9} | {'GapLoss':<9} | {'Interest':<9}")
    print("-" * 90)
    for r in results:
        print(f"{r['delta']:<6.2f} | {r['theta_sum']:<9.2f} | {r['delta_sum']:<11.2f} | {r['gamma_drag' if 'gamma_drag' in r else 'gamma_sum']:<10.2f} | {r['vega_sum']:<9.2f} | {r['slippage_sum']:<9.2f} | {r['gap_sum']:<9.2f} | {r['interest_sum']:<9.2f}")

if __name__ == "__main__":
    main()
