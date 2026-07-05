from flask import Flask, jsonify
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
 
app = Flask(__name__)
NY_TZ = pytz.timezone('America/New_York')
 
def get_data(interval, period):
    ticker = yf.Ticker("^DJI")
    df = ticker.history(period=period, interval=interval)
    df.columns = [c.lower() for c in df.columns]
    return df
 
def get_sp500(interval, period):
    ticker = yf.Ticker("^GSPC")
    df = ticker.history(period=period, interval=interval)
    df.columns = [c.lower() for c in df.columns]
    return df
 
def find_fvg(df):
    fvgs = []
    for i in range(1, len(df)-1):
        if df['low'].iloc[i+1] > df['high'].iloc[i-1]:
            fvgs.append({
                'type': 'bullish',
                'top': round(float(df['low'].iloc[i+1]), 1),
                'bottom': round(float(df['high'].iloc[i-1]), 1)
            })
        if df['high'].iloc[i+1] < df['low'].iloc[i-1]:
            fvgs.append({
                'type': 'bearish',
                'top': round(float(df['low'].iloc[i-1]), 1),
                'bottom': round(float(df['high'].iloc[i+1]), 1)
            })
    return fvgs[-3:] if fvgs else []
 
def find_ob(df):
    obs = []
    for i in range(1, len(df)-1):
        if df['close'].iloc[i] < df['open'].iloc[i]:
            if df['close'].iloc[i+1] > df['high'].iloc[i]:
                obs.append({
                    'type': 'bullish',
                    'top': round(float(df['high'].iloc[i]), 1),
                    'bottom': round(float(df['low'].iloc[i]), 1)
                })
        if df['close'].iloc[i] > df['open'].iloc[i]:
            if df['close'].iloc[i+1] < df['low'].iloc[i]:
                obs.append({
                    'type': 'bearish',
                    'top': round(float(df['high'].iloc[i]), 1),
                    'bottom': round(float(df['low'].iloc[i]), 1)
                })
    return obs[-3:] if obs else []
 
def find_liquidity(df):
    highs = []
    lows = []
    for i in range(2, len(df)-2):
        if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i+1]:
            highs.append(round(float(df['high'].iloc[i]), 1))
        if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i+1]:
            lows.append(round(float(df['low'].iloc[i]), 1))
    return {
        'highs': highs[-3:] if highs else [],
        'lows': lows[-3:] if lows else []
    }
 
def get_direction(df_1d):
    last = df_1d.iloc[-1]
    prev = df_1d.iloc[-2]
    if last['close'] > prev['high']:
        return 'BULLISH'
    elif last['close'] < prev['low']:
        return 'BEARISH'
    elif last['close'] > last['open']:
        return 'BULLISH'
    else:
        return 'BEARISH'
 
def detect_cisd(df):
    for i in range(2, len(df)):
        if df['close'].iloc[i-2] < df['open'].iloc[i-2]:
            if df['close'].iloc[i-1] > df['open'].iloc[i-1]:
                cisd_level = float(df['open'].iloc[i])
                if df['close'].iloc[i] > cisd_level:
                    return {
                        'type': 'BUY',
                        'level': round(cisd_level, 1),
                        'entry': round(float(df['close'].iloc[i]), 1)
                    }
        if df['close'].iloc[i-2] > df['open'].iloc[i-2]:
            if df['close'].iloc[i-1] < df['open'].iloc[i-1]:
                cisd_level = float(df['open'].iloc[i])
                if df['close'].iloc[i] < cisd_level:
                    return {
                        'type': 'SELL',
                        'level': round(cisd_level, 1),
                        'entry': round(float(df['close'].iloc[i]), 1)
                    }
    return None
 
def detect_sharp_turn(df):
    for i in range(2, len(df)):
        if float(df['low'].iloc[i]) > float(df['high'].iloc[i-2]):
            return {
                'type': 'BUY',
                'entry': round(float(df['close'].iloc[i]), 1),
                'fvg_top': round(float(df['low'].iloc[i]), 1),
                'fvg_bottom': round(float(df['high'].iloc[i-2]), 1)
            }
        if float(df['high'].iloc[i]) < float(df['low'].iloc[i-2]):
            return {
                'type': 'SELL',
                'entry': round(float(df['close'].iloc[i]), 1),
                'fvg_top': round(float(df['low'].iloc[i-2]), 1),
                'fvg_bottom': round(float(df['high'].iloc[i]), 1)
            }
    return None
 
