import os
import json
import requests
from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="방재실 차량 관제 통합 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOCAL_FILE = "enex_log.json"
EXTERNAL_IP = "121.144.101.67"
BASE_PROXY = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935"
SCS_URL = f"{BASE_PROXY}/scs/get"
ENEX_URL = f"{BASE_PROXY}/enexrcg"

AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Authorization": AUTH_TOKEN,
    "Connection": "close",
    "Content-Type": "application/json",
    "Origin": "http://192.168.100.10:84",
    "Referer": "http://192.168.100.10:84/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

def fetch_and_merge_data():
    print("🔄 관제 데이터 동기화 시작...")
    
    # 1. 정기차량 명부
    scs_payload = {
        "parkname": "", "carno": "", "username": "", "org": "", "part": "",
        "pos": "", "scuserid": "", "scsttypeid": "", "shopid": "", "carexist": 0
    }
    try:
        r_scs = requests.post(SCS_URL, headers=headers, json=scs_payload, timeout=30)
        scs_data = r_scs.json() if (r_scs.status_code == 200 and len(r_scs.text) > 100) else []
    except Exception as e:
        print(f"❌ 명부 에러: {e}")
        scs_data = []

    # 2. 입출차 로그
    now_str = datetime.now().strftime("%Y-%m-%dT23:59:59")
    enex_payload = {
        "parkno": "", "bgndt": "2026-09-01T00:00:00", "enddt": now_str,
        "carno": "", "enextypeid": "", "tkttypeid": "", "eqno": ""
    }
    try:
        r_enex = requests.post(ENEX_URL, headers=headers, json=enex_payload, timeout=30)
        enex_data = r_enex.json() if (r_enex.status_code == 200 and len(r_enex.text) > 100) else []
    except Exception as e:
        print(f"❌ 입출차 에러: {e}")
        enex_data = []

    # 3. 데이터 결합 및 차량별 이력/타입 축적
    car_events = {}
    for item in sorted(enex_data, key=lambda x: str(x.get("enexdt") or x.get("entdt") or x.get("io_time") or "")):
        c_clean = str(item.get("carno") or "").strip().replace(" ", "")
        if not c_clean:
            continue
            
        io_name = str(item.get("enextypename") or item.get("etname") or item.get("io") or "")
        io_id = str(item.get("enextypeid") or "")
        is_out = ("출차" in io_name or io_id == "2" or "출" in str(item.get("eqname") or ""))
        ev_time = str(item.get("enexdt") or item.get("entdt") or item.get("io_time") or "").replace("T", " ")
        gate = item.get("eqname") or item.get("parkname") or "-"
        
        # 권종 및 예약 구분 판별 (방문예약, 모바일예약, 할인권 등)
        tkt_name = str(item.get("tkttypename") or item.get("tktname") or item.get("enextypename") or "")
        is_reservation = ("예약" in tkt_name) or ("방문" in tkt_name and "예약" in str(item)) or (str(item.get("tkttypeid")) in ["3", "4", "5"])

        if c_clean not in car_events:
            car_events[c_clean] = {
                "logs": [],
                "last_in_time": "-",
                "last_out_time": "-",
                "is_out": True,
                "last_event": "-",
                "last_time": "-",
                "is_reserved": False
            }

        if is_reservation:
            car_events[c_clean]["is_reserved"] = True

        event_label = "출차" if is_out else "입차"
        if is_out:
            car_events[c_clean]["last_out_time"] = ev_time
            car_events[c_clean]["is_out"] = True
            car_events[c_clean]["last_event"] = f"출차 ({gate})"
        else:
            car_events[c_clean]["last_in_time"] = ev_time
            car_events[c_clean]["is_out"] = False
            car_events[c_clean]["last_event"] = f"입차 ({gate})"
        
        car_events[c_clean]["last_time"] = ev_time
        car_events[c_clean]["logs"].append({
            "time": ev_time,
            "gate": gate,
            "type": event_label,
            "tkt": tkt_name
        })

    # 최종 병합
    final_records = []
    seen = set()

    for s in scs_data:
        raw_c = str(s.get("carno") or "").strip()
        c_clean = raw_c.replace(" ", "")
        if not c_clean:
            continue
        seen.add(c_clean)
        
        dong = str(s.get("part") or "").strip()
        ho = str(s.get("pos") or "").strip()
        dong_ho = f"{dong}동 {ho}호".strip() if (dong or ho) else "-"
        car_info = car_events.get(c_clean, {})

        final_records.append({
            "carno": raw_c,
            "name": str(s.get("name") or s.get("username") or "-").strip(),
            "dong_ho": dong_ho,
            "phone": str(s.get("tel") or s.get("hp") or s.get("phone") or "-").replace("-", "").strip(),
            "parking_status": "⚪ 출차 완료" if car_info.get("is_out", True) else "🟢 주차 중",
            "car_type": "정기",
            "last_event": car_info.get("last_event", "-"),
            "last_in_time": car_info.get("last_in_time", "-"),
            "last_out_time": car_info.get("last_out_time", "-"),
            "last_time": car_info.get("last_time", "-"),
            "history": car_info.get("logs", [])
        })

    for c_clean, car_info in car_events.items():
        if c_clean not in seen:
            car_type = "예약" if car_info["is_reserved"] else "일반"
            final_records.append({
                "carno": c_clean,
                "name": "-",
                "dong_ho": "-",
                "phone": "-",
                "parking_status": "⚪ 출차 완료" if car_info["is_out"] else "🟢 주차 중",
                "car_type": car_type,
                "last_event": car_info["last_event"],
                "last_in_time": car_info["last_in_time"],
                "last_out_time": car_info["last_out_time"],
                "last_time": car_info["last_time"],
                "history": car_info["logs"]
            })

    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(final_records, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 동기화 완료: {len(final_records)}건 저장")
    return len(final_records)

@app.get("/")
def root():
    return {"status": "ok", "message": "방재실 차량 관제 API"}

@app.post("/sync")
def sync_trigger():
    cnt = fetch_and_merge_data()
    return {"result": "success", "message": f"{cnt}건 동기화 완료", "count": cnt}

@app.get("/search")
def search_car(q: str = Query(..., description="차량번호, 동호수, 성명, 연락처")):
    query = q.strip().replace(" ", "").replace("-", "")
    if not os.path.exists(LOCAL_FILE):
        return {"result": "error", "message": "동기화 파일이 없습니다. /sync를 실행하세요."}

    with open(LOCAL_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)

    matched = []
    for item in records:
        carno = str(item.get("carno", "")).replace(" ", "")
        name = str(item.get("name", "")).strip()
        dong_ho = str(item.get("dong_ho", "")).replace(" ", "").replace("-", "")
        phone = str(item.get("phone", "")).replace("-", "").strip()

        if (query in carno) or (query in name) or (query in dong_ho) or (phone != "-" and query in phone):
            matched.append(item)

    return {"result": "success", "count": len(matched), "data": matched}

# 기간별 상세 이력 검색 (타임라인)
@app.get("/history")
def get_car_history(carno: str = Query(...), start_date: str = Query(""), end_date: str = Query("")):
    query = carno.strip().replace(" ", "")
    if not os.path.exists(LOCAL_FILE):
        return {"result": "error", "message": "동기화 파일이 없습니다."}

    with open(LOCAL_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)

    for item in records:
        if query in str(item.get("carno", "")).replace(" ", ""):
            history = item.get("history", [])
            # 날짜 필터링
            filtered = []
            for h in history:
                h_date = h["time"][:10]  # YYYY-MM-DD
                if start_date and h_date < start_date:
                    continue
                if end_date and h_date > end_date:
                    continue
                filtered.append(h)
            
            # 최신순 정렬
            filtered.sort(key=lambda x: x["time"], reverse=True)
            return {
                "result": "success",
                "carno": item["carno"],
                "name": item["name"],
                "dong_ho": item["dong_ho"],
                "car_type": item["car_type"],
                "data": filtered
            }

    return {"result": "error", "message": "해당 차량 내역을 찾을 수 없습니다."}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)

