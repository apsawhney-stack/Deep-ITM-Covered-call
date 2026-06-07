import os
import sys
from datetime import date
sys.path.append("/Users/aps/projects/Deep ITM Covered Call")
from backtester.data_loader import DataLoader
from thetadata import OptionReqType, OptionRight, DateRange

loader = DataLoader(creds_path="creds.txt")
client = loader.get_client()

with client.connect():
    trade_date = date(2024, 7, 22)
    target_dte = 45
    ticker = "TSLA"
    
    # Get expirations
    expirations = client.get_expirations_REST(ticker)
    target_expiry = trade_date + datetime.timedelta(days=target_dte) if hasattr(datetime, 'timedelta') else trade_date + datetime.date(2024, 1, 2) - datetime.date(2024, 1, 2)
    import datetime
    target_expiry = trade_date + datetime.timedelta(days=target_dte)
    
    exp_dates = []
    for e in expirations:
        if hasattr(e, 'to_pydatetime'):
            exp_dates.append(e.to_pydatetime().date())
        elif hasattr(e, 'date'):
            exp_dates.append(e.date())
        else:
            exp_dates.append(e)
            
    selected_expiry = min(exp_dates, key=lambda d: abs(d - target_expiry))
    print("Trade Date:", trade_date)
    print("Target Expiry Date (Trade Date + 45):", target_expiry)
    print("Selected Expiry Date:", selected_expiry)
    
    # Get strikes
    strikes = client.get_strikes_REST(ticker, selected_expiry)
    print("Number of strikes:", len(strikes))
    print("Sample strikes:", strikes[:10])
    
    # Try to fetch EOD for a single strike
    sample_strike = strikes[len(strikes)//2]
    print("Trying to fetch EOD quote for strike:", sample_strike)
    try:
        df = client.get_hist_option_REST(
            req=OptionReqType.EOD_QUOTE_GREEKS,
            root=ticker,
            exp=selected_expiry,
            strike=sample_strike,
            right=OptionRight.CALL,
            date_range=DateRange(trade_date, trade_date)
        )
        print("Success! DataFrame:")
        print(df)
    except Exception as e:
        print("Failed to fetch:", e)
