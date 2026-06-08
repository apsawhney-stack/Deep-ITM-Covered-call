import os
import yaml
from datetime import date
from backtester.data_loader import DataLoader
from backtester.engine import BacktestEngine

def main():
    # Load configuration
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
        
    config['target_dte'] = 45
    config['baseline_delta'] = 0.70
    
    # Initialize DataLoader in mock/offline mode
    loader = DataLoader(creds_path="creds.txt")
    loader.is_mock = True
    
    # Run backtest
    engine = BacktestEngine(config, loader)
    engine.run_backtest()
    
    # Print formatted trade log
    log = engine.trade_log
    
    print("\n" + "="*95)
    print(f"      CHRONOLOGICAL TRADE LOG FOR DTE = 45, DELTA = 0.70 (Total Trades: {len(log)})")
    print("="*95)
    print(f"{'Date':<12} | {'Event':<15} | {'Option Symbol':<22} | {'Stock Px':<8} | {'Opt Px':<7} | {'Net Return':<11}")
    print("-"*95)
    
    for t in log:
        event = t['event']
        dt = str(t['date'])
        symbol = t['symbol']
        stock_px = f"{t['stock_price']:.2f}"
        opt_px = f"{t['option_price']:.2f}"
        net_ret = f"${t['net_return']:,.2f}"
        print(f"{dt:<12} | {event:<15} | {symbol:<22} | {stock_px:<8} | {opt_px:<7} | {net_ret:<11}")
        
    print("="*95)

if __name__ == "__main__":
    main()
