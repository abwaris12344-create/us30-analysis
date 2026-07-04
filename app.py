from flask import Flask, jsonify
import pandas as pd
import numpy as np
from tvdatafeed import TvDatafeed, Interval
from datetime import datetime
import pytz
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import io
import base64

app = Flask(__name__)

tv = TvDatafeed()

NY_TZ = pytz.timezone('America/New_York')

def get_data(interval, bars=100):
    interval_map = {
        '1D': Interval.in_daily,
        '4H': Interval.in_4_hour,
        '1H': Interval.in_1_hour,
        '5M': Interval.in_5_minute,
        '1M': Interval.in_1_minute
    }
    df = tv.get_hist(
        symbol='US30',
        exchange='OANDA',
        interval=interval_map[interval],
        n_bars=bars
    )
    return df

def find_fvg(df):
    fvgs = []
    for i in range(1, len(df)-1):
        # Bullish FVG
        if df['low'].iloc[i+1] > df['high'].iloc[i-1]:
            fvgs.append({
                'type': 'bullish',
                'top': df['low'].iloc[i+1],
                'bottom': df['high'].iloc[i-1],
                'index': i
            })
        # Bearish FVG
        if df['high'].iloc[i+1] < df['low'].iloc[i-1]:
            fvgs.append({
                'type': 'bearish',
                'top': df['low'].iloc[i-1],
                'bottom': df['high'].iloc[i+1],
                'index': i
            })
    return fvgs[-3:] if fvgs else []

def find_ob(df):
    obs = []
    for i in range(1, len(df)-1):
        # Bullish OB: last bearish candle before big bullish move
        if df['close'].iloc[i] < df['open'].iloc[i]:
            if df['close'].iloc[i+1] > df['high'].iloc[i]:
                obs.append({
                    'type': 'bullish',
                    'top': df['high'].iloc[i],
                    'bottom': df['low'].iloc[i],
                    'index': i
                })
        # Bearish OB: last bullish candle before big bearish move
        if df['close'].iloc[i] > df['open'].iloc[i]:
            if df['close'].iloc[i+1] < df['low'].iloc[i]:
                obs.append({
                    'type': 'bearish',
                    'top': df['high'].iloc[i],
                    'bottom': df['low'].iloc[i],
                    'index': i
                })
    return obs[-3:] if obs else []

def find_liquidity(df):
    highs = []
    lows = []
    for i in range(2, len(df)-2):
        if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i+1]:
            highs.append(df['high'].iloc[i])
        if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i+1]:
            lows.append(df['low'].iloc[i])
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

def detect_cisd(df_1m):
    for i in range(2, len(df_1m)):
        # Bullish CISD
        if df_1m['close'].iloc[i-2] < df_1m['open'].iloc[i-2]:
            if df_1m['close'].iloc[i-1] > df_1m['open'].iloc[i-1]:
                cisd_level = df_1m['open'].iloc[i]
                if df_1m['close'].iloc[i] > cisd_level:
                    return {
                        'type': 'BUY',
                        'level': cisd_level,
                        'entry': df_1m['close'].iloc[i],
                        'candle_index': i
                    }
        # Bearish CISD
        if df_1m['close'].iloc[i-2] > df_1m['open'].iloc[i-2]:
            if df_1m['close'].iloc[i-1] < df_1m['open'].iloc[i-1]:
                cisd_level = df_1m['open'].iloc[i]
                if df_1m['close'].iloc[i] < cisd_level:
                    return {
                        'type': 'SELL',
                        'level': cisd_level,
                        'entry': df_1m['close'].iloc[i],
                        'candle_index': i
                    }
    return None

def detect_sharp_turn(df_5m):
    for i in range(2, len(df_5m)):
        # Bullish ST: FVG forms on 5M
        if df_5m['low'].iloc[i] > df_5m['high'].iloc[i-2]:
            return {
                'type': 'BUY',
                'entry': df_5m['close'].iloc[i],
                'fvg_top': df_5m['low'].iloc[i],
                'fvg_bottom': df_5m['high'].iloc[i-2]
            }
        # Bearish ST: FVG forms on 5M
        if df_5m['high'].iloc[i] < df_5m['low'].iloc[i-2]:
            return {
                'type': 'SELL',
                'entry': df_5m['close'].iloc[i],
                'fvg_top': df_5m['low'].iloc[i-2],
                'fvg_bottom': df_5m['high'].iloc[i]
            }
    return None

def check_smt(df_us30_1m, df_sp500_1m):
    us30_low = df_us30_1m['low'].iloc[-5:].min()
    sp500_low = df_sp500_1m['low'].iloc[-5:].min()
    us30_prev_low = df_us30_1m['low'].iloc[-10:-5].min()
    sp500_prev_low = df_sp500_1m['low'].iloc[-10:-5].min()
    if sp500_low < sp500_prev_low and us30_low > us30_prev_low:
        return True
    if us30_low < us30_prev_low and sp500_low > sp500_prev_low:
        return True
    return False

def find_sl(df, direction, entry):
    if direction == 'BUY':
        recent_low = df['low'].iloc[-10:].min()
        return recent_low
    else:
        recent_high = df['high'].iloc[-10:].max()
        return recent_high

