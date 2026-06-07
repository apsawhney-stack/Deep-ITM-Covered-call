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
            match = re.search(r"Delta = (0\.\d+)", line)
            if match:
                current_delta = float(match.group(1))
            sweep_lines = []
        elif current_delta is not None:
            if "Running sweep: DTE =" in line or "Starting Parameter Sweep Grid Search" in line:
                sweeps[current_delta] = sweep_lines
                current_delta = None
            else:
                sweep_lines.append(line)
                
    if current_delta is not None:
        sweeps[current_delta] = sweep_lines
        
    for delta in [0.60, 0.65, 0.70, 0.75, 0.80]:
        block = sweeps.get(delta, [])
        if not block:
            continue
            
        print(f"\n======================================================================")
        print(f"DTE 45 | Baseline Delta = {delta}")
        print(f"======================================================================")
        
        cycle_idx = 0
        for line in block:
            # Parse New Position
            if "Opened NEW Position:" in line:
                cycle_idx += 1
                match = re.search(r"Bought (\d+) shares at ([\d\.]+), Sold (\d+)x (\S+) at ([\d\.]+)", line)
                if match:
                    shares = int(match.group(1))
                    stock_price = float(match.group(2))
                    contracts = int(match.group(3))
                    premium = float(match.group(5))
                    net_debit = stock_price - premium
                    total_debit = shares * stock_price - contracts * 100 * premium
                    print(f"  Cycle {cycle_idx} ENTRY: {shares} shares @ {stock_price:.2f}, {contracts}x calls @ {premium:.2f} (Net Cost: ${total_debit:,.2f})")
            
            # Parse Roll Option
            if "ROLLED Option:" in line:
                match = re.search(r"Sold (\d+)x (\S+) at ([\d\.]+)", line)
                if match:
                    rc = int(match.group(1))
                    rp = float(match.group(3))
                    print(f"    - ROLL: Sold {rc}x @ {rp:.2f}")
                    
            # Parse Option Buyback/Close
            if "Closed Option Early:" in line:
                match = re.search(r"Bought back (\S+) at ([\d\.]+)", line)
                if match:
                    bp = float(match.group(2))
                    print(f"    - CLOSE OPTION EARLY: Bought back @ {bp:.2f}")
                    
            # Parse Liquidations
            if "Forced Option Liquidation:" in line:
                match = re.search(r"Bought back (\S+) at ([\d\.]+)", line)
                if match:
                    bp = float(match.group(2))
                    print(f"    - EXIT OPTION: Bought back @ {bp:.2f}")
            if "Forced Stock Liquidation:" in line:
                match = re.search(r"Sold (\d+) shares at ([\d\.]+)", line)
                if match:
                    sp = float(match.group(2))
                    print(f"    - EXIT STOCK: Sold {shares} shares @ {sp:.2f}")
            
            # Parse HWM Sweep or Drawdown Check
            if "HWM Sweep Activated:" in line:
                match = re.search(r"Swept ([\d\.]+) out of ([\d\.]+)", line)
                if match:
                    swept = float(match.group(1))
                    print(f"    >>> HWM SWEEP: Swept ${swept:,.2f}")
            if "Drawdown Sweep Check:" in line:
                match = re.search(r"Ending Cash ([\d\.]+)", line)
                if match:
                    ending = float(match.group(1))
                    print(f"    >>> DRAWDOWN CHECK: Ending Cash ${ending:,.2f}")

if __name__ == "__main__":
    parse_sweep_logs("/Users/aps/.gemini/antigravity/brain/40bec107-7eca-41bc-a38d-db03ae0f5207/.system_generated/tasks/task-2155.log")
