import os
import time
import requests
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# root 디렉토리 및 templates 디렉토리 모두 인식되도록 설정
app = Flask(__name__, template_folder='.')
CORS(app)

APP_KEY = os.getenv("KIS_APPKEY", "").strip()
APP_SECRET = os.getenv("KIS_APPSECRET", "").strip()
CANO = os.getenv("KIS_CANO", "").strip()
ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01").strip()

URL_BASE = "https://openapi.koreainvestment.com:9443"
ACCESS_TOKEN = ""

stock_cache = {}

# 6자리 순수 종목코드 매핑 추가
KNOWN_STOCK_NAMES_MAP = {
    "코스피": "^KS11", "코스피 지수": "^KS11", "kospi": "^KS11",
    "코스닥": "^KQ11", "kosdaq": "^KQ11",
    "환율": "KRW=X", "원달러": "KRW=X", "원달러 환율": "KRW=X", "usd/krw": "KRW=X",

    "금": "KRX_GOLD_1G", "순금": "KRX_GOLD_1G", "금 1g": "KRX_GOLD_1G", 
    "krx금": "KRX_GOLD_1G", "krx 금현물 1g": "KRX_GOLD_1G", "금현물": "KRX_GOLD_1G",

    "삼성전자": "005930", "sk하이닉스": "000660", "lg에너지솔루션": "373220",
    "naver": "035420", "네이버": "035420", "현대차": "005380",

    "테슬라": "TSLA", "tesla": "TSLA", "엔비디아": "NVDA", "nvidia": "NVDA",
    "apple inc": "AAPL", "애플": "AAPL", "microsoft": "MSFT", "마이크로소프트": "MSFT",

    "^KS11": "코스피",
    "^KQ11": "코스닥",
    "KRW=X": "원/달러 환율",
    "KRX_GOLD_1G": "KRX 금 1g (실물)",
    
    # 6자리 숫자 및 .KS 형태 둘 다 한글명 매핑
    "005930": "삼성전자", "005930.KS": "삼성전자",
    "000660": "SK하이닉스", "000660.KS": "SK하이닉스",
    "373220": "LG에너지솔루션", "373220.KS": "LG에너지솔루션",
    "035420": "NAVER", "035420.KS": "NAVER",
    "005380": "현대차", "005380.KS": "현대차",
    "458730": "타미당", "458730.KS": "타미당",
    "379810": "코나백", "379810.KS": "코나백",
    "490490": "솔미채", "490490.KS": "솔미채",
    "BTC-KRW": "비트코인",
    "TSLA": "Tesla",
    "NVDA": "NVIDIA",
    "AAPL": "Apple Inc",
    "MSFT": "Microsoft",
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ Trust",
    "SCHD": "Schwab US Dividend Equity ETF"
}

def get_access_token():
    global ACCESS_TOKEN
    if ACCESS_TOKEN:
        return ACCESS_TOKEN

    url = f"{URL_BASE}/oauth2/tokenP"
    headers = {"content-type": "application/json; charset=utf-8"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }

    try:
        res = requests.post(url, headers=headers, json=body, timeout=5)
        res_data = res.json()
        if "access_token" in res_data:
            ACCESS_TOKEN = res_data["access_token"]
            return ACCESS_TOKEN
    except Exception as e:
        print(f"KIS 토큰 발급 실패: {e}")
    return None

def fetch_from_kis_api(ticker_code):
    token = get_access_token()
    clean_code = ticker_code.split('.')[0].strip().zfill(6)
    default_name = KNOWN_STOCK_NAMES_MAP.get(clean_code, KNOWN_STOCK_NAMES_MAP.get(ticker_code, ticker_code))

    if not token:
        return None

    url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST01010100",
        "custtype": "P"
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": clean_code
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                if output:
                    price = float(output.get("stck_prpr", 0))
                    change = float(output.get("prdy_vrss", 0))
                    change_rate = float(output.get("prdy_ctrt", 0))
                    
                    sign = output.get("prdy_vrss_sign", "3")
                    if sign in ["4", "5"]:
                        change = -abs(change)

                    display_name = output.get("hts_kor_isnm") or default_name

                    return {
                        "code": clean_code,
                        "name": display_name,
                        "price": price,
                        "change": change,
                        "change_percent": change_rate
                    }
    except Exception as e:
        print(f"[{ticker_code}] KIS API 조회 실패: {e}")

    return None

def fetch_gold_1g_krw():
    url_gold = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=5d"
    url_fx = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1d&range=5d"
    headers = {'User-Agent': 'Mozilla/5.0'}

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

                price_1g = (gold_usd_curr * fx_curr) / 31.1034768
                prev_1g = (gold_usd_prev * fx_prev) / 31.1034768
                change = price_1g - prev_1g
                change_percent = (change / prev_1g * 100) if prev_1g != 0 else 0.0

                return {
                    "code": "KRX_GOLD_1G",
                    "name": "KRX 금 1g (실물)",
                    "price": round(price_1g, 0),
                    "change": round(change, 0),
                    "change_percent": round(change_percent, 2)
                }
    except Exception as e:
        print(f"금 시세 계산 실패: {e}")

    return {"code": "KRX_GOLD_1G", "name": "KRX 금 1g (실물)", "price": 0.0, "change": 0.0, "change_percent": 0.0}

def fetch_from_yahoo_chart_api(ticker_code):
    if ticker_code == "KRX_GOLD_1G":
        return fetch_gold_1g_krw()

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_code}?interval=1d&range=5d"
    headers = {'User-Agent': 'Mozilla/5.0'}

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
        stock_info = None
        clean_code = ticker.split('.')[0].strip()

        if len(clean_code) == 6 and clean_code.isdigit():
            stock_info = fetch_from_kis_api(clean_code)

        if not stock_info or stock_info['price'] == 0:
            stock_info = fetch_from_yahoo_chart_api(ticker)

        data[ticker] = stock_info
        if stock_info and stock_info['price'] > 0:
            stock_cache[ticker] = {'timestamp': time.time(), 'data': stock_info}

    return data

@app.route('/')
def index():
    if os.path.exists('index.html'):
        return render_template('index.html')
    return render_template('templates/index.html')

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
        codes_to_search.add(query)

    if codes_to_search:
        all_stock_data = get_stock_data(list(codes_to_search))
        for code, stock_info in all_stock_data.items():
            if stock_info and stock_info['price'] > 0:
                results.append(stock_info)

    results.sort(key=lambda x: x['name'])
    return jsonify(results[:10])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=True)
