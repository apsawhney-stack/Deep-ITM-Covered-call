# Implementation Plan: Architecture Optimization & Multi-Ticker Integration

## Problem Statement
Our current options backtester faces speed, stability, and asset limitations:
1. **Network Latency:** Iterating through 30+ strikes individually per trade day creates heavy HTTP overhead.
2. **Subprocess Instability:** The Java Theta Terminal socket binds (`12000` / `25510`) cause collisions and crashes when running concurrent analysis scripts.
3. **Disk I/O Bottlenecks:** The engine reads cached Parquet files from disk daily, compounding search latency across sweeps.
4. **TSLA Lock-in:** Volatility indicators (VRP) and benchmark routines are hardcoded to TSLA and its respective CBOE volatility index (`^VXTSLA`).

For a detailed analysis of the code lines and anticipated speedups, please refer to the design document: [architecture_optimization_and_multi_ticker_plan.md](file:///Users/aps/.gemini/antigravity/brain/40bec107-7eca-41bc-a38d-db03ae0f5207/architecture_optimization_and_multi_ticker_plan.md).

---

## Open Questions

> [!IMPORTANT]
> ### 1. Ticker Volatility Index Settings
> For stock tickers that do not have a dedicated CBOE Volatility Index (e.g., smaller mid-caps), should the system compute the 30-day ATM implied volatility dynamically from daily ATM option quotes (more accurate but requires downloading), or is the historical volatility scaler (e.g., $1.25 \times \text{RV}_{\text{YZ, 20}}$) sufficient?
>
> ### 2. Pre-Fetching Execution Mode
> Would you prefer the option pre-fetching module to run automatically as a pre-check at the start of the backtester, or should it be a standalone CLI command (e.g., `python main.py --prefetch`) that prepares the cache once before backtesting?

---

## Proposed Changes

### Core Loader and Cache Components

#### [MODIFY] [data_loader.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/data_loader.py)
* **Direct gRPC Client:** Import the new `ThetaClient` from the v3 library. Instantiate the client using `email` and `password` parameters rather than `username`/`passwd`. Remove all environment variables and subprocess handling related to `ThetaTerminal.jar`.
* **In-Memory Caching:** Implement a dictionary-based contract cache (`self.contract_cache = {}`) to prevent reading identical Parquet files from disk repeatedly across parameter sweeps.
* **Bulk Greeks Retrieval:** Rewrite `get_options_chain()` to make a single call to `option_history_greeks_all()` with `strike="*"` and `strike_range=15`.
* **Volatility Index Map:** Implement a lookup table mapping stock symbols to their respective CBOE volatility indices (e.g., `^VXTSLA`, `^VXAPL`, `^VXMSFT`, `^VXNVD`, `^VIX`).

---

### Execution and Benchmark Components

#### [MODIFY] [engine.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/backtester/engine.py)
* **Polars Performance:** Refactor the row iteration loop in `run_backtest()` to read daily data as a Polars dictionary/list of tuples instead of using Pandas `.iterrows()`.
* **Universal Ticker Rules:** Update position logger calls and console printing to remove hardcoded "TSLA" references and replace them with `self.asset`.

#### [MODIFY] [main.py](file:///Users/aps/projects/Deep%20ITM%20Covered%20Call/main.py)
* **gRPC Connection:** Remove the legacy `with client.connect():` block wrapping the execution, as connections are now handled directly by the gRPC client.
* **Universal Labels:** Parameterize chart titles, plot legends, print tables, and console outputs to dynamically reference the config-defined `asset`.

---

### New Modules

#### [NEW] `scratch/prefetch_option_data.py`
* Create a dedicated pre-fetching utility. This script reads the configuration and stock database, simulates the daily entry/roll trigger dates, and batch-downloads the required options chain and contract data to populate the cache directory.

---

## Verification Plan

### Automated Verification
* Run the pre-fetcher script to download a cache slice for a specific ticker (e.g., `AAPL`).
* Run a single AAPL backtest cycle in offline/mock mode to verify that the loader successfully completes without any live server connections.
* Compare execution times of the mock-cached run against the live-connection run to measure latency reductions.

### Manual Verification
* Run the full parameter sweep grid search offline and verify that `results/backtest_results.csv` and `results/equity_curves.png` are correctly compiled and formatted with ticker-generic labels.

---

## Solution Hypothesis
1. **gRPC Migration:** Bypassing `ThetaTerminal.jar` eliminates session collision errors (`INVALID_SESSION_ID`) and allows diagnostic scripts to run concurrently without causing socket lockout.
2. **Wildcard Greeks Query:** Requesting all strikes in a single batch call reduces HTTP round-trip overhead by $\approx 95\%$ per roll date.
3. **In-Memory Caching:** Storing parsed dataframes in RAM removes disk I/O latency, leading to an estimated 5x to 10x local speedup.
4. **Pre-fetching:** Isolating options retrieval into a pre-fetch step lets the main sweeps execute entirely offline in milliseconds, protected from server-side throttles.
5. **Universal Index Registry:** Mapping tickers to specific volatility proxies and calculating fallback IV from EOD quotes generalizes the backtester for any liquid asset.