def generate_chart(df_1h, levels_1d, levels_4h, levels_1h, direction):
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#1a1a2e')

    # Plot candles
    for i in range(len(df_1h)):
        color = '#26a69a' if df_1h['close'].iloc[i] >= df_1h['open'].iloc[i] else '#ef5350'
        ax.plot([i, i], [df_1h['low'].iloc[i], df_1h['high'].iloc[i]], color=color, linewidth=0.8)
        ax.add_patch(plt.Rectangle(
            (i - 0.3, min(df_1h['open'].iloc[i], df_1h['close'].iloc[i])),
            0.6,
            abs(df_1h['close'].iloc[i] - df_1h['open'].iloc[i]),
            color=color
        ))

    # Plot D1 levels
    for fvg in levels_1d.get('fvgs', []):
        ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.2, color='#FFD700', label='D1 FVG')
        ax.axhline(y=fvg['top'], color='#FFD700', linewidth=0.5, linestyle='--')

    for ob in levels_1d.get('obs', []):
        color = '#00FF88' if ob['type'] == 'bullish' else '#FF4444'
        ax.axhspan(ob['bottom'], ob['top'], alpha=0.15, color=color)
        ax.text(len(df_1h)-1, ob['top'], f"D1 OB", color=color, fontsize=6, ha='right')

    # Plot 4H levels
    for fvg in levels_4h.get('fvgs', []):
        ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.2, color='#FF8C00', label='4H FVG')

    for ob in levels_4h.get('obs', []):
        color = '#00BFFF' if ob['type'] == 'bullish' else '#FF69B4'
        ax.axhspan(ob['bottom'], ob['top'], alpha=0.15, color=color)
        ax.text(len(df_1h)-1, ob['top'], f"4H OB", color=color, fontsize=6, ha='right')

    # Plot 1H levels
    for fvg in levels_1h.get('fvgs', []):
        ax.axhspan(fvg['bottom'], fvg['top'], alpha=0.25, color='#9370DB')
        ax.text(len(df_1h)-1, fvg['top'], f"1H FVG", color='#9370DB', fontsize=6, ha='right')

    # Plot liquidity
    for h in levels_1h.get('liquidity', {}).get('highs', []):
        ax.axhline(y=h, color='#FF6347', linewidth=0.8, linestyle=':', label='Liquidity')
    for l in levels_1h.get('liquidity', {}).get('lows', []):
        ax.axhline(y=l, color='#7CFC00', linewidth=0.8, linestyle=':')

    # Direction label
    dir_color = '#26a69a' if direction == 'BULLISH' else '#ef5350'
    ax.text(2, df_1h['high'].max(), f'DIRECTION: {direction}',
            color=dir_color, fontsize=12, fontweight='bold')

    ax.set_title('US30 — 1H Analysis', color='white', fontsize=14)
    ax.tick_params(colors='white')
    ax.spines['bottom'].set_color('#444')
    ax.spines['left'].set_color('#444')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight',
                facecolor='#1a1a2e', dpi=150)
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close()
    return img_base64


@app.route('/analysis', methods=['GET'])
def analysis():
    try:
        df_1d = get_data('1D', 50)
        df_4h = get_data('4H', 100)
        df_1h = get_data('1H', 100)

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

        # Build text summary
        d1_liq = levels_1d['liquidity']
        text = f"""📊 US30 PRE-SESSION ANALYSIS
━━━━━━━━━━━━━━━━━━━━
🗓 {datetime.now(NY_TZ).strftime('%Y-%m-%d')}
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
            'direction': direction,
            'levels_1d': levels_1d,
            'levels_4h': levels_4h,
            'levels_1h': levels_1h
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/scan', methods=['GET'])
def scan():
    try:
        now_ny = datetime.now(NY_TZ)
        hour = now_ny.hour
        minute = now_ny.minute

        # Only scan 9:35 AM to 11:50 AM
        if not ((hour == 9 and minute >= 35) or
                (hour == 10) or
                (hour == 11 and minute <= 50)):
            return jsonify({'status': 'ok', 'signal': None,
                          'message': 'Outside trading window'})

        df_1m = get_data('1M', 50)
        df_5m = get_data('5M', 50)
        df_sp500_1m = tv.get_hist('SPX500', 'OANDA',
                                   Interval.in_1_minute, n_bars=50)

        cisd = detect_cisd(df_1m)
        st = detect_sharp_turn(df_5m)
        smt = check_smt(df_1m, df_sp500_1m)

        signal = None
        if cisd:
            sl = find_sl(df_1m, cisd['type'], cisd['entry'])
            sl_distance = abs(cisd['entry'] - sl)
            tp = cisd['entry'] + (sl_distance * 2) if cisd['type'] == 'BUY' \
                else cisd['entry'] - (sl_distance * 2)
            signal = {
                'pattern': 'CISD',
                'type': cisd['type'],
                'entry': round(cisd['entry'], 1),
                'sl': round(sl, 1),
                'tp': round(tp, 1),
                'sl_distance': round(sl_distance, 1),
                'smt': smt
            }
        elif st:
            sl = find_sl(df_5m, st['type'], st['entry'])
            sl_distance = abs(st['entry'] - sl)
            tp = st['entry'] + (sl_distance * 2) if st['type'] == 'BUY' \
                else st['entry'] - (sl_distance * 2)
            signal = {
                'pattern': 'SHARP_TURN',
                'type': st['type'],
                'entry': round(st['entry'], 1),
                'sl': round(sl, 1),
                'tp': round(tp, 1),
                'sl_distance': round(sl_distance, 1),
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

            return jsonify({
                'status': 'ok',
                'signal': signal,
                'text': text
            })

        return jsonify({'status': 'ok', 'signal': None})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)