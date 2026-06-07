# Deep ITM Covered Call Backtester Checklist: Performance Optimization & Relaunch

- `[ ]` Refactor `backtester/data_loader.py` to use stateless REST API (`_REST` methods) and implement 4-way parallel thread pools (`ThreadPoolExecutor(max_workers=4)`) for strike chain and daily fallback queries.
- `[ ]` Modify `main.py` to wrap the sweep loops inside a single persistent socket terminal connection block.
- `[ ]` Reconstruct `results/backtest_results.csv` with DTE=15 and DTE=30 completed runs to implement checkpoint-resume.
- `[ ]` Run and verify the sweeps for DTE=45 and DTE=7, keeping DTE=15 and DTE=30 skipped.
- `[ ]` Launch `code_reviewer` subagent to verify no regressions against the strategy specification/architecture plan.
- `[ ]` Update `walkthrough.md` with final results.
