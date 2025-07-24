import pandas as pd
import numpy as np
import yfinance as yf
import requests
from datetime import datetime, timedelta
import time

class CANSLIMScreener:
    def __init__(self, stocks_list, api_key=None):
        self.stocks = stocks_list
        self.api_key = api_key
        self.results = []

    def fetch_financials(self, ticker):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            quarterly_earnings = stock.quarterly_earnings
            annual_earnings = stock.earnings

            q_eps_growth = 0
            if not quarterly_earnings.empty and len(quarterly_earnings) > 1:
                latest_eps = quarterly_earnings['Earnings'].iloc[-1]
                prev_eps = quarterly_earnings['Earnings'].iloc[-2]
                q_eps_growth = ((latest_eps - prev_eps) / abs(prev_eps)) * 100 if prev_eps != 0 else 0

            a_eps_growth = 0
            if not annual_earnings.empty and len(annual_earnings) >= 3:
                eps_values = annual_earnings['Earnings'][-3:]
                annual_growths = [(eps_values[i] - eps_values[i-1]) / abs(eps_values[i-1]) * 100 for i in range(1, len(eps_values))]
                a_eps_growth = np.mean(annual_growths)

            shares_out = info.get('sharesOutstanding', 0)
            institutional_own = info.get('heldPercentInstitutions', 0) * 100

            return {
                'q_eps_growth': q_eps_growth,
                'a_eps_growth': a_eps_growth,
                'shares_out': shares_out,
                'institutional_own': institutional_own,
                'quarterly_earnings': quarterly_earnings
            }
        except Exception:
            return None

    def fetch_price_data(self, ticker, period='1y'):
        try:
            return yf.download(ticker, period=period, progress=False)
        except Exception:
            return pd.DataFrame()

    def check_accelerating_earnings(self, quarterly_earnings):
        if len(quarterly_earnings) < 3:
            return False
        growths = [(quarterly_earnings['Earnings'].iloc[i] - quarterly_earnings['Earnings'].iloc[i-1]) / abs(quarterly_earnings['Earnings'].iloc[i-1]) * 100 for i in range(-2, 0)]
        return growths[-1] > growths[-2] and growths[-1] > 25

    def check_deceleration(self, quarterly_earnings):
        if len(quarterly_earnings) < 3:
            return False
        growths = [(quarterly_earnings['Earnings'].iloc[i] - quarterly_earnings['Earnings'].iloc[i-1]) / abs(quarterly_earnings['Earnings'].iloc[i-1]) * 100 for i in range(-3, 0)]
        return growths[-1] < growths[-2] and growths[-2] < growths[-3] and growths[-1] < 15

    def relative_strength(self, stock_data, market_data):
        if stock_data.empty or market_data.empty:
            return False
        rs = (stock_data['Close'] / market_data['Close']) * 100
        return rs.iloc[-1] > rs.mean()

    def detect_base_on_base(self, data):
        if data.empty:
            return False
        data['pct_change'] = data['Close'].pct_change()
        consolidations = []
        window = 20
        for i in range(window, len(data), window):
            slice_data = data.iloc[i-window:i]
            if max(slice_data['Close']) - min(slice_data['Close']) < 0.15 * min(slice_data['Close']):
                consolidations.append(True)
            else:
                consolidations.append(False)
        return len(consolidations) >= 2 and consolidations[-1] and consolidations[-2]

    def volume_dry_up(self, data):
        if data.empty:
            return False
        pullbacks = data[data['Close'].pct_change() < -0.05]
        if pullbacks.empty:
            return True
        avg_vol = data['Volume'].mean()
        return (pullbacks['Volume'] < avg_vol).all()

    def screen_stock(self, ticker):
        time.sleep(1)
        financials = self.fetch_financials(ticker)
        if financials is None:
            return None

        price_data = self.fetch_price_data(ticker)
        market_data = self.fetch_price_data('^GSPC')

        if financials['q_eps_growth'] < 25 or self.check_deceleration(financials['quarterly_earnings']):
            return None

        if financials['a_eps_growth'] < 25:
            return None

        if price_data.empty or price_data['Close'].iloc[-1] < price_data['Close'].max() * 0.95:
            return None

        if financials['shares_out'] > 200000000:
            return None
        if not self.volume_dry_up(price_data):
            return None

        if not self.relative_strength(price_data, market_data):
            return None

        if financials['institutional_own'] < 30:
            return None

        if market_data.empty or market_data['Close'].iloc[-1] < market_data['Close'].rolling(200).mean().iloc[-1]:
            return None

        has_base_on_base = self.detect_base_on_base(price_data)

        return {
            'ticker': ticker,
            'q_eps_growth': financials['q_eps_growth'],
            'a_eps_growth': financials['a_eps_growth'],
            'shares_out': financials['shares_out'],
            'institutional_own': financials['institutional_own'],
            'has_base_on_base': has_base_on_base
        }

    def run_screener(self):
        for i, ticker in enumerate(self.stocks):
            print(f"Screening {ticker} ({i+1}/{len(self.stocks)})...")
            result = self.screen_stock(ticker)
            if result:
                self.results.append(result)
        return self.results

def get_all_tickers():
    url = 'https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt'
    response = requests.get(url)
    if response.status_code == 200:
        tickers = [line.strip() for line in response.text.splitlines() if line.strip()]
        return list(set(tickers))
    else:
        raise ValueError("Failed to fetch ticker list")

# Example usage: Screen all US stocks
stocks_list = get_all_tickers()
print(f"Fetched {len(stocks_list)} tickers.")
screener = CANSLIMScreener(stocks_list)
results = screener.run_screener()

# Save to CSV
pd.DataFrame(results).to_csv('canslim_results.csv', index=False)
print(f"Results saved to canslim_results.csv. Passing stocks: {len(results)}")