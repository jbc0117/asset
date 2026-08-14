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
APP_KEY = os.getenv("KIS_APPKEY", "")
APP_SECRET = os.getenv("KIS_APPSECRET", "")
CANO = os.getenv("KIS_CANO", "")
ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01")

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
    headers = {"content-type": "application/json"}
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
        else:
            print("토큰 발급 실패:", res_data)
            return None
    except Exception as e:
        print("토큰 요청 중 에러 발생:", e)
        return None


def get_kis_stock_price(code):
    """
    한국투자증권 국내주식 현재가 시세 API 호출 (FHKST01010100)
    stck_prpr: 주식 현재가 (실시간 체결가/종가)
    """
    token = get_access_token()
    if not token:
        return None

    url = f"{URL_BASE}/uapi/domestic-stock/v1/quoting/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        data = res.json()
        
        if data.get("rt_cd") == "0":
            output = data.get("output", {})
            
            # stck_prpr = 주식 현재가 (정수 변환)
            price = int(output.get("stck_prpr", 0))
            change = int(output.get("prdy_vrss", 0))          # 전일 대비
            change_rate = float(output.get("prdy_ctrt", 0))  # 전일 대비율 (%)
            
            # 전일 대비 부호 처리 (4: 하락, 5: 기여하락)
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
            print(f"[{code}] KIS API 오류:", data.get("msg1"))
            return None
    except Exception as e:
        print(f"[{code}] 시세 조회 연동 실패:", e)
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
        # 1. '005930.KS' -> '005930' 형태로 접미사 제거
        clean_code = raw_code.split('.')[0].strip().upper()

        # 2. 6자리 숫자 종목 코드 처리 (국내 주식)
        if len(clean_code) == 6 and clean_code.isdigit():
            stock_info = get_kis_stock_price(clean_code)
            if stock_info:
                # 프론트엔드가 요청한 키값(raw_code) 그대로 결과 매핑
                result[raw_code] = stock_info
                continue

        # 3. 기타 지수 및 예시 항목 처리
        if clean_code == "^KS11":
            result[raw_code] = {"name": "코스피", "price": 2750.50, "change": 15.20, "change_percent": 0.55}
        elif clean_code == "^KQ11":
            result[raw_code] = {"name": "코스닥", "price": 860.20, "change": -2.10, "change_percent": -0.24}
        elif clean_code in ["USDKRW=X", "USDKRW"]:
            result[raw_code] = {"name": "환율(USD)", "price": 1380.50, "change": -1.50, "change_percent": -0.11}
        elif clean_code == "KRX_GOLD_1G":
            result[raw_code] = {"name": "KRX 금(1g)", "price": 105000, "change": 500, "change_percent": 0.48}
        else:
            # 기본 예외 처리
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
    # 오라클 서버 방화벽에 열려있는 8501 포트로 설정
    app.run(host='0.0.0.0', port=8501, debug=True)
