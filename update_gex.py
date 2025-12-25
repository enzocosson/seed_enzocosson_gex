"""
Script de mise à jour des niveaux GEX pour TradingView
Génère UNIQUEMENT les CSV
"""
import requests
import pandas as pd
from datetime import datetime
import sys
from config import *

def log(message):
    """Logger simple"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")

def fetch_gex_data(ticker, aggregation='full'):
    """Récupère les données GEX"""
    url = f"{BASE_URL}/{ticker}/classic/{aggregation}?key={API_KEY}"
    try:
        response = requests.get(url, timeout=API_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        log(f"✅ {ticker}/{aggregation} récupéré - {len(data.get('strikes', []))} strikes")
        return data
    except Exception as e:
        log(f"❌ Erreur {ticker}/{aggregation}: {e}")
        return None

def convert_to_futures(source_ticker, gex_data):
    """Convertit SPX/NDX en ES/NQ"""
    
    if not gex_data:
        return []
    
    config = TICKERS[source_ticker]
    ratio = config['ratio']
    target = config['target']
    
    levels = []
    
    # 1. Zero Gamma
    zero_gamma = gex_data.get('zero_gamma', 0)
    if zero_gamma != 0:
        levels.append({
            'strike': round(zero_gamma / ratio, 2),
            'gex_vol': 0,
            'gex_oi': 0,
            'type': 'zero_gamma',
            'importance': 10,
            'label': 'Zero Gamma'
        })
        log(f"   ✅ Zero Gamma: {round(zero_gamma / ratio, 2)}")
    else:
        log(f"   ⚠️  Zero Gamma = 0")
    
    # 2. Niveaux majeurs
    major_pos_vol = gex_data.get('major_pos_vol', 0)
    major_neg_vol = gex_data.get('major_neg_vol', 0)
    major_pos_oi = gex_data.get('major_pos_oi', 0)
    major_neg_oi = gex_data.get('major_neg_oi', 0)
    sum_gex_vol = gex_data.get('sum_gex_vol', 0)
    sum_gex_oi = gex_data.get('sum_gex_oi', 0)
    
    if major_pos_vol != 0:
        levels.append({
            'strike': round(major_pos_vol / ratio, 2),
            'gex_vol': sum_gex_vol,
            'gex_oi': 0,
            'type': 'support',
            'importance': 9,
            'label': 'Major Support (Vol)'
        })
    
    if major_neg_vol != 0:
        levels.append({
            'strike': round(major_neg_vol / ratio, 2),
            'gex_vol': sum_gex_vol,
            'gex_oi': 0,
            'type': 'resistance',
            'importance': 9,
            'label': 'Major Resistance (Vol)'
        })
    
    if major_pos_oi != 0:
        levels.append({
            'strike': round(major_pos_oi / ratio, 2),
            'gex_vol': 0,
            'gex_oi': sum_gex_oi,
            'type': 'support',
            'importance': 8,
            'label': 'Major Support (OI)'
        })
    
    if major_neg_oi != 0:
        levels.append({
            'strike': round(major_neg_oi / ratio, 2),
            'gex_vol': 0,
            'gex_oi': sum_gex_oi,
            'type': 'resistance',
            'importance': 8,
            'label': 'Major Resistance (OI)'
        })
    
    # 3. Top strikes
    strikes = gex_data.get('strikes', [])
    
    if strikes:
        strikes_data = []
        for strike_array in strikes:
            if len(strike_array) >= 3:
                strike_price = strike_array[0]
                gex_vol = strike_array[1]
                gex_oi = strike_array[2]
                
                importance_score = abs(gex_vol) + abs(gex_oi)
                
                if importance_score > 50:
                    strikes_data.append({
                        'strike': strike_price,
                        'gex_vol': gex_vol,
                        'gex_oi': gex_oi,
                        'importance': importance_score
                    })
        
        strikes_data.sort(key=lambda x: x['importance'], reverse=True)
        
        for strike_info in strikes_data[:TOP_STRIKES_COUNT]:
            if abs(strike_info['gex_vol']) > abs(strike_info['gex_oi']):
                strike_type = 'support' if strike_info['gex_vol'] > 0 else 'resistance'
            else:
                strike_type = 'support' if strike_info['gex_oi'] > 0 else 'resistance'
            
            levels.append({
                'strike': round(strike_info['strike'] / ratio, 2),
                'gex_vol': strike_info['gex_vol'],
                'gex_oi': strike_info['gex_oi'],
                'type': strike_type,
                'importance': 7,
                'label': strike_type.capitalize()
            })
        
        log(f"   ✅ {len(strikes_data[:TOP_STRIKES_COUNT])} strikes ajoutés")
    
    # 4. Hotspots
    max_priors = gex_data.get('max_priors', [])
    hotspots_added = 0
    
    if max_priors:
        intervals = ['1min', '5min', '10min']
        
        for idx, strike_array in enumerate(max_priors[:3]):
            if strike_array and len(strike_array) >= 2:
                strike_val = strike_array[0]
                gex_change = strike_array[1] if len(strike_array) > 1 else 0
                
                if strike_val != 0 and abs(gex_change) > 10:
                    interval_name = intervals[idx] if idx < len(intervals) else f'{idx}min'
                    
                    levels.append({
                        'strike': round(strike_val / ratio, 2),
                        'gex_vol': gex_change,
                        'gex_oi': 0,
                        'type': 'hotspot',
                        'importance': 6,
                        'label': f'Max Change {interval_name}'
                    })
                    hotspots_added += 1
    
    if hotspots_added > 0:
        log(f"   ✅ {hotspots_added} hotspots")
    
    log(f"✅ {target}: {len(levels)} niveaux générés")
    return levels

def main():
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    log("=" * 60)
    log(f"🚀 DÉMARRAGE MISE À JOUR GEX - {timestamp}")
    log("=" * 60)
    
    if not API_KEY:
        log("❌ ERREUR: GEXBOT_API_KEY non définie")
        sys.exit(1)
    
    success_count = 0
    
    for source_ticker, config in TICKERS.items():
        log(f"\n📊 Traitement {source_ticker} → {config['target']}...")
        
        gex_data = fetch_gex_data(source_ticker, aggregation='full')
        
        if gex_data:
            spot = gex_data.get('spot', 0)
            min_dte = gex_data.get('min_dte', 0)
            
            log(f"   Spot: {spot}")
            log(f"   Min DTE: {min_dte}")
            
            levels = convert_to_futures(source_ticker, gex_data)
            
            if levels:
                df = pd.DataFrame(levels)
                df = df.sort_values(['importance', 'strike'], ascending=[False, True])
                df = df.drop_duplicates(subset=['strike'], keep='first')
                
                output_file = OUTPUT_FILES[config['target']]
                df.to_csv(output_file, index=False)
                log(f"✅ Fichier sauvegardé: {output_file} ({len(df)} niveaux)")
                success_count += 1
            else:
                log(f"⚠️  Aucun niveau pour {config['target']}")
        else:
            log(f"❌ Erreur {config['target']}")
    
    with open(OUTPUT_FILES['TIMESTAMP'], 'w') as f:
        f.write(timestamp)
    
    log("\n" + "=" * 60)
    log(f"✅ TERMINÉ - {success_count}/{len(TICKERS)} succès")
    log("=" * 60)
    
    sys.exit(0 if success_count > 0 else 1)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
