import os
import math
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta

# Hardcoded TSLA Earnings Announcement Dates (2020 - 2026)
TSLA_EARNINGS_DATES = {
    # 2020
    date(2020, 4, 29), date(2020, 7, 22), date(2020, 10, 21),
    # 2021
    date(2021, 1, 27), date(2021, 4, 26), date(2021, 7, 26), date(2021, 10, 20),
    # 2022
    date(2022, 1, 26), date(2022, 4, 20), date(2022, 7, 20), date(2022, 10, 19),
    # 2023
    date(2023, 1, 25), date(2023, 4, 19), date(2023, 7, 19), date(2023, 10, 18),
    # 2024
    date(2024, 1, 24), date(2024, 4, 23), date(2024, 7, 23), date(2024, 10, 23),
    # 2025
    date(2025, 1, 29), date(2025, 4, 22), date(2025, 7, 23), date(2025, 10, 22),
    # 2026
    date(2026, 1, 28), date(2026, 4, 22)
}

# Hardcoded FOMC Announcement Dates (2020 - 2026)
FOMC_ANNOUNCEMENT_DATES = {
    # 2020
    date(2020, 1, 29), date(2020, 3, 15), date(2020, 3, 18), date(2020, 4, 29),
    date(2020, 6, 10), date(2020, 7, 29), date(2020, 9, 16), date(2020, 11, 5), date(2020, 12, 16),
    # 2021
    date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28), date(2021, 6, 16),
    date(2021, 7, 28), date(2021, 9, 22), date(2021, 11, 3), date(2021, 12, 15),
    # 2022
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15),
    date(2022, 7, 27), date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    # 2023
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    # 2024
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 4, 30), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 11, 5), date(2025, 12, 10),
    # 2026
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)
}

# Compile week numbers for quick labeling
FOMC_WEEKS = {d.isocalendar()[:2] for d in FOMC_ANNOUNCEMENT_DATES}
EARNINGS_WEEKS = {d.isocalendar()[:2] for d in TSLA_EARNINGS_DATES}

def calculate_base_metrics(returns: pd.Series, values: pd.Series, dates: pd.Series, treasury_rates: pd.Series) -> dict:
    """
    Helper to calculate standard portfolio performance metrics for a series of daily returns.
    """
    if len(returns) == 0:
        return {
            'cagr': 0.0, 'sharpe': 0.0, 'sortino': 0.0, 'max_dd': 0.0,
            'win_rate': 0.0, 'volatility': 0.0
        }
        
    # Standardize values
    returns = returns.fillna(0.0)
    
    # Calculate calendar days for CAGR
    days_elapsed = (dates.iloc[-1] - dates.iloc[0]).days
    if days_elapsed <= 0:
        days_elapsed = 1
        
    start_val = values.iloc[0]
    end_val = values.iloc[-1]
    
    # CAGR
    if start_val > 0 and end_val > 0:
        cagr = (end_val / start_val) ** (365.25 / days_elapsed) - 1.0
    else:
        cagr = 0.0
        
    # Excess Returns (using daily Treasury rates)
    # Treasury rates are in decimals (e.g. 0.045 for 4.5%)
    daily_rf = treasury_rates.fillna(0.0) / 252.0
    excess_ret = returns - daily_rf
    
    mean_excess = excess_ret.mean()
    std_ret = returns.std()
    
    # Annualized Volatility
    vol = std_ret * math.sqrt(252)
    
    # Annualized Sharpe
    if std_ret > 0:
        sharpe = (mean_excess * 252) / vol
    else:
        sharpe = 0.0
        
    # Annualized Sortino
    downside_ret = excess_ret.copy()
    downside_ret[downside_ret > 0] = 0.0
    downside_std = downside_ret.std()
    
    if downside_std > 0:
        sortino = (mean_excess * 252) / (downside_std * math.sqrt(252))
    else:
        sortino = 0.0
        
    # Max Drawdown
    peaks = values.cummax()
    drawdowns = (values - peaks) / peaks
    max_dd = drawdowns.min()
    
    # Win Rate
    win_rate = (returns > 0).sum() / len(returns) if len(returns) > 0 else 0.0
    
    return {
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'volatility': vol
    }

