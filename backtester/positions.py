import math
import numpy as np

class PositionTracker:
    def __init__(self, starting_capital: float = 100000.0):
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.shares = 0
        self.active_option = None
        self.income_ledger = 0.0
        
        # Risk baseline parameters (trade cycle tracking)
        self.hwm = starting_capital  # High-Water Mark
        self.capital_deployed = 0.0
        self.S_initial_entry = 0.0
        self.S_stop = 0.0
        self.contracts = 0

    def calculate_slippage_prices(self, bid: float, ask: float, vol_5d: float, vix: float, D_stale: int = 0, delta: float = 0.85):
        """
        Calculates execution prices using the regime-sensitive slippage model.
        Applies effective spread expansion if quote is stale.
        """
        spread = ask - bid
        if spread < 0:
            spread = 0.0
            
        # Apply Effective Spread Expansion if stale
        if D_stale > 0:
            m_stale = 1.0 + 0.5 * D_stale
            m_vol = 1.0 + max(0.0, vix - 20.0) / 10.0
            m_delta = 1.0 + max(0.0, abs(delta) - 0.85) * 2.0
            expanded_spread = spread * m_stale * m_vol * m_delta
            
            # Expand ask and contract bid around the midpoint
            mid = (bid + ask) / 2.0
            bid = max(0.01, mid - expanded_spread / 2.0)
            ask = mid + expanded_spread / 2.0
            spread = ask - bid
            
        # Volatility classification
        if vol_5d < 0.30 and vix < 15.0:
            # Low Volatility: 10% price improvement inside spread
            sf = 0.10
        elif vol_5d >= 0.50 or vix > 35.0:
            # Panic Volatility: cross the spread paying a 10% penalty
            sf = -0.10
        else:
            # Elevated Volatility: midpoint fill (0% improvement)
            sf = 0.0
            
        exec_buy = ask - (spread * sf)   # Cost to buy back short option
        exec_sell = bid + (spread * sf)  # Premium received when writing option
        return exec_buy, exec_sell

    def open_position(self, stock_price: float, option_symbol: str, strike: float, expiry_date,
                      bid: float, ask: float, delta: float, vol_5d: float, vix: float, is_roll: bool = False):
        """
        Opens a new covered call position. Under fixed-sizing rules, contract counts are determined
        based on active trading capital. Stop thresholds are set static from initial entry.
        """
        # Calculate execution premium
        exec_buy, exec_sell = self.calculate_slippage_prices(bid, ask, vol_5d, vix)
        premium = exec_sell
        
        # Calculate extrinsic value at entry
        entry_extrinsic = premium - max(0.0, stock_price - strike)
        
        if not is_roll:
            # 1. New Entry: Calculate contract count based on current cash
            net_debit = stock_price - premium
            contracts = math.floor(self.cash / (net_debit * 100))
            
            if contracts < 1:
                print(f"Warning: Insufficient cash ({self.cash:.2f}) to buy even 1 contract of stock ({net_debit * 100:.2f})")
                return False
                
            self.contracts = contracts
            self.shares = contracts * 100
            
            # Stock Purchase
            self.cash -= self.shares * stock_price
            # Option Premium Credit
            self.cash += self.contracts * 100 * premium
            
            # Set static stop thresholds relative to initial cycle entry
            self.S_initial_entry = stock_price
            self.capital_deployed = (self.shares * self.S_initial_entry) - (self.contracts * 100 * premium)
            self.S_stop = 0.92 * (self.S_initial_entry - premium)
            
            print(f"Opened NEW Position: Bought {self.shares} shares at {stock_price:.2f}, Sold {self.contracts}x {option_symbol} at {premium:.2f} (Delta {delta:.2f})")
            print(f"Static stop-loss threshold set at S_stop = {self.S_stop:.2f}")
        else:
            # 2. Roll Option: Shares are already owned. Sell new contracts matching current share count
            contracts = int(self.shares / 100)
            self.contracts = contracts
            # Option Premium Credit
            self.cash += self.contracts * 100 * premium
            
            # Non-dragging rule: S_initial_entry and S_stop remain completely UNCHANGED (static)
            print(f"ROLLED Option: Sold {self.contracts}x {option_symbol} at {premium:.2f} (Delta {delta:.2f}) on existing shares.")
            print(f"Stop-loss remains anchored at S_stop = {self.S_stop:.2f}")
            
        self.active_option = {
            'symbol': option_symbol,
            'strike': strike,
            'expiry': expiry_date,
            'entry_premium': premium,
            'entry_extrinsic': entry_extrinsic,
            'roll_disabled': False,
            'stock_entry_price': stock_price
        }
        return True

    def close_option_early(self, bid: float, ask: float, vol_5d: float, vix: float, D_stale: int = 0, delta: float = 0.85):
        """
        Closes the short option early (Realized Roll).
        """
        if self.active_option is None:
            return 0.0
            
        exec_buy, exec_sell = self.calculate_slippage_prices(bid, ask, vol_5d, vix, D_stale, delta)
        buyback_cost = self.contracts * 100 * exec_buy
        self.cash -= buyback_cost
        
        # Realized Option P&L
        realized_loss_gain = (self.active_option['entry_premium'] - exec_buy) * self.contracts * 100
        print(f"Closed Option Early: Bought back {self.active_option['symbol']} at {exec_buy:.2f} (Cost: {buyback_cost:.2f})")
        self.active_option = None
        return buyback_cost

    def settle_option_at_expiration(self, close_price: float):
        """
        Settles the short option at expiration. Shares are called away if TSLA is above strike,
        otherwise option expires worthless.
        """
        if self.active_option is None:
            return
            
        strike = self.active_option['strike']
        symbol = self.active_option['symbol']
        
        if close_price > strike:
            # Shares called away
            proceeds = self.shares * strike
            self.cash += proceeds
            print(f"Option {symbol} EXPIRED ITM at {close_price:.2f}. Shares called away at strike {strike:.2f} (Proceeds: {proceeds:.2f}).")
            self.shares = 0
            self.contracts = 0
        else:
            # Option expires worthless
            print(f"Option {symbol} EXPIRED OTM/worthless at {close_price:.2f}. Kept {self.shares} shares.")
            # We keep the shares, contracts count is unchanged
            
        self.active_option = None
        # Position is now clean or stock is held with no option. Evaluate sweeps if position is fully liquidated
        if self.shares == 0:
            self.evaluate_high_water_mark_sweep()

    def liquidate_position(self, stock_price: float, option_buyback_price: float = 0.0):
        """
        Liquidates all shares and options to Cash. Triggers when stop-loss or EMA exit is hit.
        Then evaluates the High-Water Mark sweep.
        """
        option_cost = 0.0
        if self.active_option is not None:
            option_cost = self.contracts * 100 * option_buyback_price
            self.cash -= option_cost
            print(f"Forced Option Liquidation: Bought back {self.active_option['symbol']} at {option_buyback_price:.2f} (Cost: {option_cost:.2f})")
            self.active_option = None
            
        stock_proceeds = self.shares * stock_price
        self.cash += stock_proceeds
        print(f"Forced Stock Liquidation: Sold {self.shares} shares at {stock_price:.2f} (Proceeds: {stock_proceeds:.2f})")
        
        self.shares = 0
        self.contracts = 0
        
        # Position is fully cash. Run High-Water Mark sweep
        self.evaluate_high_water_mark_sweep()

    def evaluate_high_water_mark_sweep(self):
        """
        Runs the High-Water Mark sweep ledger to prevent capital erosion during drawdowns.
        Yield is swept ONLY when Ending Cash > HWM.
        """
        ending_cash = self.cash
        if ending_cash > self.hwm:
            # Net new profit achieved above previous peak
            swept_amount = ending_cash - self.hwm
            self.income_ledger += swept_amount
            # Reset active trading cash to HWM
            self.cash = self.hwm
            print(f"HWM Sweep Activated: Swept {swept_amount:.2f} out of {ending_cash:.2f}. Income Ledger total: {self.income_ledger:.2f}. HWM holds at {self.hwm:.2f}.")
        else:
            # Drawdown state: do not sweep. Active capital remains depleted, HWM holds at previous peak
            print(f"Drawdown Sweep Check: Ending Cash {ending_cash:.2f} <= HWM {self.hwm:.2f}. No sweep. Trading capital locked at {ending_cash:.2f}.")

    def accrue_interest(self, rate: float, dt: float):
        """
        Accrues daily cash sweep yield on idle cash balance when in a Cash Override state.
        Rate is converted to decimal, and calendar days elapsed (dt) are factored.
        """
        if self.cash <= 0.0 or rate <= 0.0:
            return
        # Daily rate = decimal rate / 365
        daily_interest = self.cash * (rate / 365.0) * dt
        self.cash += daily_interest
        # print(f"Accrued Cash Sweep Interest: {daily_interest:.4f} (Rate: {rate * 100:.2f}%, dt: {dt})")
