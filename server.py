import re
import os
import json
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="방재실 주차 관제 통합 서버")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCS_CACHE_FILE = os.path.join(BASE_DIR, "scs_user.json")
ENEX_CACHE_FILE = os.path.join(BASE_DIR, "enex_log.json")

PROXY_BASE = "http://121.144.101.67:8080/http://192.168.100.10:9935"
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Authorization": AUTH_TOKEN,
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "http://192.168.100.10:84",
    "Referer": "http://192.168.100.10:84/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

def load_json_file(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_json_file(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_phone(item):
    for k in [
        "phoneno", "usertel", "scusertel", "tel",
        "hp", "mobile", "cellphone", "tel1",
    ]:
        val = str(item.get(k, "")).strip()
        if val and val != "-" and len(val) >= 7:
            return val
    return "-"

def extract_name(item):
    for k in ["siname", "owner", "scusername", "username", "name"]:
        val = str(item.get(k, "")).strip()
        if val and val not in ["정기", "일반", "방문", "사전예약", "아파트너", "-"]:
            return val
    raw = str(
        item.get("siname") or item.get("username") or item.get("scusername") or "-"
    ).strip()
    return raw if raw else "-"

# ✨ 차종(차량 모델명) 추출 함수
def extract_car_model(item):
    for k in [
        "cartypename", "cartype", "carmodel", "carname", 
        "carnm", "kind", "model", "cartype_name", "car_type"
    ]:
        val = str(item.get(k, "")).strip()
        if val and val not in ["-", "None", "null"]:
            return val
    return ""

@app.get("/")
def root():
    return {"status": "running", "message": "방재실 통합 관제 백엔드 정상 작동 중"}

# 1. 1방재실 데이터 동기화
@app.api_route("/sync", methods=["GET", "POST"])
def sync_data():
    try:
        # SCS 명부 동기화
        scs_url = f"{PROXY_BASE}/scs/get"
        scs_payload = {
            "parkname": "", "carno": "", "username": "", "org": "",
            "part": "", "pos": "", "scuserid": "", "scsttypeid": "",
            "shopid": "", "carexist": 0, "token": AUTH_TOKEN,
        }
        res_scs = requests.post(scs_url, json=scs_payload, headers=HEADERS, timeout=20)
        scs_list = []
        if res_scs.status_code == 200:
            parsed = res_scs.json()
            scs_list = parsed if isinstance(parsed, list) else parsed.get("list", [])
            save_json_file(SCS_CACHE_FILE, scs_list)

        # 입출차 로그 동기화 (최근 7일)
        today = datetime.now()
        b_date = (today - timedelta(days=7)).strftime("%Y-%m-%d") + "T00:00:00"
        e_date = today.strftime("%Y-%m-%d") + "T23:59:59"

        enex_url = f"{PROXY_BASE}/enexrcg"
        enex_payload = {
            "parkno": "", "bgndt": b_date, "enddt": e_date,
            "carno": "", "enextypeid": "", "tkttypeid": "", "eqno": "",
        }
        res_enex = requests.post(enex_url, json=enex_payload, headers=HEADERS, timeout=25)
        enex_list = []
        if res_enex.status_code == 200 and len(res_enex.text) > 10:
            try:
                parsed = res_enex.json()
                enex_list = (
                    parsed if isinstance(parsed, list)
                    else (parsed.get("rows") or parsed.get("data") or parsed.get("list") or [])
                )
                save_json_file(ENEX_CACHE_FILE, enex_list)
            except Exception:
                pass

        return {
            "result": "success",
            "message": "1방재실 데이터 동기화 완료",
            "scs_count": len(scs_list),
            "enex_count": len(enex_list),
        }
    except Exception as e:
        return {"result": "error", "message": str(e)}

# 2. 통합 검색 (?q= 차량번호, 이름, 동호수, 전화번호)
@app.get("/search")
def search_car(
    q: str = Query("", description="검색어 (차량번호, 사람 이름, 동호수, 전화번호)"),
    carno: str = Query("", description="차량번호"),
    name: str = Query("", description="이름"),
):
    keyword = (q.strip() or carno.strip() or name.strip()).replace(" ", "")
    if not keyword:
        return {"result": "success", "count": 0, "data": []}

    is_four_digits = keyword.isdigit() and len(keyword) == 4

    scs_data = load_json_file(SCS_CACHE_FILE)
    enex_data = load_json_file(ENEX_CACHE_FILE)

    # 1) 입출차 로그에서 차량별 최신 상태 및 전체 히스토리 누적
    enex_map = {}
    for log in enex_data:
        c = str(log.get("carno", "")).strip().replace(" ", "")
        if not c:
            continue
        io_type = str(log.get("enextypename") or log.get("io") or "-").strip()
        event_time = str(log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-")
        gate = str(log.get("eqname") or log.get("parkname") or "-")

        hist_item = {
            "io_type": io_type,
            "gate": gate,
            "time": event_time,
        }

        if c not in enex_map:
            enex_map[c] = {
                "parking_status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
                "last_event": f"{io_type} ({gate})",
                "last_time": event_time,
                "history": [hist_item],
            }
        else:
            if len(enex_map[c]["history"]) < 20:
                enex_map[c]["history"].append(hist_item)

    matched = []
    matched_carnos = set()

    def get_match_type(target_carno, target_name, target_dongho, target_phone):
        clean_c = target_carno.replace(" ", "")
        
        # 1. 차량번호: 4자리 숫자면 끝 4자리만 일치, 아니면 전체 포함
        if is_four_digits:
            if clean_c.endswith(keyword):
                return "carno"
        else:
            if keyword in clean_c:
                return "carno"

        # 2. 전화번호 정밀 매칭
        digits = "".join([ch for ch in str(target_phone) if ch.isdigit()])
        if len(digits) >= 7:
            if is_four_digits:
                last_4 = digits[-4:]
                mid_4 = digits[-8:-4]
                if keyword == last_4 or keyword == mid_4:
                    return "phone"
            else:
                if keyword in digits:
                    return "phone"

        # 3. 이름 매칭
        if target_name != "-" and keyword in target_name:
            return "name"

        # 4. 동호수 스마트 정밀 매칭
        q_numbers = re.findall(r'\d+', q)
        target_numbers = re.findall(r'\d+', target_dongho)

        if len(q_numbers) >= 2 and len(target_numbers) >= 2:
            if q_numbers[0] == target_numbers[0] and q_numbers[1] == target_numbers[1]:
                return "dongho"
        elif not is_four_digits:
            clean_dongho = target_dongho.replace(" ", "")
            norm_keyword = keyword.replace("-", "").replace(" ", "")
            if norm_keyword and (norm_keyword in clean_dongho):
                return "dongho"

        return None

    # 2) SCS 정기권/예약 명부 우선 조회
    for item in scs_data:
        c = str(item.get("carno", "")).strip()
        clean_c = c.replace(" ", "")
        if not clean_c:
            continue

        u_name = extract_name(item)
        car_model = extract_car_model(item)
        dong = str(item.get("part", "") or item.get("dong", "")).strip()
        ho = str(item.get("pos", "") or item.get("ho", "")).strip()
        org = str(item.get("org", "")).strip()
        dong_ho = f"{dong}동 {ho}호" if dong and ho else (org if org else "-")
        phone = extract_phone(item)

        m_type = get_match_type(c, u_name, dong_ho, phone)
        if m_type:
            log_info = enex_map.get(clean_c)
            matched.append({
                "carno": c,
                "car_model": car_model,
                "name": u_name,
                "dong_ho": dong_ho,
                "phone": phone,
                "match_type": m_type,
                "parking_status": log_info["parking_status"] if log_info else "⚪ 미통과 (기록 없음)",
                "last_event": log_info["last_event"] if log_info else "-",
                "last_time": log_info["last_time"] if log_info else "-",
                "history": log_info["history"] if log_info else [],
            })
            matched_carnos.add(clean_c)

    # 3) SCS 명부에 없는 일반 방문차량 보충
    for item in enex_data:
        c = str(item.get("carno", "")).strip()
        clean_c = c.replace(" ", "")
        if not clean_c or clean_c in matched_carnos:
            continue

        s_name = extract_name(item)
        car_model = extract_car_model(item)
        dong = str(item.get("part", "")).strip()
        ho = str(item.get("pos", "")).strip()
        dong_ho = f"{dong}동 {ho}호" if dong and ho else "-"
        phone = extract_phone(item)

        m_type = get_match_type(c, s_name, dong_ho, phone)
        if m_type:
            log_info = enex_map.get(clean_c, {})
            matched.append({
                "carno": c,
                "car_model": car_model,
                "name": s_name,
                "dong_ho": dong_ho,
                "phone": phone,
                "match_type": m_type,
                "parking_status": log_info.get("parking_status", "⚪ 출차 완료"),
                "last_event": log_info.get("last_event", "-"),
                "last_time": log_info.get("last_time", "-"),
                "history": log_info.get("history", []),
            })
            matched_carnos.add(clean_c)

    return {"result": "success", "count": len(matched), "data": matched[:100]}

# 3. 아파트너 예약차량 단독 엔드포인트
@app.get("/reserved")
def get_reserved_cars(target_date: str = Query("", description="조회일자")):
    scs_data = load_json_file(SCS_CACHE_FILE)
    enex_data = load_json_file(ENEX_CACHE_FILE)
    clean_target = target_date.replace("-", "").strip()

    enex_status_map = {}
    for log in enex_data:
        c = str(log.get("carno", "")).strip().replace(" ", "")
        if not c or c in enex_status_map:
            continue
        io_type = str(log.get("enextypename") or log.get("io") or "-").strip()
        event_time = str(log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-")
        gate = str(log.get("eqname") or log.get("parkname") or "-")

        enex_status_map[c] = {
            "status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
            "last_event": f"{io_type} ({gate})",
            "last_time": event_time,
        }

    results = []
    for item in scs_data:
        sc_user = str(item.get("scusername", ""))
        msg = str(item.get("msg", ""))
        memo = str(item.get("memo", ""))

        if (
            "아파트너사전예약" in sc_user
            or "APTNER" in msg
            or "아파트너" in memo
            or "사전예약" in sc_user
        ):
            bgn = str(item.get("usebgndt", ""))
            clean_bgn = bgn.replace("-", "").split(" ")[0] if bgn else ""
            res_date = bgn.split(" ")[0] if bgn else "-"

            if clean_target and clean_bgn and (clean_target not in clean_bgn):
                continue

            dong = str(item.get("part", "")).strip()
            ho = str(item.get("pos", "")).strip()
            org = str(item.get("org", "")).strip()
            dong_ho = f"{dong}동 {ho}호" if (dong and ho) else (org if org else "-")

            carno = str(item.get("carno", "-"))
            clean_carno = carno.replace(" ", "")

            log_info = enex_status_map.get(clean_carno, {})
            p_status = log_info.get("status", "입차 대기")
            l_event = log_info.get("last_event", "-")
            l_time = log_info.get("last_time", "-")

            results.append({
                "carno": carno,
                "car_type": "예약",
                "name": "아파트너사전예약",
                "phone": extract_phone(item),
                "dong_ho": dong_ho,
                "res_date": res_date,
                "start_time": item.get("usebgndt", "-"),
                "end_time": item.get("useenddt", "-"),
                "registered_at": item.get("mkdt", "-"),
                "parking_status": p_status,
                "last_event": l_event,
                "last_time": l_time,
            })

    return {"result": "success", "count": len(results), "data": results}


















# import re
# import os
# import json
# import requests
# from datetime import datetime, timedelta
# from fastapi import FastAPI, Query
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI(title="방재실 주차 관제 통합 서버")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# SCS_CACHE_FILE = os.path.join(BASE_DIR, "scs_user.json")
# ENEX_CACHE_FILE = os.path.join(BASE_DIR, "enex_log.json")

# PROXY_BASE = "http://121.144.101.67:8080/http://192.168.100.10:9935"
# AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# HEADERS = {
#     "Accept": "application/json, text/javascript, */*; q=0.01",
#     "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
#     "Authorization": AUTH_TOKEN,
#     "Connection": "keep-alive",
#     "Content-Type": "application/json",
#     "Origin": "http://192.168.100.10:84",
#     "Referer": "http://192.168.100.10:84/",
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
# }

# def load_json_file(file_path):
#     if os.path.exists(file_path):
#         try:
#             with open(file_path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception:
#             return []
#     return []

# def save_json_file(file_path, data):
#     with open(file_path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)

# def extract_phone(item):
#     for k in [
#         "phoneno", "usertel", "scusertel", "tel",
#         "hp", "mobile", "cellphone", "tel1",
#     ]:
#         val = str(item.get(k, "")).strip()
#         if val and val != "-" and len(val) >= 7:
#             return val
#     return "-"

# def extract_name(item):
#     for k in ["siname", "owner", "scusername", "username", "name"]:
#         val = str(item.get(k, "")).strip()
#         if val and val not in ["정기", "일반", "방문", "사전예약", "아파트너", "-"]:
#             return val
#     raw = str(
#         item.get("siname") or item.get("username") or item.get("scusername") or "-"
#     ).strip()
#     return raw if raw else "-"

# # ✨ 차종(차량 모델명) 추출 함수
# def extract_car_model(item):
#     for k in ["cartypename", "cartype", "carmodel", "carnm", "model", "kind"]:
#         val = str(item.get(k, "")).strip()
#         if val and val not in ["-", "None", "null"]:
#             return val
#     return ""

# @app.get("/")
# def root():
#     return {"status": "running", "message": "방재실 통합 관제 백엔드 정상 작동 중"}

# # 1. 1방재실 데이터 동기화
# @app.api_route("/sync", methods=["GET", "POST"])
# def sync_data():
#     try:
#         # SCS 명부 동기화
#         scs_url = f"{PROXY_BASE}/scs/get"
#         scs_payload = {
#             "parkname": "", "carno": "", "username": "", "org": "",
#             "part": "", "pos": "", "scuserid": "", "scsttypeid": "",
#             "shopid": "", "carexist": 0, "token": AUTH_TOKEN,
#         }
#         res_scs = requests.post(scs_url, json=scs_payload, headers=HEADERS, timeout=20)
#         scs_list = []
#         if res_scs.status_code == 200:
#             parsed = res_scs.json()
#             scs_list = parsed if isinstance(parsed, list) else parsed.get("list", [])
#             save_json_file(SCS_CACHE_FILE, scs_list)

#         # 입출차 로그 동기화 (최근 7일)
#         today = datetime.now()
#         b_date = (today - timedelta(days=7)).strftime("%Y-%m-%d") + "T00:00:00"
#         e_date = today.strftime("%Y-%m-%d") + "T23:59:59"

#         enex_url = f"{PROXY_BASE}/enexrcg"
#         enex_payload = {
#             "parkno": "", "bgndt": b_date, "enddt": e_date,
#             "carno": "", "enextypeid": "", "tkttypeid": "", "eqno": "",
#         }
#         res_enex = requests.post(enex_url, json=enex_payload, headers=HEADERS, timeout=25)
#         enex_list = []
#         if res_enex.status_code == 200 and len(res_enex.text) > 10:
#             try:
#                 parsed = res_enex.json()
#                 enex_list = (
#                     parsed if isinstance(parsed, list)
#                     else (parsed.get("rows") or parsed.get("data") or parsed.get("list") or [])
#                 )
#                 save_json_file(ENEX_CACHE_FILE, enex_list)
#             except Exception:
#                 pass

#         return {
#             "result": "success",
#             "message": "1방재실 데이터 동기화 완료",
#             "scs_count": len(scs_list),
#             "enex_count": len(enex_list),
#         }
#     except Exception as e:
#         return {"result": "error", "message": str(e)}

# # 2. 통합 검색 (?q= 차량번호, 이름, 동호수, 전화번호)
# @app.get("/search")
# def search_car(
#     q: str = Query("", description="검색어 (차량번호, 사람 이름, 동호수, 전화번호)"),
#     carno: str = Query("", description="차량번호"),
#     name: str = Query("", description="이름"),
# ):
#     keyword = (q.strip() or carno.strip() or name.strip()).replace(" ", "")
#     if not keyword:
#         return {"result": "success", "count": 0, "data": []}

#     is_four_digits = keyword.isdigit() and len(keyword) == 4

#     scs_data = load_json_file(SCS_CACHE_FILE)
#     enex_data = load_json_file(ENEX_CACHE_FILE)

#     # 1) 입출차 로그에서 차량별 최신 상태 및 전체 히스토리 누적
#     enex_map = {}
#     for log in enex_data:
#         c = str(log.get("carno", "")).strip().replace(" ", "")
#         if not c:
#             continue
#         io_type = str(log.get("enextypename") or log.get("io") or "-").strip()
#         event_time = str(log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-")
#         gate = str(log.get("eqname") or log.get("parkname") or "-")

#         hist_item = {
#             "io_type": io_type,
#             "gate": gate,
#             "time": event_time,
#         }

#         if c not in enex_map:
#             enex_map[c] = {
#                 "parking_status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
#                 "last_event": f"{io_type} ({gate})",
#                 "last_time": event_time,
#                 "history": [hist_item],
#             }
#         else:
#             if len(enex_map[c]["history"]) < 20:
#                 enex_map[c]["history"].append(hist_item)

#     matched = []
#     matched_carnos = set()

#     def get_match_type(target_carno, target_name, target_dongho, target_phone):
#         clean_c = target_carno.replace(" ", "")
        
#         # 1. 차량번호: 4자리 숫자면 끝 4자리만 일치, 아니면 전체 포함
#         if is_four_digits:
#             if clean_c.endswith(keyword):
#                 return "carno"
#         else:
#             if keyword in clean_c:
#                 return "carno"

#         # 2. 전화번호 정밀 매칭
#         digits = "".join([ch for ch in str(target_phone) if ch.isdigit()])
#         if len(digits) >= 7:
#             if is_four_digits:
#                 last_4 = digits[-4:]
#                 mid_4 = digits[-8:-4]
#                 if keyword == last_4 or keyword == mid_4:
#                     return "phone"
#             else:
#                 if keyword in digits:
#                     return "phone"

#         # 3. 이름 매칭
#         if target_name != "-" and keyword in target_name:
#             return "name"

#         # 4. 동호수 스마트 정밀 매칭 (122-202, 122동 202호 등 완벽 대응)
#         q_numbers = re.findall(r'\d+', q)
#         target_numbers = re.findall(r'\d+', target_dongho)

#         if len(q_numbers) >= 2 and len(target_numbers) >= 2:
#             if q_numbers[0] == target_numbers[0] and q_numbers[1] == target_numbers[1]:
#                 return "dongho"
#         elif not is_four_digits:
#             clean_dongho = target_dongho.replace(" ", "")
#             norm_keyword = keyword.replace("-", "").replace(" ", "")
#             if norm_keyword and (norm_keyword in clean_dongho):
#                 return "dongho"

#         return None

#     # 2) SCS 정기권/예약 명부 우선 조회
#     for item in scs_data:
#         c = str(item.get("carno", "")).strip()
#         clean_c = c.replace(" ", "")
#         if not clean_c:
#             continue

#         u_name = extract_name(item)
#         car_model = extract_car_model(item)
#         dong = str(item.get("part", "") or item.get("dong", "")).strip()
#         ho = str(item.get("pos", "") or item.get("ho", "")).strip()
#         org = str(item.get("org", "")).strip()
#         dong_ho = f"{dong}동 {ho}호" if dong and ho else (org if org else "-")
#         phone = extract_phone(item)

#         m_type = get_match_type(c, u_name, dong_ho, phone)
#         if m_type:
#             log_info = enex_map.get(clean_c)
#             matched.append({
#                 "carno": c,
#                 "car_model": car_model,
#                 "name": u_name,
#                 "dong_ho": dong_ho,
#                 "phone": phone,
#                 "match_type": m_type,
#                 "parking_status": log_info["parking_status"] if log_info else "⚪ 미통과 (기록 없음)",
#                 "last_event": log_info["last_event"] if log_info else "-",
#                 "last_time": log_info["last_time"] if log_info else "-",
#                 "history": log_info["history"] if log_info else [],
#             })
#             matched_carnos.add(clean_c)

#     # 3) SCS 명부에 없는 일반 방문차량 보충
#     for item in enex_data:
#         c = str(item.get("carno", "")).strip()
#         clean_c = c.replace(" ", "")
#         if not clean_c or clean_c in matched_carnos:
#             continue

#         s_name = extract_name(item)
#         car_model = extract_car_model(item)
#         dong = str(item.get("part", "")).strip()
#         ho = str(item.get("pos", "")).strip()
#         dong_ho = f"{dong}동 {ho}호" if dong and ho else "-"
#         phone = extract_phone(item)

#         m_type = get_match_type(c, s_name, dong_ho, phone)
#         if m_type:
#             log_info = enex_map.get(clean_c, {})
#             matched.append({
#                 "carno": c,
#                 "car_model": car_model,
#                 "name": s_name,
#                 "dong_ho": dong_ho,
#                 "phone": phone,
#                 "match_type": m_type,
#                 "parking_status": log_info.get("parking_status", "⚪ 출차 완료"),
#                 "last_event": log_info.get("last_event", "-"),
#                 "last_time": log_info.get("last_time", "-"),
#                 "history": log_info.get("history", []),
#             })
#             matched_carnos.add(clean_c)

#     return {"result": "success", "count": len(matched), "data": matched[:100]}

# # 3. 아파트너 예약차량 단독 엔드포인트
# @app.get("/reserved")
# def get_reserved_cars(target_date: str = Query("", description="조회일자")):
#     scs_data = load_json_file(SCS_CACHE_FILE)
#     enex_data = load_json_file(ENEX_CACHE_FILE)
#     clean_target = target_date.replace("-", "").strip()

#     enex_status_map = {}
#     for log in enex_data:
#         c = str(log.get("carno", "")).strip().replace(" ", "")
#         if not c or c in enex_status_map:
#             continue
#         io_type = str(log.get("enextypename") or log.get("io") or "-").strip()
#         event_time = str(log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-")
#         gate = str(log.get("eqname") or log.get("parkname") or "-")

#         enex_status_map[c] = {
#             "status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
#             "last_event": f"{io_type} ({gate})",
#             "last_time": event_time,
#         }

#     results = []
#     for item in scs_data:
#         sc_user = str(item.get("scusername", ""))
#         msg = str(item.get("msg", ""))
#         memo = str(item.get("memo", ""))

#         if (
#             "아파트너사전예약" in sc_user
#             or "APTNER" in msg
#             or "아파트너" in memo
#             or "사전예약" in sc_user
#         ):
#             bgn = str(item.get("usebgndt", ""))
#             clean_bgn = bgn.replace("-", "").split(" ")[0] if bgn else ""
#             res_date = bgn.split(" ")[0] if bgn else "-"

#             if clean_target and clean_bgn and (clean_target not in clean_bgn):
#                 continue

#             dong = str(item.get("part", "")).strip()
#             ho = str(item.get("pos", "")).strip()
#             org = str(item.get("org", "")).strip()
#             dong_ho = f"{dong}동 {ho}호" if (dong and ho) else (org if org else "-")

#             carno = str(item.get("carno", "-"))
#             clean_carno = carno.replace(" ", "")

#             log_info = enex_status_map.get(clean_carno, {})
#             p_status = log_info.get("status", "입차 대기")
#             l_event = log_info.get("last_event", "-")
#             l_time = log_info.get("last_time", "-")

#             results.append({
#                 "carno": carno,
#                 "car_type": "예약",
#                 "name": "아파트너사전예약",
#                 "phone": extract_phone(item),
#                 "dong_ho": dong_ho,
#                 "res_date": res_date,
#                 "start_time": item.get("usebgndt", "-"),
#                 "end_time": item.get("useenddt", "-"),
#                 "registered_at": item.get("mkdt", "-"),
#                 "parking_status": p_status,
#                 "last_event": l_event,
#                 "last_time": l_time,
#             })

#     return {"result": "success", "count": len(results), "data": results}














# import re
# import os
# import json
# import requests
# from datetime import datetime, timedelta
# from fastapi import FastAPI, Query
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI(title="방재실 주차 관제 통합 서버")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# SCS_CACHE_FILE = os.path.join(BASE_DIR, "scs_user.json")
# ENEX_CACHE_FILE = os.path.join(BASE_DIR, "enex_log.json")

# PROXY_BASE = "http://121.144.101.67:8080/http://192.168.100.10:9935"
# AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# HEADERS = {
#     "Accept": "application/json, text/javascript, */*; q=0.01",
#     "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
#     "Authorization": AUTH_TOKEN,
#     "Connection": "keep-alive",
#     "Content-Type": "application/json",
#     "Origin": "http://192.168.100.10:84",
#     "Referer": "http://192.168.100.10:84/",
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
# }

# def load_json_file(file_path):
#     if os.path.exists(file_path):
#         try:
#             with open(file_path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception:
#             return []
#     return []

# def save_json_file(file_path, data):
#     with open(file_path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)

# def extract_phone(item):
#     for k in [
#         "phoneno", "usertel", "scusertel", "tel",
#         "hp", "mobile", "cellphone", "tel1",
#     ]:
#         val = str(item.get(k, "")).strip()
#         if val and val != "-" and len(val) >= 7:
#             return val
#     return "-"

# def extract_name(item):
#     for k in ["siname", "owner", "scusername", "username", "name"]:
#         val = str(item.get(k, "")).strip()
#         if val and val not in ["정기", "일반", "방문", "사전예약", "아파트너", "-"]:
#             return val
#     raw = str(
#         item.get("siname") or item.get("username") or item.get("scusername") or "-"
#     ).strip()
#     return raw if raw else "-"



# @app.get("/")
# def root():
#     return {"status": "running", "message": "방재실 통합 관제 백엔드 정상 작동 중"}

# # 1. 1방재실 데이터 동기화
# @app.api_route("/sync", methods=["GET", "POST"])
# def sync_data():
#     try:
#         # SCS 명부 동기화
#         scs_url = f"{PROXY_BASE}/scs/get"
#         scs_payload = {
#             "parkname": "", "carno": "", "username": "", "org": "",
#             "part": "", "pos": "", "scuserid": "", "scsttypeid": "",
#             "shopid": "", "carexist": 0, "token": AUTH_TOKEN,
#         }
#         res_scs = requests.post(scs_url, json=scs_payload, headers=HEADERS, timeout=20)
#         scs_list = []
#         if res_scs.status_code == 200:
#             parsed = res_scs.json()
#             scs_list = parsed if isinstance(parsed, list) else parsed.get("list", [])
#             save_json_file(SCS_CACHE_FILE, scs_list)

#         # 입출차 로그 동기화 (최근 7일)
#         today = datetime.now()
#         b_date = (today - timedelta(days=7)).strftime("%Y-%m-%d") + "T00:00:00"
#         e_date = today.strftime("%Y-%m-%d") + "T23:59:59"

#         enex_url = f"{PROXY_BASE}/enexrcg"
#         enex_payload = {
#             "parkno": "", "bgndt": b_date, "enddt": e_date,
#             "carno": "", "enextypeid": "", "tkttypeid": "", "eqno": "",
#         }
#         res_enex = requests.post(enex_url, json=enex_payload, headers=HEADERS, timeout=25)
#         enex_list = []
#         if res_enex.status_code == 200 and len(res_enex.text) > 10:
#             try:
#                 parsed = res_enex.json()
#                 enex_list = (
#                     parsed if isinstance(parsed, list)
#                     else (parsed.get("rows") or parsed.get("data") or parsed.get("list") or [])
#                 )
#                 save_json_file(ENEX_CACHE_FILE, enex_list)
#             except Exception:
#                 pass

#         return {
#             "result": "success",
#             "message": "1방재실 데이터 동기화 완료",
#             "scs_count": len(scs_list),
#             "enex_count": len(enex_list),
#         }
#     except Exception as e:
#         return {"result": "error", "message": str(e)}

# # 2. 통합 검색 (?q= 차량번호, 이름, 동호수, 전화번호)
# @app.get("/search")
# def search_car(
#     q: str = Query("", description="검색어 (차량번호, 사람 이름, 동호수, 전화번호)"),
#     carno: str = Query("", description="차량번호"),
#     name: str = Query("", description="이름"),
# ):
#     keyword = (q.strip() or carno.strip() or name.strip()).replace(" ", "")
#     if not keyword:
#         return {"result": "success", "count": 0, "data": []}

#     is_four_digits = keyword.isdigit() and len(keyword) == 4

#     scs_data = load_json_file(SCS_CACHE_FILE)
#     enex_data = load_json_file(ENEX_CACHE_FILE)

#     # 1) 입출차 로그에서 차량별 '최신 상태' 및 '과거 전체 통과 내역(history)' 누적
#     enex_map = {}
#     for log in enex_data:
#         c = str(log.get("carno", "")).strip().replace(" ", "")
#         if not c:
#             continue
#         io_type = str(log.get("enextypename") or log.get("io") or "-").strip()
#         event_time = str(log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-")
#         gate = str(log.get("eqname") or log.get("parkname") or "-")

#         hist_item = {
#             "io_type": io_type,
#             "gate": gate,
#             "time": event_time,
#         }

#         if c not in enex_map:
#             enex_map[c] = {
#                 "parking_status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
#                 "last_event": f"{io_type} ({gate})",
#                 "last_time": event_time,
#                 "history": [hist_item],
#             }
#         else:
#             if len(enex_map[c]["history"]) < 20:
#                 enex_map[c]["history"].append(hist_item)

#     matched = []
#     matched_carnos = set()

#     # def get_match_type(target_carno, target_name, target_dongho, target_phone):
#     #     clean_c = target_carno.replace(" ", "")
#     #     clean_p = target_phone.replace("-", "").strip()

#     #     # 차량번호 뒷자리(4자리 검색 시) 또는 포함
#     #     if (is_four_digits and clean_c.endswith(keyword)) or (not is_four_digits and keyword in clean_c):
#     #         return "carno"
#     #     # 전화번호 매칭 (끝자리 또는 포함)
#     #     if clean_p != "-" and keyword in clean_p:
#     #         return "phone"
#     #     # 이름 매칭
#     #     if target_name != "-" and keyword in target_name:
#     #         return "name"
#     #     # 동호수 매칭
#     #     if keyword in target_dongho.replace(" ", ""):
#     #         return "dongho"
#     #     return None

#     # def get_match_type(target_carno, target_name, target_dongho, target_phone):
#     #     clean_c = target_carno.replace(" ", "")
#     #     clean_p = target_phone.replace("-", "").strip()

#     #     # 1. 차량번호: 4자리 입력 시 끝자리 일치, 그 외는 포함
#     #     if (is_four_digits and clean_c.endswith(keyword)) or (not is_four_digits and keyword in clean_c):
#     #         return "carno"

#     #     # 2. 전화번호 정밀 매칭:
#     #     # 4자리 검색 시 국번(중간 4자리)이나 뒷번호(끝 4자리)와 딱 맞을 때만 인정!
#     #     if clean_p != "-" and len(clean_p) >= 8:
#     #         if is_four_digits:
#     #             # 010-XXXX-YYYY 구조에서 중간 4자리(clean_p[-8:-4]) 또는 끝 4자리(clean_p[-4:])
#     #             mid_4 = clean_p[-8:-4]
#     #             last_4 = clean_p[-4:]
#     #             if keyword == mid_4 or keyword == last_4:
#     #                 return "phone"
#     #         else:
#     #             if keyword in clean_p:
#     #                 return "phone"

#     #     # 3. 이름 매칭
#     #     if target_name != "-" and keyword in target_name:
#     #         return "name"

#     #     # 4. 동호수 매칭
#     #     if keyword in target_dongho.replace(" ", ""):
#     #         return "dongho"

#     #     return None

#     # def get_match_type(target_carno, target_name, target_dongho, target_phone):
#     #     clean_c = target_carno.replace(" ", "")
        
#     #     # 1. 차량번호 매칭: 4자리 숫자면 끝 4자리만 일치, 아니면 포함
#     #     if is_four_digits:
#     #         if clean_c.endswith(keyword):
#     #             return "carno"
#     #     else:
#     #         if keyword in clean_c:
#     #             return "carno"

#     #     # 2. 전화번호 매칭: 숫자만 추출해서 국번(가운데) 또는 뒷자리(끝)와 정확히 일치하는지 확인
#     #     only_digits = re.sub(r'[^0-9]', '', target_phone)
#     #     if len(only_digits) >= 8:
#     #         if is_four_digits:
#     #             # 번호가 11자리(010-1234-5678)면: 국번=1234, 뒷자리=5678
#     #             # 번호가 10자리(02-1234-5678 등)면: 국번=1234, 뒷자리=5678
#     #             last4 = only_digits[-4:]
#     #             mid4 = only_digits[-8:-4]
#     #             if keyword == last4 or keyword == mid4:
#     #                 return "phone"
#     #         else:
#     #             if keyword in only_digits:
#     #                 return "phone"

#     #     # 3. 이름 매칭
#     #     if target_name != "-" and keyword in target_name:
#     #         return "name"

#     #     # 4. 동호수 매칭 (숫자 4자리일 때는 동/호수 숫자가 딱 떨어지는지 확인)
#     #     clean_dongho = target_dongho.replace(" ", "")
#     #     if not is_four_digits and keyword in clean_dongho:
#     #         return "dongho"

#     #     return None




#     def get_match_type(target_carno, target_name, target_dongho, target_phone):
#         clean_c = target_carno.replace(" ", "")
        
#         # 1. 차량번호: 4자리 숫자면 끝 4자리만 일치, 아니면 전체 포함
#         if is_four_digits:
#             if clean_c.endswith(keyword):
#                 return "carno"
#         else:
#             if keyword in clean_c:
#                 return "carno"

#         # 2. 전화번호 정밀 매칭
#         digits = "".join([ch for ch in str(target_phone) if ch.isdigit()])
#         if len(digits) >= 7:
#             if is_four_digits:
#                 last_4 = digits[-4:]
#                 mid_4 = digits[-8:-4]
#                 if keyword == last_4 or keyword == mid_4:
#                     return "phone"
#             else:
#                 if keyword in digits:
#                     return "phone"

#         # 3. 이름 매칭
#         if target_name != "-" and keyword in target_name:
#             return "name"

#         # 4. 동호수 스마트 정밀 매칭 (122-202, 122동 202호 등 완벽 대응)
#         # 검색어에서 숫자 덩어리들을 추출 (예: "122-202" -> ['122', '202'])
#         q_numbers = re.findall(r'\d+', q)
#         target_numbers = re.findall(r'\d+', target_dongho)

#         if len(q_numbers) >= 2 and len(target_numbers) >= 2:
#             # 검색어의 첫 번째 숫자가 '동', 두 번째 숫자가 '호'와 완벽히 일치할 때만 매칭
#             if q_numbers[0] == target_numbers[0] and q_numbers[1] == target_numbers[1]:
#                 return "dongho"
#         elif not is_four_digits:
#             # 단일 단어 검색일 경우 (예: "122동")
#             clean_dongho = target_dongho.replace(" ", "")
#             norm_keyword = keyword.replace("-", "").replace(" ", "")
#             if norm_keyword and (norm_keyword in clean_dongho):
#                 return "dongho"

#         return None

#         # 일반 단어/숫자 포함 검사 (단순 4자리 숫자는 제외하여 잡음 방지)
#         if not is_four_digits and norm_keyword and (norm_keyword in norm_dongho):
#             return "dongho"

#         return None

#     # 2) SCS 정기권/예약 명부 우선 조회
#     for item in scs_data:
#         c = str(item.get("carno", "")).strip()
#         clean_c = c.replace(" ", "")
#         if not clean_c:
#             continue

#         u_name = extract_name(item)
#         dong = str(item.get("part", "") or item.get("dong", "")).strip()
#         ho = str(item.get("pos", "") or item.get("ho", "")).strip()
#         org = str(item.get("org", "")).strip()
#         dong_ho = f"{dong}동 {ho}호" if dong and ho else (org if org else "-")
#         phone = extract_phone(item)

#         m_type = get_match_type(c, u_name, dong_ho, phone)
#         if m_type:
#             log_info = enex_map.get(clean_c)
#             matched.append({
#                 "carno": c,
#                 "name": u_name,
#                 "dong_ho": dong_ho,
#                 "phone": phone,
#                 "match_type": m_type,
#                 "parking_status": log_info["parking_status"] if log_info else "⚪ 미통과 (기록 없음)",
#                 "last_event": log_info["last_event"] if log_info else "-",
#                 "last_time": log_info["last_time"] if log_info else "-",
#                 "history": log_info["history"] if log_info else [],
#             })
#             matched_carnos.add(clean_c)

#     # 3) SCS 명부에 없는 일반 방문차량 보충
#     for item in enex_data:
#         c = str(item.get("carno", "")).strip()
#         clean_c = c.replace(" ", "")
#         if not clean_c or clean_c in matched_carnos:
#             continue

#         s_name = extract_name(item)
#         dong = str(item.get("part", "")).strip()
#         ho = str(item.get("pos", "")).strip()
#         dong_ho = f"{dong}동 {ho}호" if dong and ho else "-"
#         phone = extract_phone(item)

#         m_type = get_match_type(c, s_name, dong_ho, phone)
#         if m_type:
#             log_info = enex_map.get(clean_c, {})
#             matched.append({
#                 "carno": c,
#                 "name": s_name,
#                 "dong_ho": dong_ho,
#                 "phone": phone,
#                 "match_type": m_type,
#                 "parking_status": log_info.get("parking_status", "⚪ 출차 완료"),
#                 "last_event": log_info.get("last_event", "-"),
#                 "last_time": log_info.get("last_time", "-"),
#                 "history": log_info.get("history", []),
#             })
#             matched_carnos.add(clean_c)

#     return {"result": "success", "count": len(matched), "data": matched[:100]}

# # 3. 아파트너 예약차량 단독 엔드포인트
# @app.get("/reserved")
# def get_reserved_cars(target_date: str = Query("", description="조회일자")):
#     scs_data = load_json_file(SCS_CACHE_FILE)
#     enex_data = load_json_file(ENEX_CACHE_FILE)
#     clean_target = target_date.replace("-", "").strip()

#     enex_status_map = {}
#     for log in enex_data:
#         c = str(log.get("carno", "")).strip().replace(" ", "")
#         if not c or c in enex_status_map:
#             continue
#         io_type = str(log.get("enextypename") or log.get("io") or "-").strip()
#         event_time = str(log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-")
#         gate = str(log.get("eqname") or log.get("parkname") or "-")

#         enex_status_map[c] = {
#             "status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
#             "last_event": f"{io_type} ({gate})",
#             "last_time": event_time,
#         }

#     results = []
#     for item in scs_data:
#         sc_user = str(item.get("scusername", ""))
#         msg = str(item.get("msg", ""))
#         memo = str(item.get("memo", ""))

#         if (
#             "아파트너사전예약" in sc_user
#             or "APTNER" in msg
#             or "아파트너" in memo
#             or "사전예약" in sc_user
#         ):
#             bgn = str(item.get("usebgndt", ""))
#             clean_bgn = bgn.replace("-", "").split(" ")[0] if bgn else ""
#             res_date = bgn.split(" ")[0] if bgn else "-"

#             if clean_target and clean_bgn and (clean_target not in clean_bgn):
#                 continue

#             dong = str(item.get("part", "")).strip()
#             ho = str(item.get("pos", "")).strip()
#             org = str(item.get("org", "")).strip()
#             dong_ho = f"{dong}동 {ho}호" if (dong and ho) else (org if org else "-")

#             carno = str(item.get("carno", "-"))
#             clean_carno = carno.replace(" ", "")

#             log_info = enex_status_map.get(clean_carno, {})
#             p_status = log_info.get("status", "입차 대기")
#             l_event = log_info.get("last_event", "-")
#             l_time = log_info.get("last_time", "-")

#             results.append({
#                 "carno": carno,
#                 "car_type": "예약",
#                 "name": "아파트너사전예약",
#                 "phone": extract_phone(item),
#                 "dong_ho": dong_ho,
#                 "res_date": res_date,
#                 "start_time": item.get("usebgndt", "-"),
#                 "end_time": item.get("useenddt", "-"),
#                 "registered_at": item.get("mkdt", "-"),
#                 "parking_status": p_status,
#                 "last_event": l_event,
#                 "last_time": l_time,
#             })

#     return {"result": "success", "count": len(results), "data": results}