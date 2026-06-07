import os
import math
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
        self._load_credentials()

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

    def get_client(self):
        if self.is_mock:
            raise RuntimeError("DataLoader is in mock mode, which is disabled.")
        if self.client is None:
            try:
                # Prepend portable Java path to environment on macOS
                java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
                if os.path.exists(java_bin_dir) and java_bin_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
                
                # Use a default timeout of 15 seconds to allow fast failover/recovery on slow ThetaData responses
                self.client = ThetaClient(username=self.email, passwd=self.password, timeout=15)
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
                    from thetadata import StockReqType, DateRange
                    stock_df = client.get_hist_stock_REST(
                        req=StockReqType.EOD,
                        root=ticker,
                        date_range=DateRange(start_date, end_date)
                    )
                    if isinstance(stock_df, pl.DataFrame):
                        stock_df = stock_df.to_pandas()
                    stock_df.columns = [col.name.capitalize() if hasattr(col, 'name') else str(col).capitalize() for col in stock_df.columns]
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
        
        # 2. Download Macro data from yfinance (Treasury 3M yield ^IRX, VIX ^VIX, and Tesla Volatility Index ^VXTSLA)
        print("Downloading Treasury Yield (^IRX), VIX (^VIX), and CBOE Tesla Volatility Index (^VXTSLA) from Yahoo Finance...")
        yf_start = (start_date - timedelta(days=365)).strftime("%Y-%m-%d") # pad 252 trading days for VRP rolling stats
        yf_end = (end_date + timedelta(days=2)).strftime("%Y-%m-%d")
        
        macro_data = yf.download(["^IRX", "^VIX", "^VXTSLA"], start=yf_start, end=yf_end)
        
        # Extract Close prices
        close_prices = macro_data['Close']
        if isinstance(close_prices.columns, pd.MultiIndex):
            close_prices.columns = close_prices.columns.get_level_values(0)
            
        close_prices.index = close_prices.index.date
        close_prices = close_prices.reset_index().rename(columns={'index': 'Date'})
        
        # Match columns robustly by string containment
        irx_cols = [c for c in close_prices.columns if '^IRX' in str(c)]
        vix_cols = [c for c in close_prices.columns if '^VIX' in str(c)]
        vxtsla_cols = [c for c in close_prices.columns if '^VXTSLA' in str(c)]
        
        if irx_cols:
            close_prices['Treasury_Yield_3M'] = close_prices[irx_cols[0]] / 100.0 # Convert percentage (e.g. 4.5 -> 0.045)
        else:
            close_prices['Treasury_Yield_3M'] = 0.03
            
        if vix_cols:
            close_prices['VIX'] = close_prices[vix_cols[0]]
        else:
            close_prices['VIX'] = 20.0
            
        if vxtsla_cols:
            close_prices['IV_ATM_30'] = close_prices[vxtsla_cols[0]] / 100.0 # Convert CBOE volatility to decimal (e.g. 55.0 -> 0.55)
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
        
        # Fallback if IV_ATM_30 is all NaN or has too many NaNs due to delisting
        if 'IV_ATM_30' not in merged.columns:
            merged['IV_ATM_30'] = np.nan
        if merged['IV_ATM_30'].isna().all() or merged['IV_ATM_30'].isna().sum() > len(merged) * 0.5:
            print("Warning: CBOE Tesla Volatility Index (^VXTSLA) was not found on yfinance or was delisted. Using 1.25x Yang-Zhang RV (floor 45%) as IV proxy.")
            merged['IV_ATM_30'] = (merged['RV_YZ_20'] * 1.25).clip(lower=0.45)
            
        # Ensure VIX and Treasury rates have no NaNs
        if 'VIX' not in merged.columns:
            merged['VIX'] = 20.0
        merged['VIX'] = merged['VIX'].fillna(20.0)
        
        if 'Treasury_Yield_3M' not in merged.columns:
            merged['Treasury_Yield_3M'] = 0.03
        merged['Treasury_Yield_3M'] = merged['Treasury_Yield_3M'].fillna(0.03)
        
        # 5. Calculate Volatility Risk Premium (VRP) spread and z-score
        # VRP = IV_ATM - RV_YZ
        merged['VRP'] = merged['IV_ATM_30'] - merged['RV_YZ_20']
        
        # Calculate 252-day rolling mean and std of VRP
        merged['VRP_mean_252'] = merged['VRP'].rolling(window=252, min_periods=20).mean().ffill().bfill()
        merged['VRP_std_252'] = merged['VRP'].rolling(window=252, min_periods=20).std().ffill().bfill()
        
        # Calculate Normalized VRP z-score
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
        if os.path.exists(cache_path):
            try:
                return pl.read_parquet(cache_path)
            except Exception as e:
                print(f"Options chain cache read error for {trade_date}: {e}. Reloading.")

        if self.is_mock:
            raise RuntimeError("DataLoader is in mock/offline mode, which is disabled.")
            
        # Implement robust retry loop around ThetaData connection and querying
        import time
        max_retries = 5
        backoff = 2.0
        
        for attempt in range(1, max_retries + 1):
            try:
                client = self.get_client()
                if client is None:
                    raise RuntimeError("ThetaClient is not initialized")
                    
                from thetadata import OptionReqType, OptionRight, DateRange
                
                # 1. Fetch expirations using REST
                expirations = client.get_expirations_REST(ticker)
                
                # Find closest expiration to target_dte
                target_expiry = trade_date + timedelta(days=target_dte)
                exp_dates = []
                for e in expirations:
                    if hasattr(e, 'to_pydatetime'):
                        exp_dates.append(e.to_pydatetime().date())
                    elif hasattr(e, 'date'):
                        exp_dates.append(e.date())
                    else:
                        exp_dates.append(e)
                
                selected_expiry = min(exp_dates, key=lambda d: abs(d - target_expiry))
                
                # 2. Load stock price to filter strikes (faster)
                filepath = os.path.join(self.data_dir, f"{ticker}_daily.parquet")
                stock_close = 200.0
                if os.path.exists(filepath):
                    stock_db = pd.read_parquet(filepath)
                    stock_db['Date'] = pd.to_datetime(stock_db['Date']).dt.date
                    day_row = stock_db[stock_db['Date'] == trade_date]
                    if not day_row.empty:
                        stock_close = float(day_row['Close'].values[0])
                    else:
                        stock_close = float(stock_db.iloc[-1]['Close'])
                
                # 3. Fetch strikes using REST
                strikes = client.get_strikes_REST(ticker, selected_expiry)
                
                # Filter strikes within 80% to 120% of stock price to reduce calls
                filtered_strikes = [float(s) for s in strikes if 0.8 * stock_close <= float(s) <= 1.2 * stock_close]
                
                # 4. Fetch EOD quotes for calls in parallel (4 concurrent REST API calls)
                from concurrent.futures import ThreadPoolExecutor, as_completed
                records = []
                
                def fetch_strike_data(strike):
                    try:
                        df = client.get_hist_option_REST(
                            req=OptionReqType.EOD_QUOTE_GREEKS,
                            root=ticker,
                            exp=selected_expiry,
                            strike=strike,
                            right=OptionRight.CALL,
                            date_range=DateRange(trade_date, trade_date)
                        )
                        if df is not None and not df.empty:
                            row = df.iloc[0]
                            row_dict = {col.name.lower() if hasattr(col, 'name') else str(col).lower(): val for col, val in row.items()}
                            
                            strike_code = f"{int(strike * 1000):08d}"
                            osi_symbol = f"{ticker}{selected_expiry.strftime('%y%m%d')}C{strike_code}"
                            
                            return {
                                'symbol': osi_symbol,
                                'right': 'C',
                                'strike': strike,
                                'expiry': selected_expiry.strftime("%Y-%m-%d"),
                                'bid': float(row_dict.get('bid', 0)),
                                'ask': float(row_dict.get('ask', 0)),
                                'delta': float(row_dict.get('delta', 0.5)),
                                'implied_volatility': float(row_dict.get('implied_vol', 0.5)),
                                'open_interest': int(row_dict.get('open_interest', 1000)) if 'open_interest' in row_dict else 1000,
                                'volume': int(row_dict.get('volume', 150)) if 'volume' in row_dict else 150
                            }
                    except Exception:
                        pass
                    return None

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {executor.submit(fetch_strike_data, strike): strike for strike in filtered_strikes}
                    for future in as_completed(futures):
                        res = future.result()
                        if res is not None:
                            records.append(res)
                            
                if not records:
                    raise RuntimeError("No records returned from options chain query")
                    
                df_pl = pl.DataFrame(records)
                try:
                    df_pl.write_parquet(cache_path)
                except Exception as cache_err:
                    print(f"Failed to cache options chain: {cache_err}")
                return df_pl
                
            except Exception as e:
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
        
        from thetadata import OptionRight, OptionReqType, DateRange
        right = OptionRight.CALL if option_symbol[cp_idx] == 'C' else OptionRight.PUT

        cache_path = os.path.join(self.cache_dir, f"{option_symbol}.parquet")
        
        # Check if cache covers requested range
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
                    
                    if min_cached <= start_date and (max_cached >= end_date or max_cached >= expiry_date):
                        # Cache covers requested date range, return it directly
                        df = df.with_columns(pl.Series("date", parsed_dates))
                        return df.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))
            except Exception as cache_err:
                print(f"Cache read error for {option_symbol}: {cache_err}. Reloading from source.")

        if self.is_mock:
            raise RuntimeError("DataLoader is in mock/offline mode, which is disabled.")
            
        # Fetch all history up to the day before expiry date to avoid the server-side Greeks timeout on expiration day (DTE=0)
        # Cap at yesterday to avoid querying future dates that do not exist yet on the server
        fetch_end_date = min(expiry_date - timedelta(days=1), date.today() - timedelta(days=1))
        
        # Check if the requested range overlaps with known TSLA options data gaps on ThetaData (2026-01-20 and 2026-01-21)
        has_gap = False
        for gap_date in [date(2026, 1, 20), date(2026, 1, 21)]:
            if start_date <= gap_date <= fetch_end_date:
                has_gap = True
                break
        
        client = self.get_client()
        if client is not None:
            # Attempt 1: Fetch the entire range in one call using REST
            if not has_gap:
                try:
                    df = client.get_hist_option_REST(
                        req=OptionReqType.EOD_QUOTE_GREEKS,
                        root=root,
                        exp=expiry_date,
                        strike=strike,
                        right=right,
                        date_range=DateRange(start_date, fetch_end_date)
                    )
                    
                    df.columns = [col.name.lower() if hasattr(col, 'name') else str(col).lower() for col in df.columns]
                    
                    if 'implied_vol' in df.columns:
                        df = df.rename(columns={'implied_vol': 'implied_volatility'})
                    if 'date' in df.columns:
                        df['date'] = pd.to_datetime(df['date']).dt.date
                    if 'open_interest' not in df.columns:
                        df['open_interest'] = 1000
                    if 'volume' not in df.columns:
                        df['volume'] = 150
                        
                    df_pl = pl.from_pandas(df)
                    if df_pl.height > 0:
                        df_pl.write_parquet(cache_path)
                        return df_pl.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))
                except Exception as e:
                    print(f"Warning: Combined range REST query for {option_symbol} failed/timed out: {e}. Falling back to day-by-day REST queries.")
            else:
                print(f"Skipping combined range query for {option_symbol} due to overlap with known data gaps. Querying day-by-day instead.")
                
            # Attempt 2: Fallback to querying day-by-day in parallel (4 concurrent REST API calls)
            import time
            import numpy as np
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            # Generate calendar dates, skipping known data gap dates
            curr = start_date
            dates = []
            while curr <= fetch_end_date:
                # Only query trading days (weekdays) and skip known gaps
                if curr.weekday() < 5 and curr not in [date(2026, 1, 20), date(2026, 1, 21)]:
                    dates.append(curr)
                curr += timedelta(days=1)
                
            daily_dfs = []
            
            def fetch_day_data(d):
                max_day_retries = 3
                day_backoff = 1.0
                for day_attempt in range(1, max_day_retries + 1):
                    try:
                        day_df = client.get_hist_option_REST(
                            req=OptionReqType.EOD_QUOTE_GREEKS,
                            root=root,
                            exp=expiry_date,
                            strike=strike,
                            right=right,
                            date_range=DateRange(d, d)
                        )
                        if day_df is not None and not day_df.empty:
                            return day_df
                        break
                    except Exception as day_err:
                        if day_attempt == max_day_retries:
                            break
                        sleep_time = day_backoff * (0.8 + 0.4 * np.random.rand())
                        time.sleep(sleep_time)
                        day_backoff *= 2.0
                return None

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(fetch_day_data, d): d for d in dates}
                for future in as_completed(futures):
                    res = future.result()
                    if res is not None:
                        daily_dfs.append(res)
                            
            if not daily_dfs:
                raise RuntimeError(f"Failed to fetch contract history from ThetaData after combined range timeout and day-by-day fallback. Stopping process as requested.")
                
            # Combine all successfully fetched daily dataframes
            combined_df = pd.concat(daily_dfs, ignore_index=True)
            combined_df.columns = [col.name.lower() if hasattr(col, 'name') else str(col).lower() for col in combined_df.columns]
            
            if 'implied_vol' in combined_df.columns:
                combined_df = combined_df.rename(columns={'implied_vol': 'implied_volatility'})
            if 'date' in combined_df.columns:
                combined_df['date'] = pd.to_datetime(combined_df['date']).dt.date
            if 'open_interest' not in combined_df.columns:
                combined_df['open_interest'] = 1000
            if 'volume' not in combined_df.columns:
                combined_df['volume'] = 150
                
            df_pl = pl.from_pandas(combined_df)
            if df_pl.height == 0:
                raise RuntimeError(f"Empty history returned for {option_symbol} from day-by-day fallback.")
                
            df_pl.write_parquet(cache_path)
            return df_pl.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))
            
        raise RuntimeError("DataLoader entered mock mode path in get_option_contract_history, which is disabled.")
