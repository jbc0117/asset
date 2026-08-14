from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

# API 캐시 (1분간 저장)
stock_cache = {}

# 종목명 및 티커 매핑
KNOWN_STOCK_NAMES_MAP = {
    "코스피": "^KS11", "코스피 지수": "^KS11", "kospi": "^KS11",
    "코스닥": "^KQ11", "kosdaq": "^KQ11",
    "환율": "KRW=X", "원달러": "KRW=X", "원달러 환율": "KRW=X", "usd/krw": "KRW=X",

    "금": "KRX_GOLD_1G", "순금": "KRX_GOLD_1G", "금 1g": "KRX_GOLD_1G", 
    "krx금": "KRX_GOLD_1G", "krx 금현물 1g": "KRX_GOLD_1G", "금현물": "KRX_GOLD_1G",

    "삼성전자": "005930.KS", "sk하이닉스": "000660.KS", "lg에너지솔루션": "373220.KS",
    "naver": "035420.KS", "네이버": "035420.KS", "현대차": "005380.KS",
    "타미당": "458730.KS", "코나백": "379810.KS", "솔미채": "490490.KS",

    "테슬라": "TSLA", "tesla": "TSLA", "엔비디아": "NVDA", "nvidia": "NVDA",
    "apple inc": "AAPL", "애플": "AAPL", "microsoft": "MSFT", "마이크로소프트": "MSFT",
    "s&p 500": "SPY", "spy": "SPY", "나스닥 100": "QQQ", "qqq": "QQQ",
    "schd": "SCHD", "슈드": "SCHD", "qld": "QLD", "voo": "VOO", "vti": "VTI",
    "jepi": "JEPI", "jepq": "JEPQ", "비트코인": "BTC-KRW",

    "^KS11": "코스피",
    "^KQ11": "코스닥",
    "KRW=X": "원/달러 환율",
    "KRX_GOLD_1G": "KRX 금 1g (실물)",
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "373220.KS": "LG에너지솔루션",
    "035420.KS": "NAVER",
    "005380.KS": "현대차",
    "458730.KS": "타미당",
    "379810.KS": "코나백",
    "490490.KS": "솔미채",
    "BTC-KRW": "비트코인",
    "TSLA": "Tesla",
    "NVDA": "NVIDIA",
    "AAPL": "Apple Inc",
    "MSFT": "Microsoft",
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ Trust",
    "SCHD": "Schwab US Dividend Equity ETF"
}

def fetch_gold_1g_krw():
    """
    국제 금 선물(GC=F) 시세와 원/달러 환율(KRW=X)을 결합하여 금 1g 원화 시세 산출
    (1 트로이온스 = 31.1034768 g)
    """
    url_gold = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d"
    url_fx = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1d&range=5d"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        res_gold = requests.get(url_gold, headers=headers, timeout=2.5)
        res_fx = requests.get(url_fx, headers=headers, timeout=2.5)

        if res_gold.status_code == 200 and res_fx.status_code == 200:
            gold_closes = [c for c in res_gold.json()['chart']['result'][0]['indicators']['quote'][0]['close'] if c is not None]
            fx_closes = [c for c in res_fx.json()['chart']['result'][0]['indicators']['quote'][0]['close'] if c is not None]

            if gold_closes and fx_closes:
                gold_usd_curr = gold_closes[-1]
                gold_usd_prev = gold_closes[-2] if len(gold_closes) > 1 else gold_usd_curr

                fx_curr = fx_closes[-1]
                fx_prev = fx_closes[-2] if len(fx_closes) > 1 else fx_curr

                # 금 1g 원화 계산
                price_1g = (gold_usd_curr * fx_curr) / 31.1034768
                prev_1g = (gold_usd_prev * fx_prev) / 31.1034768

                change = price_1g - prev_1g
                change_percent = (change / prev_1g * 100) if prev_1g != 0 else 0.0

                return {
                    "code": "KRX_GOLD_1G",
                    "name": "KRX 금 1g (실물)",
                    "price": round(price_1g, 0),  # 원 단위 반올림
                    "change": round(change, 0),
                    "change_percent": round(change_percent, 2)
                }
    except Exception as e:
        print(f"금 시세 계산 실패: {e}")

    return {
        "code": "KRX_GOLD_1G",
        "name": "KRX 금 1g (실물)",
        "price": 0.0,
        "change": 0.0,
        "change_percent": 0.0
    }

def fetch_from_yahoo_chart_api(ticker_code):
    # 금 1g 조회 시 전용 계산 함수 호출
    if ticker_code == "KRX_GOLD_1G":
        return fetch_gold_1g_krw()

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_code}?interval=1d&range=5d"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        res = requests.get(url, headers=headers, timeout=2.5)
        if res.status_code == 200:
            data = res.json()
            result = data.get('chart', {}).get('result', [])
            if result:
                quote = result[0].get('indicators', {}).get('quote', [{}])[0]
                closes = [c for c in quote.get('close', []) if c is not None]

                if closes:
                    current_price = float(closes[-1])
                    prev_price = float(closes[-2]) if len(closes) > 1 else current_price
                    change = current_price - prev_price
                    change_percent = (change / prev_price * 100) if prev_price != 0 else 0.0

                    display_name = KNOWN_STOCK_NAMES_MAP.get(ticker_code, ticker_code)
                    return {
                        "code": ticker_code,
                        "name": display_name,
                        "price": round(current_price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_percent, 2)
                    }
    except Exception as e:
        print(f"[{ticker_code}] Yahoo Chart API 조회 실패: {e}")

    return {
        "code": ticker_code,
        "name": KNOWN_STOCK_NAMES_MAP.get(ticker_code, ticker_code),
        "price": 0.0,
        "change": 0.0,
        "change_percent": 0.0
    }

def get_stock_data(tickers):
    data = {}
    tickers_to_fetch = []

    for ticker in tickers:
        if ticker in stock_cache and time.time() - stock_cache[ticker]['timestamp'] < 60:
            data[ticker] = stock_cache[ticker]['data']
        else:
            tickers_to_fetch.append(ticker)

    for ticker in tickers_to_fetch:
        stock_info = fetch_from_yahoo_chart_api(ticker)
        data[ticker] = stock_info
        if stock_info['price'] > 0:
            stock_cache[ticker] = {'timestamp': time.time(), 'data': stock_info}

    return data

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stock-prices', methods=['POST'])
def get_prices():
    req_data = request.get_json(silent=True) or {}
    codes = req_data.get('codes', [])
    if not codes:
        return jsonify({})

    unique_codes = list(set(codes))
    price_data = get_stock_data(unique_codes)
    return jsonify(price_data)

@app.route('/api/search-stocks', methods=['GET'])
def search_stocks():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return jsonify([])

    results = []
    codes_to_search = set()

    for name_or_alias, code in KNOWN_STOCK_NAMES_MAP.items():
        if query in name_or_alias.lower() or query in code.lower():
            codes_to_search.add(code)

    if query.isdigit() and len(query) == 6:
        codes_to_search.add(f"{query}.KS")

    if len(query) >= 2 and query.replace('.', '').isalnum():
        codes_to_search.add(query.upper())

    if codes_to_search:
        all_stock_data = get_stock_data(list(codes_to_search))
        for code, stock_info in all_stock_data.items():
            if stock_info:
                results.append(stock_info)

    results.sort(key=lambda x: x['name'])
    return jsonify(results[:10])

if __name__ == '__main__':
    app.run(debug=True)