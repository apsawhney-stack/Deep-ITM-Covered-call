# ThetaData Architectural Optimization & Multi-Ticker Integration Plan

## 1. Problem Statement

Our options strategy backtester currently faces three primary limitations:
1. **Execution Bottlenecks & Network Overhead:** Retrieving options chains EOD pricing and Greeks is highly sequential. For every roll date, the backtester makes up to 30+ separate HTTP REST requests (one per strike) to retrieve the required quotes. During a 2-year daily backtest with multiple parameter sweeps, this causes significant network-bound latency.
2. **Subprocess Instability & Connection Lockout:** The backtester depends on a local Java `ThetaTerminal.jar` process running in the background. The terminal binds to local sockets (port `12000` for socket, `25510` for REST). If any other script (such as an offline diagnostic tool) attempts to query data or access the port, the connection is dropped, socket collisions occur, and the main backtest sweep crashes.
3. **Ticker Hardcoding:** The system is built specifically for `TSLA`. The Volatility Risk Premium (VRP) calculation is hardcoded to retrieve the CBOE Tesla Volatility Index (`^VXTSLA`) from Yahoo Finance, and visual/log labels are hardcoded. This prevents testing other assets.
4. **Disk I/O Latency:** Although options data is cached locally as Parquet files to avoid re-downloading, the engine reads these files from disk daily for active contracts, leading to thousands of disk reads per grid search sweep.

---

## 2. Current Codebase Analysis

Our codebase is divided into four main modules under [backtester/](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester):
1. [data_loader.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py): Handles credential checks, stock/macro downloads (via yfinance), option chain downloads, and individual contract EOD history fetches. It manages the connection to a local `ThetaTerminal.jar` instance.
2. [engine.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/engine.py): Executes the daily backtest event loop. For every day, it checks stop-losses, rolls, assignments, trend regimes, and writes calls by calling `data_loader` methods.
3. [positions.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/positions.py): Tracks portfolio state (shares, cash, equity curves, slippage calculations, high-water-mark sweeps).
4. [main.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/main.py): Runs the parameter sweep grid search sequentially and compiles final comparison metrics/charts against benchmarks.

---

## 3. Implementation of the 4 Performance Points