def calculate_metrics(daily_df: pd.DataFrame, trade_log: list, config: dict, stock_df: pd.DataFrame) -> dict:
    """
    Computes advanced portfolio risk, trade attribution, and regime metrics.
    """
    if len(daily_df) < 2:
        print("Warning: Insufficient daily history to compute metrics.")
        return {}
        
    # Ensure correct date formats
    daily_df['date'] = pd.to_datetime(daily_df['date']).dt.date
    stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.date
    
    # Sort by date
    daily_df = daily_df.sort_values('date').reset_index(drop=True)
    
    # Calculate daily returns
    daily_df['daily_return'] = daily_df['portfolio_value'].pct_change()
    daily_df.loc[0, 'daily_return'] = 0.0
    
    # 1. Overall Portfolio Metrics
    overall = calculate_base_metrics(
        returns=daily_df['daily_return'].iloc[1:],
        values=daily_df['portfolio_value'],
        dates=daily_df['date'],
        treasury_rates=daily_df['treasury_rate']
    )
    
    # Expected Shortfall (CVaR - 95%)
    valid_returns = daily_df['daily_return'].iloc[1:].dropna()
    if len(valid_returns) > 0:
        sorted_ret = valid_returns.sort_values()
        cutoff = int(math.ceil(0.05 * len(sorted_ret)))
        if cutoff > 0:
            cvar_95 = sorted_ret.iloc[:cutoff].mean()
        else:
            cvar_95 = sorted_ret.iloc[0]
    else:
        cvar_95 = 0.0
    overall['cvar_95'] = cvar_95
    
    # 2. Event-Segregated Analytics (Earnings, FOMC, Crash, Non-Event)
    # Label weeks and days
    earnings_weeks = []
    fomc_weeks = []
    crash_days = []
    non_event_days = []
    
    daily_df['week_id'] = daily_df['date'].apply(lambda d: d.isocalendar()[:2])
    daily_df['is_earnings_week'] = daily_df['week_id'].apply(lambda w: w in EARNINGS_WEEKS)
    daily_df['is_fomc_week'] = daily_df['week_id'].apply(lambda w: w in FOMC_WEEKS)
    
    # Stock return for crash check
    daily_df['stock_return'] = daily_df['stock_close'].pct_change()
    daily_df.loc[0, 'stock_return'] = 0.0
    
    # Crash Clusters: VIX > 25 or stock drops > 5% in a single session
    daily_df['is_crash_day'] = (daily_df['vix'] > 25.0) | (daily_df['stock_return'] <= -0.05)
    
    # Non-Event Weeks: Exclude both earnings and FOMC weeks
    daily_df['is_non_event_week'] = (~daily_df['is_earnings_week']) & (~daily_df['is_fomc_week'])
    
    # Filter datasets and calculate metrics
    categories = {
        'earnings_weeks': daily_df[daily_df['is_earnings_week']],
        'fomc_weeks': daily_df[daily_df['is_fomc_week']],
        'crash_clusters': daily_df[daily_df['is_crash_day']],
        'non_event_weeks': daily_df[daily_df['is_non_event_week']]
    }
    
    segregated_metrics = {}
    for name, df_sub in categories.items():
        if len(df_sub) >= 2:
            df_sub = df_sub.sort_values('date')
            sub_ret = df_sub['daily_return']
            
            # Attributable Compounded Return
            compounded = (1.0 + sub_ret).prod() - 1.0
            # Annualize by daily count relative to standard trading year (252 days)
            cagr = (1.0 + compounded) ** (252.0 / len(df_sub)) - 1.0
            
            # Max Drawdown based on contiguous sub-equity curve
            peaks = df_sub['portfolio_value'].cummax()
            drawdowns = (df_sub['portfolio_value'] - peaks) / peaks
            max_dd = drawdowns.min()
            
            base_m = calculate_base_metrics(
                returns=sub_ret,
                values=df_sub['portfolio_value'],
                dates=df_sub['date'],
                treasury_rates=df_sub['treasury_rate']
            )
            
            segregated_metrics[name] = {
                'cagr': cagr,
                'sharpe': base_m['sharpe'],
                'sortino': base_m['sortino'],
                'max_dd': max_dd,
                'win_rate': base_m['win_rate'],
                'volatility': base_m['volatility']
            }
        else:
            segregated_metrics[name] = {
                'cagr': 0.0, 'sharpe': 0.0, 'sortino': 0.0, 'max_dd': 0.0,
                'win_rate': 0.0, 'volatility': 0.0
            }
            
    # 3. Overnight Gap Matrix (Top 5 largest overnight TSLA gap-downs)
    # Gap = (Open_t - Close_{t-1}) / Close_{t-1}
    daily_df['overnight_gap'] = (daily_df['stock_open'] - daily_df['stock_close'].shift(1)) / daily_df['stock_close'].shift(1)
    # Find top 5 largest negative gaps
    top_gaps = daily_df.dropna(subset=['overnight_gap']).sort_values('overnight_gap').head(5).copy()
    
    gap_matrix = []
    for idx, row in top_gaps.iterrows():
        # Drawdown on that day
        peaks_till_now = daily_df.loc[:idx, 'portfolio_value'].max()
        curr_dd = (row['portfolio_value'] - peaks_till_now) / peaks_till_now
        
        gap_matrix.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'stock_gap': row['overnight_gap'],
            'portfolio_return': row['daily_return'],
            'portfolio_drawdown': curr_dd
        })
        
    # 4. VIX Regime Attribution Table
    vix_regimes = {
        'low_vix': daily_df[daily_df['vix'] < 15.0],
        'mod_vix': daily_df[(daily_df['vix'] >= 15.0) & (daily_df['vix'] <= 30.0)],
        'panic_vix': daily_df[daily_df['vix'] > 30.0]
    }
    
    vix_attribution = {}
    for name, df_sub in vix_regimes.items():
        if len(df_sub) >= 2:
            df_sub = df_sub.sort_values('date')
            sub_ret = df_sub['daily_return']
            
            # Attributable Compounded Return
            compounded = (1.0 + sub_ret).prod() - 1.0
            # Annualize by daily count relative to standard trading year (252 days)
            cagr = (1.0 + compounded) ** (252.0 / len(df_sub)) - 1.0
            
            # Max Drawdown based on contiguous sub-equity curve
            peaks = df_sub['portfolio_value'].cummax()
            drawdowns = (df_sub['portfolio_value'] - peaks) / peaks
            max_dd = drawdowns.min()
            
            base_m = calculate_base_metrics(
                returns=sub_ret,
                values=df_sub['portfolio_value'],
                dates=df_sub['date'],
                treasury_rates=df_sub['treasury_rate']
            )
            
            vix_attribution[name] = {
                'cagr': cagr,
                'sharpe': base_m['sharpe'],
                'sortino': base_m['sortino'],
                'max_dd': max_dd,
                'win_rate': base_m['win_rate'],
                'volatility': base_m['volatility']
            }
        else:
            vix_attribution[name] = {
                'cagr': 0.0, 'sharpe': 0.0, 'sortino': 0.0, 'max_dd': 0.0,
                'win_rate': 0.0, 'volatility': 0.0
            }
            
    # 5. Delta Exposure & Short-Gamma Crisis Metrics
    # Filter for days when options were active
    active_days = daily_df[daily_df['active_option'] != 'None'].copy()
    
    if len(active_days) > 0:
        active_days['net_delta'] = 1.0 - active_days['option_delta']
        max_net_delta = active_days['net_delta'].max()
        avg_net_delta = active_days['net_delta'].mean()
        
        # Vol-of-Vol Index: Annualized standard deviation of daily changes in ATM IV
        # Merge with stock_df to get IV_ATM_30
        daily_merged = pd.merge(daily_df, stock_df[['Date', 'IV_ATM_30']], left_on='date', right_on='Date', how='left')
        daily_merged['iv_atm_diff'] = daily_merged['IV_ATM_30'].diff()
        vol_of_vol = daily_merged['iv_atm_diff'].std() * math.sqrt(252)
        
        # Calculate daily Gamma stress: |delta_t - delta_{t-1}| / (|return_t| * 100)
        active_days['delta_diff'] = active_days['option_delta'].diff().abs()
        active_days['stock_ret_abs'] = active_days['stock_return'].abs()
        
        # Filter for non-zero stock returns to avoid division by zero
        gamma_stress_days = active_days[(active_days['stock_ret_abs'] > 0.0001) & (active_days['delta_diff'].notna())].copy()
        if len(gamma_stress_days) > 0:
            gamma_stress_days['gamma_stress'] = gamma_stress_days['delta_diff'] / (gamma_stress_days['stock_ret_abs'] * 100.0)
            max_gamma_stress = gamma_stress_days['gamma_stress'].max()
            avg_gamma_stress = gamma_stress_days['gamma_stress'].mean()
        else:
            max_gamma_stress = 0.0
            avg_gamma_stress = 0.0
    else:
        max_net_delta = 0.0
        avg_net_delta = 0.0
        vol_of_vol = 0.0
        max_gamma_stress = 0.0
        avg_gamma_stress = 0.0
        
    # 6. Daily/Trade-level P&L Decomposition
    # Decompose portfolio daily return into Delta Drift, Gamma Drag, Vega Impact, and Theta Harvest
    daily_df['delta_drift'] = 0.0
    daily_df['gamma_drag'] = 0.0
    daily_df['vega_impact'] = 0.0
    daily_df['theta_harvest'] = 0.0
    daily_df['slippage_cost'] = 0.0
    daily_df['gap_loss'] = 0.0
    daily_df['interest_earned'] = 0.0
    
    # Map trade log details to dates for transactions
    trade_map = {}
    for trade in trade_log:
        t_date = trade['date']
        if isinstance(t_date, str):
            t_date = datetime.strptime(t_date[:10], "%Y-%m-%d").date()
        if t_date not in trade_map:
            trade_map[t_date] = []
        trade_map[t_date].append(trade)
        
    # Calculate daily greeks and attribution step-by-step
    for t in range(1, len(daily_df)):
        row_prev = daily_df.iloc[t - 1]
        row_curr = daily_df.iloc[t]
        t_date = row_curr['date']
        
        # Check active contracts
        shares_prev = row_prev['shares']
        stock_prev = row_prev['stock_close']
        stock_curr = row_curr['stock_close']
        dS = stock_curr - stock_prev
        
        # Decompose cash interest first
        r_rate = row_prev['treasury_rate']
        dt = (t_date - row_prev['date']).days
        interest = row_prev['cash'] * (r_rate / 365.0) * dt
        daily_df.loc[t, 'interest_earned'] = interest
        
        # Check if there is an explicit trade transaction on this day
        trades = trade_map.get(t_date)
        if trades:
            # Mark slippage and gap loss from trade log
            daily_df.loc[t, 'slippage_cost'] = sum(abs(tr.get('pnl_slippage', 0.0)) for tr in trades)
            daily_df.loc[t, 'gap_loss'] = sum(abs(tr.get('pnl_gap', 0.0)) for tr in trades)
            
        # Decompose options P&L if option was held from t-1
        if row_prev['active_option'] != 'None':
            # We had an active contract
            opt_val_prev = row_prev['option_value']
            opt_val_curr = row_curr['option_value']
            opt_delta_prev = row_prev['option_delta']
            opt_delta_curr = row_curr['option_delta']
            opt_iv_prev = row_prev['option_iv']
            opt_iv_curr = row_curr['option_iv']
            opt_strike = row_prev['option_strike']
            opt_dte_prev = row_prev['option_dte']
            
            # Number of option contracts
            contracts = int(shares_prev / 100)
            
            # Delta component (Directional exposure of the covered call)
            # Net Portfolio Delta = Shares - Contracts * 100 * Option_Delta
            # Net Delta Drift = Contracts * 100 * (1 - Option_Delta) * dS
            delta_drift = contracts * 100 * (1.0 - opt_delta_prev) * dS
            daily_df.loc[t, 'delta_drift'] = delta_drift
            
            # Option price change (short position, so return is -dP)
            dP = opt_val_curr - opt_val_prev
            option_return = -contracts * 100 * dP
            
            # Gamma Drag approximation
            if abs(dS) > 0.001:
                gamma = (opt_delta_curr - opt_delta_prev) / dS
            else:
                gamma = 0.0
            gamma_drag = -contracts * 100 * 0.5 * gamma * (dS ** 2)
            daily_df.loc[t, 'gamma_drag'] = gamma_drag
            
            # Vega Impact approximation
            # Approximate Vega using standard Black-Scholes formula components
            T_years = opt_dte_prev / 365.25
            if T_years > 0 and opt_iv_prev > 0 and stock_prev > 0:
                d1 = (math.log(stock_prev / opt_strike) + (0.05 + 0.5 * (opt_iv_prev ** 2)) * T_years) / (opt_iv_prev * math.sqrt(T_years))
                phi_d1 = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * (d1 ** 2))
                vega_est = stock_prev * math.sqrt(T_years) * phi_d1
            else:
                vega_est = 0.0
            
            vega_impact = -contracts * 100 * vega_est * (opt_iv_curr - opt_iv_prev)
            daily_df.loc[t, 'vega_impact'] = vega_impact
            
            # Theta Harvest (residual option return after subtracting Delta, Gamma, and Vega components)
            theta_harvest = option_return - (-contracts * 100 * opt_delta_prev * dS + gamma_drag + vega_impact)
            daily_df.loc[t, 'theta_harvest'] = theta_harvest
        else:
            # No option active, it was a pure cash or stock position drift day
            if shares_prev > 0:
                # Stock held with no option
                daily_df.loc[t, 'delta_drift'] = shares_prev * dS
                
    # Sum up attributions
    total_delta_drift = daily_df['delta_drift'].sum()
    total_gamma_drag = daily_df['gamma_drag'].sum()
    total_vega_impact = daily_df['vega_impact'].sum()
    total_theta_harvest = daily_df['theta_harvest'].sum()
    total_slippage = daily_df['slippage_cost'].sum()
    total_gap_loss = daily_df['gap_loss'].sum()
    total_interest = daily_df['interest_earned'].sum()
    
    # 7. Other Risk Indicators
    # Early Assignment Frequency
    total_cycles = len([t for t in trade_log if t['event'] == 'ENTRY'])
    assignments = len([t for t in trade_log if t['event'] == 'ASSIGNMENT'])
    assignment_freq = assignments / total_cycles if total_cycles > 0 else 0.0
    
    # Liquidity Rejections
    rejections = len([t for t in trade_log if t.get('event') == 'LIQUIDITY_REJECT']) # Wait, is this logged?
    # Let's use the engine counter if available or lookups
    rejection_rate = 0.0
    
    # VRP Attribution Log (Average VRP at Entry)
    entry_dates = [t['date'] for t in trade_log if t['event'] == 'ENTRY']
    entry_vrp_zs = []
    for d in entry_dates:
        vrp_rows = stock_df[stock_df['Date'] == d]
        if len(vrp_rows) > 0:
            entry_vrp_zs.append(float(vrp_rows['VRP_z'].values[0]))
    avg_entry_vrp_z = np.mean(entry_vrp_zs) if entry_vrp_zs else 0.0
    
    return {
        'overall': overall,
        'segregated': segregated_metrics,
        'vix_attribution': vix_attribution,
        'gap_matrix': gap_matrix,
        'delta_max': max_net_delta,
        'delta_avg': avg_net_delta,
        'vol_of_vol': vol_of_vol,
        'gamma_stress_max': max_gamma_stress,
        'gamma_stress_avg': avg_gamma_stress,
        'attribution': {
            'delta_drift': total_delta_drift,
            'gamma_drag': total_gamma_drag,
            'vega_impact': total_vega_impact,
            'theta_harvest': total_theta_harvest,
            'slippage_cost': total_slippage,
            'gap_loss': total_gap_loss,
            'interest_earned': total_interest
        },
        'assignment_freq': assignment_freq,
        'avg_entry_vrp_z': avg_entry_vrp_z,
        'daily_df': daily_df
    }
