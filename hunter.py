import pandas as pd
import requests
import matplotlib
# 必須在 import pyplot 之前設定，確保在無螢幕伺服器（GitHub Actions）能正常繪圖
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import numpy as np
import warnings
import io
import time
import json
import os  # 新增：用於讀取環境變數
from tqdm import tqdm # 移除 .notebook，因為 Actions 環境使用標準終端機

warnings.filterwarnings("ignore")

# --- Discord 配置 ---
# 修改點：從 GitHub Secrets 讀取網址，保護你的隱私安全
DISCORD_WEBHOOK_URL = os.getenv("MY_DISCORD_WEBHOOK")

class BingXStructureHunterV37_CloudFix:
    def __init__(self):
        self.targets = []
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def send_discord_report(self, content):
        # 如果環境變數沒設定，則不執行發送
        if not DISCORD_WEBHOOK_URL:
            print("⚠️ 未檢測到環境變數 MY_DISCORD_WEBHOOK，跳過 Discord 報告")
            return
        try: 
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
        except: 
            pass

    def upload_plot_to_discord(self, fig, symbol, sig_type):
        if not DISCORD_WEBHOOK_URL:
            return
        try:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
            buf.seek(0)
            payload = {"content": f"🎯 **{symbol}** 獵殺信號觸發！ ({sig_type})"}
            files = {"file": (f"{symbol}_analysis.png", buf, "image/png")}
            requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files, timeout=15)
            time.sleep(1.5)
        except Exception as e:
            print(f"Discord 上傳失敗: {e}")

    # ... [中間 get_bingx_symbols, fetch_data_bingx 等函數保持不變] ...
    # (為了節省篇幅，此處省略你原本沒變動的 API 請求與數據處理邏輯，請確保保留在你原本的文件中)

    def get_bingx_symbols(self, count):
        try:
            url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data['code'] == 0:
                    all_pairs = [item['symbol'] for item in data['data'] if '-USDT' in item['symbol']]
                    self.targets = sorted(all_pairs)[:count]
                    return True
            return False
        except:
            return False

    def fetch_data_bingx(self, symbol, interval='1h', limit=500):
        url = "https://open-api.bingx.com/openApi/swap/v2/quote/klines"
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        try:
            r = self.session.get(url, params=params, timeout=10)
            if r.status_code != 200: return None, f"HTTP {r.status_code}"
            data = r.json()
            if data['code'] != 0 or not data.get('data'): return None, "無數據"
            klines = data['data']
            df_data = []
            for k in klines:
                df_data.append({
                    'Time': int(k[0] if isinstance(k, list) else k['time']),
                    'O': float(k[1] if isinstance(k, list) else k['open']),
                    'H': float(k[2] if isinstance(k, list) else k['high']),
                    'L': float(k[3] if isinstance(k, list) else k['low']),
                    'C': float(k[4] if isinstance(k, list) else k['close']),
                    'V': float(k[5] if isinstance(k, list) else k['volume'])
                })
            df = pd.DataFrame(df_data)
            df['Time'] = pd.to_datetime(df['Time'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Taipei')
            return df.sort_values('Time').reset_index(drop=True), "成功"
        except Exception as e: return None, str(e)

    def find_swing_points(self, df, lookback):
        highs, lows = [], []
        if len(df) < lookback * 2 + 1: return [], []
        h_vals, l_vals = df['H'].values, df['L'].values
        last_idx = len(df) - 1
        for i in range(lookback, len(df) - lookback):
            if h_vals[i] == h_vals[i-lookback : i+lookback+1].max():
                highs.append({'index': i, 'price': h_vals[i], 'time': df['Time'].iloc[i], 'expiry': last_idx})
            if l_vals[i] == l_vals[i-lookback : i+lookback+1].min():
                lows.append({'index': i, 'price': l_vals[i], 'time': df['Time'].iloc[i], 'expiry': last_idx})
        return highs, lows

    def process_liquidity_logic(self, df, highs, lows):
        sigs = []
        last_idx = len(df) - 1
        for i in range(1, len(df) - 1):
            curr, nxt = df.iloc[i], df.iloc[i+1]
            for h in highs:
                if h['index'] < i and i <= h['expiry']:
                    if curr['H'] > h['price']:
                        h['expiry'] = i
                        if curr['C'] <= h['price'] and i >= (last_idx - 30):
                            sigs.append({'時間': curr['Time'], '信號': '看空獵殺', '結構價': h['price']})
            for l in lows:
                if l['index'] < i and i <= l['expiry']:
                    if curr['L'] < l['price']:
                        l['expiry'] = i
                        if curr['C'] >= l['price'] and i >= (last_idx - 30):
                            sigs.append({'時間': curr['Time'], '信號': '看多獵殺', '結構價': l['price']})
        return sigs

    def visualize_and_upload(self, df, symbol, sigs, highs, lows, interval):
        plt.style.use('dark_background')
        plot_df = df.tail(300).copy().reset_index(drop=True)
        time_to_idx = {t: i for i, t in enumerate(plot_df['Time'])}
        x_range = np.arange(len(plot_df))
        
        fig, ax1 = plt.subplots(figsize=(15, 8))
        ax1.vlines(x_range, plot_df['L'], plot_df['H'], color='#ffffff', alpha=0.3)
        ax1.plot(x_range, plot_df['C'], color='#ffffff', alpha=0.9, linewidth=1.2)

        plot_start_time = plot_df['Time'].iloc[0]
        # 繪製線條... [省略詳細繪圖代碼，請保留你原本的邏輯]
        # 注意：最後記得使用 fig.savefig 而非 plt.show()
        
        self.upload_plot_to_discord(fig, symbol, "Structure Hunt")
        plt.close(fig)

# --- 執行進入點 (適合 GitHub Actions) ---
if __name__ == "__main__":
    hunter = BingXStructureHunterV37_CloudFix()
    if hunter.get_bingx_symbols(100): # 測試先跑 100 個防止 Actions 跑太久
        print(f"🔍 掃描開始...")
        for s in tqdm(hunter.targets):
            df, status = hunter.fetch_data_bingx(s, '1h', 500)
            if df is not None:
                h, l = hunter.find_swing_points(df, 100)
                sigs = hunter.process_liquidity_logic(df, h, l)
                if sigs:
                    print(f"🎯 發現信號: {s}")
                    hunter.visualize_and_upload(df, s, sigs, h, l, '1h')
    hunter.send_discord_report("✅ 每小時自動掃描完成")
