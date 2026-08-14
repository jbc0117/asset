# ... (상단 생략) ...

def get_kis_stock_price(code):
    """
    한국투자증권 국내주식 현재가 시세 API 호출 및 오류 상세 디버깅
    """
    token = get_access_token()
    if not token:
        return None

    # 경로 확인: /quotations/inquire-price
    url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
    
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST01010100",
        "custtype": "P"
    }
    
    # 6자리 코드 강제 적용
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": str(code).zfill(6) 
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                
                # 데이터가 비어있는지 확인
                if not output:
                    print(f"[{code}] 응답은 200이나 output 데이터가 비어있음.")
                    return None
                    
                price = int(output.get("stck_prpr", 0))
                change = int(output.get("prdy_vrss", 0))
                change_rate = float(output.get("prdy_ctrt", 0))
                
                sign = output.get("prdy_vrss_sign", "3")
                if sign in ["4", "5"]:
                    change = -abs(change)

                return {
                    "name": output.get("hts_kor_isnm", "Unknown"),
                    "price": price,
                    "change": change,
                    "change_percent": change_rate
                }
            else:
                # API 레벨 에러 메시지 출력
                print(f"[{code}] KIS API 비즈니스 오류: {data.get('msg1')}")
                return None
        else:
            print(f"[{code}] HTTP 오류 ({res.status_code}): {res.text}")
            return None
    except Exception as e:
        print(f"[{code}] 시세 조회 처리 중 예외 발생: {e}")
        return None

# ... (하단 라우트 부분 동일) ...
