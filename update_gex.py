"""
Script de mise à jour des niveaux GEX pour TradingView
Récupère uniquement les données GexBot (sans IV/volatilité)
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
from datetime import datetime
import sys
import time
from config import *

def log(message):
    """Logger simple"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {message}")

# ==================== HTTP Session avec retries ====================
def create_session(retries=3, backoff_factor=0.5, status_forcelist=(500,502,503,504)):
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(['GET','POST'])
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    session.headers.update({'User-Agent': 'GexTradingScript/1.0', 'Accept': 'application/json'})
    return session


# ==================== GEXBOT API ====================
def fetch_classic(session, ticker, aggregation='full'):
    """Récupère la ressource `/ {TICKER}/classic/{aggregation}` en utilisant une session fournie."""
    url = f"{BASE_URL}/{ticker}/classic/{aggregation}?key={API_KEY}"
    try:
        resp = session.get(url, timeout=API_TIMEOUT)
        if resp.status_code == 200:
            log(f"✅ {ticker} classic/{aggregation} récupéré")
            return resp.json()
        else:
            log(f"⚠️  {ticker} classic/{aggregation} status {resp.status_code}")
            return None
    except requests.RequestException as e:
        log(f"❌ Erreur requête {ticker} classic/{aggregation}: {e}")
        return None

# ==================== CONVERSION ====================

def convert_to_futures(source_ticker, full_resp, zero_resp=None, one_resp=None):
    """Convertit SPX/NDX en ES/NQ à partir des réponses `full` (strikes) et `zero` (majors)."""
    config = TICKERS[source_ticker]
    ratio = config['ratio']
    target = config['target']

    levels = []

    # 1. Niveaux majeurs depuis `zero_resp` (si présent)
    if zero_resp:
        # zero_gamma
        zg = zero_resp.get('zero_gamma')
        if zg is not None:
            levels.append({
                'strike': round(zg / ratio, 2),
                'gex_vol': 0,
                'gex_oi': 0,
                'type': 'zero_gamma',
                'importance': 10,
                'label': 'Zero Gamma'
            })

        # major positions (naming in API: major_pos_vol, major_pos_oi, major_neg_vol, major_neg_oi)
        mpos_vol = zero_resp.get('major_pos_vol')
        mneg_vol = zero_resp.get('major_neg_vol')
        mpos_oi = zero_resp.get('major_pos_oi')
        mneg_oi = zero_resp.get('major_neg_oi')

        if mpos_vol:
            levels.append({
                'strike': round(mpos_vol / ratio, 2),
                'gex_vol': zero_resp.get('sum_gex_vol', 0),
                'gex_oi': 0,
                'type': 'support',
                'importance': 9,
                'label': 'Major Support (Vol)'
            })

        if mneg_vol:
            levels.append({
                'strike': round(mneg_vol / ratio, 2),
                'gex_vol': zero_resp.get('sum_gex_vol', 0),
                'gex_oi': 0,
                'type': 'resistance',
                'importance': 9,
                'label': 'Major Resistance (Vol)'
            })

        if mpos_oi:
            levels.append({
                'strike': round(mpos_oi / ratio, 2),
                'gex_vol': 0,
                'gex_oi': zero_resp.get('sum_gex_oi', 0),
                'type': 'support',
                'importance': 8,
                'label': 'Major Support (OI)'
            })

        if mneg_oi:
            levels.append({
                'strike': round(mneg_oi / ratio, 2),
                'gex_vol': 0,
                'gex_oi': zero_resp.get('sum_gex_oi', 0),
                'type': 'resistance',
                'importance': 8,
                'label': 'Major Resistance (OI)'
            })

    # 2. Top strikes depuis `full_resp` -> structure: strikes is list of [strike, gex_vol, gex_oi]
    if full_resp and 'strikes' in full_resp:
        strikes_data = []
        for strike_array in full_resp['strikes']:
            if len(strike_array) >= 3:
                strike = strike_array[0]
                gex_vol = strike_array[1]
                gex_oi = strike_array[2]
                importance_score = abs(gex_vol) + abs(gex_oi)

                strikes_data.append({
                    'strike': strike,
                    'gex_vol': gex_vol,
                    'gex_oi': gex_oi,
                    'importance': importance_score
                })

        strikes_data.sort(key=lambda x: x['importance'], reverse=True)

        for strike_info in strikes_data[:TOP_STRIKES_COUNT]:
            strike_type = 'support' if strike_info['gex_vol'] > 0 else 'resistance'
            levels.append({
                'strike': round(strike_info['strike'] / ratio, 2),
                'gex_vol': strike_info['gex_vol'],
                'gex_oi': strike_info['gex_oi'],
                'type': strike_type,
                'importance': 7,
                'label': strike_type.capitalize()
            })

    # 3. Max changes: essayer de lire des champs potentiels dans `full_resp`/`one_resp`
    # Certains payloads peuvent contenir des clés comme 'max_priors' ou 'max_change'. On les recherche prudemment.
    max_sources = [one_resp, full_resp, zero_resp]
    for src in max_sources:
        if not src:
            continue
        # recherche d'un dict contenant des clés 'one','five','fifteen' ou 'max_change'
        if 'one' in src and isinstance(src['one'], list) and len(src['one']) >= 2:
            levels.append({
                'strike': round(src['one'][0] / ratio, 2),
                'gex_vol': src['one'][1],
                'gex_oi': 0,
                'type': 'hotspot',
                'importance': 6,
                'label': 'Max Change 1min'
            })
        # fallback: max_priors may be a list of hotspots
        if 'max_priors' in src and isinstance(src['max_priors'], list):
            for item in src['max_priors'][:3]:
                if isinstance(item, list) and len(item) >= 2:
                    levels.append({
                        'strike': round(item[0] / ratio, 2),
                        'gex_vol': item[1],
                        'gex_oi': 0,
                        'type': 'hotspot',
                        'importance': 6,
                        'label': 'Max Prior'
                    })

    log(f"✅ {target}: {len(levels)} niveaux générés")
    return levels