def check_smt(df_dji, df_sp500):
    try:
        dji_low = df_dji['low'].iloc[-5:].min()
        sp_low = df_sp500['low'].iloc[-5:].min()
        dji_prev = df_dji['low'].iloc[-10:-5].min()
        sp_prev = df_sp500['low'].iloc[-10:-5].min()
        if sp_low < sp_prev and dji_low > dji_prev:
            return True
        if dji_low < dji_prev and sp_low > sp_prev:
            return True
    except:
        pass
    return False
 
def find_sl(df, direction):
    if direction == 'BUY':
        return round(float(df['low'].iloc[-10:].min()), 1)
    else:
        return round(float(df['high'].iloc[-10:].max()), 1)
 
def generate_chart(df_1h, levels_1d, levels_4h, levels_1h, direction):
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')
 
    df = df_1h.tail(60).reset_index(drop=True)
 
    for i in range(len(df)):
        color = '#26a69a' if float(df['close'].iloc[i]) >= float(df['open'].iloc[i]) else '#ef5350'
        ax.plot([i, i], [float(df['low'].iloc[i]), float(df['high'].iloc[i])],
                color=color, linewidth=0.8)
        ax.add_patch(plt.Rectangle(
            (i - 0.3, min(float(df['open'].iloc[i]), float(df['close'].iloc[i]))),
            0.6,
            abs(float(df['close'].iloc[i]) - float(df['open'].iloc[i])),
            color=color
        ))
 
    for fvg in levels_1d.get('fvgs', []):
        ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.15, color='#FFD700')
        ax.text(len(df)-1, fvg['top'], 'D1 FVG', color='#FFD700', fontsize=6, ha='right')
 
    for ob in levels_4h.get('obs', []):
        color = '#00BFFF' if ob['type'] == 'bullish' else '#FF69B4'
        ax.axhspan(ob['bottom'], ob['top'], alpha=0.15, color=color)
        ax.text(len(df)-1, ob['top'], '4H OB', color=color, fontsize=6, ha='right')
 
    for fvg in levels_1h.get('fvgs', []):
        ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.2, color='#9370DB')
        ax.text(len(df)-1, fvg['top'], '1H FVG', color='#9370DB', fontsize=6, ha='right')
 
    for h in levels_1h.get('liquidity', {}).get('highs', []):
        ax.axhline(y=h, color='#FF6347', linewidth=0.8, linestyle=':')
    for l in levels_1h.get('liquidity', {}).get('lows', []):
        ax.axhline(y=l, color='#7CFC00', linewidth=0.8, linestyle=':')
 
    dir_color = '#26a69a' if direction == 'BULLISH' else '#ef5350'
    price_range = float(df['high'].max()) - float(df['low'].min())
    ax.text(2, float(df['high'].max()) - price_range * 0.05,
            f'DIRECTION: {direction}', color=dir_color, fontsize=12, fontweight='bold')
 
    ax.set_title('US30 — 1H Analysis', color='white', fontsize=14)
    ax.tick_params(colors='white')
    for spine in ['bottom', 'left']:
        ax.spines[spine].set_color('#444')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
 
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#1a1a2e', dpi=150)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()
    return img_b64
 
 
