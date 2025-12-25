"""Script de test pour GexBot API"""
import requests
from config import API_KEY, BASE_URL

def test_endpoint(ticker, endpoint_type):
    """Test d'un endpoint"""
    # Construire l'URL selon la documentation: /{TICKER}/classic/{AGGREGATION_PERIOD}
    url = f"{BASE_URL}/{ticker}/classic/{endpoint_type}?key={API_KEY}"
    headers = {
        'User-Agent': 'GexTradingScript/1.0',
        'Accept': 'application/json'
    }
    print(f"\n📡 Test {ticker} - {endpoint_type}")
    
    try:
        response = requests.get(url, headers=headers, timeout=15)

        # Afficher status et body pour debug quand ce n'est pas 200
        print(f"   Status HTTP: {response.status_code}")
        if not response.ok:
            print(f"   Response body: {response.text!r}")
            return False

        data = response.json()

        print(f"   ✅ Status: {response.status_code}")
        # Afficher les clés racines et informations utiles
        if isinstance(data, dict):
            keys = list(data.keys())
            print(f"   JSON keys: {keys}")
            if 'strikes' in data:
                print(f"   📈 Strikes: {len(data['strikes'])}")
            if 'spot' in data:
                print(f"   💰 Spot: {data.get('spot')}")

        else:
            print(f"   Response JSON type: {type(data)}")

        return True
        
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
        return False

def main():
    print("=" * 60)
    print("🧪 TEST API GEXBOT")
    print("=" * 60)
    
    if not API_KEY:
        print("❌ GEXBOT_API_KEY non définie")
        return
    
    print(f"✅ Clé API: {API_KEY[:10]}...")
    
    # Tests
    tests = [
        ('SPX', 'zero'),
        ('SPX', 'full'),
        ('SPX', 'one'),
        ('NDX', 'zero'),
        ('NDX', 'full'),
        ('NDX', 'one')
    ]
    
    results = []
    for ticker, endpoint in tests:
        result = test_endpoint(ticker, endpoint)
        results.append((f"{ticker} {endpoint}", result))
    
    # Résumé
    print("\n" + "=" * 60)
    print("📋 RÉSUMÉ")
    print("=" * 60)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    passed = sum(1 for _, r in results if r)
    print(f"\n🎯 {passed}/{len(results)} tests réussis")
    
    if passed == len(results):
        print("\n✅ Parfait ! Lancez: python update_gex.py")

if __name__ == '__main__':
    main()
