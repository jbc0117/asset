from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)

# ==========================================
# 🔑 한국투자증권(KIS) Open API 설정
# 본인의 발급 정보로 변경해 주세요.
# ==========================================
KIS_APPKEY = "PSdhPrNbbSlUcAj7S6Cn62892BNxv4K4xELo"
KIS_APPSECRET = "IgHKIo/pL0/Aj6zjm9lcLZDVjFKBaaFkkUk6UUls3qtgvAVkr8NJ55rtSwaUCbZhbSaly3gc4JVyByPQNi/QmuZqWQU9b/q3flew+gXuvuR6elmq+iquZew/IGiY4nEMBJZZynpuAasE0s0CW3iHqOLGaYNxeHqia40bw22XtU/FEhUCFhc="
KIS_CANO = "10032116"       # 계좌번호 8자리 (필요시)
KIS_ACNT_PRDT_CD = "01"                # 계좌상품코드 2자리

# 실모의투자/실전투자 URL (실전: https://openapi.koreainvestment.com:9443)
# 모의투자: https://openapivts.koreainvestment.com:29443
KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"

# 토큰 및 시세 캐시
token_cache = {"token": "", "expires_at": 0}
stock_cache = {}

# 종목명 및 티커 매핑 (한국주식 6자리 종목코드 중심)
KNOWN_STOCK_NAMES_MAP = {
    "삼성전자": "005930", "sk하이닉스": "000660", "lg에너지솔루션": "373220",
    "naver": "035420", "네이버": "035420", "현대차": "005380",
    "타미당": "458730", "코나백": "379810", "솔미채": "490490",

    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "035420": "NAVER",
    "005380": "현대차",
    "458730": "타미당",
    "379810": "코나백",
    "490490": "솔미채"
}

def get_kis_access_token():
    """한국투자증권 접근 토큰(OAuth 2.0) 발급 및 자동 갱신 (유효기간: 24시간)"""
    now = time.time()
    if token_cache["token"] and token_cache["expires_at"] > now + 60:
        return token_cache["token"]

    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APPKEY,
        "appsecret": KIS_APPSECRET
    }
    
    try:
        res = requests.post(url, json=body, timeout=5)
        if res.status_code == 200:
            data = res.json()
            token_cache["token"] = data.get("access_token")
            # 86400초(24시간) 보관
            token_cache["expires_at"] = now + int(data.get("expires_in", 86400))
            return token_cache["token"]
    except Exception as e:
        print(f"KIS 토큰 발급 실패: {e}")
    
    return None

def fetch_kis_stock_price(stock_code):
    """한국투자증권 주식현재가 시세 API 호출 (FHKST01010100)"""
    # 6자리 종목코드로 변환 (ex: 005930.KS -> 005930)
    clean_code = stock_code.split('.')[0].zfill(6)
    
    token = get_kis_access_token()
    if not token:
        return None

    url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quoting/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APPKEY,
        "appsecret": KIS_APPSECRET,
        "tr_id": "FHKST01010100"  # 주식현재가 시세 TR ID
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": clean_code
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=3)
        if res.status_code == 200:
            output = res.json().get("output", {})
            if output and output.get("stck_prpr"):
                current_price = float(output["stck_prpr"])    # 현재가
                change = float(output["prdy_vrss"])            # 전일 대비 변동액
                change_percent = float(output["prdy_ctrt"])    # 등락률
                
                # KIS API에서 한글 종목명도 직접 받아올 수 있음 (hts_kor_isnm)
                stock_name = output.get("hts_kor_isnm") or KNOWN_STOCK_NAMES_MAP.get(clean_code, clean_code)

                return {
                    "code": clean_code,
                    "name": stock_name,
                    "price": current_price,
                    "change": change,
                    "change_percent": change_percent
                }
    except Exception as e:
        print(f"[{clean_code}] KIS 시세 조회 실패: {e}")

    return {
        "code": clean_code,
        "name": KNOWN_STOCK_NAMES_MAP.get(clean_code, clean_code),
        "price": 0.0,
        "change": 0.0,
        "change_percent": 0.0
    }

def get_stock_data(tickers):
    data = {}
    tickers_to_fetch = []

    for ticker in tickers:
        clean_code = ticker.split('.')[0]
        # 1분(60초) 캐싱
        if clean_code in stock_cache and time.time() - stock_cache[clean_code]['timestamp'] < 60:
            data[ticker] = stock_cache[clean_code]['data']
        else:
            tickers_to_fetch.append(ticker)

    for ticker in tickers_to_fetch:
        stock_info = fetch_kis_stock_price(ticker)
        if stock_info:
            data[ticker] = stock_info
            if stock_info['price'] > 0:
                stock_cache[stock_info['code']] = {'timestamp': time.time(), 'data': stock_info}

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

    # 1. 로컬 매핑 테이블 검색
    for name_or_alias, code in KNOWN_STOCK_NAMES_MAP.items():
        if query in name_or_alias.lower() or query in code.lower():
            codes_to_search.add(code)

    # 2. 숫자 6자리 종목코드 직접 검색 (ex: 005930)
    if query.isdigit() and len(query) == 6:
        codes_to_search.add(query)

    # KIS API 시세 검색/조회
    if codes_to_search:
        all_stock_data = get_stock_data(list(codes_to_search))
        for code, stock_info in all_stock_data.items():
            if stock_info and stock_info['price'] > 0:
                results.append(stock_info)

    results.sort(key=lambda x: x['name'])
    return jsonify(results[:10])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=True)