# ==================== MAIN ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Met à jour les niveaux GEX et génère CSV pour ES/NQ')
    parser.add_argument('--agg', choices=['zero','full','one'], help='Forcer une aggregation spécifique (ex: zero)')
    parser.add_argument('--api-key', help="Clé API GEXBOT (remplace la variable d'environnement)")
    parser.add_argument('--retries', type=int, default=3, help="Nombre de tentatives HTTP en cas d'erreur")
    args = parser.parse_args()

    # Override API_KEY si passé en paramètre
    global API_KEY
    if args.api_key:
        API_KEY = args.api_key

    # Créer session HTTP
    session = create_session(retries=args.retries)

    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    log("=" * 60)
    log(f"🚀 DÉMARRAGE MISE À JOUR GEX - {timestamp}")
    log("=" * 60)
    
    if not API_KEY:
        log("❌ ERREUR: GEXBOT_API_KEY non définie")
        sys.exit(1)
    
    # Traiter chaque ticker
    for source_ticker, config in TICKERS.items():
        log(f"\n📊 Traitement {source_ticker} → {config['target']}...")
        
        # Récupérer les agrégations documentées: zero (majors), full (chaîne complète), one (alternative)
        if args.agg:
            zero = fetch_classic(session, source_ticker, 'zero') if args.agg == 'zero' else None
            full = fetch_classic(session, source_ticker, 'full') if args.agg == 'full' else None
            one = fetch_classic(session, source_ticker, 'one') if args.agg == 'one' else None
        else:
            zero = fetch_classic(session, source_ticker, 'zero')
            full = fetch_classic(session, source_ticker, 'full')
            one = fetch_classic(session, source_ticker, 'one')

        if full or zero:
            levels = convert_to_futures(source_ticker, full_resp=full, zero_resp=zero, one_resp=one)
            
            df = pd.DataFrame(levels)
            df = df.sort_values(['importance', 'strike'], ascending=[False, True])
            
            output_file = OUTPUT_FILES[config['target']]
            df.to_csv(output_file, index=False)
            log(f"✅ Fichier sauvegardé: {output_file}")
            
            if zero:
                log(f"   Zero Gamma: {zero.get('zero_gamma', 'N/A')}")
                log(f"   Spot: {zero.get('spot', 'N/A')}")
        else:
            log(f"❌ Impossible de générer {config['target']}")
    
    # Timestamp
    with open(OUTPUT_FILES['TIMESTAMP'], 'w') as f:
        f.write(timestamp)
    
    log("\n" + "=" * 60)
    log(f"✅ MISE À JOUR TERMINÉE - {timestamp}")
    log("=" * 60)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"❌ ERREUR CRITIQUE: {e}")
        sys.exit(1)