# import json
# import os
# from fastapi import FastAPI, Query
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI(title="방재실 입출차 통합 검색 서버")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# LOCAL_FILE = "enex_log.json"


# @app.get("/")
# def root():
#     return {"status": "ok", "message": "방재실 검색 API 가동 중"}


# @app.get("/search")
# def search_car(
#     q: str = Query(..., description="차량번호 뒷자리, 동호수, 이름, 전화번호")
# ):
#     query = q.strip().replace(" ", "").replace("-", "")

#     if not os.path.exists(LOCAL_FILE):
#         return {
#             "result": "error",
#             "message": "enex_log.json 파일이 없습니다. python main.py를 먼저 실행하세요.",
#         }

#     try:
#         with open(LOCAL_FILE, "r", encoding="utf-8") as f:
#             records = json.load(f)
#     except Exception as e:
#         return {"result": "error", "message": f"데이터 로드 오류: {e}"}

#     matched = []
#     for item in records:
#         carno = str(item.get("carno", "")).replace(" ", "")
#         name = str(item.get("name", "")).strip()
#         dong_ho = str(item.get("dong_ho", "")).replace(" ", "").replace("-", "")
#         phone = str(item.get("phone", "")).replace("-", "").strip()

#         # 1. 차량번호 뒷 4자리 또는 전체 포함 검색
#         # 2. 입주민 성명 일치/포함 검색
#         # 3. 동호수 (예: 101동 102호, 101102, 102호) 매칭
#         # 4. 전화번호 뒷 4자리 또는 전체 매칭
#         if (
#             (query in carno)
#             or (query in name)
#             or (query in dong_ho)
#             or (phone != "-" and query in phone)
#         ):
#             matched.append(item)

