import re
import os

def parse_sweep_logs(log_path):
    if not os.path.exists(log_path):
        print(f"Log file {log_path} not found.")
        return
        
    with open(log_path, 'r') as f:
        lines = f.readlines()
        
    sweeps = {}
    current_delta = None
    sweep_lines = []
    
    # Isolate lines for DTE = 45 sweeps
    for line in lines:
        if "Running sweep: DTE = 45, Delta =" in line:
            if current_delta is not None:
                sweeps[current_delta] = sweep_lines
            # Extract delta value
            match = re.search(r"Delta = (0\.\d+)", line)
            if match:
                current_delta = float(match.group(1))
            else:
                current_delta = None
            sweep_lines = []
        elif current_delta is not None:
            if "Running sweep: DTE =" in line or "Starting Parameter Sweep Grid Search" in line:
                sweeps[current_delta] = sweep_lines
                current_delta = None
            else:
                sweep_lines.append(line.strip())
                
    if current_delta is not None:
        sweeps[current_delta] = sweep_lines
        
    # Now analyze each sweep
    for delta, block in sweeps.items():
        print(f"\n======================================================================")
        print(f"DTE 45 | Baseline Delta = {delta}")
        print(f"======================================================================")
        
        entries = []
        rolls = []
        liquidations = []
        sweeps_count = 0
        total_swept = 0.0
        
        cagr = None
        sharpe = None
        sortino = None
        max_dd = None
        
        # Track current state within sweep
        active_s_stop = None
        active_shares = 0
        active_contracts = 0
        active_entry_price = 0.0
        active_premium = 0.0
        
        for line in block:
            # Parse result
            if "Result: CAGR =" in line:
                match = re.search(r"CAGR = ([\-\d\.]+)%, Sortino = ([\-\d\.]+), MaxDD = ([\-\d\.]+)%", line)
                if match:
                    cagr = float(match.group(1))
                    sortino = float(match.group(2))
                    max_dd = float(match.group(3))
                continue
                
            # Parse entry
            # Format: Opened NEW Position: Bought 600 shares at 187.44, Sold 6x TSLA240802C00170000 at 24.06 (Delta 0.74)
            if "Opened NEW Position:" in line:
                match = re.search(r"Bought (\d+) shares at ([\d\.]+), Sold (\d+)x (\S+) at ([\d\.]+)", line)
                if match:
                    active_shares = int(match.group(1))
                    active_entry_price = float(match.group(2))
                    active_contracts = int(match.group(3))
                    active_premium = float(match.group(5))
                    entries.append({
                        'shares': active_shares,
                        'price': active_entry_price,
                        'premium': active_premium
                    })
                    
            # Parse S_stop set
            # Format: Static stop-loss threshold set at S_stop = 150.31
            if "Static stop-loss threshold set at S_stop =" in line:
                match = re.search(r"S_stop = ([\d\.]+)", line)
                if match:
                    active_s_stop = float(match.group(1))
                    
            # Parse Roll
            # Format: ROLLED Option: Sold 6x TSLA240913C00190000 at 40.25 (Delta 1.00) on existing shares.
            # OR ROLL event in trade log format
            if "ROLLED Option:" in line:
                rolls.append(line)
                
            # Parse liquidation
            # Format: Forced Stock Liquidation: Sold 600 shares at 198.88 (Proceeds: 119328.00)
            if "Forced Stock Liquidation:" in line:
                match = re.search(r"Sold (\d+) shares at ([\d\.]+)", line)
                if match:
                    shares = int(match.group(1))
                    liq_price = float(match.group(2))
                    
                    # Distinguish Stop-Loss vs Trend-Exit vs Cash-Override
                    is_stop_loss = False
                    if active_s_stop is not None:
                        # If the liquidation price is at or below the stop loss threshold
                        # (Allow a tiny buffer for floating point or rounding)
                        if liq_price <= active_s_stop + 0.5:
                            is_stop_loss = True
                            
                    exit_type = "STOP_LOSS" if is_stop_loss else "TREND_EXIT"
                    liquidations.append({
                        'type': exit_type,
                        'price': liq_price,
                        'shares': shares,
                        'stop_loss_threshold': active_s_stop
                    })
                    
                    # Reset active thresholds
                    active_s_stop = None
                    active_shares = 0
                    active_contracts = 0
                    
            # Parse HWM Sweep
            # Format: HWM Sweep Activated: Swept 26376.49 out of 126376.49.
            if "HWM Sweep Activated:" in line:
                match = re.search(r"Swept ([\d\.]+) out of ([\d\.]+)", line)
                if match:
                    swept_amount = float(match.group(1))
                    total_swept += swept_amount
                    sweeps_count += 1
                    
        # Print summary for this delta
        print(f"Overall Metrics: CAGR = {cagr}%, Sortino = {sortino}, MaxDD = {max_dd}%")
        print(f"Trade Statistics:")
        print(f"  Total Cycles (Entries): {len(entries)}")
        print(f"  Total Rolls:            {len(rolls)}")
        print(f"  Total Liquidations:     {len(liquidations)}")
        
        stops_count = sum(1 for l in liquidations if l['type'] == 'STOP_LOSS')
        exits_count = sum(1 for l in liquidations if l['type'] == 'TREND_EXIT')
        print(f"    - Stop-Loss Triggers: {stops_count}")
        print(f"    - Trend-Exit Triggers:{exits_count}")
        print(f"  HWM Yield Sweeps:       {sweeps_count} (Total Swept: ${total_swept:,.2f})")
        
        # Detail of each cycle
        print("\n  Cycle Details:")
        for idx, ent in enumerate(entries):
            liq_str = "N/A (Active/Expired)"
            if idx < len(liquidations):
                liq = liquidations[idx]
                liq_str = f"{liq['type']} at {liq['price']:.2f} (S_stop was {liq['stop_loss_threshold']:.2f})"
            
            # Estimate cushion
            cushion = ent['premium']
            cushion_pct = (cushion / ent['price']) * 100
            print(f"    Cycle {idx+1}: Entry Stock={ent['price']:.2f}, Option Premium={ent['premium']:.2f} ({cushion_pct:.1f}% cushion) | Exit: {liq_str}")

if __name__ == "__main__":
    parse_sweep_logs("/Users/aps/.gemini/antigravity/brain/40bec107-7eca-41bc-a38d-db03ae0f5207/.system_generated/tasks/task-2155.log")
