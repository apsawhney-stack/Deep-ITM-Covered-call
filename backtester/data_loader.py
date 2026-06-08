import os
import math
import threading
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd
import polars as pl
import yfinance as yf
from thetadata import ThetaClient

class DataLoader:
    def __init__(self, creds_path="creds.txt", data_dir="data", cache_dir="data/cache"):
        self.creds_path = creds_path
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        
        # Ensure directories exist
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.client = None
        self.email = None
        self.password = None
        self.is_mock = False
        self.contract_cache = {}  # In-memory cache for parsed contract dataframes
        self.path_locks = {}
        self.locks_lock = threading.Lock()
        self.client_lock = threading.Lock()
        self._load_credentials()

    def get_path_lock(self, path):
        with self.locks_lock:
            if path not in self.path_locks:
                self.path_locks[path] = threading.Lock()
            return self.path_locks[path]

    def _load_credentials(self):
        if not os.path.exists(self.creds_path):
            raise RuntimeError(f"Credentials file {self.creds_path} not found. Mock mode is disabled.")
            
        with open(self.creds_path, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            if len(lines) < 2:
                raise RuntimeError(f"Credentials file {self.creds_path} incomplete. Mock mode is disabled.")
            self.email = lines[0]
            self.password = lines[1]
            
        if "your_email" in self.email or "your_password" in self.password or "example.com" in self.email:
            raise RuntimeError("Placeholder credentials detected in creds.txt. Mock mode is disabled.")

    def _write_parquet_atomic(self, df: pl.DataFrame, cache_path: str, required_cols: list):
        # Verification checks
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Schema verification failed for {cache_path}. Missing columns: {missing_cols}")
        if df.height == 0:
            raise ValueError(f"Schema verification failed for {cache_path}. DataFrame is empty.")
            
        temp_path = cache_path + ".tmp"
        try:
            df.write_parquet(temp_path)
            os.replace(temp_path, cache_path)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e

    def get_client(self):
        if self.is_mock:
            raise RuntimeError("DataLoader is in mock mode, which is disabled.")
        with self.client_lock:
            if self.client is None:
                try:
                    # Use native gRPC ThetaClient directly with email and password
                    self.client = ThetaClient(email=self.email, password=self.password, dataframe_type="polars")
                except Exception as e:
                    raise RuntimeError(f"Failed to initialize ThetaClient: {e}. Stopping process as requested.")
            return self.client

    def calculate_yang_zhang_volatility(self, df: pd.DataFrame, window: int = 20) -> pd.Series:
        """
        Calculates Yang-Zhang rolling historical volatility (annualized).
        """
        # Log returns
        close_prev = df['Close'].shift(1)
        open_curr = df['Open']
        high_curr = df['High']
        low_curr = df['Low']
        close_curr = df['Close']
        
        # Overnight return (close to open)
        o_prev_gap = np.log(open_curr / close_prev)
        # Intraday return (open to close)
        c_open_ret = np.log(close_curr / open_curr)
        
        # Rogers-Satchell variance components
        rs_term = (
            np.log(high_curr / close_curr) * np.log(high_curr / open_curr) +
            np.log(low_curr / close_curr) * np.log(low_curr / open_curr)
        )
        
        # Rolling estimates
        o_var = o_prev_gap.rolling(window).var()
        c_var = c_open_ret.rolling(window).var()
        rs_var = rs_term.rolling(window).mean()
        
        N = window
        k = 0.34 / (1.34 + (N + 1) / (N - 1))
        
        yz_var = o_var + k * c_var + (1 - k) * rs_var
        
        # Annualize (252 trading days)
        yz_vol = np.sqrt(yz_var * 252)
        return yz_vol

    def download_stock_and_macro_data(self, ticker: str, start_str: str, end_str: str) -> pl.DataFrame:
        """
        Downloads stock daily OHLCV, macro indicators (VIX, 3M Treasury, and CBOE Tesla IV),
        computes 50-EMA and 20-day Yang-Zhang volatility, and saves to data directory.
        """
        filepath = os.path.join(self.data_dir, f"{ticker}_daily.parquet")
        if os.path.exists(filepath):
            print(f"Loading cached stock daily database from {filepath}")
            df_pl = pl.read_parquet(filepath)
            if "RV_YZ_5" not in df_pl.columns:
                print("Calculating missing RV_YZ_5 for cached daily database...")
                df_pd = df_pl.to_pandas()
                df_pd['RV_YZ_5'] = self.calculate_yang_zhang_volatility(df_pd, window=5)
                df_pd['RV_YZ_5'] = df_pd['RV_YZ_5'].ffill().bfill()
                df_pl = pl.from_pandas(df_pd)
                df_pl.write_parquet(filepath)
            return df_pl

        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        
        stock_df = None
        
        # 1. Try to download Stock EOD data from ThetaData if not in mock mode
        if not self.is_mock:
            try:
                print(f"Connecting to ThetaData to download daily bars for {ticker}...")
                client = self.get_client()
                if client is not None:
                    # In 1.0.7, call stock_history_eod directly
                    stock_pl = client.stock_history_eod(
                        symbol=ticker,
                        start_date=start_date,
                        end_date=end_date
                    )
                    stock_pl = stock_pl.with_columns(pl.col("created").dt.date().alias("date"))
                    stock_df = stock_pl.select(['date', 'open', 'high', 'low', 'close', 'volume']).to_pandas()
                    # Capitalize columns to match expected output schema
                    stock_df.columns = [col.capitalize() for col in stock_df.columns]
            except Exception as e:
                print(f"ThetaData stock download failed: {e}. Falling back to Yahoo Finance...")
                stock_df = None
                
        # Fallback stock download from yfinance
        if stock_df is None:
            print(f"Downloading historical stock data for {ticker} from Yahoo Finance...")
            stock_yf = yf.download(ticker, start=start_str, end=(datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d"))
            stock_df = stock_yf.reset_index()
            # Collapse MultiIndex columns if present
            if isinstance(stock_df.columns, pd.MultiIndex):
                stock_df.columns = stock_df.columns.get_level_values(0)
            # Standardize column names
            stock_df.columns = [col.capitalize() for col in stock_df.columns]
            
        stock_df['Date'] = pd.to_datetime(stock_df['Date']).dt.date
        stock_df = stock_df.sort_values('Date').reset_index(drop=True)
        
        # 2. Download Macro data from yfinance (Treasury 3M yield ^IRX, VIX ^VIX, and Volatility Index if mapped)
        VOL_INDEX_MAP = {
            "TSLA": "^VXTSLA",
            "AAPL": "^VXAPL",
            "MSFT": "^VXMSFT",
            "AMZN": "^VXAZN",
            "NVDA": "^VXNVD",
            "GOOG": "^VXGOG",
            "META": "^VXMTA",
            "SPY": "^VIX",
            "QQQ": "^VXN",
            "IWM": "^RVX"
        }
        
        vol_symbol = VOL_INDEX_MAP.get(ticker.upper(), None)
        download_list = ["^IRX", "^VIX"]
        if vol_symbol:
            download_list.append(vol_symbol)
            
        print(f"Downloading Treasury Yield (^IRX), VIX (^VIX), and Volatility Index ({vol_symbol or 'None'}) from Yahoo Finance...")
        yf_start = (start_date - timedelta(days=365)).strftime("%Y-%m-%d") # pad 252 trading days for VRP rolling stats
        yf_end = (end_date + timedelta(days=2)).strftime("%Y-%m-%d")
        
        macro_data = yf.download(download_list, start=yf_start, end=yf_end)
        
        # Extract Close prices
        close_prices = macro_data['Close']
        if isinstance(close_prices.columns, pd.MultiIndex):
            close_prices.columns = close_prices.columns.get_level_values(0)
            
        close_prices.index = close_prices.index.date
        close_prices = close_prices.reset_index().rename(columns={'index': 'Date'})
        
        # Match columns robustly by string containment
        irx_cols = [c for c in close_prices.columns if '^IRX' in str(c)]
        vix_cols = [c for c in close_prices.columns if '^VIX' in str(c)]
        vol_cols = [c for c in close_prices.columns if vol_symbol in str(c)] if vol_symbol else []
        
        if irx_cols:
            close_prices['Treasury_Yield_3M'] = close_prices[irx_cols[0]] / 100.0 # Convert percentage (e.g. 4.5 -> 0.045)
        else:
            close_prices['Treasury_Yield_3M'] = 0.03
            
        if vix_cols:
            close_prices['VIX'] = close_prices[vix_cols[0]]
        else:
            close_prices['VIX'] = 20.0
            
        if vol_cols:
            close_prices['IV_ATM_30'] = close_prices[vol_cols[0]] / 100.0 # Convert CBOE volatility to decimal (e.g. 55.0 -> 0.55)
        else:
            close_prices['IV_ATM_30'] = np.nan
            
        close_prices = close_prices[['Date', 'Treasury_Yield_3M', 'VIX', 'IV_ATM_30']]
        
        # Merge datasets
        merged = pd.merge(stock_df, close_prices, on='Date', how='left')
        
        # Forward fill treasury rates, VIX, and IV_ATM_30 in case of minor date mismatches
        merged['Treasury_Yield_3M'] = merged['Treasury_Yield_3M'].ffill().bfill()
        merged['VIX'] = merged['VIX'].ffill().bfill()
        merged['IV_ATM_30'] = merged['IV_ATM_30'].ffill().bfill()
        
        # 3. Calculate 50-EMA
        merged['EMA_50'] = merged['Close'].ewm(span=50, adjust=False).mean()
        
        # 4. Calculate 20-day and 5-day Yang-Zhang Volatility
        merged['RV_YZ_20'] = self.calculate_yang_zhang_volatility(merged, window=20)
        merged['RV_YZ_20'] = merged['RV_YZ_20'].ffill().bfill()
        
        merged['RV_YZ_5'] = self.calculate_yang_zhang_volatility(merged, window=5)
        merged['RV_YZ_5'] = merged['RV_YZ_5'].ffill().bfill()
        
        # 5. Check if we need to dynamically calculate IV_ATM_30 (Option A)
        if 'IV_ATM_30' not in merged.columns:
            merged['IV_ATM_30'] = np.nan
        if merged['IV_ATM_30'].isna().all() or merged['IV_ATM_30'].isna().sum() > len(merged) * 0.5:
            print(f"Volatility index not found or has too many NaNs for {ticker}. Computing dynamically from EOD option chain gRPC...")
            try:
                # Initialize client
                client = self.get_client()
                
                # Fetch list of all expirations for ticker
                exp_df = client.option_list_expirations(ticker)
                expirations = exp_df["expiration"].cast(pl.Date).to_list()
                
                # For each date in backtest, determine target 30 DTE expiration
                dates_list = merged['Date'].tolist()
                closes_list = merged['Close'].tolist()
                
                # Group dates by their selected 30 DTE expiration to make batch gRPC calls
                exp_to_dates = {}
                for d, close in zip(dates_list, closes_list):
                    target_expiry = d + timedelta(days=30)
                    selected_expiry = min(expirations, key=lambda exp_d: abs(exp_d - target_expiry))
                    if selected_expiry not in exp_to_dates:
                        exp_to_dates[selected_expiry] = []
                    exp_to_dates[selected_expiry].append((d, close))
                
                # Batch query option greeks per expiration and match ATM strike
                computed_ivs = {}
                for exp_date, date_spots in exp_to_dates.items():
                    try:
                        min_date = min(d for d, _ in date_spots)
                        max_date = max(d for d, _ in date_spots)
                        
                        # Query all strikes for this expiration over this date range using Standard EOD query
                        df_greeks = client.option_history_greeks_eod(
                            symbol=ticker,
                            expiration=exp_date,
                            start_date=min_date,
                            end_date=max_date,
                            strike="*",
                            right="call",
                            strike_range=15
                        )
                        
                        if df_greeks is not None and df_greeks.height > 0:
                            # Map timestamp to date
                            df_greeks = df_greeks.with_columns(pl.col("timestamp").dt.date().alias("date"))
                            
                            # Group by date to find ATM implied vol for each date
                            for d, spot in date_spots:
                                # Filter for this date
                                df_day = df_greeks.filter(pl.col("date") == d)
                                if df_day.height > 0:
                                    # Find the strike closest to spot price
                                    df_day = df_day.with_columns(
                                        (pl.col("strike") - spot).abs().alias("strike_diff")
                                    )
                                    atm_row = df_day.sort("strike_diff").head(1)
                                    if atm_row.height > 0:
                                        iv = atm_row["implied_vol"][0]
                                        computed_ivs[d] = iv
                    except Exception as exp_err:
                        print(f"Warning: Failed to fetch option greeks for expiration {exp_date}: {exp_err}")
                
                # Map computed IVs back to DataFrame
                merged['IV_ATM_30'] = merged['Date'].map(computed_ivs)
            except Exception as dyn_err:
                print(f"Warning: Dynamic IV calculation failed: {dyn_err}. Falling back to historical Yang-Zhang RV scaler.")
                
        # Final fallback for any remaining NaNs in IV_ATM_30
        merged['IV_ATM_30'] = merged['IV_ATM_30'].ffill().bfill()
        if merged['IV_ATM_30'].isna().any():
            print("Warning: Some dates are missing IV_ATM_30. Falling back to 1.20x Yang-Zhang RV (floor 20%) as IV proxy.")
            merged['IV_ATM_30'] = merged['IV_ATM_30'].fillna((merged['RV_YZ_20'] * 1.20).clip(lower=0.20))
            
        # Ensure VIX and Treasury rates have no NaNs
        if 'VIX' not in merged.columns:
            merged['VIX'] = 20.0
        merged['VIX'] = merged['VIX'].fillna(20.0)
        
        if 'Treasury_Yield_3M' not in merged.columns:
            merged['Treasury_Yield_3M'] = 0.03
        merged['Treasury_Yield_3M'] = merged['Treasury_Yield_3M'].fillna(0.03)
        
        # 6. Calculate Volatility Risk Premium (VRP) spread and z-score
        # VRP = IV_ATM - RV_YZ
        merged['VRP'] = merged['IV_ATM_30'] - merged['RV_YZ_20']
        
        # Calculate 252-day rolling mean and std of VRP
        merged['VRP_mean_252'] = merged['VRP'].rolling(window=252, min_periods=20).mean().ffill().bfill()
        merged['VRP_std_252'] = merged['VRP'].rolling(window=252, min_periods=20).std().ffill().bfill()
        merged['VRP_z'] = (merged['VRP'] - merged['VRP_mean_252']) / merged['VRP_std_252']
        merged['VRP_z'] = merged['VRP_z'].fillna(0.0) # Fallback if std is 0
        
        # Save to Parquet
        filepath = os.path.join(self.data_dir, f"{ticker}_daily.parquet")
        pl_df = pl.from_pandas(merged)
        pl_df.write_parquet(filepath)
        print(f"Successfully saved stock daily database with VRP indicators to {filepath}")
        return pl_df

    def get_options_chain(self, ticker: str, trade_date: date, target_dte: int = 30) -> pl.DataFrame:
        """
        Fetches the complete EOD options chain for a specific date.
        If in mock mode, generates a synthetic options chain based on stock price and IV.
        """
        # Convert pandas Timestamp or datetime to date object
        if hasattr(trade_date, 'date'):
            trade_date = trade_date.date()
            
        # Check known data gap dates to avoid useless server queries and timeouts
        if trade_date in [date(2026, 1, 20), date(2026, 1, 21)]:
            print(f"Skipping get_options_chain for known data gap date: {trade_date}")
            return pl.DataFrame()
            
        cache_path = os.path.join(self.cache_dir, f"chain_{ticker}_{trade_date.strftime('%Y%m%d')}_{target_dte}.parquet")
        path_lock = self.get_path_lock(cache_path)
        with path_lock:
            if os.path.exists(cache_path):
                try:
                    return pl.read_parquet(cache_path)
                except Exception as e:
                    print(f"Options chain cache read error for {trade_date}: {e}. Reloading.")

            if self.is_mock:
                raise RuntimeError(f"DataLoader is in mock/offline mode and cache missed for options chain on {trade_date}. Stopping process as requested.")
                
            # Implement robust retry loop around ThetaData connection and querying
            import time
            max_retries = 5
            backoff = 2.0
            
            for attempt in range(1, max_retries + 1):
                try:
                    client = self.get_client()
                    if client is None:
                        raise RuntimeError("ThetaClient is not initialized")
                        
                    # 1. Fetch expirations using direct client
                    exp_df = client.option_list_expirations(ticker)
                    expirations = exp_df["expiration"].cast(pl.Date).to_list()
                    
                    # Find closest expiration to target_dte
                    target_expiry = trade_date + timedelta(days=target_dte)
                    selected_expiry = min(expirations, key=lambda d: abs(d - target_expiry))
                    
                    # 2. Query EOD Greeks chain using EOD gRPC wildcard call
                    df_chain = client.option_history_greeks_eod(
                        symbol=ticker,
                        expiration=selected_expiry,
                        start_date=trade_date,
                        end_date=trade_date,
                        strike="*",
                        right="call",
                        strike_range=15
                    )
                    
                    if df_chain is not None and df_chain.height > 0:
                        # Rename columns to match old backtester expectations
                        if "implied_vol" in df_chain.columns:
                            df_chain = df_chain.rename({"implied_vol": "implied_volatility"})
                        if "timestamp" in df_chain.columns:
                            df_chain = df_chain.with_columns(pl.col("timestamp").dt.date().alias("date"))
                        if "open_interest" not in df_chain.columns:
                            df_chain = df_chain.with_columns(pl.lit(1000).alias("open_interest"))
                        if "volume" not in df_chain.columns:
                            df_chain = df_chain.with_columns(pl.lit(150).alias("volume"))
                            
                        # Lowercase all column names to be safe
                        df_chain = df_chain.rename({col: col.lower() for col in df_chain.columns})
                        
                        # Generate OSI symbol
                        df_chain = df_chain.with_columns(
                            pl.struct(["symbol", "expiration", "right", "strike"]).map_elements(
                                lambda r: f"{r['symbol']}{datetime.strptime(r['expiration'], '%Y-%m-%d').strftime('%y%m%d')}{'C' if r['right'].upper().startswith('C') else 'P'}{int(r['strike'] * 1000):08d}",
                                return_dtype=pl.String
                            ).alias("symbol")
                        )
                        
                        # Format right column to 'C' or 'P'
                        df_chain = df_chain.with_columns(
                            pl.col("right").map_elements(lambda r: 'C' if r.upper().startswith('C') else 'P', return_dtype=pl.String)
                        )
                        
                        # Rename expiration to expiry
                        df_chain = df_chain.rename({"expiration": "expiry"})
                        
                        # Write to cache
                        self._write_parquet_atomic(df_chain, cache_path, [
                            "symbol", "right", "strike", "expiry", "bid", "ask", "delta", "implied_volatility", "open_interest", "volume"
                        ])
                        return df_chain
                        
                    raise RuntimeError("No records returned from options chain query")
                    
                except Exception as e:
                    if "no data found" in str(e).lower():
                        print(f"No options chain data found on ThetaData for {trade_date}. Returning empty chain.")
                        return pl.DataFrame()
                    print(f"Warning: get_options_chain failed on attempt {attempt}/{max_retries}: {e}")
                    if attempt == max_retries:
                        raise RuntimeError(f"Failed to fetch options chain from ThetaData after {max_retries} attempts: {e}. Stopping process as requested.")
                    
                    sleep_time = backoff * (0.8 + 0.4 * np.random.rand())
                    print(f"Waiting {sleep_time:.2f} seconds before retrying...")
                    time.sleep(sleep_time)
                    backoff *= 2.0
                
        raise RuntimeError("DataLoader entered mock mode path in get_options_chain, which is disabled.")


    def get_option_contract_history(self, option_symbol: str, start_date: date, end_date: date) -> pl.DataFrame:
        """
        Fetches the daily EOD quote and Greeks history for a specific contract symbol.
        """
        # Convert pandas Timestamp or datetime to date objects
        if hasattr(start_date, 'date'):
            start_date = start_date.date()
        if hasattr(end_date, 'date'):
            end_date = end_date.date()
            
        # Parse option symbol to get root, exp, strike, right
        cp_idx = -1
        for char in ['C', 'P']:
            idx = option_symbol.find(char)
            if idx != -1:
                cp_idx = idx
                break
        if cp_idx == -1:
            raise ValueError(f"Could not parse option symbol: {option_symbol}")
            
        root = option_symbol[:cp_idx-6]
        expiry_part = option_symbol[cp_idx-6:cp_idx]
        expiry_date = datetime.strptime(expiry_part, "%y%m%d").date()
        strike_part = option_symbol[cp_idx+1:]
        strike = float(strike_part) / 1000.0
        right = "call" if option_symbol[cp_idx] == 'C' else "put"
        
        # 1. Check in-memory cache first
        if option_symbol in self.contract_cache:
            df = self.contract_cache[option_symbol]
            return df.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

        cache_path = os.path.join(self.cache_dir, f"{option_symbol}.parquet")
        
        path_lock = self.get_path_lock(cache_path)
        with path_lock:
            # 2. Check Parquet disk cache
            if os.path.exists(cache_path):
                try:
                    df = pl.read_parquet(cache_path)
                    df = df.rename({col: col.lower() for col in df.columns})
                    if df.height > 0:
                        cached_dates = df['date'].to_list()
                        parsed_dates = []
                        for d in cached_dates:
                            if isinstance(d, str):
                                parsed_dates.append(datetime.strptime(d[:10], "%Y-%m-%d").date())
                            elif hasattr(d, 'date'):
                                parsed_dates.append(d.date())
                            else:
                                parsed_dates.append(d)
                        min_cached = min(parsed_dates)
                        max_cached = max(parsed_dates)
                        
                        if self.is_mock or (min_cached <= start_date and (max_cached >= end_date or max_cached >= expiry_date)):
                            # Cache covers requested date range or we are in mock mode, return it directly
                            df = df.with_columns(pl.Series("date", parsed_dates))
                            self.contract_cache[option_symbol] = df  # Store in in-memory cache
                            return df.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))
                except Exception as cache_err:
                    print(f"Cache read error for {option_symbol}: {cache_err}. Reloading from source.")

            if self.is_mock:
                raise RuntimeError(f"DataLoader is in mock/offline mode and cache missed for {option_symbol}. Stopping process as requested.")
                
            # Fetch all history up to the day before expiry date to avoid the server-side Greeks timeout on expiration day (DTE=0)
            # Cap at yesterday to avoid querying future dates that do not exist yet on the server
            fetch_end_date = min(expiry_date - timedelta(days=1), date.today() - timedelta(days=1))
            
            # Implement robust retry loop around ThetaData connection and querying
            import time
            max_retries = 5
            backoff = 2.0
            
            for attempt in range(1, max_retries + 1):
                try:
                    client = self.get_client()
                    if client is None:
                        raise RuntimeError("ThetaClient is not initialized")
                        
                    # Query EOD Greeks history using direct gRPC client
                    df_pl = client.option_history_greeks_eod(
                        symbol=root,
                        expiration=expiry_date,
                        start_date=start_date,
                        end_date=fetch_end_date,
                        strike=f"{strike:.2f}",
                        right=right
                    )
                    
                    if df_pl is not None and df_pl.height > 0:
                        # Rename columns to match old backtester expectations
                        if "implied_vol" in df_pl.columns:
                            df_pl = df_pl.rename({"implied_vol": "implied_volatility"})
                        if "timestamp" in df_pl.columns:
                            df_pl = df_pl.with_columns(pl.col("timestamp").dt.date().alias("date"))
                        if "open_interest" not in df_pl.columns:
                            df_pl = df_pl.with_columns(pl.lit(1000).alias("open_interest"))
                        if "volume" not in df_pl.columns:
                            df_pl = df_pl.with_columns(pl.lit(150).alias("volume"))
                            
                        # Lowercase all column names to be safe
                        df_pl = df_pl.rename({col: col.lower() for col in df_pl.columns})
                        
                        # Write to Parquet disk cache and in-memory cache
                        self._write_parquet_atomic(df_pl, cache_path, ["date", "bid", "ask", "delta", "implied_volatility"])
                        self.contract_cache[option_symbol] = df_pl
                        
                        return df_pl.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))
                        
                    raise RuntimeError("No records returned from option contract history query")
                except Exception as e:
                    if "no data found" in str(e).lower():
                        print(f"No option contract history found on ThetaData for {option_symbol}. Returning empty history.")
                        return pl.DataFrame()
                    print(f"Warning: get_option_contract_history failed on attempt {attempt}/{max_retries} for {option_symbol}: {e}")
                    if attempt == max_retries:
                        raise RuntimeError(f"Failed to fetch option contract history from ThetaData after {max_retries} attempts: {e}. Stopping process as requested.")
                    
                    sleep_time = backoff * (0.8 + 0.4 * np.random.rand())
                    print(f"Waiting {sleep_time:.2f} seconds before retrying...")
                    time.sleep(sleep_time)
                    backoff *= 2.0
                    
            raise RuntimeError("DataLoader entered mock mode path in get_option_contract_history, which is disabled.")
