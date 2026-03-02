import pandas as pd
import requests
import matplotlib
# 必須在伺服器環境設定為 Agg
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import numpy as np
import warnings
import io
import time
import os
from tqdm import tqdm

warnings.filterwarnings("ignore")

# 建議將此環境變數設定在系統中，或直接在此輸入 Webhook URL (不建議公開)
DISCORD_WEBHOOK_URL = os.getenv("MY_DISCORD_WEBHOOK")

class BingXStructureHunterV37_CloudFix:
    def __init__(self):
        self.targets = []
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def send_discord_report(self, content):
        if not DISCORD_WEBHOOK_URL: return
        try: requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
        except: pass

    def upload_plot_to_discord(self, fig, symbol, sig_type):
        if not DISCORD_WEBHOOK_URL: return
        try:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=120)
            buf.seek(0)
            payload = {"content": f"🎯 **{symbol}** 結構獵殺信號！"}
            files = {"file": (f"{symbol}.png", buf, "image/png")}
            requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files, timeout=15)
        except Exception as e:
            print(f"Discord 上傳失敗: {e}")

    def get_bingx_symbols(self, count):
        try:
            url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # 篩選 USDT 合約交易對
                all_pairs = [item['symbol'] for item in data['data'] if '-USDT' in item['symbol']]
                # 這裡調整為掃描前 N 個幣種
                self.targets = sorted(all_pairs)[:count]
                return True
            return False
        except: return False

    def fetch_data_bingx(self, symbol, interval='1h', limit=500):
        url = "https://open-api.bingx.com/openApi/swap/v2/quote/klines"
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        try:
            r = self.session.get(url, params=params, timeout=10)
            klines = r.json()['data']
            df_data = []
            for k in klines:
                d = k if isinstance(k, dict) else {'time': k[0], 'open': k[1], 'high': k[2], 'low': k[3], 'close': k[4], 'volume': k[5]}
                df_data.append({'Time': int(d['time']), 'O': float(d['open']), 'H': float(d['high']), 'L': float(d['low']), 'C': float(d['close'])})
            df = pd.DataFrame(df_data)
            df['Time'] = pd.to_datetime(df['Time'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Taipei')
            return df.sort_values('Time').reset_index(drop=True), "OK"
        except: return None, "Err"

    def find_swing_points(self, df, lookback=100):
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
        for i in range(lookback := 10, len(df) - 1):
            curr = df.iloc[i]
            for h in highs:
                if h['index'] < i and i <= h['expiry']:
                    if curr['H'] > h['price']:
                        h['expiry'] = i
                        if curr['C'] <= h['price'] and i >= (last_idx - 20):
                            sigs.append({'idx': i, 'time': curr['Time'], 'type': 'Short', 'price': h['price']})
            for l in lows:
                if l['index'] < i and i <= l['expiry']:
                    if curr['L'] < l['price']:
                        l['expiry'] = i
                        if curr['C'] >= l['price'] and i >= (last_idx - 20):
                            sigs.append({'idx': i, 'time': curr['Time'], 'type': 'Long', 'price': l['price']})
        return sigs

    def visualize_and_upload(self, df, symbol, sigs, highs, lows):
        plt.style.use('dark_background')
        # 只畫最近 200 根以確保 K 線清晰
        plot_df = df.tail(200).copy().reset_index(drop=True)
        time_to_idx = {t: i for i, t in enumerate(plot_df['Time'])}
        
        fig, ax = plt.subplots(figsize=(16, 9))
        
        # --- 手動繪製 K 線圖 ---
        for i in range(len(plot_df)):
            color = '#22c55e' if plot_df['C'].iloc[i] >= plot_df['O'].iloc[i] else '#ef4444'
            ax.vlines(i, plot_df['L'].iloc[i], plot_df['H'].iloc[i], color=color, linewidth=1)
            height = abs(plot_df['C'].iloc[i] - plot_df['O'].iloc[i])
            bottom = min(plot_df['O'].iloc[i], plot_df['C'].iloc[i])
            ax.add_patch(plt.Rectangle((i - 0.3, bottom), 0.6, max(height, 0.0001), color=color))

        # --- 繪製結構虛線 ---
        plot_start_t = plot_df['Time'].iloc[0]
        max_idx = len(plot_df) - 1
        
        for h in highs:
            h_end_t = df.iloc[h['expiry']]['Time']
            if h_end_t < plot_start_t: continue
            start_x = time_to_idx.get(h['time'], 0)
            end_x = time_to_idx.get(h_end_t, max_idx)
            ax.hlines(h['price'], xmin=start_x, xmax=end_x, color='red', linestyle='--', alpha=0.6, linewidth=1.5)

        for l in lows:
            l_end_t = df.iloc[l['expiry']]['Time']
            if l_end_t < plot_start_t: continue
            start_x = time_to_idx.get(l['time'], 0)
            end_x = time_to_idx.get(l_end_t, max_idx)
            ax.hlines(l['price'], xmin=start_x, xmax=end_x, color='cyan', linestyle='--', alpha=0.6, linewidth=1.5)

        # --- 標註信號點 ---
        for s in sigs:
            if s['time'] in time_to_idx:
                idx = time_to_idx[s['time']]
                ax.scatter(idx, plot_df.loc[idx, 'H' if s['type']=='Short' else 'L'], 
                           s=300, edgecolors='#fbbf24', facecolors='none', lw=2, zorder=5)
                ax.text(idx, plot_df.loc[idx, 'H' if s['type']=='Short' else 'L'], " SWEEP!", 
                        color='#fbbf24', fontweight='bold', ha='center', va='bottom' if s['type']=='Short' else 'top')

        ax.set_title(f"{symbol} 1H Structure Hunter", color='white', fontsize=18)
        ax.grid(True, alpha=0.1)
        self.upload_plot_to_discord(fig, symbol, "Sweep")
        plt.close(fig)

if __name__ == "__main__":
    hunter = BingXStructureHunterV37_CloudFix()
    # 這裡修改為 500
    target_count = 500
    if hunter.get_bingx_symbols(target_count):
        print(f"🔍 正在掃描 BingX 前 {len(hunter.targets)} 個交易對...")
        for s in tqdm(hunter.targets):
            df, status = hunter.fetch_data_bingx(s, '1h', 500)
            if df is not None:
                h, l = hunter.find_swing_points(df, 100)
                sigs = hunter.process_liquidity_logic(df, h, l)
                if sigs:
                    hunter.visualize_and_upload(df, s, sigs, h, l)
            
            # 加入極短延遲，保護 API 請求不被封鎖
            time.sleep(0.05)
            
    hunter.send_discord_report(f"✅ 自動掃描作業完成。共掃描 {len(hunter.targets)} 個交易對。")