#     return {"result": "success", "count": len(matched), "data": matched}


# if __name__ == "__main__":
#     import uvicorn

#     port = int(os.environ.get("PORT", 8000))
#     uvicorn.run("server:app", host="0.0.0.0", port=port)


# import os
# import re
# import requests
# import uvicorn
# from fastapi import FastAPI, Query
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# TARGET_URL = "http://192.168.100.10:9935/enexrcg"
# HEADERS = {
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
#     "Origin": "http://192.168.100.10:84",
#     "Referer": "http://192.168.100.10:84/",
# }


# @app.get("/search")
# def search_car(q: str = Query(..., description="차량번호, 이름, 동호수, 전화번호")):
#     q = q.strip().replace(" ", "")

#     try:
#         # 1. 관제 데이터 요청
#         res = requests.get(TARGET_URL, headers=HEADERS, timeout=5)
#         raw_data = res.json()
#     except Exception as e:
#         return {"result": "error", "message": f"관제 서버 통신 실패: {str(e)}"}

#     # 리스트 구조 확인
#     records = []
#     if isinstance(raw_data, list):
#         records = raw_data
#     elif isinstance(raw_data, dict):
#         records = (
#             raw_data.get("rows") or raw_data.get("data") or raw_data.get("list") or []
#         )

#     # 2. 최신 상태 기준 중복 제거 (carno 기준 최신 1건)
#     latest_status = {}
#     for item in records:
#         carno = str(item.get("carno", "")).strip().replace(" ", "")
#         if not carno:
#             continue

#         dong = str(item.get("part", "")).strip()
#         ho = str(item.get("pos", "")).strip()
#         dong_ho = f"{dong}동 {ho}호" if dong and ho else ""
#         io_type = str(item.get("io", "")).strip()

#         # 전화번호 필드 감지 (tel, hp, phone 등)
#         phone = (
#             str(
#                 item.get("tel")
#                 or item.get("hp")
#                 or item.get("phone")
#                 or item.get("handphone")
#                 or ""
#             )
#             .strip()
#             .replace("-", "")
#             .replace(" ", "")
#         )

