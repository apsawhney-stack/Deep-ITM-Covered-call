import os
import yaml
import json
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from backtester.data_loader import DataLoader
from backtester.engine import BacktestEngine
from backtester.metrics import calculate_metrics

def main():
    print("==============================================================")
    print("      GENERATING DYNAMIC TRADE LOG HTML FOR DTE 45 / DELTA 0.70")
    print("==============================================================")
    
    # 1. Load Configuration
    if not os.path.exists("config.yaml"):
        print("Error: config.yaml not found.")
        return
        
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
        
    config['target_dte'] = 45
    config['baseline_delta'] = 0.70
    
    # Initialize DataLoader in mock/offline mode
    loader = DataLoader(creds_path="creds.txt")
    loader.is_mock = True
    
    # Load daily stock data
    stock_path = os.path.join("data", "TSLA_daily.parquet")
    if not os.path.exists(stock_path):
        print(f"Error: {stock_path} not found.")
        return
    stock_df = pd.read_parquet(stock_path)
    
    # Convert date column to python date objects
    stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.date
    
    # Run backtest
    print("Running Backtest Simulation...")
    engine = BacktestEngine(config, loader)
    daily_history_pl = engine.run_backtest()
    daily_df = daily_history_pl.to_pandas()
    daily_df['date'] = pd.to_datetime(daily_df['date']).dt.date
    
    print(f"Backtest finished. Logged {len(engine.trade_log)} events.")
    
    # Calculate metrics
    print("Calculating overall performance metrics...")
    metrics = calculate_metrics(daily_df, engine.trade_log, config, stock_df)
    daily_df = metrics['daily_df']
    
    # Process trade log to group into trade cycles
    trade_cycles = []
    current_cycle = None
    cycle_id = 1
    
    log = engine.trade_log
    
    for i, t in enumerate(log):
        event_type = t['event']
        dt = t['date']
        if not isinstance(dt, date):
            dt = pd.to_datetime(dt).date()
        dt_str = dt.strftime("%Y-%m-%d")
        
        symbol = t['symbol']
        stock_price = t['stock_price']
        option_price = t['option_price']
        net_return = t['net_return']
        
        # Start new cycle on ENTRY
        if event_type == 'ENTRY':
            if current_cycle is not None:
                # Close the old cycle
                current_cycle['endDate'] = dt_str
                current_cycle['status'] = 'CLOSED'
                current_cycle['exitReason'] = 'UNKNOWN'
                trade_cycles.append(current_cycle)
                
            current_cycle = {
                'id': cycle_id,
                'startDate': dt_str,
                'endDate': '—',
                'status': 'OPEN',
                'exitReason': 'ACTIVE',
                'pnl': 0.0,
                'events': [],
                'attribution': {
                    'delta': 0.0,
                    'theta': 0.0,
                    'gamma': 0.0,
                    'vega': 0.0,
                    'slippage': 0.0,
                    'gap': 0.0,
                    'interest': 0.0
                }
            }
            cycle_id += 1
            
        if current_cycle is not None:
            # Format UI event type and description
            ui_event_type = event_type
            if event_type == 'ENTRY':
                ui_event_type = 'ENTRY'
                desc = f"Opened position: Wrote contract {symbol} at ${option_price:.2f}. Stock bought at ${stock_price:.2f}."
            elif event_type == 'ROLL_ENTRY':
                ui_event_type = 'ROLL_ENTRY'
                desc = f"Wrote new contract {symbol} at ${option_price:.2f} on existing stock shares."
            elif 'ROLL_' in event_type:
                ui_event_type = 'ROLL'
                driver = event_type.replace('ROLL_', '')
                desc = f"Extrinsic exhaustion ({driver}): Closed contract {symbol} at ${option_price:.2f}."
            elif event_type == 'STOP_LOSS':
                ui_event_type = 'EXIT'
                desc = f"Stop Loss exit triggered: Cushion breached. Closed stock at ${stock_price:.2f} and option at ${option_price:.2f}."
            elif event_type == 'TREND_EXIT':
                ui_event_type = 'EXIT'
                desc = f"Trend Exit triggered: Stock closed below 50-day EMA. Liquidated stock at ${stock_price:.2f} and option at ${option_price:.2f}."
            elif event_type == 'CASH_OVERRIDE_LIQ':
                ui_event_type = 'EXIT'
                desc = f"VRP Underpricing Halt: Liquidated stock shares at ${stock_price:.2f} to return to 100% Cash."
            elif event_type == 'ASSIGNMENT':
                ui_event_type = 'EXIT'
                desc = f"Early Assignment: Option assigned early. Stock shares called away at strike. Option closed at ${option_price:.2f}."
            elif event_type == 'EXPIRATION':
                ui_event_type = 'EXIT'
                desc = f"Option expired. Closed at ${option_price:.2f}. Stock closed at ${stock_price:.2f}."
            else:
                desc = f"Event {event_type} at stock price ${stock_price:.2f}, option price ${option_price:.2f}."
                
            current_cycle['events'].append({
                'type': ui_event_type,
                'date': dt_str,
                'symbol': symbol,
                'stockPx': float(stock_price),
                'optPx': float(option_price),
                'pnl': float(net_return),
                'desc': desc
            })
            
            current_cycle['pnl'] += float(net_return)
            
            # Determine if this is a final exit event for the cycle
            is_exit = False
            exit_reason = None
            if event_type in ['STOP_LOSS', 'TREND_EXIT', 'CASH_OVERRIDE_LIQ', 'ASSIGNMENT']:
                is_exit = True
                exit_reason = event_type
            elif event_type == 'EXPIRATION':
                # Look-ahead: if the next event in log is not a ROLL_ENTRY or a ROLL, it's an exit!
                next_is_roll = False
                for j in range(i + 1, len(log)):
                    if log[j]['event'] == 'ENTRY':
                        break
                    if log[j]['event'] in ['ROLL_ENTRY', 'ROLL_Delta-Driven', 'ROLL_Theta-Driven', 'ROLL_Vega-Driven']:
                        next_is_roll = True
                        break
                if not next_is_roll:
                    is_exit = True
                    exit_reason = 'EXPIRATION'
                    
            if is_exit:
                current_cycle['endDate'] = dt_str
                current_cycle['status'] = 'CLOSED'
                
                # Map exit_reason to display friendly keys
                if exit_reason == 'STOP_LOSS':
                    current_cycle['exitReason'] = 'STOPLOSS'
                elif exit_reason == 'TREND_EXIT':
                    current_cycle['exitReason'] = 'TREND'
                elif exit_reason == 'CASH_OVERRIDE_LIQ':
                    current_cycle['exitReason'] = 'VRP'
                elif exit_reason == 'ASSIGNMENT':
                    current_cycle['exitReason'] = 'ASSIGNMENT'
                elif exit_reason == 'EXPIRATION':
                    current_cycle['exitReason'] = 'EXPIRATION'
                else:
                    current_cycle['exitReason'] = 'UNKNOWN'
                
                # Slice attribution daily history to compute exact cycle P&L decomposition
                cycle_start = datetime.strptime(current_cycle['startDate'], "%Y-%m-%d").date()
                cycle_end = datetime.strptime(current_cycle['endDate'], "%Y-%m-%d").date()
                
                cycle_df = daily_df[(daily_df['date'] >= cycle_start) & (daily_df['date'] <= cycle_end)]
                
                if not cycle_df.empty:
                    current_cycle['attribution']['delta'] = float(cycle_df['delta_drift'].sum())
                    current_cycle['attribution']['theta'] = float(cycle_df['theta_harvest'].sum())
                    current_cycle['attribution']['gamma'] = float(cycle_df['gamma_drag'].sum())
                    current_cycle['attribution']['vega'] = float(cycle_df['vega_impact'].sum())
                    current_cycle['attribution']['slippage'] = -float(cycle_df['slippage_cost'].sum())
                    current_cycle['attribution']['gap'] = -float(cycle_df['gap_loss'].sum())
                    current_cycle['attribution']['interest'] = float(cycle_df['interest_earned'].sum())
                
                trade_cycles.append(current_cycle)
                current_cycle = None
                
    # Append the last active cycle if it's still open
    if current_cycle is not None:
        current_cycle['status'] = 'ACTIVE'
        current_cycle['exitReason'] = 'ACTIVE'
        
        cycle_start = datetime.strptime(current_cycle['startDate'], "%Y-%m-%d").date()
        cycle_df = daily_df[daily_df['date'] >= cycle_start]
        if not cycle_df.empty:
            current_cycle['attribution']['delta'] = float(cycle_df['delta_drift'].sum())
            current_cycle['attribution']['theta'] = float(cycle_df['theta_harvest'].sum())
            current_cycle['attribution']['gamma'] = float(cycle_df['gamma_drag'].sum())
            current_cycle['attribution']['vega'] = float(cycle_df['vega_impact'].sum())
            current_cycle['attribution']['slippage'] = -float(cycle_df['slippage_cost'].sum())
            current_cycle['attribution']['gap'] = -float(cycle_df['gap_loss'].sum())
            current_cycle['attribution']['interest'] = float(cycle_df['interest_earned'].sum())
            
        trade_cycles.append(current_cycle)

    # Compute overall stats from compiled cycles
    completed_cycles = [c for c in trade_cycles if c['status'] == 'CLOSED']
    winning_cycles = [c for c in completed_cycles if c['pnl'] >= 0]
    losing_cycles = [c for c in completed_cycles if c['pnl'] < 0]
    
    win_rate = (len(winning_cycles) / len(completed_cycles)) * 100 if completed_cycles else 0.0
    net_profit = sum(c['pnl'] for c in trade_cycles)
    avg_return = net_profit / len(completed_cycles) if completed_cycles else 0.0
    
    active_count = sum(1 for c in trade_cycles if c['status'] == 'ACTIVE')
    active_status_str = f"{active_count} Position" if active_count == 1 else f"{active_count} Positions"
    active_desc = "DTE 45 roll active on TSLA" if active_count > 0 else "No active positions"
    
    # Read the premium template html contents
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Deep ITM Covered Call Backtester - Trade Log Dashboard</title>
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: hsl(222, 47%, 6%);
            --bg-surface: hsl(223, 47%, 11%);
            --bg-surface-elevated: hsl(223, 45%, 16%);
            --text-primary: hsl(210, 40%, 98%);
            --text-secondary: hsl(215, 20%, 75%);
            --text-muted: hsl(215, 15%, 55%);
            
            --accent-blue: hsl(210, 100%, 60%);
            --accent-purple: hsl(265, 100%, 65%);
            --accent-green: hsl(145, 80%, 50%);
            --accent-red: hsl(355, 85%, 55%);
            --accent-orange: hsl(35, 100%, 55%);
            --accent-yellow: hsl(50, 100%, 50%);
            
            --border-glow: hsla(210, 100%, 65%, 0.15);
            --border-light: hsla(215, 20%, 80%, 0.08);
            
            --shadow-lg: 0 12px 40px -10px rgba(0, 0, 0, 0.5);
            --transition-smooth: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-base);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2.5rem;
            line-height: 1.6;
        }

        h1, h2, h3, h4 {
            font-family: 'Outfit', sans-serif;
            font-weight: 600;
        }

        /* Container Layout */
        .dashboard-container {
            max-width: 1400px;
            margin: 0 auto;
        }

        /* Header styles */
        header {
            margin-bottom: 2.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-light);
            padding-bottom: 1.5rem;
        }

        .header-title h1 {
            font-size: 2.25rem;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, var(--text-primary) 30%, var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-title p {
            color: var(--text-secondary);
            font-size: 1rem;
            margin-top: 0.25rem;
        }

        .strategy-badge {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-light);
            padding: 0.5rem 1rem;
            border-radius: 12px;
            font-size: 0.9rem;
            color: var(--accent-blue);
            font-weight: 600;
        }

        /* Summary Cards Grid */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2.5rem;
        }

        .card {
            background-color: var(--bg-surface);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            padding: 1.5rem;
            box-shadow: var(--shadow-lg);
            position: relative;
            overflow: hidden;
            transition: var(--transition-smooth);
        }

        .card:hover {
            transform: translateY(-4px);
            border-color: var(--border-glow);
            box-shadow: 0 16px 45px -8px rgba(59, 130, 246, 0.15);
        }

        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--accent-blue);
        }

        .card.card-win::before { background: var(--accent-green); }
        .card.card-loss::before { background: var(--accent-red); }
        .card.card-swept::before { background: var(--accent-purple); }

        .card-label {
            font-size: 0.85rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 0.5rem;
        }

        .card-value {
            font-size: 2rem;
            font-weight: 700;
            font-family: 'Outfit', sans-serif;
            color: var(--text-primary);
        }

        .card-subtext {
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }

        /* Exit Reasons Guide (Legend) */
        .legend-section {
            background: linear-gradient(180deg, var(--bg-surface) 0%, rgba(20, 26, 41, 0.4) 100%);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 2.5rem;
        }

        .legend-title {
            font-size: 1.1rem;
            margin-bottom: 1rem;
            color: var(--text-primary);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .legend-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1rem;
        }

        .legend-item {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.75rem;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.01);
            border: 1px dashed rgba(255, 255, 255, 0.05);
        }

        .badge {
            display: inline-block;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            white-space: nowrap;
        }

        .badge-stoploss { background-color: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); }
        .badge-expiration { background-color: rgba(59, 130, 246, 0.15); color: var(--accent-blue); border: 1px solid rgba(59, 130, 246, 0.3); }
        .badge-roll { background-color: rgba(168, 85, 247, 0.15); color: var(--accent-purple); border: 1px solid rgba(168, 85, 247, 0.3); }
        .badge-trend { background-color: rgba(249, 115, 22, 0.15); color: var(--accent-orange); border: 1px solid rgba(249, 115, 22, 0.3); }
        .badge-vrp { background-color: rgba(234, 179, 8, 0.15); color: var(--accent-yellow); border: 1px solid rgba(234, 179, 8, 0.3); }
        .badge-hazard { background-color: rgba(236, 72, 153, 0.15); color: hsl(327, 85%, 65%); border: 1px solid rgba(236, 72, 153, 0.3); }
        .badge-active { background-color: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }

        .legend-desc {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        /* Filter Controls */
        .controls-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }

        .filter-group {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }

        .btn-filter {
            background-color: var(--bg-surface);
            border: 1px solid var(--border-light);
            color: var(--text-secondary);
            padding: 0.5rem 1rem;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 500;
            font-size: 0.9rem;
            transition: var(--transition-smooth);
        }

        .btn-filter:hover, .btn-filter.active {
            background-color: var(--bg-surface-elevated);
            color: var(--accent-blue);
            border-color: var(--accent-blue);
        }

        .search-box {
            background-color: var(--bg-surface);
            border: 1px solid var(--border-light);
            border-radius: 10px;
            padding: 0.5rem 1rem;
            color: var(--text-primary);
            font-family: inherit;
            min-width: 250px;
            font-size: 0.9rem;
            transition: var(--transition-smooth);
        }

        .search-box:focus {
            outline: none;
            border-color: var(--accent-blue);
            box-shadow: 0 0 10px rgba(59, 130, 246, 0.25);
        }

        /* Trade List Cards Layout */
        .trade-list {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .cycle-card {
            background-color: var(--bg-surface);
            border: 1px solid var(--border-light);
            border-radius: 16px;
            box-shadow: var(--shadow-lg);
            transition: var(--transition-smooth);
        }

        .cycle-card:hover {
            border-color: rgba(255, 255, 255, 0.15);
        }

        /* Header of Cycle Card */
        .cycle-header {
            padding: 1.25rem 1.5rem;
            display: grid;
            grid-template-columns: 80px 140px 1fr 140px 100px 40px;
            align-items: center;
            cursor: pointer;
            gap: 1rem;
            user-select: none;
        }

        .cycle-num {
            font-family: 'Outfit', sans-serif;
            font-weight: 700;
            font-size: 1.1rem;
            color: var(--text-muted);
        }

        .cycle-dates {
            font-size: 0.9rem;
            color: var(--text-secondary);
        }

        .cycle-info {
            display: flex;
            gap: 1.5rem;
            align-items: center;
            flex-wrap: wrap;
        }

        .cycle-info-item {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        .cycle-info-item strong {
            color: var(--text-primary);
        }

        .cycle-status {
            text-align: right;
        }

        .cycle-pnl {
            font-family: 'Outfit', sans-serif;
            font-weight: 700;
            font-size: 1.2rem;
            text-align: right;
        }

        .pnl-gain { color: var(--accent-green); }
        .pnl-loss { color: var(--accent-red); }

        .cycle-toggle-icon {
            text-align: center;
            color: var(--text-muted);
            font-size: 1.2rem;
            transition: transform 0.3s ease;
        }

        .cycle-card.expanded .cycle-toggle-icon {
            transform: rotate(180deg);
        }

        /* Expanded Details of Cycle Card */
        .cycle-details {
            border-top: 1px solid var(--border-light);
            padding: 1.5rem;
            background-color: rgba(20, 26, 41, 0.3);
            border-bottom-left-radius: 16px;
            border-bottom-right-radius: 16px;
            display: none;
        }

        .cycle-card.expanded .cycle-details {
            display: block;
        }

        /* Timeline Flow within Details */
        .timeline {
            position: relative;
            padding-left: 2rem;
            margin-bottom: 1.5rem;
        }

        .timeline::before {
            content: '';
            position: absolute;
            left: 7px;
            top: 0;
            bottom: 0;
            width: 2px;
            background-color: var(--border-light);
        }

        .timeline-event {
            position: relative;
            margin-bottom: 1.25rem;
        }

        .timeline-event:last-child {
            margin-bottom: 0;
        }

        .timeline-dot {
            position: absolute;
            left: -2rem;
            top: 6px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background-color: var(--bg-surface-elevated);
            border: 2px solid var(--text-muted);
            transform: translateX(1px);
        }

        .timeline-dot.dot-entry { border-color: var(--accent-blue); background-color: var(--bg-base); }
        .timeline-dot.dot-roll { border-color: var(--accent-purple); background-color: var(--bg-base); }
        .timeline-dot.dot-exit { border-color: var(--accent-red); background-color: var(--bg-base); }
        .timeline-dot.dot-trend { border-color: var(--accent-orange); background-color: var(--bg-base); }
        .timeline-dot.dot-vrp { border-color: var(--accent-yellow); background-color: var(--bg-base); }

        .timeline-content {
            background-color: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-light);
            border-radius: 10px;
            padding: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            flex-wrap: wrap;
        }

        .event-type {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .event-name {
            font-weight: 600;
            font-size: 0.95rem;
        }

        .event-date {
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .event-data {
            display: flex;
            gap: 1.5rem;
            flex-wrap: wrap;
        }

        .data-item {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .data-item strong {
            color: var(--text-primary);
        }

        .event-pnl {
            font-weight: 600;
            font-size: 0.95rem;
        }

        /* Attribution Metrics Block */
        .attribution-box {
            background-color: rgba(255, 255, 255, 0.01);
            border: 1px dashed var(--border-light);
            border-radius: 12px;
            padding: 1.25rem;
            margin-top: 1rem;
        }

        .attribution-title {
            font-size: 0.9rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            color: var(--text-secondary);
        }

        .attribution-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
        }

        .attrib-item {
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .attrib-item strong {
            display: block;
            font-size: 0.95rem;
            color: var(--text-primary);
            margin-top: 0.15rem;
        }

        /* Responsive styling */
        @media (max-width: 900px) {
            .cycle-header {
                grid-template-columns: 80px 140px 1fr 100px 40px;
            }
            .cycle-info-item:nth-child(n+3) {
                display: none;
            }
        }

        @media (max-width: 650px) {
            body {
                padding: 1.25rem;
            }
            .cycle-header {
                grid-template-columns: 1fr 100px 30px;
                grid-template-rows: auto auto;
                row-gap: 0.5rem;
            }
            .cycle-num {
                grid-row: 1;
                grid-column: 1;
            }
            .cycle-dates {
                grid-row: 2;
                grid-column: 1;
            }
            .cycle-info {
                display: none;
            }
            .cycle-status {
                grid-row: 1;
                grid-column: 2;
            }
            .cycle-pnl {
                grid-row: 2;
                grid-column: 2;
                font-size: 1.1rem;
            }
            .cycle-toggle-icon {
                grid-row: 1 / span 2;
                grid-column: 3;
            }
            header {
                flex-direction: column;
                align-items: flex-start;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>

    <div class="dashboard-container">
        <!-- Dashboard Header -->
        <header>
            <div class="header-title">
                <h1>Deep ITM Covered Call Backtester</h1>
                <p>Systematic Options Sweep Execution Log • Historical Diagnostics</p>
            </div>
            <div class="strategy-badge" id="strategyBadge">
                TSLA • DTE 45 • Delta 0.70 Strategy
            </div>
        </header>

        <!-- Summary Statistics -->
        <div class="summary-grid">
            <div class="card card-win" id="winRateCard">
                <div class="card-label">Overall Win Rate</div>
                <div class="card-value" id="winRateVal">_WIN_RATE_%</div>
                <div class="card-subtext" id="winRateSub">_WIN_COUNT_ Winning Cycles / _LOSS_COUNT_ Losing Cycles</div>
            </div>
            <div class="card card-swept" id="netProfitCard">
                <div class="card-label">Cumulative Net Return</div>
                <div class="card-value _PNL_CLASS_" id="netProfitVal">_NET_PROFIT_</div>
                <div class="card-subtext">Excludes active strategy yield sweeps</div>
            </div>
            <div class="card" id="avgReturnCard">
                <div class="card-label">Avg Return / Cycle</div>
                <div class="card-value _AVG_PNL_CLASS_" id="avgReturnVal">_AVG_RETURN_</div>
                <div class="card-subtext">Across _CYCLE_COUNT_ completed cycles</div>
            </div>
            <div class="card" id="activeCyclesCard">
                <div class="card-label">Active Trade Status</div>
                <div class="card-value" id="activeCyclesVal" style="color: var(--accent-orange);">_ACTIVE_STATUS_</div>
                <div class="card-subtext">_ACTIVE_DESC_</div>
            </div>
        </div>

        <!-- System Exit Reasons Reference (Guide) -->
        <div class="legend-section">
            <h2 class="legend-title">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 16a1 1 0 1 1 1-1 1 1 0 0 1-1 1zm1-5.07A1.33 1.33 0 0 0 12 11.5a1.5 1.5 0 0 1-3 0A3.33 3.33 0 0 1 12.3 8.3c1 0 1.7.7 1.7 1.7 0 .8-.5 1.2-1 2z"/></svg>
                The 6 Systematic Exit & Roll Reasons
            </h2>
            <div class="legend-grid">
                <div class="legend-item">
                    <span class="badge badge-trend">Trend Exit</span>
                    <div class="legend-desc"><strong>EMA-50 Crossover:</strong> Triggered at 3:45 PM close when the stock price falls below the 50-day EMA by 5% or more. Liquidates underlying stock and option.</div>
                </div>
                <div class="legend-item">
                    <span class="badge badge-vrp">VRP Halt</span>
                    <div class="legend-desc"><strong>Underpriced Volatility:</strong> VRP z-score drops below -1.0. Halts all option writing and liquidates stock/options immediately to lock in capital to 100% cash.</div>
                </div>
                <div class="legend-item">
                    <span class="badge badge-roll">Early Roll</span>
                    <div class="legend-desc"><strong>Extrinsic Exhaustion:</strong> Decay of the option's extrinsic value to &le; 15% of the entry premium. Triggers buyback of active option and writes a new contract.</div>
                </div>
                <div class="legend-item">
                    <span class="badge badge-stoploss">Stop Loss</span>
                    <div class="legend-desc"><strong>Static Cushion Exit:</strong> Intraday low touches $S_{\text{stop}} = 0.92 \times (S_{\text{entry}} - P_{\text{entry}})$. Stock exits pessimistically, option closed at EOD Ask.</div>
                </div>
                <div class="legend-item">
                    <span class="badge badge-expiration">Expiration</span>
                    <div class="legend-desc"><strong>Option Settlement:</strong> Contract matures. Shares are called away if Stock > Strike, else the option expires worthless and stock shares are retained.</div>
                </div>
                <div class="legend-item">
                    <span class="badge badge-hazard">Assignment</span>
                    <div class="legend-desc"><strong>Early Assignment Hazard:</strong> Probabilistic assignment risk triggered daily when DTE &le; 10 and option extrinsic &le; $0.25.</div>
                </div>
            </div>
        </div>

        <!-- Controls (Filters, Search) -->
        <div class="controls-row">
            <div class="filter-group" id="filterGroup">
                <button class="btn-filter active" onclick="filterLogs('ALL')" id="filterAll">All Reasons</button>
                <button class="btn-filter" onclick="filterLogs('TREND')" id="filterTrend">Trend Exit</button>
                <button class="btn-filter" onclick="filterLogs('VRP')" id="filterVrp">VRP Halt</button>
                <button class="btn-filter" onclick="filterLogs('ROLL')" id="filterRoll">Early Roll</button>
                <button class="btn-filter" onclick="filterLogs('STOPLOSS')" id="filterStoploss">Stop Loss</button>
                <button class="btn-filter" onclick="filterLogs('EXPIRATION')" id="filterExpiration">Expiration</button>
                <button class="btn-filter" onclick="filterLogs('ASSIGNMENT')" id="filterAssignment">Assignment</button>
                <button class="btn-filter" onclick="filterLogs('ACTIVE')" id="filterActive">Active</button>
            </div>
            <input type="text" class="search-box" id="searchBox" placeholder="Search by symbol or date..." onkeyup="searchLogs()">
        </div>

        <!-- Interactive Trade List -->
        <div class="trade-list" id="tradeList">
            <!-- Trade cycles will be rendered dynamically by JavaScript -->
        </div>
    </div>

    <!-- JavaScript Data and Logic -->
    <script>
        // Real backtest output data for DTE=45 / Delta=0.70
        const tradeCycles = _TRADE_CYCLES_JSON_;

        // Format Currency Helper
        function formatCurrency(val) {
            const absVal = Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            return val >= 0 ? `+$${absVal}` : `-$${absVal}`;
        }

        // Render Trade Cycles to DOM
        function renderCycles(data) {
            const listContainer = document.getElementById("tradeList");
            listContainer.innerHTML = "";

            if (data.length === 0) {
                listContainer.innerHTML = `
                    <div style="text-align: center; padding: 3rem; color: var(--text-muted); border: 1px dashed var(--border-light); border-radius: 16px;">
                        No trade cycles match the search or filter criteria.
                    </div>
                `;
                return;
            }

            data.forEach((cycle) => {
                const isWin = cycle.pnl >= 0;
                const pnlClass = isWin ? "pnl-gain" : "pnl-loss";
                let badgeClass = `badge-${cycle.exitReason.toLowerCase()}`;
                if (cycle.exitReason === "ASSIGNMENT") badgeClass = "badge-hazard";
                
                let reasonLabel = cycle.exitReason;
                if (cycle.exitReason === "TREND") reasonLabel = "Trend Exit";
                else if (cycle.exitReason === "VRP") reasonLabel = "VRP Halt";
                else if (cycle.exitReason === "ROLL") reasonLabel = "Early Roll";
                else if (cycle.exitReason === "STOPLOSS") reasonLabel = "Stop Loss";
                else if (cycle.exitReason === "EXPIRATION") reasonLabel = "Expiration";
                else if (cycle.exitReason === "ASSIGNMENT") reasonLabel = "Assignment";
                else if (cycle.exitReason === "ACTIVE") reasonLabel = "Active";

                // Generate events timeline HTML
                let timelineHtml = "";
                cycle.events.forEach((ev) => {
                    let dotClass = "dot-entry";
                    if (ev.type === "ROLL" || ev.type === "ROLL_ENTRY") dotClass = "dot-roll";
                    else if (ev.type === "EXIT") {
                        if (cycle.exitReason === "TREND") dotClass = "dot-trend";
                        else if (cycle.exitReason === "VRP") dotClass = "dot-vrp";
                        else if (cycle.exitReason === "STOPLOSS") dotClass = "dot-exit";
                        else dotClass = "dot-exit";
                    }

                    timelineHtml += `
                        <div class="timeline-event">
                            <div class="timeline-dot ${dotClass}"></div>
                            <div class="timeline-content">
                                <div class="event-type">
                                    <span class="event-name">${ev.type}</span>
                                    <span class="event-date">${ev.date}</span>
                                </div>
                                <div class="event-data">
                                    <div class="data-item">Symbol: <strong>${ev.symbol}</strong></div>
                                    <div class="data-item">Stock Px: <strong>$${ev.stockPx.toFixed(2)}</strong></div>
                                    <div class="data-item">Option Premium: <strong>$${ev.optPx.toFixed(2)}</strong></div>
                                </div>
                                <div class="event-pnl ${ev.pnl >= 0 ? 'pnl-gain' : 'pnl-loss'}">
                                    ${ev.pnl !== 0 ? formatCurrency(ev.pnl) : '—'}
                                </div>
                                <div style="font-size: 0.85rem; color: var(--text-secondary); width: 100%; margin-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.02); padding-top: 0.5rem;">
                                    ${ev.desc}
                                </div>
                            </div>
                        </div>
                    `;
                });

                const cardHtml = `
                    <div class="cycle-card" id="cycleCard-${cycle.id}">
                        <div class="cycle-header" onclick="toggleDetails(${cycle.id})">
                            <div class="cycle-num">Cycle #${cycle.id}</div>
                            <div class="cycle-dates">${cycle.startDate} to ${cycle.endDate}</div>
                            <div class="cycle-info">
                                <div class="cycle-info-item">Duration: <strong>${calculateDuration(cycle.startDate, cycle.endDate)} days</strong></div>
                                <div class="cycle-info-item">Entry Option: <strong>${cycle.events[0].symbol}</strong></div>
                            </div>
                            <div class="cycle-status">
                                <span class="badge ${badgeClass}">${reasonLabel}</span>
                            </div>
                            <div class="cycle-pnl ${pnlClass}">
                                ${cycle.status === "ACTIVE" ? '—' : formatCurrency(cycle.pnl)}
                            </div>
                            <div class="cycle-toggle-icon">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                            </div>
                        </div>
                        <div class="cycle-details">
                            <div class="timeline">
                                ${timelineHtml}
                            </div>
                            ${cycle.status !== "ACTIVE" ? `
                            <div class="attribution-box">
                                <div class="attribution-title">P&L Return Attribution breakdown</div>
                                <div class="attribution-grid">
                                    <div class="attrib-item">Delta Drift (Dir)<strong>${formatCurrency(cycle.attribution.delta)}</strong></div>
                                    <div class="attrib-item">Theta Decay (Time)<strong>${formatCurrency(cycle.attribution.theta)}</strong></div>
                                    <div class="attrib-item">Gamma Drag (Convex)<strong>${formatCurrency(cycle.attribution.gamma)}</strong></div>
                                    <div class="attrib-item">Vega Volatility<strong>${formatCurrency(cycle.attribution.vega)}</strong></div>
                                    <div class="attrib-item">Slippage Cost<strong>${formatCurrency(cycle.attribution.slippage)}</strong></div>
                                    <div class="attrib-item">Gap Loss (Overnight)<strong>${formatCurrency(cycle.attribution.gap)}</strong></div>
                                    <div class="attrib-item">Treasury Interest<strong>${formatCurrency(cycle.attribution.interest)}</strong></div>
                                </div>
                            </div>
                            ` : ''}
                        </div>
                    </div>
                `;
                listContainer.insertAdjacentHTML('beforeend', cardHtml);
            });
        }

        // Toggle Cycle Card expansion
        function toggleDetails(id) {
            const card = document.getElementById(`cycleCard-${id}`);
            card.classList.toggle("expanded");
        }

        // Calculate Calendar Days helper
        function calculateDuration(start, end) {
            if (end === "—") {
                const diffTime = Math.abs(new Date() - new Date(start));
                return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            }
            const diffTime = Math.abs(new Date(end) - new Date(start));
            return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        }

        // Filter Functionality
        let currentFilter = "ALL";
        function filterLogs(filterType) {
            currentFilter = filterType;
            
            // Toggle active filter button styling
            const buttons = document.querySelectorAll(".btn-filter");
            buttons.forEach(btn => btn.classList.remove("active"));
            
            if (filterType === "ALL") document.getElementById("filterAll").classList.add("active");
            else if (filterType === "TREND") document.getElementById("filterTrend").classList.add("active");
            else if (filterType === "VRP") document.getElementById("filterVrp").classList.add("active");
            else if (filterType === "ROLL") document.getElementById("filterRoll").classList.add("active");
            else if (filterType === "STOPLOSS") document.getElementById("filterStoploss").classList.add("active");
            else if (filterType === "EXPIRATION") document.getElementById("filterExpiration").classList.add("active");
            else if (filterType === "ASSIGNMENT") document.getElementById("filterAssignment").classList.add("active");
            else if (filterType === "ACTIVE") document.getElementById("filterActive").classList.add("active");

            applyFilterAndSearch();
        }

        // Search Functionality
        function searchLogs() {
            applyFilterAndSearch();
        }

        // Joint Filter and Search logic
        function applyFilterAndSearch() {
            const searchQuery = document.getElementById("searchBox").value.toLowerCase();
            
            const filteredData = tradeCycles.filter(cycle => {
                // Check filter type
                let matchesFilter = false;
                if (currentFilter === "ALL") {
                    matchesFilter = true;
                } else if (currentFilter === "ROLL") {
                    // Match if the cycle contains any roll event
                    matchesFilter = cycle.events.some(ev => ev.type.includes("ROLL"));
                } else {
                    matchesFilter = cycle.exitReason === currentFilter;
                }
                
                // Check search query matches symbol, date, or events description
                const matchesSearch = 
                    cycle.startDate.includes(searchQuery) ||
                    cycle.endDate.includes(searchQuery) ||
                    cycle.events.some(ev => 
                        ev.symbol.toLowerCase().includes(searchQuery) || 
                        ev.desc.toLowerCase().includes(searchQuery)
                    );
                
                return matchesFilter && matchesSearch;
            });

            renderCycles(filteredData);
        }

        // Initial Page Render
        window.onload = function() {
            renderCycles(tradeCycles);
        };
    </script>
</body>
</html>
"""
    
    # Replace placeholders with computed stats and JSON data
    html_output = html_template
    html_output = html_output.replace("_WIN_RATE_", f"{win_rate:.1f}")
    html_output = html_output.replace("_WIN_COUNT_", str(len(winning_cycles)))
    html_output = html_output.replace("_LOSS_COUNT_", str(len(losing_cycles)))
    
    pnl_sign = "+" if net_profit >= 0 else "-"
    pnl_class = "pnl-gain" if net_profit >= 0 else "pnl-loss"
    abs_pnl_str = f"${abs(net_profit):,.2f}"
    html_output = html_output.replace("_PNL_CLASS_", pnl_class)
    html_output = html_output.replace("_NET_PROFIT_", f"{pnl_sign}{abs_pnl_str}")
    
    avg_pnl_sign = "+" if avg_return >= 0 else "-"
    avg_pnl_class = "pnl-gain" if avg_return >= 0 else "pnl-loss"
    abs_avg_pnl_str = f"${abs(avg_return):,.2f}"
    html_output = html_output.replace("_AVG_PNL_CLASS_", avg_pnl_class)
    html_output = html_output.replace("_AVG_RETURN_", f"{avg_pnl_sign}{abs_avg_pnl_str}")
    
    html_output = html_output.replace("_CYCLE_COUNT_", str(len(completed_cycles)))
    html_output = html_output.replace("_ACTIVE_STATUS_", active_status_str)
    html_output = html_output.replace("_ACTIVE_DESC_", active_desc)
    
    # Inject JSON representation of trade cycles
    html_output = html_output.replace("_TRADE_CYCLES_JSON_", json.dumps(trade_cycles, indent=8))
    
    # Write to trade_log.html in root
    output_path = "trade_log.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_output)
        
    print(f"Successfully generated HTML report at: {output_path}")

if __name__ == "__main__":
    main()