### A. Migration to v3 Direct gRPC Client (No Java Terminal)
* **Objective:** Eliminate the `ThetaTerminal.jar` subprocess and local HTTP/socket server entirely. Run client queries directly to ThetaData servers using their new gRPC Python client.
* **Code Changes:**
  * **[data_loader.py: Line 8](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py#L8):** Change import from `from thetadata import ThetaClient` to the new `thetadata` client structure.
  * **[data_loader.py: Lines 40-54](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py#L40-L54) (`get_client`):** Rewrite to instantiate the new direct client:
    ```python
    self.client = ThetaClient(email=self.email, password=self.password)
    ```
    Remove the Java bin environment path configurations and subprocess handlers.
  * **[main.py: Line 121](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/main.py#L121):** Remove the `with client.connect():` context manager wrapper as the new client connects directly over gRPC on demand.

### B. Bulk Options Chain Retrieval (Strike `*` Wildcards)
* **Objective:** Fetch all strikes for a given expiration on a date in a single request.
* **Code Changes:**
  * **[data_loader.py: Lines 238-374](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py#L238-L374) (`get_options_chain`):** Replace the strike loop and `ThreadPoolExecutor` with a single direct call utilizing a wildcard strike parameter:
    ```python
    # In v3 direct client, request all strikes at once for the date and expiration
    df = self.client.option_history_greeks_all(
        symbol=ticker,
        expiration=selected_expiry,
        date=trade_date,
        strike="*",
        right="call"
    )
    ```
    This single request retrieves a table of all strikes. We filter it locally using Polars.

### C. Pre-Fetching and Offline Mock Mode
* **Objective:** Allow the grid sweep search to run $100\%$ offline.
* **Code Changes:**
  * **[NEW] `scratch/prefetch_option_data.py`:** Create a script that sweeps the date database using the same logic as `engine.py` (stock price vs 50-EMA, VRP z-score) to determine what expirations and strikes the strategy will roll into.
  * This script queries ThetaData in bulk for those specific contracts and caches them in `data/cache/`.
  * **[data_loader.py: Line 11](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py#L11):** Set `self.is_mock = True` during main runs. In mock mode, if a contract or chain is not found in `data/cache/`, throw a detailed error rather than calling the live API.

### D. In-Memory Caching & Polars Optimization
* **Objective:** Prevent repeated disk reads of cached Parquet files and optimize data traversal.
* **Code Changes:**
  * **[data_loader.py: Line 11](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py#L11):** Introduce an in-memory dictionary cache `self.contract_cache = {}` inside `DataLoader`.
  * **[data_loader.py: Lines 407-427](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py#L407-L427) (`get_option_contract_history`):** Before reading the Parquet file from disk, check if it's already in `self.contract_cache`. If not, read it once, store it in the dictionary, and return.
  * **[engine.py: Lines 244-637](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/engine.py#L244-L637) (`run_backtest`):** Instead of looping using Pandas `.iterrows()`, load the daily database into Polars, convert it to a Python list of namedtuples (`df.to_dicts()`), and loop.

---

## 4. Roadmap for Multi-Ticker Extension

Currently, the backtester is optimized for `TSLA`. To generalize the system for any equity ticker (e.g., `AAPL`, `MSFT`, `NVDA`, `SPY`), we must implement the following changes:

### A. Volatility Index Mapping (IV Proxy)
The VRP filter requires a 30-day ATM implied volatility index. We will add a mapping system in `data_loader.py` that maps stock tickers to their corresponding CBOE Volatility Index on Yahoo Finance:

| Stock Ticker | CBOE Volatility Index |
| :--- | :--- |
| **TSLA** | `^VXTSLA` |
| **AAPL** | `^VXAPL` |
| **MSFT** | `^VXMSFT` |
| **AMZN** | `^VXAZN` |
| **NVDA** | `^VXNVD` |
| **GOOG** | `^VXGOG` |
| **META** | `^VXMTA` |
| **SPY** | `^VIX` |
| **QQQ** | `^VXN` |
| **IWM** | `^RVX` |

### B. General Volatility Fallback
For tickers that do not have a dedicated CBOE volatility index, we will implement a dynamic implied volatility proxy in `data_loader.py`:
* **Approach:** If the yfinance download for the designated volatility index returns NaNs or is missing, compute the ATM Implied Volatility directly by querying the EOD quote of the ATM call option from ThetaData for each trading day.
* **Formula Fallback:** If option data is not available, default to the historical volatility scaler:
  $$\text{IV}_{\text{ATM}} = \text{RV}_{\text{YZ, 20}} \times 1.20$$

### C. Parameterizing Labels and Benchmarks
Several hardcoded references in `main.py` must be parameterized:
* **Benchmark Simulation:** Change the Buy & Hold label from "Buy & Hold TSLA" to `f"Buy & Hold {self.asset}"`.
* **Output Graphics:** Update the chart title and legends in `plt.plot` to dynamically insert `config['asset']`.
* **Console Outputs:** Replace strings like `"TSLA Overnight Gap"` with `f"{self.asset} Overnight Gap"`.

### D. Dynamic Option Settings (Chop & Drift Profiles)
Different assets have unique volatility profiles (e.g., `AAPL` has lower volatility than `TSLA`). The baseline parameters in `config.yaml` should be modified to support ticker-specific presets:
* **Vol-Dependent Stop Loss:** Instead of a static $8\%$ stop-loss, define the stop-loss as a function of the stock's 20-day Yang-Zhang volatility:
  $$\text{Stop Loss \%} = \text{RV}_{\text{YZ, 20}} \times 0.25$$
* **DTE Grids:** While highly volatile assets (`TSLA`, `NVDA`) benefit from shorter DTE sweeps (`7`, `15` DTE), stable stocks (`AAPL`, `MSFT`) may perform better with longer DTE overwrites (`30`, `45` DTE). Parameterizing the grid boundaries will allow optimal search configurations per asset.

---

## 5. Solution Hypothesis

We hypothesize that implementing these changes will resolve our core limitations in the following ways:
1. **Direct gRPC Client (Resolves Subprocess Instability):** Connecting directly to ThetaData's remote servers over gRPC eliminates port binding constraints on `127.0.0.1`. **Hypothesis:** Multiple backtesters and diagnostics tools can run concurrently on the same machine without triggering socket collision errors (e.g. `INVALID_SESSION_ID`) or closing active connection pipelines.
2. **Wildcard `strike=*` Queries (Resolves Network Latency):** Querying all strikes for a given DTE expiration in a single request replaces the loop that sends 30 separate HTTP calls. **Hypothesis:** The network overhead of retrieving option chains will drop by $\approx 95\%$, leading to a massive speedup in trading-day rolling calculations.
3. **In-Memory Caching (Resolves Disk I/O Bottlenecks):** Keeping parsed options data in a Python dictionary cache avoids reading cached Parquet files from the physical disk repeatedly during parameter sweeps. **Hypothesis:** Since different sweeps (e.g., different Deltas) query the same contract files, accessing data from RAM will speed up the local execution of the backtester by an estimated 5x to 10x.
4. **Pre-fetching Utility (Resolves Server Throttling):** Pre-downloading the deterministic option history *before* starting the backtest sweep allows the main engine to run completely offline. **Hypothesis:** Offline runs will execute in milliseconds, isolating the backtester from server-side throttles, rate limits, and network latency.
5. **Universal Index Mapping & ATM IV Fallback (Resolves Ticker Hardcoding):** Dynamically mapping tickers to their CBOE Volatility index and introducing an option-derived IV fallback decouples the backtester from `TSLA`. **Hypothesis:** The backtester will be capable of loading, calculating VRP metrics, and running options strategies for any stock ticker listed on major US exchanges.

---

## 6. Hazards & Implementation Considerations

As we transition to these optimized mechanisms, we must account for several implementation hazards:
1. **Memory Exhaustion on Broad Expirations:** Wildcard `strike=*` queries can return extremely large datasets (often thousands of rows of intraday records if not managed).
   * *Mitigation:* We must enforce the `strike_range` parameter (e.g., `strike_range=15`) in the query to limit records to the 31 strikes closest to spot, and set `interval="1d"` to only pull end-of-day quotes rather than high-frequency minute bars.
2. **Corrupted Cache & Stale Files:** If a pre-fetch download session is terminated early, partial files may be written to `data/cache`. The backtester could read incomplete Parquet files and throw errors or generate inaccurate results.
   * *Mitigation:* The pre-fetch utility must implement atomic writes (writing to a temporary file first, then renaming on success) and a validation pass verifying row counts and header schema before caching.
3. **VRP Outliers on Non-Liquid Tickers:** Option-derived implied volatility fallbacks can experience severe price gaps on illiquid underlyings if the ATM mid-price is wide or undefined (bid=0).
   * *Mitigation:* The fallback algorithm must apply a sanity boundary check. If bid/ask midpoint is wide (e.g. spread ratio $>30\%$) or undefined, default to a historical volatility proxy ($1.25 \times \text{RV}_{\text{YZ, 20}}$) with a hard floor of $20\%$ to prevent division-by-zero or calculation blowups.
4. **Account Concurrency Collisions:** Even in gRPC mode, the direct client still consumes account-wide concurrency slots. Multiple parallel pre-fetch threads can easily lock out the account.
   * *Mitigation:* Ensure the pre-fetcher script strictly respects a throttle semaphore limiting concurrent HTTP/gRPC pipelines to 1 below the account maximum.

---

## 7. Verification & Testing Strategy

To ensure zero regression and validate performance, we will implement the following verification strategy:
1. **Historical Regression Parity Test (Zero-Deviation Verification):**
   * *Process:* Take a completed parameter run from the current sweep (e.g., DTE 45, Delta 0.80) that has already logged metrics in `results/backtest_results.csv`.
   * *Verification:* Run the same DTE/Delta backtest using the new gRPC client and Polars loop.
   * *Success Criteria:* The final daily portfolio value series and metrics (CAGR, Sharpe, MaxDD, Win Rate) must match the legacy run **to the penny** (0.00% variance).
2. **Pre-fetch Cache Validation Test:**
   * *Process:* Execute `prefetch_option_data.py` for a new ticker (e.g., `AAPL`) for a 1-month subset.
   * *Verification:* Disconnect network access (or set `self.is_mock = True`) and run the AAPL simulation.
   * *Success Criteria:* The backtest engine must run to completion without making any live server connections, proving the pre-fetch coverage is complete.
3. **Throttling & Backoff Stress Test:**
   * *Process:* Intentionally trigger rate-limiting by setting the pre-fetcher to 10 concurrent threads.
   * *Verification:* Monitor the error logging.
   * *Success Criteria:* The client must successfully catch HTTP `429` responses, apply exponential backoff, retry, and finish the download without crashing.