#         status_info = {
#             "carno": item.get("carno"),
#             "dong": dong,
#             "ho": ho,
#             "dong_ho": dong_ho,
#             "name": str(item.get("siname", "")).strip(),
#             "phone": phone,
#             "io_type": io_type,
#             "parking_status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
#             "last_time": item.get("io_time", ""),
#             "gate": item.get("gatename", ""),
#             "car_type": item.get("cartype", ""),
#         }

#         # 최신 시각 우선 덮어쓰기
#         if carno not in latest_status:
#             latest_status[carno] = status_info
#         else:
#             if str(item.get("io_time", "")) > str(latest_status[carno]["last_time"]):
#                 latest_status[carno] = status_info

#     # 3. 통합 검색 (차량번호, 이름, 동호수, 전화번호)
#     matched = []
#     for carno, data in latest_status.items():
#         dong_ho_clean = data["dong_ho"].replace(" ", "")
#         dong_dash_ho = f"{data['dong']}-{data['ho']}"
#         user_phone = data["phone"]

#         if (
#             (q in carno)
#             or (q == data["name"])
#             or (q in dong_ho_clean)
#             or (q in dong_dash_ho)
#             or (user_phone and q in user_phone)  # 🌟 전화번호 뒷자리 또는 전체 검색
#         ):
#             matched.append(data)

#     return {"result": "success", "count": len(matched), "data": matched}


# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 8000))
#     uvicorn.run("server:app", host="0.0.0.0", port=port)

# 2026/09/13
# import json
# import os
# from fastapi import FastAPI, Query

# app = FastAPI(title="방재실 입출차 검색 서버")
# LOCAL_FILE = "enex_log.json"


# @app.get("/search")
# def search_car(q: str = Query(..., description="차량번호, 성명, 동호수, 전화번호")):
#     q = q.strip().replace(" ", "")

#     if not os.path.exists(LOCAL_FILE):
#         return {
#             "result": "error",
#             "message": "enex_log.json 데이터 파일이 존재하지 않습니다.",
#         }

#     try:
#         with open(LOCAL_FILE, "r", encoding="utf-8") as f:
#             raw = json.load(f)
#             records = (
#                 raw
#                 if isinstance(raw, list)
#                 else (raw.get("rows") or raw.get("data") or raw.get("list") or [])
#             )
#     except Exception as e:
#         return {"result": "error", "message": f"파일 읽기 오류: {e}"}

#     # 차량번호 기준 최신 1건만 유지하기 위한 딕셔너리
#     matched_dict = {}

#     for item in records:
#         carno = str(item.get("carno") or "").strip()
#         carno_clean = carno.replace(" ", "")
#         name = str(item.get("siname") or item.get("name") or "").strip()
#         dong = str(item.get("part") or "").strip()
#         ho = str(item.get("pos") or "").strip()
#         dong_ho = f"{dong}동 {ho}호".strip()
#         phone = (
#             str(item.get("tel") or item.get("hp") or item.get("phone") or "")
#             .replace("-", "")
#             .strip()
#         )

#         # 검색 조건 매칭 (차량번호, 이름, 동호수, 전화번호)
#         if (
#             (q in carno_clean)
#             or (q in name)
#             or (q in dong_ho.replace(" ", ""))
#             or (phone and q in phone)
#         ):
#             io_type = str(
#                 item.get("enextypename")
#                 or item.get("io")
#                 or item.get("enextypeid")
#                 or ""
#             )
#             is_in = "입차" in io_type or io_type == "1"

#             matched_dict[carno_clean] = {
#                 "carno": carno,
#                 "dong_ho": dong_ho if dong_ho != "동 호" else "-",
#                 "name": name or "-",
#                 "phone": phone or "-",
#                 "parking_status": "🟢 주차 중" if is_in else "⚪ 출차 완료",
#                 "gate": item.get("eqname") or item.get("parkname") or "-",
#                 "last_time": (
#                     item.get("enexdt") or item.get("entdt") or item.get("io_time") or ""
#                 ).replace("T", " "),
#             }

#     matched_list = list(matched_dict.values())
#     return {
#         "result": "success",
#         "count": len(matched_list),
#         "data": matched_list,
#     }
