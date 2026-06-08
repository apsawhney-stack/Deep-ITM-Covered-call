import os
import random
from datetime import datetime, date, timedelta
import numpy as np
import polars as pl
from .positions import PositionTracker
from .data_loader import DataLoader

class BacktestEngine:
    def __init__(self, config: dict, loader: DataLoader):
        self.config = config
        self.loader = loader
        
        # Initialize position tracker
        self.tracker = PositionTracker(starting_capital=config['starting_capital'])
        
        # State loggers
        self.daily_history = []
        self.trade_log = []
        
        # Fetch configurations
        self.asset = config.get('asset', 'TSLA')
        self.target_dte = config.get('target_dte', 30)
        self.relative_roll_threshold = config.get('relative_roll_threshold', 0.15)
        self.stop_loss_pct = config.get('stop_loss_pct', 0.08)
        self.adverse_fill_factor = config.get('adverse_fill_factor', 0.01)
        self.vrp_rich_threshold = config.get('vrp_rich_threshold', 0.5)
        self.vrp_compressed_threshold = config.get('vrp_compressed_threshold', -1.0)
        
        # Liquidity config
        self.min_open_interest = config.get('min_open_interest', 100)
        self.min_daily_volume = config.get('min_daily_volume', 10)
        self.max_spread_to_mid = config.get('max_spread_to_mid', 0.15)
        
        # Stats counters
        self.early_assignments_count = 0
        self.liquidity_rejections_count = 0
        self.total_attempts_count = 0

    def get_regime_and_delta(self, pct_diff: float, vrp_z: float):
        """
        Determines the portfolio posture and target Delta using the Tiered Overwrite Matrix
        and the VRP z-Score Filter.
        """
        # Check if we have a config override for baseline delta
        override_delta = self.config.get('baseline_delta')
        
        # If EMA filter is disabled
        if self.config.get('disable_ema_filter', False):
            base_d = override_delta if override_delta is not None else 0.80
            if self.config.get('disable_vrp_filter', False):
                return "Bullish", base_d, "Constant Delta Posture"
            if vrp_z >= self.vrp_rich_threshold:
                return "Bullish", base_d, "Constant Delta Posture (VRP Rich)"
            elif self.vrp_compressed_threshold <= vrp_z < self.vrp_rich_threshold:
                return "Bullish", min(0.95, base_d + 0.05), "Constant Delta Posture (VRP Compressed)"
            else:
                return "VRP Underpriced", None, "Halt Option Writing (Cash Override)"
        
        # 1. Determine baseline trend regime and target Delta
        if pct_diff >= 0.02:
            regime = "Bullish"
            baseline_delta = override_delta if override_delta is not None else 0.80
            posture = "Yield Harvesting"
        elif -0.019 <= pct_diff < 0.02:
            regime = "Neutral Chop"
            baseline_delta = min(0.95, override_delta + 0.08) if override_delta is not None else 0.88
            posture = "Defensive Overwrite"
        elif -0.049 <= pct_diff < -0.019:
            regime = "Bearish Transition"
            baseline_delta = min(0.95, override_delta + 0.15) if override_delta is not None else 0.95
            posture = "Max Intrinsic Cushion"
        else:
            # Deep Bear (pct_diff <= -0.05)
            return "Deep Bear", None, "100% Cash Override"
            
        # 2. Apply VRP Filter adjustments (Entry Gate)
        if self.config.get('disable_vrp_filter', False):
            return regime, baseline_delta, posture
            
        if vrp_z >= self.vrp_rich_threshold:
            # VRP Rich: Keep baseline
            final_delta = baseline_delta
            posture += " (VRP Rich)"
        elif self.vrp_compressed_threshold <= vrp_z < self.vrp_rich_threshold:
            # VRP Compressed: Shift to defensive (Delta + 0.05, ceiling 0.95)
            final_delta = min(0.95, baseline_delta + 0.05)
            posture += " (VRP Compressed, Delta +0.05)"
        else:
            # VRP Underpriced (vrp_z < -1.0): Halt all writing
            return "VRP Underpriced", None, "Halt Option Writing (Cash Override)"
            
        return regime, final_delta, posture

    def select_best_contract(self, chain: pl.DataFrame, target_delta: float, current_date: date):
        """
        Locates the optimal option contract for target DTE and Delta.
        Applies the Phantom Liquidity Filter and Money-Seeking scan directions.
        """
        self.total_attempts_count += 1
        
        # Standardize chain column names to lowercase
        cols = {c.lower(): c for c in chain.columns}
        
        # Determine right column name for Call/Put filter
        right_col = cols.get('right') or cols.get('option_type') or cols.get('option_right')
        if not right_col:
            raise ValueError(f"Could not find call/put indicator column in option chain. Available: {chain.columns}")
            
        # Filter for Calls only
        calls = chain.filter(pl.col(right_col).str.to_uppercase().str.starts_with("C"))
        if len(calls) == 0:
            return None
            
        # Get expiry column
        expiry_col = cols.get('expiry') or cols.get('expiration') or cols.get('expiry_date')
        
        # Find expirations >= current_date + target_dte
        min_date = current_date + timedelta(days=self.target_dte)
        # Parse dates
        expiries = []
        for x in calls[expiry_col].unique().to_list():
            if isinstance(x, str):
                exp_date = datetime.strptime(x[:10], "%Y-%m-%d").date()
            elif isinstance(x, datetime):
                exp_date = x.date()
            elif isinstance(x, date):
                exp_date = x
            else:
                continue
            if exp_date >= min_date:
                expiries.append(exp_date)
                
        if not expiries:
            return None
            
        # Select closest expiration date
        selected_expiry = min(expiries, key=lambda d: (d - min_date).days)
        selected_expiry_str = selected_expiry.strftime("%Y-%m-%d")
        
        # Filter calls for this expiration
        # Check if the column is string or date objects
        first_val = calls[expiry_col][0]
        if isinstance(first_val, str):
            expiry_filtered = calls.filter(pl.col(expiry_col).str.starts_with(selected_expiry_str[:10]))
        else:
            expiry_filtered = calls.filter(pl.col(expiry_col).cast(pl.Date) == selected_expiry)
            
        if len(expiry_filtered) == 0:
            return None
            
        # Select strike based on Delta and Liquidity
        strike_col = cols.get('strike') or cols.get('strike_price')
        delta_col = cols.get('delta')
        bid_col = cols.get('bid')
        ask_col = cols.get('ask')
        oi_col = cols.get('open_interest') or cols.get('openinterest') or cols.get('oi')
        vol_col = cols.get('volume') or cols.get('vol')
        symbol_col = cols.get('symbol') or cols.get('option_symbol') or cols.get('osi_symbol')
        
        # Sort candidates by strike to allow sequential scanning
        # Since we scan toward-the-money (lower delta, meaning higher strike price for calls),
        # sorting strikes ascending is perfect.
        candidates = expiry_filtered.sort(strike_col)
        
        # Find index of the contract closest to target delta
        delta_diff = (candidates[delta_col].abs() - target_delta).abs()
        best_idx = delta_diff.arg_min()
        
        # Convert to list of dicts for fast pure Polars/Python traversal
        candidate_dicts = candidates.to_dicts()
        
        # Scan sequentially toward the money (downward Delta / upward strike)
        # For call options, strike price and Delta are inversely related:
        # Lower Delta means HIGHER strike price.
        # So we scan from best_idx forward (to higher index/strikes).
        for idx in range(best_idx, len(candidate_dicts)):
            row = candidate_dicts[idx]
            
            # Extract parameters
            bid = float(row[bid_col])
            ask = float(row[ask_col])
            oi = int(row[oi_col]) if row[oi_col] is not None else 0
            vol = int(row[vol_col]) if row[vol_col] is not None else 0
            delta = float(row[delta_col])
            strike = float(row[strike_col])
            symbol = row[symbol_col]
            
            # Liquidity checks
            mid = (bid + ask) / 2.0
            spread = ask - bid
            
            if mid <= 0:
                continue
                
            spread_ratio = spread / mid
            
            # Abort if we drift below 0.60 Delta during the scan (or target_delta if target_delta < 0.60)
            delta_floor = min(0.60, target_delta)
            if abs(delta) < delta_floor:
                print(f"Liquidity scan aborted: Delta {delta:.2f} fell below {delta_floor:.2f} floor.")
                break
                
            # Filter matches
            if oi >= self.min_open_interest and vol >= self.min_daily_volume and spread_ratio <= self.max_spread_to_mid:
                # Liquid contract found!
                return {
                    'symbol': symbol,
                    'strike': strike,
                    'expiry': selected_expiry,
                    'bid': bid,
                    'ask': ask,
                    'delta': delta
                }
                
        # If we failed to find any liquid candidate scanning toward the money, register rejection
        self.liquidity_rejections_count += 1
        print(f"Liquidity rejection: No contracts passed filters starting from target Delta {target_delta:.2f}")
        return None

    def run_backtest(self):
        """
        Executes the daily event loop simulation across the configuration date range.
        """
        print(f"Initializing Backtest Engine for {self.asset}...")
        
        # 1. Download/Load daily database
        df_pl = self.loader.download_stock_and_macro_data(
            ticker=self.asset,
            start_str=self.config['start_date'],
            end_str=self.config['end_date']
        )
        
        # Filter for the requested start_date and end_date to avoid cache range bleed
        start_date_obj = datetime.strptime(self.config['start_date'], "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(self.config['end_date'], "%Y-%m-%d").date()
        
        # Ensure Date column is cast to Date type and sorted
        df_pl = df_pl.with_columns(
            pl.col("Date").cast(pl.Date)
        ).sort("Date")
        
        df_filtered = df_pl.filter(
            (pl.col("Date") >= start_date_obj) & (pl.col("Date") <= end_date_obj)
        )
        
        # Convert to list of dicts for fast traversal
        df_dicts = df_filtered.to_dicts()
        
        # Simulation variables
        prev_date = None
        
        print("Starting Daily Simulation Loop...")
        for row in df_dicts:
            current_date = row['Date']
            if hasattr(current_date, 'date'):
                current_date = current_date.date()
            elif isinstance(current_date, str):
                current_date = datetime.strptime(current_date[:10], "%Y-%m-%d").date()
                
            # Calculate calendar days elapsed (dt) for interest sweep
            if prev_date is None:
                dt = 1
            else:
                dt = (current_date - prev_date).days
                
            stock_close = float(row['Close'])
            stock_open = float(row['Open'])
            stock_low = float(row['Low'])
            stock_high = float(row['High']) if 'High' in row else stock_close
            ema_50 = float(row['EMA_50'])
            vol_5d = float(row['RV_YZ_5'])
            vix = float(row['VIX'])
            treasury_rate = float(row['Treasury_Yield_3M'])
            vrp_z = float(row['VRP_z'])
            
            # --- STEP A: ACCRUE INTEREST ON CASH ---
            # If in cash, sweep interest daily
            if self.tracker.shares == 0:
                self.tracker.accrue_interest(treasury_rate, dt)
                
            # --- FETCH ACTIVE OPTION QUOTE ONCE PER DAY ---
            bid, ask, delta, D_stale = None, None, None, 0
            exec_buy, exec_sell, current_extrinsic = 0.0, 0.0, 0.0
            roll_disabled = False
            option_iv = 0.50
            
            if self.tracker.active_option is not None:
                opt_symbol = self.tracker.active_option['symbol']
                try:
                    # Query contract history from entry date up to current date to detect staleness
                    opt_history = self.loader.get_option_contract_history(
                        opt_symbol, 
                        self.tracker.active_option['entry_date'], 
                        current_date
                    )
                    if len(opt_history) > 0:
                        # Get the most recent quote
                        opt_history_sorted = opt_history.sort('date')
                        last_quote = opt_history_sorted.row(-1, named=True)
                        quote_date = last_quote['date']
                        if isinstance(quote_date, str):
                            quote_date = datetime.strptime(quote_date[:10], "%Y-%m-%d").date()
                        elif isinstance(quote_date, datetime):
                            quote_date = quote_date.date()
                        elif isinstance(quote_date, date):
                            quote_date = quote_date
                            
                        D_stale = (current_date - quote_date).days
                        
                        bid = float(last_quote['bid'])
                        ask = float(last_quote['ask'])
                        delta = float(last_quote['delta']) if 'delta' in last_quote else 0.85
                        option_iv = float(last_quote['implied_volatility']) if 'implied_volatility' in last_quote else 0.50
                        
                        # Spread expansion and slippage pricing
                        exec_buy, exec_sell = self.tracker.calculate_slippage_prices(bid, ask, vol_5d, vix, D_stale, delta)
                        current_extrinsic = exec_buy - max(0.0, stock_close - self.tracker.active_option['strike'])
                        
                        # Stale quote lockout
                        if D_stale >= 3 and vix > 35:
                            roll_disabled = True
                except Exception as e:
                    raise RuntimeError(f"Failed to fetch contract history on {current_date}: {e}. Stopping process as requested.")
                    
            # --- STEP B: CHECK INTRADAY STOP-LOSS ---
            if self.tracker.active_option is not None and not self.config.get('disable_stop_loss', False):
                if stock_low <= self.tracker.S_stop:
                    # Intraday Stop-loss triggered!
                    # Pessimistic Stock liquidation price: min(Open, S_stop * (1.0 - self.adverse_fill_factor))
                    stock_liq = min(stock_open, self.tracker.S_stop * (1.0 - self.adverse_fill_factor))
                    
                    # Fetch EOD options quotes (pre-fetched or fallback)
                    opt_symbol = self.tracker.active_option['symbol']
                    opt_ask = ask if ask is not None else self.tracker.active_option['entry_premium'] * 1.5
                        
                    # Realized P&L decomposition
                    exec_buy_val = opt_ask
                    stock_unrealized = (stock_liq - self.tracker.S_initial_entry) * self.tracker.shares
                    option_realized = (self.tracker.active_option['entry_premium'] - exec_buy_val) * self.tracker.contracts * 100
                    net_cycle_loss = stock_unrealized + option_realized
                    
                    # Cache active position details before state destruction
                    shares = self.tracker.shares
                    contracts = self.tracker.contracts
                    
                    # Execute liquidation
                    self.tracker.liquidate_position(stock_liq, option_buyback_price=opt_ask)
                    
                    self.trade_log.append({
                        'date': current_date,
                        'event': 'STOP_LOSS',
                        'symbol': opt_symbol,
                        'stock_price': stock_liq,
                        'option_price': opt_ask,
                        'net_return': net_cycle_loss,
                        'pnl_theta': 0.0,
                        'pnl_delta': stock_unrealized,
                        'pnl_gamma': 0.0,
                        'pnl_vega': 0.0,
                        'pnl_slippage': (stock_liq - self.tracker.S_stop) * shares,
                        'pnl_gap': min(0.0, (stock_open - self.tracker.S_stop)) * shares if stock_open < self.tracker.S_stop else 0.0
                    })
                    prev_date = current_date
                    # Log history
                    self._log_history(current_date, stock_close, stock_open, stock_high, stock_low, ema_50, vix, vrp_z, treasury_rate)
                    continue

            # --- STEP C: CHECK EXPIRATION ---
            if self.tracker.active_option is not None:
                if current_date >= self.tracker.active_option['expiry']:
                    # Option Expiration reached
                    opt_symbol = self.tracker.active_option['symbol']
                    strike = self.tracker.active_option['strike']
                    entry_premium = self.tracker.active_option['entry_premium']
                    
                    # Cache active position details before settlement
                    shares = self.tracker.shares
                    contracts = self.tracker.contracts
                    
                    # Settle
                    self.tracker.settle_option_at_expiration(stock_close)
                    
                    # Calculate correct realized return at assignment
                    net_ret = (strike - self.tracker.S_initial_entry) * shares + (entry_premium * contracts * 100) if stock_close > strike else 0.0
                    
                    self.trade_log.append({
                        'date': current_date,
                        'event': 'EXPIRATION',
                        'symbol': opt_symbol,
                        'stock_price': stock_close,
                        'option_price': 0.0,
                        'net_return': net_ret,
                        'pnl_theta': entry_premium * contracts * 100,
                        'pnl_delta': (stock_close - self.tracker.S_initial_entry) * shares if stock_close <= strike else (strike - self.tracker.S_initial_entry) * shares,
                        'pnl_gamma': 0.0,
                        'pnl_vega': 0.0,
                        'pnl_slippage': 0.0,
                        'pnl_gap': 0.0
                    })
                    
                    # If shares are called away, we are in cash
                    if self.tracker.shares == 0:
                        prev_date = current_date
                        self._log_history(current_date, stock_close, stock_open, stock_high, stock_low, ema_50, vix, vrp_z, treasury_rate)
                        continue

            # --- STEP D: CHECK EARLY ROLLS (3:45 PM CLOSE) ---
            if self.tracker.active_option is not None:
                opt_symbol = self.tracker.active_option['symbol']
                
                if bid is not None and ask is not None:
                    # Check roll condition
                    if not roll_disabled and current_extrinsic <= self.tracker.active_option['entry_extrinsic'] * self.relative_roll_threshold:
                        # Roll trigger hit!
                        active_opt_cached = self.tracker.active_option
                        buyback_cost = self.tracker.close_option_early(bid, ask, vol_5d, vix, D_stale, delta)
                        
                        # Determine Roll Driver
                        days_held = (current_date - active_opt_cached.get('entry_date', current_date - timedelta(days=10))).days
                        if (active_opt_cached['expiry'] - current_date).days <= 3:
                            driver = 'Theta-Driven'
                        elif abs(stock_close - active_opt_cached['stock_entry_price']) / active_opt_cached['stock_entry_price'] > 0.05:
                            driver = 'Delta-Driven'
                        else:
                            driver = 'Vega-Driven'
                            
                        self.trade_log.append({
                            'date': current_date,
                            'event': f'ROLL_{driver}',
                            'symbol': opt_symbol,
                            'stock_price': stock_close,
                            'option_price': exec_buy,
                            'net_return': (active_opt_cached['entry_premium'] - exec_buy) * self.tracker.contracts * 100,
                            'pnl_theta': active_opt_cached['entry_extrinsic'] * self.tracker.contracts * 100,
                            'pnl_delta': (stock_close - active_opt_cached['stock_entry_price']) * self.tracker.shares,
                            'pnl_gamma': 0.0,
                            'pnl_vega': 0.0,
                            'pnl_slippage': (exec_buy - ask) * self.tracker.contracts * 100,
                            'pnl_gap': 0.0
                        })
                        
                        # Now roll into a new option contract
                        self.tracker.active_option = None
                        
            # --- STEP E: EVALUATE PROBABILISTIC ASSIGNMENT ---
            if self.tracker.active_option is not None:
                # Early assignment hazard check
                dte = (self.tracker.active_option['expiry'] - current_date).days
                opt_symbol = self.tracker.active_option['symbol']
                
                if bid is not None and ask is not None:
                    if dte <= 10 and current_extrinsic <= 0.25:
                        # Calculate assignment probability
                        p_assign = min(1.0, max(0.0, 1.0 - current_extrinsic / 0.25)) * (1.0 - dte / 10.0)
                        if random.random() <= p_assign:
                            # EARLY ASSIGNMENT TRIGGERED!
                            self.early_assignments_count += 1
                            strike = self.tracker.active_option['strike']
                            proceeds = self.tracker.shares * strike
                            
                            # Realized Option P&L
                            opt_loss = (self.tracker.active_option['entry_premium'] - current_extrinsic) * self.tracker.contracts * 100
                            
                            self.tracker.active_option = None
                            self.tracker.shares = 0
                            self.tracker.contracts = 0
                            self.tracker.cash += proceeds
                            
                            # Run HWM sweep
                            self.tracker.evaluate_high_water_mark_sweep()
                            
                            self.trade_log.append({
                                'date': current_date,
                                'event': 'ASSIGNMENT',
                                'symbol': opt_symbol,
                                'stock_price': stock_close,
                                'option_price': current_extrinsic,
                                'net_return': proceeds - self.tracker.capital_deployed,
                                'pnl_theta': 0.0,
                                'pnl_delta': 0.0,
                                'pnl_gamma': 0.0,
                                'pnl_vega': 0.0,
                                'pnl_slippage': 0.0,
                                'pnl_gap': 0.0
                            })
                            
                            prev_date = current_date
                            self._log_history(current_date, stock_close, stock_open, stock_high, stock_low, ema_50, vix, vrp_z, treasury_rate)
                            continue

            # --- STEP F: TREND EXIT ---
            if self.tracker.shares > 0 and not self.config.get('disable_ema_filter', False):
                pct_diff = (stock_close - ema_50) / ema_50
                if pct_diff <= -0.05:  # Deep Bear exit
                    # Fetch current EOD option buyback price to liquidate
                    current_val = ask if ask is not None else 0.0
                    
                    # Realized Cycle P&L
                    shares = self.tracker.shares
                    contracts = self.tracker.contracts
                    opt_symbol = self.tracker.active_option['symbol'] if self.tracker.active_option is not None else 'None'
                    stock_realized = (stock_close - self.tracker.S_initial_entry) * shares
                    if self.tracker.active_option is not None:
                        option_realized = (self.tracker.active_option['entry_premium'] - current_val) * contracts * 100
                    else:
                        option_realized = 0.0
                    net_cycle_return = stock_realized + option_realized
                    
                    self.tracker.liquidate_position(stock_close, option_buyback_price=current_val)
                    
                    self.trade_log.append({
                        'date': current_date,
                        'event': 'TREND_EXIT',
                        'symbol': opt_symbol,
                        'stock_price': stock_close,
                        'option_price': current_val,
                        'net_return': net_cycle_return,
                        'pnl_theta': 0.0,
                        'pnl_delta': stock_realized,
                        'pnl_gamma': 0.0,
                        'pnl_vega': 0.0,
                        'pnl_slippage': 0.0,
                        'pnl_gap': 0.0
                    })
                    prev_date = current_date
                    self._log_history(current_date, stock_close, stock_open, stock_high, stock_low, ema_50, vix, vrp_z, treasury_rate)
                    continue

            # --- STEP G: NEW ENTRY TRIGGER ---
            if self.tracker.shares == 0:
                pct_diff = (stock_close - ema_50) / ema_50
                
                # Check VRP z-score and EMA trend matrix
                regime, target_delta, posture = self.get_regime_and_delta(pct_diff, vrp_z)
                
                # Only write calls if regime is bullish/chop/transition and VRP z-score is acceptable
                if target_delta is not None and target_delta > 0:
                    # We enter the trade cycle!
                    # Fetch EOD options chain for current date
                    try:
                        chain = self.loader.get_options_chain(self.asset, current_date, target_dte=self.target_dte)
                        # Select optimal contract
                        selected = self.select_best_contract(chain, target_delta, current_date)
                    except Exception as e:
                        print(f"Warning: Failed to fetch options chain on {current_date}: {e}. Skipping trade entry on this day.")
                        selected = None
                        
                    if selected is not None:
                        # Open new position
                        opened = self.tracker.open_position(
                            stock_price=stock_close,
                            option_symbol=selected['symbol'],
                            strike=selected['strike'],
                            expiry_date=selected['expiry'],
                            bid=selected['bid'],
                            ask=selected['ask'],
                            delta=selected['delta'],
                            vol_5d=vol_5d,
                            vix=vix,
                            is_roll=False
                        )
                        if opened:
                            # Record entry date to active_option for held calculations
                            self.tracker.active_option['entry_date'] = current_date
                            self.trade_log.append({
                                'date': current_date,
                                'event': 'ENTRY',
                                'symbol': selected['symbol'],
                                'stock_price': stock_close,
                                'option_price': selected['bid'],
                                'net_return': 0.0,
                                'pnl_theta': 0.0,
                                'pnl_delta': 0.0,
                                'pnl_gamma': 0.0,
                                'pnl_vega': 0.0,
                                'pnl_slippage': 0.0,
                                'pnl_gap': 0.0
                            })
            elif self.tracker.active_option is None:
                # Stock is held, option was closed early or expired. Re-write option matching current trend regime
                pct_diff = (stock_close - ema_50) / ema_50
                regime, target_delta, posture = self.get_regime_and_delta(pct_diff, vrp_z)
                
                if target_delta is None or target_delta <= 0:
                    # Cache active position details
                    shares = self.tracker.shares
                    stock_realized = (stock_close - self.tracker.S_initial_entry) * shares if shares > 0 else 0.0
                    
                    # BLOCK writing call -> MUST liquidate underlying stock to enforce Cash Override
                    self.tracker.liquidate_position(stock_close, option_buyback_price=0.0)
                    print(f"Halt/Cash Override enforced. Liquidated shares to return to 100% Cash.")
                    self.trade_log.append({
                        'date': current_date,
                        'event': 'CASH_OVERRIDE_LIQ',
                        'symbol': 'None',
                        'stock_price': stock_close,
                        'option_price': 0.0,
                        'net_return': stock_realized,
                        'pnl_theta': 0.0,
                        'pnl_delta': stock_realized,
                        'pnl_gamma': 0.0,
                        'pnl_vega': 0.0,
                        'pnl_slippage': 0.0,
                        'pnl_gap': 0.0
                    })
                else:
                    try:
                        chain = self.loader.get_options_chain(self.asset, current_date, target_dte=self.target_dte)
                        selected = self.select_best_contract(chain, target_delta, current_date)
                    except Exception as e:
                        print(f"Warning: Failed to fetch options chain on {current_date}: {e}. Skipping trade roll on this day.")
                        selected = None
                        
                    if selected is not None:
                        # Roll option (keep stock)
                        opened = self.tracker.open_position(
                            stock_price=stock_close,
                            option_symbol=selected['symbol'],
                            strike=selected['strike'],
                            expiry_date=selected['expiry'],
                            bid=selected['bid'],
                            ask=selected['ask'],
                            delta=selected['delta'],
                            vol_5d=vol_5d,
                            vix=vix,
                            is_roll=True
                        )
                        if opened:
                            self.tracker.active_option['entry_date'] = current_date
                            self.trade_log.append({
                                'date': current_date,
                                'event': 'ROLL_ENTRY',
                                'symbol': selected['symbol'],
                                'stock_price': stock_close,
                                'option_price': selected['bid'],
                                'net_return': 0.0,
                                'pnl_theta': 0.0,
                                'pnl_delta': 0.0,
                                'pnl_gamma': 0.0,
                                'pnl_vega': 0.0,
                                'pnl_slippage': 0.0,
                                'pnl_gap': 0.0
                            })
                            
            # Log history
            self._log_history(current_date, stock_close, stock_open, stock_high, stock_low, ema_50, vix, vrp_z, treasury_rate,
                             option_val=ask if ask is not None else 0.0, option_delta=delta if delta is not None else 0.85, option_iv=option_iv)
            prev_date = current_date
            
        print("Backtest simulation completed successfully.")
        return self._compile_history()

    def _log_history(self, current_date, stock_close, stock_open, stock_high, stock_low, ema_50, vix, vrp_z, treasury_rate,
                     option_val=0.0, option_delta=0.0, option_iv=0.0):
        # Calculate current net portfolio liquidation value
        option_symbol = 'None'
        option_strike = 0.0
        option_expiry = None
        option_dte = 0
        
        if self.tracker.active_option is not None:
            option_symbol = self.tracker.active_option['symbol']
            option_strike = self.tracker.active_option['strike']
            option_expiry = self.tracker.active_option['expiry']
            option_dte = (option_expiry - current_date).days
            
            if option_val == 0.0:
                option_val = self.tracker.active_option['entry_premium']
                option_delta = 0.85
                option_iv = 0.50
        else:
            option_val = 0.0
            option_delta = 0.0
            option_iv = 0.0
            
        portfolio_value = self.tracker.cash + (self.tracker.shares * stock_close) - (self.tracker.contracts * 100 * option_val) + self.tracker.income_ledger
        
        self.daily_history.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': self.tracker.cash,
            'shares': self.tracker.shares,
            'stock_close': stock_close,
            'stock_open': stock_open,
            'stock_high': stock_high,
            'stock_low': stock_low,
            'active_option': option_symbol,
            'option_value': option_val,
            'option_delta': option_delta,
            'option_iv': option_iv,
            'option_strike': option_strike,
            'option_expiry': option_expiry,
            'option_dte': option_dte,
            'income_ledger': self.tracker.income_ledger,
            'hwm': self.tracker.hwm,
            'vix': vix,
            'vrp_z': vrp_z,
            'ema_50': ema_50,
            'treasury_rate': treasury_rate
        })

    def _compile_history(self) -> pl.DataFrame:
        hist_df = pl.DataFrame(self.daily_history)
        hist_df = hist_df.with_columns(
            pl.col("date").cast(pl.Date)
        )
        return hist_df
