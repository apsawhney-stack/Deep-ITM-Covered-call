import os
import yaml
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from backtester.data_loader import DataLoader
from backtester.engine import BacktestEngine

def run_single_sweep(config, loader, dte, delta):
    """
    Runs a single backtest sweep configuration to trigger any missing downloads.
    """
    print(f"  [Pre-fetcher] Starting dry-run: DTE = {dte}, Delta = {delta}", flush=True)
    run_config = config.copy()
    run_config['target_dte'] = dte
    run_config['baseline_delta'] = delta
    
    try:
        engine = BacktestEngine(run_config, loader)
        engine.run_backtest()
        print(f"  [Pre-fetcher] Dry-run completed: DTE = {dte}, Delta = {delta}", flush=True)
    except Exception as e:
        print(f"  [Pre-fetcher] ERROR in dry-run DTE = {dte}, Delta = {delta}: {e}", flush=True)

def prefetch_all(config_path="config.yaml", creds_path="creds.txt", max_workers=3):
    print("==============================================================", flush=True)
    print("   RUNNING AUTOMATED OPTION DATA PRE-FETCHER PRE-CHECK        ", flush=True)
    print("==============================================================", flush=True)
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file {config_path} not found.")
        
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    loader = DataLoader(creds_path=creds_path)
    loader.is_mock = False  # Make sure we download from live client
    
    # Download stock daily data first
    print(f"[Pre-fetcher] Fetching stock and macro daily data for {config['asset']}...", flush=True)
    loader.download_stock_and_macro_data(
        ticker=config['asset'],
        start_str=config['start_date'],
        end_str=config['end_date']
    )
    
    # Define Parameter Sweep Range to precheck
    dte_sweep = [15, 30, 45, 7]
    delta_sweep = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.93, 0.95]
    
    tasks = []
    print(f"[Pre-fetcher] Scheduling dry-run parameter sweeps with concurrency limit of {max_workers} threads...", flush=True)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for dte in dte_sweep:
            for delta in delta_sweep:
                futures.append(
                    executor.submit(run_single_sweep, config, loader, dte, delta)
                )
                
        for future in as_completed(futures):
            # Raise exception if worker failed
            future.result()
            
    print("[Pre-fetcher] Automated option data precheck/prefetching completed successfully.", flush=True)
    print("==============================================================", flush=True)

if __name__ == "__main__":
    prefetch_all()