@app.route('/analysis', methods=['GET'])
def analysis():
    try:
        df_1d = get_data('1d', '60d')
        df_4h = get_data('4h', '60d')
        df_1h = get_data('1h', '30d')
 
        direction = get_direction(df_1d)
 
        levels_1d = {
            'fvgs': find_fvg(df_1d),
            'obs': find_ob(df_1d),
            'liquidity': find_liquidity(df_1d)
        }
        levels_4h = {
            'fvgs': find_fvg(df_4h),
            'obs': find_ob(df_4h),
            'liquidity': find_liquidity(df_4h)
        }
        levels_1h = {
            'fvgs': find_fvg(df_1h),
            'obs': find_ob(df_1h),
            'liquidity': find_liquidity(df_1h)
        }
 
        chart = generate_chart(df_1h, levels_1d, levels_4h, levels_1h, direction)
 
        d1_liq = levels_1d['liquidity']
        current_price = round(float(df_1h['close'].iloc[-1]), 1)
 
        text = f"""📊 US30 PRE-SESSION ANALYSIS
━━━━━━━━━━━━━━━━━━━━
🗓 {datetime.now(NY_TZ).strftime('%Y-%m-%d')}
💰 Current Price: {current_price}
🧭 Direction: {'🟢 BULLISH' if direction == 'BULLISH' else '🔴 BEARISH'}
 
📅 D1 Key Levels:
  Liquidity Above: {max(d1_liq['highs']) if d1_liq['highs'] else 'N/A'}
  Liquidity Below: {min(d1_liq['lows']) if d1_liq['lows'] else 'N/A'}
  FVGs: {len(levels_1d['fvgs'])} identified
  OBs: {len(levels_1d['obs'])} identified
 
📊 4H Key Levels:
  FVGs: {len(levels_4h['fvgs'])} identified
  OBs: {len(levels_4h['obs'])} identified
  Liquidity Highs: {len(levels_4h['liquidity']['highs'])}
  Liquidity Lows: {len(levels_4h['liquidity']['lows'])}
 
⏱ 1H Key Levels:
  FVGs: {len(levels_1h['fvgs'])} identified
  OBs: {len(levels_1h['obs'])} identified
 
⏳ Waiting for NY session 9:35 AM...
━━━━━━━━━━━━━━━━━━━━"""
 
        return jsonify({
            'status': 'ok',
            'type': 'analysis',
            'text': text,
            'chart': chart,
            'direction': direction
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
 
 
@app.route('/scan', methods=['GET'])
def scan():
    try:
        now_ny = datetime.now(NY_TZ)
        hour = now_ny.hour
        minute = now_ny.minute
 
        if not ((hour == 9 and minute >= 35) or
                (hour == 10) or
                (hour == 11 and minute <= 50)):
            return jsonify({'status': 'ok', 'signal': None,
                            'message': 'Outside trading window'})
 
        df_1m = get_data('1m', '1d')
        df_5m = get_data('5m', '5d')
        df_sp500 = get_sp500('1m', '1d')
 
        cisd = detect_cisd(df_1m.tail(20))
        st = detect_sharp_turn(df_5m.tail(20))
        smt = check_smt(df_1m, df_sp500)
 
        signal = None
        if cisd:
            sl = find_sl(df_1m.tail(10), cisd['type'])
            sl_dist = round(abs(cisd['entry'] - sl), 1)
            tp = round(cisd['entry'] + (sl_dist * 2), 1) if cisd['type'] == 'BUY' \
                else round(cisd['entry'] - (sl_dist * 2), 1)
            signal = {
                'pattern': 'CISD',
                'type': cisd['type'],
                'entry': cisd['entry'],
                'sl': sl,
                'tp': tp,
                'sl_distance': sl_dist,
                'smt': smt
            }
        elif st:
            sl = find_sl(df_5m.tail(10), st['type'])
            sl_dist = round(abs(st['entry'] - sl), 1)
            tp = round(st['entry'] + (sl_dist * 2), 1) if st['type'] == 'BUY' \
                else round(st['entry'] - (sl_dist * 2), 1)
            signal = {
                'pattern': 'SHARP_TURN',
                'type': st['type'],
                'entry': st['entry'],
                'sl': sl,
                'tp': tp,
                'sl_distance': sl_dist,
                'smt': smt
            }
 
        if signal:
            direction = '🟢 BUY' if signal['type'] == 'BUY' else '🔴 SELL'
            text = f"""🎯 ENTRY SIGNAL — US30
━━━━━━━━━━━━━━━━━━━━
⏰ {now_ny.strftime('%H:%M')} NY Time
📍 Pattern: {signal['pattern']}
{direction}
Entry: {signal['entry']}
SL: {signal['sl']} ({signal['sl_distance']} pts)
TP: {signal['tp']} (1:2 RRR)
SMT: {'✅ Confirmed' if signal['smt'] else '➖ Not detected'}
━━━━━━━━━━━━━━━━━━━━
⚠️ Verify manually before trading"""
 
            return jsonify({'status': 'ok', 'signal': signal, 'text': text})
 
        return jsonify({'status': 'ok', 'signal': None, 'message': 'No signal'})
 
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
 
 
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'time': datetime.now(NY_TZ).strftime('%H:%M NY')})
 
 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
