import os
import time
import sqlite3
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder='.')
CORS(app)

APP_KEY = os.getenv("KIS_APPKEY", "").strip()
APP_SECRET = os.getenv("KIS_APPSECRET", "").strip()
URL_BASE = "https://openapivts.koreainvestment.com:9443" if "vts" in os.getenv("KIS_URL_TYPE", "").lower() else "https://openapi.koreainvestment.com:9443"
ACCESS_TOKEN = ""

stock_cache = {}

NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://m.stock.naver.com/'
}

def init_db():
    conn = sqlite3.connect('family_portfolio.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            user_id TEXT,
            ticker TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            user_id TEXT,
            member TEXT,
            account TEXT,
            name TEXT,
            ticker TEXT,
            quantity REAL,
            dividend REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS investment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            record_date TEXT,
            assets REAL,
            return_rate REAL,
            profit_loss REAL,
            mom_assets REAL,
            mom_return_rate REAL,
            mom_profit_loss REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

KNOWN_STOCK_NAMES_MAP = {
    "코스피": "^KS11", "코스피 지수": "^KS11", "kospi": "^KS11",
    "코스닥": "^KQ11", "kosdaq": "^KQ11",
    "환율": "KRW=X", "원달러": "KRW=X", "원달러 환율": "KRW=X", "usd/krw": "KRW=X", "USDKRW=X": "원달러 환율",
    "금": "KRX_GOLD_1G", "순금": "KRX_GOLD_1G", "금 1g": "KRX_GOLD_1G", 
    "krx금": "KRX_GOLD_1G", "krx 금현물 1g": "KRX_GOLD_1G", "금현물": "KRX_GOLD_1G", "KRX 금현물": "KRX_GOLD_1G", "KRX 금(1g)": "KRX_GOLD_1G",

    "247540": "에코프로비엠",
    "005930": "삼성전자", 
    "000660": "SK하이닉스", 
    "373220": "LG에너지솔루션",
    "035420": "NAVER", 
    "005380": "현대차",
    "458730": "TIGER 미국배당다우존스", 
    "379810": "KODEX 미국배당다우존스", 
    "490490": "ACE 미국배당다우존스", 
    "0048K0": "TIGER 미국S&P500",

    "^KS11": "코스피",
    "^KQ11": "코스닥",
    "KRW=X": "원/달러 환율",
    "USDKRW=X": "원/달러 환율",
    "KRX_GOLD_1G": "KRX 금 1g (실물)",
    "BTC-KRW": "비트코인"
}

NAME_TO_CODE = {
    "에코프로비엠": "247540",
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "LG에너지솔루션": "373220",
    "NAVER": "035420",
    "현대차": "005380",
    "TIGER 미국배당다우존스": "458730",
    "KODEX 미국배당다우존스": "379810",
    "ACE 미국배당다우존스": "490490",
    "TIGER 미국S&P500": "0048K0"
}

def resolve_code(ticker):
    ticker = ticker.strip()
    if ticker in NAME_TO_CODE:
        return NAME_TO_CODE[ticker]
    return ticker

def get_access_token():
    global ACCESS_TOKEN
    if ACCESS_TOKEN:
        return ACCESS_TOKEN

    if not APP_KEY or not APP_SECRET:
        return None

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
        print(f"[KIS Token Error]: {e}")
    return None

def fetch_from_naver_backup(code):
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        res = requests.get(url, headers=NAVER_HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data and "closePrice" in data:
                price = float(str(data.get("closePrice", "0")).replace(",", ""))
                change = float(str(data.get("compareToPreviousPrice", "0")).replace(",", ""))
                change_rate = float(str(data.get("fluctuationsRatio", "0")).replace(",", ""))
                name = data.get("stockName") or KNOWN_STOCK_NAMES_MAP.get(code, code)
                return {"code": code, "name": name, "price": price, "change": change, "change_percent": change_rate}
    except Exception as e:
        print(f"[{code}] Naver 주식 백업 오류: {e}")
    return None

def fetch_from_kis_api(ticker_code):
    global ACCESS_TOKEN
    clean_code = resolve_code(ticker_code)
    default_name = KNOWN_STOCK_NAMES_MAP.get(clean_code, KNOWN_STOCK_NAMES_MAP.get(ticker_code, ticker_code))

    token = get_access_token()
    if token:
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
                            change_rate = -abs(change_rate)

                        api_name = output.get("hts_kor_isnm")
                        display_name = api_name.strip() if api_name and api_name.strip() else default_name

                        if price > 0:
                            return {
                                "code": clean_code,
                                "name": display_name,
                                "price": price,
                                "change": change,
                                "change_percent": change_rate
                            }
                else:
                    ACCESS_TOKEN = ""
        except Exception as e:
            print(f"[{clean_code}] KIS API 오류: {e}")

    backup = fetch_from_naver_backup(clean_code)
    if backup:
        return backup

    return {"code": clean_code, "name": default_name, "price": 0.0, "change": 0.0, "change_percent": 0.0}

def fetch_index(ticker_code):
    global ACCESS_TOKEN
    default_name = "코스피" if ticker_code == "^KS11" else "코스닥"
    market_type = "KOSPI" if ticker_code == "^KS11" else "KOSDAQ"
    market_code = "0001" if ticker_code == "^KS11" else "1001"

    token = get_access_token()
    if token:
        url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-index-price"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
            "tr_id": "FHPUP02100000",
            "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": market_code}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    if output:
                        price = float(output.get("bstp_nmix_prpr", 0))
                        change = float(output.get("bstp_nmix_prdy_vrss", 0))
                        change_rate = float(output.get("bstp_nmix_prdy_ctrt", 0))
                        sign = output.get("prdy_vrss_sign", "3")
                        if sign in ["4", "5"]:
                            change = -abs(change)
                            change_rate = -abs(change_rate)
                        if price > 0:
                            return {
                                "code": ticker_code,
                                "name": default_name,
                                "price": round(price, 2),
                                "change": round(change, 2),
                                "change_percent": round(change_rate, 2)
                            }
                else:
                    ACCESS_TOKEN = ""
        except Exception as e:
            print(f"[{ticker_code}] KIS 지수 오류: {e}")

    try:
        url = f"https://m.stock.naver.com/api/index/{market_type}/basic"
        res = requests.get(url, headers=NAVER_HEADERS, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data and "closePrice" in data:
                price = float(str(data.get("closePrice", "0")).replace(",", ""))
                change = float(str(data.get("compareToPreviousPrice", "0")).replace(",", ""))
                change_rate = float(str(data.get("fluctuationsRatio", "0")).replace(",", ""))
                return {"code": ticker_code, "name": default_name, "price": price, "change": change, "change_percent": change_rate}
    except Exception as e:
        print(f"[{ticker_code}] Naver 지수 백업 오류: {e}")

    return {"code": ticker_code, "name": default_name, "price": 0.0, "change": 0.0, "change_percent": 0.0}

def fetch_gold(ticker_code="KRX_GOLD_1G"):
    token = get_access_token()
    if token:
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
            "FID_INPUT_ISCD": "M04020000"
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
                            change_rate = -abs(change_rate)

                        if price > 0:
                            return {
                                "code": ticker_code,
                                "name": "KRX 금 1g (실물)",
                                "price": price,
                                "change": change,
                                "change_percent": change_rate
                            }
        except Exception as e:
            print(f"[{ticker_code}] KIS 금시세 API 오류: {e}")

    urls = [
        "https://m.stock.naver.com/front-api/v1/marketIndex/prices?category=metal",
        "https://m.stock.naver.com/api/index/M04020000/basic",
        "https://api.stock.naver.com/index/M04020000/basic"
    ]
    for url in urls:
        try:
            res = requests.get(url, headers=NAVER_HEADERS, timeout=3)
            if res.status_code == 200:
                raw = res.json()
                data = raw
                
                if isinstance(raw, dict) and "result" in raw and isinstance(raw["result"], list):
                    for item in raw["result"]:
                        if item.get("itemCode") == "M04020000" or "금" in item.get("itemName", ""):
                            data = item
                            break
                elif isinstance(raw, list):
                    for item in raw:
                        if item.get("itemCode") == "M04020000":
                            data = item
                            break

                if isinstance(data, dict):
                    price_val = data.get("closePrice") or data.get("now") or data.get("price")
                    if price_val:
                        price = float(str(price_val).replace(",", ""))
                        change_val = data.get("compareToPreviousPrice") or data.get("change") or "0"
                        change = float(str(change_val).replace(",", ""))
                        ratio_val = data.get("fluctuationsRatio") or data.get("changeRate") or "0"
                        change_rate = float(str(ratio_val).replace(",", ""))
                        
                        if price > 0:
                            return {
                                "code": ticker_code,
                                "name": "KRX 금 1g (실물)",
                                "price": price,
                                "change": change,
                                "change_percent": change_rate
                            }
        except Exception as e:
            print(f"[금 시세 파싱 실패 - {url}]: {e}")

    return {"code": ticker_code, "name": "KRX 금 1g (실물)", "price": 0.0, "change": 0.0, "change_percent": 0.0}

def fetch_exchange_rate(ticker_code):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/USDKRW=X?interval=1d&range=5d"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=3.0)
        if res.status_code == 200:
            data = res.json()
            result = data.get('chart', {}).get('result', [])
            if result:
                meta = result[0].get('meta', {})
                current_price = meta.get('regularMarketPrice')
                quote = result[0].get('indicators', {}).get('quote', [{}])[0]
                closes = [c for c in quote.get('close', []) if c is not None]
                if current_price is None and closes:
                    current_price = closes[-1]
                if current_price is not None and closes:
                    prev_price = closes[-2] if len(closes) > 1 else current_price
                    change = current_price - prev_price
                    change_percent = (change / prev_price * 100) if prev_price != 0 else 0.0
                    return {
                        "code": ticker_code,
                        "name": "원/달러 환율",
                        "price": round(current_price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_percent, 2)
                    }
    except Exception as e:
        print(f"[환율 오류]: {e}")

    return {"code": ticker_code, "name": "원/달러 환율", "price": 1350.0, "change": 0.0, "change_percent": 0.0}

def fetch_from_upbit_api(ticker_code):
    market = "KRW-BTC" if ticker_code == "BTC-KRW" else ticker_code
    url = f"https://api.upbit.com/v1/ticker?markets={market}"
    headers = {"accept": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=3.0)
        if res.status_code == 200:
            data = res.json()
            if data and isinstance(data, list):
                item = data[0]
                current_price = float(item.get("trade_price", 0))
                change_price = float(item.get("signed_change_price", 0))
                change_rate = float(item.get("signed_change_rate", 0)) * 100
                return {
                    "code": ticker_code,
                    "name": "비트코인",
                    "price": round(current_price, 2),
                    "change": round(change_price, 2),
                    "change_percent": round(change_rate, 2)
                }
    except:
        pass
    return None

def get_stock_data(tickers, watchlist_tickers=None):
    if watchlist_tickers is None:
        watchlist_tickers = []
        
    data = {}
    tickers_to_fetch = []

    for ticker in tickers:
        if ticker in stock_cache and time.time() - stock_cache[ticker]['timestamp'] < 30:
            data[ticker] = stock_cache[ticker]['data']
        else:
            tickers_to_fetch.append(ticker)

    for ticker in tickers_to_fetch:
        stock_info = None
        
        if ticker in ["KRW=X", "USDKRW=X"]:
            stock_info = fetch_exchange_rate(ticker)
        elif ticker in ["^KS11", "^KQ11"]:
            stock_info = fetch_index(ticker)
        elif ticker in ["KRX_GOLD_1G", "금", "금현물", "KRX 금(1g)", "KRX 금 1g (실물)", "금 1g"]:
            stock_info = fetch_gold(ticker)
        elif ticker == "BTC-KRW":
            stock_info = fetch_from_upbit_api(ticker)
        else:
            stock_info = fetch_from_kis_api(ticker)

        if not stock_info:
            stock_info = {
                "code": ticker,
                "name": KNOWN_STOCK_NAMES_MAP.get(ticker, ticker),
                "price": 0.0,
                "change": 0.0,
                "change_percent": 0.0
            }

        data[ticker] = stock_info
        if stock_info and stock_info.get('price', 0) > 0:
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
    user_id = req_data.get('user_id', '')
    if not codes:
        return jsonify({})

    watchlist = []
    if user_id:
        try:
            conn = sqlite3.connect('family_portfolio.db')
            cursor = conn.cursor()
            cursor.execute('SELECT ticker FROM watchlist WHERE user_id = ?', (user_id,))
            watchlist = [row[0] for row in cursor.fetchall()]
            conn.close()
        except:
            pass

    unique_codes = list(set(codes))
    price_data = get_stock_data(unique_codes, watchlist)
    return jsonify(price_data)

@app.route('/api/search-stock', methods=['GET'])
def search_stocks():
    query = request.args.get('query', '').strip().lower()
    if not query:
        return jsonify([])

    results = []
    codes_to_search = set()

    for name, code in NAME_TO_CODE.items():
        if query in name.lower() or query in code.lower():
            codes_to_search.add(code)

    for key, value in KNOWN_STOCK_NAMES_MAP.items():
        if query in key.lower() or query in value.lower():
            codes_to_search.add(resolve_code(key))
            codes_to_search.add(resolve_code(value))

    if len(query) == 6 and query.isdigit():
        codes_to_search.add(query)

    if codes_to_search:
        all_stock_data = get_stock_data(list(codes_to_search))
        for code, stock_info in all_stock_data.items():
            if stock_info and stock_info.get('price', 0) > 0:
                results.append(stock_info)

    results.sort(key=lambda x: x['name'])
    return jsonify(results[:10])

@app.route('/api/load-data/<user_id>', methods=['GET'])
def load_user_data(user_id):
    conn = sqlite3.connect('family_portfolio.db')
    cursor = conn.cursor()
    cursor.execute('SELECT ticker FROM watchlist WHERE user_id = ?', (user_id,))
    watchlist = [row[0] for row in cursor.fetchall()]
    cursor.execute('SELECT member, account, name, ticker, quantity, dividend FROM portfolio WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    family_portfolio = {}
    for member, account, name, ticker, quantity, dividend in rows:
        if member not in family_portfolio:
            family_portfolio[member] = {}
        if account not in family_portfolio[member]:
            family_portfolio[member][account] = []
        family_portfolio[member][account].append({
            "name": name,
            "code": ticker,
            "quantity": quantity,
            "dividend": dividend
        })
        
    return jsonify({
        "watchlist": watchlist,
        "family_portfolio": family_portfolio
    })

@app.route('/api/save-data/<user_id>', methods=['POST'])
def save_user_data(user_id):
    req_data = request.get_json(silent=True) or {}
    watchlist = req_data.get('watchlist', [])
    family_portfolio = req_data.get('family_portfolio', {})
    
    conn = sqlite3.connect('family_portfolio.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM watchlist WHERE user_id = ?', (user_id,))
    for ticker in watchlist:
        cursor.execute('INSERT INTO watchlist (user_id, ticker) VALUES (?, ?)', (user_id, ticker))
        
    cursor.execute('DELETE FROM portfolio WHERE user_id = ?', (user_id,))
    for member, accounts in family_portfolio.items():
        for account, stocks in accounts.items():
            for stock in stocks:
                cursor.execute('''
                    INSERT INTO portfolio (user_id, member, account, name, ticker, quantity, dividend)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, member, account, stock.get('name'), stock.get('code'), stock.get('quantity', 0), stock.get('dividend', 0)))
                
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/history/<user_id>', methods=['GET'])
def get_history(user_id):
    conn = sqlite3.connect('family_portfolio.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT record_date, assets, return_rate, profit_loss, mom_assets, mom_return_rate, mom_profit_loss
        FROM investment_history WHERE user_id = ? ORDER BY id ASC
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "date": r[0],
            "assets": r[1],
            "return_rate": r[2],
            "profit_loss": r[3],
            "mom_assets": r[4],
            "mom_return_rate": r[5],
            "mom_profit_loss": r[6]
        })
    return jsonify(data)

@app.route('/api/history/<user_id>', methods=['POST'])
def save_history(user_id):
    req_data = request.get_json(silent=True) or {}
    history = req_data.get('history', [])
    
    conn = sqlite3.connect('family_portfolio.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM investment_history WHERE user_id = ?', (user_id,))
    
    for item in history:
        cursor.execute('''
            INSERT INTO investment_history 
            (user_id, record_date, assets, return_rate, profit_loss, mom_assets, mom_return_rate, mom_profit_loss)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, item.get('date'), item.get('assets', 0), item.get('return_rate', 0),
              item.get('profit_loss', 0), item.get('mom_assets', 0), 
              item.get('mom_return_rate', 0), item.get('mom_profit_loss', 0)))
        
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=True)