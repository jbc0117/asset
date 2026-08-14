import os
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

app = Flask(__name__, template_folder='.')

# ---------------------------------------------------------------------------
# [환경 변수 로드]
# ---------------------------------------------------------------------------
APP_KEY = os.getenv("KIS_APPKEY", "").strip()
APP_SECRET = os.getenv("KIS_APPSECRET", "").strip()
CANO = os.getenv("KIS_CANO", "").strip()
ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01").strip()

# 한국투자증권 실전투자 Domain
URL_BASE = "https://openapi.koreainvestment.com:9443"

ACCESS_TOKEN = ""

def get_access_token():
    """
    한국투자증권 OAuth2.0 접근 토큰 발급
    """
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
        print("--- [토큰 발급 응답 상태코드] ---:", res.status_code)
        
        res_data = res.json()
        if "access_token" in res_data:
            ACCESS_TOKEN = res_data["access_token"]
            return ACCESS_TOKEN
        else:
            print("토큰 발급 실패 상세:", res_data)
            return None
    except Exception as e:
        print("토큰 요청 중 에러 발생:", e)
        return None


def get_kis_stock_price(code):
    """
    한국투자증권 국내주식 현재가 시세 API 호출 (FHKST01010100)
    """
    token = get_access_token()
    if not token:
        print(f"[{code}] 토큰이 없어 시세 조회를 진행하지 못합니다.")
        return None

    # 한국투자증권 공식 주식현재가 시세 URL
    url = f"{URL_BASE}/uapi/domestic-stock/v1/quoting/inquire-price"
    
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST01010100",
        "custtype": "P"  # 개인(P) 구분
    }
    
    # 한국투자증권 규격에 맞춘 대문자 쿼리 파라미터
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        print(f"--- [{code} 시세 응답 상태코드] ---:", res.status_code)
        
        data = res.json()
        if data.get("rt_cd") == "0":
            output = data.get("output", {})
            price = int(output.get("stck_prpr", 0))
            change = int(output.get("prdy_vrss", 0))
            change_rate = float(output.get("prdy_ctrt", 0))
            
            sign = output.get("prdy_vrss_sign", "3")
            if sign in ["4", "5"]:
                change = -abs(change)

            return {
                "name": output.get("hts_kor_isnm", code),
                "price": price,
                "change": change,
                "change_percent": change_rate
            }
        else:
            print(f"[{code}] KIS API 오류 메시지:", data.get("msg1"))
            return None
    except Exception as e:
        print(f"[{code}] 시세 조회 파싱 에러:", e)
        return None


# ---------------------------------------------------------------------------
# [라우트 정의]
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/stock-prices', methods=['POST'])
def api_stock_prices():
    req_data = request.get_json() or {}
    codes = req_data.get('codes', [])

    result = {}

    for raw_code in codes:
        clean_code = raw_code.split('.')[0].strip().upper()

        if len(clean_code) == 6 and clean_code.isdigit():
            stock_info = get_kis_stock_price(clean_code)
            if stock_info:
                result[raw_code] = stock_info
                result[clean_code] = stock_info
                continue

        if clean_code == "^KS11":
            result[raw_code] = {"name": "코스피", "price": 2750.50, "change": 15.20, "change_percent": 0.55}
        elif clean_code == "^KQ11":
            result[raw_code] = {"name": "코스닥", "price": 860.20, "change": -2.10, "change_percent": -0.24}
        elif clean_code in ["USDKRW=X", "USDKRW"]:
            result[raw_code] = {"name": "환율(USD)", "price": 1380.50, "change": -1.50, "change_percent": -0.11}
        elif clean_code == "KRX_GOLD_1G":
            result[raw_code] = {"name": "KRX 금(1g)", "price": 105000, "change": 500, "change_percent": 0.48}
        else:
            result[raw_code] = {"name": raw_code, "price": 0, "change": 0, "change_percent": 0.0}

    return jsonify(result)


@app.route('/api/search-stocks', methods=['GET'])
def search_stocks():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify([])

    sample_stocks = [
        {"code": "005930", "name": "삼성전자", "price": 0},
        {"code": "000660", "name": "SK하이닉스", "price": 0},
        {"code": "035420", "name": "NAVER", "price": 0},
        {"code": "035720", "name": "카카오", "price": 0},
        {"code": "005380", "name": "현대차", "price": 0},
    ]

    results = [s for s in sample_stocks if query in s['name'] or query in s['code']]
    
    for item in results:
        info = get_kis_stock_price(item['code'])
        if info:
            item['price'] = info['price']

    return jsonify(results)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=True)
