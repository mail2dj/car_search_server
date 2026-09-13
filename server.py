import os
import json
import requests
from datetime import datetime
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

# 대영 IOT 전용 인증 토큰
AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# 프록시 및 대영 IOT 필수 통신 헤더
HEADERS = {
    "x-requested-with": "XMLHttpRequest",
    "Origin": "http://121.144.101.67:8080",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "token": AUTH_TOKEN,
    "Authorization": f"Bearer {AUTH_TOKEN}",
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


@app.get("/")
def root():
    return {"status": "running", "message": "방재실 통합 관제 백엔드 정상 작동 중"}


# 1. 1방재실 최신 관제 동기화 (GET/POST 지원)
@app.api_route("/sync", methods=["GET", "POST"])
def sync_data():
    try:
        # SCS 정기/예약 명부 동기화
        scs_url = f"{PROXY_BASE}/scs/get"
        scs_payload = {
            "parkname": "",
            "carno": "",
            "username": "",
            "org": "",
            "part": "",
            "pos": "",
            "scuserid": "",
            "scsttypeid": "",
            "shopid": "",
            "carexist": 0,
            "token": AUTH_TOKEN,
        }
        res_scs = requests.post(scs_url, json=scs_payload, headers=HEADERS, timeout=20)
        scs_list = []
        scs_debug = f"status: {res_scs.status_code}, text: {res_scs.text[:200]}"
        if res_scs.status_code == 200:
            try:
                scs_list = res_scs.json().get("list", [])
                save_json_file(SCS_CACHE_FILE, scs_list)
            except Exception as je:
                scs_debug += f" (json parse error: {je})"

        # ENEX 입출차 로그 동기화
        today_str = datetime.now().strftime("%Y-%m-%d")
        enex_url = f"{PROXY_BASE}/enexrcg"
        enex_payload = {
            "sdate": "2026-09-01",
            "edate": today_str,
            "carno": "",
            "parkname": "",
            "eqname": "",
            "enextypename": "",
            "tkttypename": "",
            "token": AUTH_TOKEN,
        }
        res_enex = requests.post(
            enex_url, json=enex_payload, headers=HEADERS, timeout=25
        )
        enex_list = []
        enex_debug = f"status: {res_enex.status_code}, text: {res_enex.text[:200]}"
        if res_enex.status_code == 200:
            try:
                enex_list = res_enex.json().get("list", [])
                save_json_file(ENEX_CACHE_FILE, enex_list)
            except Exception as je:
                enex_debug += f" (json parse error: {je})"

        return {
            "result": (
                "success" if (len(scs_list) > 0 or len(enex_list) > 0) else "warning"
            ),
            "message": "1방재실 관제 동기화 완료",
            "scs_count": len(scs_list),
            "enex_count": len(enex_list),
            "scs_debug": scs_debug,
            "enex_debug": enex_debug,
        }
    except Exception as e:
        return {"result": "error", "message": str(e)}


# 2. 통합 조건 검색
@app.get("/search")
def search_cars(
    carno: str = Query("", description="차량번호 뒤 4자리 또는 전체"),
    name: str = Query("", description="입주민 성명"),
    phone: str = Query("", description="전화번호 뒤 4자리"),
    dongho: str = Query("", description="동-호수 (예: 202-1403)"),
):
    scs_data = load_json_file(SCS_CACHE_FILE)
    enex_data = load_json_file(ENEX_CACHE_FILE)

    scs_map = {}
    for item in scs_data:
        c = str(item.get("carno", "")).strip()
        if c:
            dong = (
                str(item.get("part", "")).strip() or str(item.get("dong", "")).strip()
            )
            ho = str(item.get("pos", "")).strip() or str(item.get("ho", "")).strip()
            org = str(item.get("org", "")).strip()

            if dong and ho:
                dong_ho = f"{dong}동 {ho}호"
            elif org and "-" in org:
                parts = org.split("-")
                dong_ho = f"{parts[0]}동 {parts[1]}호"
            elif org:
                dong_ho = org
            else:
                dong_ho = "-"

            scst = str(item.get("scsttypename", ""))
            scs_map[c] = {
                "name": item.get("username", "-") or "-",
                "phone": item.get("usertel", "-") or "-",
                "dong_ho": dong_ho,
                "car_type": (
                    "예약"
                    if ("아파트너" in scst or "사전예약" in scst or "APT" in scst)
                    else "정기"
                ),
            }

    latest_logs = {}
    for log in enex_data:
        c = str(log.get("carno", "")).strip()
        if not c:
            continue
        event_time = log.get("enextime", "-")
        io_type = log.get("enextypename", "-")
        gate = log.get("eqname", "-") or log.get("parkname", "-")
        fee = log.get("feename", "") or ""
        tkt = log.get("tkttypename", "") or ""

        if c not in latest_logs:
            latest_logs[c] = {
                "last_event": f"{io_type} ({gate})",
                "parking_status": "출차 완료" if io_type == "출차" else "주차 중",
                "last_in_time": event_time if io_type == "입차" else "-",
                "last_out_time": event_time if io_type == "출차" else "-",
                "fee_type": fee if fee else tkt,
            }
        else:
            cur = latest_logs[c]
            if io_type == "입차" and cur["last_in_time"] == "-":
                cur["last_in_time"] = event_time
            elif io_type == "출차" and cur["last_out_time"] == "-":
                cur["last_out_time"] = event_time

    all_carno_keys = set(list(scs_map.keys()) + list(latest_logs.keys()))
    results = []

    carno_q = carno.strip()
    name_q = name.strip()
    phone_q = phone.strip()
    dongho_q = dongho.replace(" ", "").replace("-", "").strip()

    for c in all_carno_keys:
        scs_info = scs_map.get(
            c, {"name": "-", "phone": "-", "dong_ho": "-", "car_type": "일반"}
        )
        log_info = latest_logs.get(
            c,
            {
                "last_event": "-",
                "parking_status": "출차 완료",
                "last_in_time": "-",
                "last_out_time": "-",
                "fee_type": "-",
            },
        )

        if carno_q and (carno_q not in c):
            continue
        if name_q and (name_q not in scs_info["name"]):
            continue
        if phone_q and (phone_q not in scs_info["phone"]):
            continue
        if dongho_q:
            clean_dongho = (
                scs_info["dong_ho"]
                .replace(" ", "")
                .replace("동", "")
                .replace("호", "")
                .replace("-", "")
            )
            if dongho_q not in clean_dongho:
                continue

        c_type = scs_info["car_type"]
        if "APT" in log_info["fee_type"] or "방문" in log_info["fee_type"]:
            c_type = "예약"

        results.append(
            {
                "carno": c,
                "car_type": c_type,
                "dong_ho": scs_info["dong_ho"],
                "name": scs_info["name"],
                "phone": scs_info["phone"],
                "parking_status": log_info["parking_status"],
                "last_event": log_info["last_event"],
                "last_in_time": log_info["last_in_time"],
                "last_out_time": log_info["last_out_time"],
            }
        )

    return {"result": "success", "count": len(results), "data": results[:100]}


# 3. 아파트너 사전예약 차량 전용 조회 (날짜별 과거 복원 지원)
@app.get("/reserved")
def get_reserved_cars(
    target_date: str = Query("", description="조회할 날짜 (YYYY-MM-DD, 미지정시 전체)")
):
    scs_data = load_json_file(SCS_CACHE_FILE)
    enex_data = load_json_file(ENEX_CACHE_FILE)

    clean_target = target_date.replace("-", "").replace("/", "").strip()
    reserved_map = {}

    # (1) SCS 명부에서 '아파트너사전예약' 추출
    for item in scs_data:
        grp = str(item.get("scsttypename", ""))
        note = str(item.get("memo", "")) or str(item.get("remk", ""))
        carno = str(item.get("carno", "")).strip()

        if "아파트너" in grp or "사전예약" in grp or "APTNER" in note or "APT" in grp:
            sdate_full = str(item.get("sdate", "")) or str(item.get("startdate", ""))
            clean_sdate = (
                sdate_full.replace("-", "").replace("/", "").split(" ")[0]
                if sdate_full
                else ""
            )
            res_date = sdate_full.split(" ")[0] if sdate_full else ""

            if clean_target and clean_sdate and (clean_target not in clean_sdate):
                continue

            dong = (
                str(item.get("part", "")).strip() or str(item.get("dong", "")).strip()
            )
            ho = str(item.get("pos", "")).strip() or str(item.get("ho", "")).strip()
            org = str(item.get("org", "")).strip()

            if dong and ho:
                dong_ho = f"{dong}동 {ho}호"
            elif org and "-" in org:
                parts = org.split("-")
                dong_ho = f"{parts[0]}동 {parts[1]}호"
            elif org:
                dong_ho = org
            else:
                dong_ho = "-"

            reserved_map[carno] = {
                "carno": carno,
                "car_type": "예약",
                "name": item.get("username", "-") or "방문예약",
                "phone": item.get("usertel", "-") or "-",
                "dong_ho": dong_ho,
                "res_date": res_date or "-",
                "tkt_name": grp,
                "parking_status": "입차 대기",
                "last_event": "-",
                "last_in_time": "-",
                "last_out_time": "-",
            }

    # (2) ENEX 입출차 로그에서 'APT방문' / '방문권' 대조 및 과거 만료 차량 복원
    for log in enex_data:
        carno = str(log.get("carno", "")).strip()
        if not carno:
            continue

        fee = str(log.get("feename", "")) or str(log.get("parkname", ""))
        tkt = str(log.get("tkttypename", ""))
        io_type = str(log.get("enextypename", "")).strip()
        event_time = str(log.get("enextime", "-"))
        gate = log.get("eqname", "-")

        clean_event = (
            event_time.replace("-", "").replace("/", "").split(" ")[0]
            if event_time != "-"
            else ""
        )
        log_date = event_time.split(" ")[0] if " " in event_time else ""
        is_apt_visit = (
            "APT" in fee or "방문" in fee or "방문" in tkt or "사전예약" in tkt
        )

        if clean_target and clean_event and (clean_target not in clean_event):
            continue

        if is_apt_visit or carno in reserved_map:
            if carno not in reserved_map:
                reserved_map[carno] = {
                    "carno": carno,
                    "car_type": "예약",
                    "name": "방문예약",
                    "phone": "-",
                    "dong_ho": "-",
                    "res_date": log_date,
                    "tkt_name": fee if fee else tkt,
                    "parking_status": "출차 완료" if io_type == "출차" else "주차 중",
                    "last_event": f"{io_type} ({gate})",
                    "last_in_time": event_time if io_type == "입차" else "-",
                    "last_out_time": event_time if io_type == "출차" else "-",
                }
            else:
                target = reserved_map[carno]
                target["last_event"] = f"{io_type} ({gate})"
                if io_type == "입차":
                    target["parking_status"] = "주차 중"
                    target["last_in_time"] = event_time
                elif io_type == "출차":
                    target["parking_status"] = "출차 완료"
                    target["last_out_time"] = event_time

    results = list(reserved_map.values())
    return {
        "result": "success",
        "target_date": target_date or "전체",
        "count": len(results),
        "data": results,
    }


# 4. 스크래치(CCTV) 추적 실시간 타임라인
@app.get("/timeline")
def get_vehicle_timeline(
    carno: str = Query(..., description="차량 전체 번호"),
    sdate: str = Query(..., description="시작일자 (YYYY-MM-DD)"),
    edate: str = Query(..., description="종료일자 (YYYY-MM-DD)"),
):
    try:
        url = f"{PROXY_BASE}/enexrcg"
        payload = {
            "sdate": sdate,
            "edate": edate,
            "carno": carno.strip(),
            "parkname": "",
            "eqname": "",
            "enextypename": "",
            "tkttypename": "",
            "token": AUTH_TOKEN,
        }
        res = requests.post(url, json=payload, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            logs = res.json().get("list", [])
            timeline = []
            for item in logs:
                timeline.append(
                    {
                        "time": item.get("enextime", "-"),
                        "type": item.get("enextypename", "-"),
                        "gate": item.get("eqname", "-") or item.get("parkname", "-"),
                        "tkt": item.get("feename", "-") or item.get("tkttypename", "-"),
                    }
                )
            return {
                "result": "success",
                "carno": carno,
                "count": len(timeline),
                "timeline": timeline,
            }
        else:
            return {
                "result": "error",
                "message": f"대영 IOT 응답 오류 ({res.status_code})",
            }
    except Exception as e:
        return {"result": "error", "message": str(e)}


# import os
# import json
# import requests
# from datetime import datetime
# from fastapi import FastAPI, Query
# from fastapi.middleware.cors import CORSMiddleware

# app = FastAPI(title="방재실 차량 관제 통합 API")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# LOCAL_FILE = "enex_log.json"
# EXTERNAL_IP = "121.144.101.67"
# BASE_PROXY = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935"
# SCS_URL = f"{BASE_PROXY}/scs/get"
# ENEX_URL = f"{BASE_PROXY}/enexrcg"

# AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# headers = {
#     "Accept": "application/json, text/javascript, */*; q=0.01",
#     "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
#     "Authorization": AUTH_TOKEN,
#     "Connection": "close",
#     "Content-Type": "application/json",
#     "Origin": "http://192.168.100.10:84",
#     "Referer": "http://192.168.100.10:84/",
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
# }


# def fetch_and_merge_data():
#     # 1. 정기차량 명부 수집
#     scs_payload = {
#         "parkname": "",
#         "carno": "",
#         "username": "",
#         "org": "",
#         "part": "",
#         "pos": "",
#         "scuserid": "",
#         "scsttypeid": "",
#         "shopid": "",
#         "carexist": 0,
#     }
#     try:
#         r_scs = requests.post(SCS_URL, headers=headers, json=scs_payload, timeout=30)
#         scs_data = (
#             r_scs.json() if (r_scs.status_code == 200 and len(r_scs.text) > 100) else []
#         )
#     except Exception as e:
#         print(f"❌ 명부 에러: {e}")
#         scs_data = []

#     # 2. 최근 입출차 로그 수집 (전체 동기화용)
#     now_str = datetime.now().strftime("%Y-%m-%dT23:59:59")
#     enex_payload = {
#         "parkno": "",
#         "bgndt": "2026-09-01T00:00:00",
#         "enddt": now_str,
#         "carno": "",
#         "enextypeid": "",
#         "tkttypeid": "",
#         "eqno": "",
#     }
#     try:
#         r_enex = requests.post(ENEX_URL, headers=headers, json=enex_payload, timeout=30)
#         enex_data = (
#             r_enex.json()
#             if (r_enex.status_code == 200 and len(r_enex.text) > 100)
#             else []
#         )
#     except Exception as e:
#         print(f"❌ 입출차 에러: {e}")
#         enex_data = []

#     car_events = {}
#     for item in sorted(
#         enex_data,
#         key=lambda x: str(x.get("enexdt") or x.get("entdt") or x.get("io_time") or ""),
#     ):
#         c_clean = str(item.get("carno") or "").strip().replace(" ", "")
#         if not c_clean:
#             continue

#         io_name = str(
#             item.get("enextypename") or item.get("etname") or item.get("io") or ""
#         )
#         io_id = str(item.get("enextypeid") or "")
#         is_out = (
#             "출차" in io_name or io_id == "2" or "출" in str(item.get("eqname") or "")
#         )
#         ev_time = str(
#             item.get("enexdt") or item.get("entdt") or item.get("io_time") or ""
#         ).replace("T", " ")
#         gate = item.get("eqname") or item.get("parkname") or "-"

#         tkt_name = str(
#             item.get("tkttypename")
#             or item.get("tktname")
#             or item.get("enextypename")
#             or ""
#         )
#         is_reservation = (
#             ("예약" in tkt_name)
#             or ("방문" in tkt_name and "예약" in str(item))
#             or (str(item.get("tkttypeid")) in ["3", "4", "5"])
#         )

#         if c_clean not in car_events:
#             car_events[c_clean] = {
#                 "logs": [],
#                 "last_in_time": "-",
#                 "last_out_time": "-",
#                 "is_out": True,
#                 "last_event": "-",
#                 "last_time": "-",
#                 "is_reserved": False,
#                 "tkt_name": tkt_name,
#             }

#         if is_reservation:
#             car_events[c_clean]["is_reserved"] = True

#         event_label = "출차" if is_out else "입차"
#         if is_out:
#             car_events[c_clean]["last_out_time"] = ev_time
#             car_events[c_clean]["is_out"] = True
#             car_events[c_clean]["last_event"] = f"출차 ({gate})"
#         else:
#             car_events[c_clean]["last_in_time"] = ev_time
#             car_events[c_clean]["is_out"] = False
#             car_events[c_clean]["last_event"] = f"입차 ({gate})"

#         car_events[c_clean]["last_time"] = ev_time
#         car_events[c_clean]["logs"].append(
#             {"time": ev_time, "gate": gate, "type": event_label, "tkt": tkt_name}
#         )

#     final_records = []
#     seen = set()

#     for s in scs_data:
#         raw_c = str(s.get("carno") or "").strip()
#         c_clean = raw_c.replace(" ", "")
#         if not c_clean:
#             continue
#         seen.add(c_clean)

#         dong = str(s.get("part") or "").strip()
#         ho = str(s.get("pos") or "").strip()
#         dong_ho = f"{dong}동 {ho}호".strip() if (dong or ho) else "-"
#         car_info = car_events.get(c_clean, {})

#         final_records.append(
#             {
#                 "carno": raw_c,
#                 "name": str(s.get("name") or s.get("username") or "-").strip(),
#                 "dong_ho": dong_ho,
#                 "phone": str(s.get("tel") or s.get("hp") or s.get("phone") or "-")
#                 .replace("-", "")
#                 .strip(),
#                 "parking_status": (
#                     "⚪ 출차 완료" if car_info.get("is_out", True) else "🟢 주차 중"
#                 ),
#                 "car_type": "정기",
#                 "tkt_name": car_info.get("tkt_name", "정기차량"),
#                 "last_event": car_info.get("last_event", "-"),
#                 "last_in_time": car_info.get("last_in_time", "-"),
#                 "last_out_time": car_info.get("last_out_time", "-"),
#                 "last_time": car_info.get("last_time", "-"),
#                 "history": car_info.get("logs", []),
#             }
#         )

#     for c_clean, car_info in car_events.items():
#         if c_clean not in seen:
#             car_type = "예약" if car_info["is_reserved"] else "일반"
#             final_records.append(
#                 {
#                     "carno": c_clean,
#                     "name": "-",
#                     "dong_ho": "-",
#                     "phone": "-",
#                     "parking_status": (
#                         "⚪ 출차 완료" if car_info["is_out"] else "🟢 주차 중"
#                     ),
#                     "car_type": car_type,
#                     "tkt_name": car_info.get("tkt_name", "일반방문"),
#                     "last_event": car_info["last_event"],
#                     "last_in_time": car_info["last_in_time"],
#                     "last_out_time": car_info["last_out_time"],
#                     "last_time": car_info["last_time"],
#                     "history": car_info["logs"],
#                 }
#             )

#     with open(LOCAL_FILE, "w", encoding="utf-8") as f:
#         json.dump(final_records, f, ensure_ascii=False, indent=2)

#     return len(final_records)


# @app.get("/")
# def root():
#     return {"status": "ok", "message": "방재실 차량 관제 API"}


# @app.post("/sync")
# def sync_trigger():
#     cnt = fetch_and_merge_data()
#     return {"result": "success", "message": f"{cnt}건 동기화 완료", "count": cnt}


# @app.get("/search")
# def search_car(q: str = Query(..., description="차량번호, 동호수, 성명, 연락처")):
#     query = q.strip().replace(" ", "").replace("-", "")
#     if not os.path.exists(LOCAL_FILE):
#         return {
#             "result": "error",
#             "message": "동기화 파일이 없습니다. /sync를 실행하세요.",
#         }

#     with open(LOCAL_FILE, "r", encoding="utf-8") as f:
#         records = json.load(f)

#     matched = []
#     for item in records:
#         carno = str(item.get("carno", "")).replace(" ", "")
#         name = str(item.get("name", "")).strip()
#         dong_ho = str(item.get("dong_ho", "")).replace(" ", "").replace("-", "")
#         phone = str(item.get("phone", "")).replace("-", "").strip()

#         if (
#             (query in carno)
#             or (query in name)
#             or (query in dong_ho)
#             or (phone != "-" and query in phone)
#         ):
#             matched.append(item)

#     return {"result": "success", "count": len(matched), "data": matched}


# # 방문 예약차량 목록 추출 전용 엔드포인트
# @app.get("/reserved")
# def get_reserved_cars():
#     if not os.path.exists(LOCAL_FILE):
#         return {"result": "error", "message": "동기화 파일이 없습니다."}

#     with open(LOCAL_FILE, "r", encoding="utf-8") as f:
#         records = json.load(f)

#     # 예약차량만 필터링
#     reserved_list = [item for item in records if item.get("car_type") == "예약"]
#     # 최근 활동순 정렬
#     reserved_list.sort(key=lambda x: str(x.get("last_time", "")), reverse=True)

#     return {"result": "success", "count": len(reserved_list), "data": reserved_list}


# # 스크래치 추적용: 차량 풀번호 + 임의 기간(From ~ To) 관제 PC 실시간 단건 조회 (부하 0%)
# @app.get("/history/live")
# def get_live_car_history(
#     carno: str = Query(..., description="차량 풀번호 (예: 04수0572)"),
#     start_date: str = Query(..., description="시작일 YYYY-MM-DD"),
#     end_date: str = Query(..., description="종료일 YYYY-MM-DD"),
# ):
#     clean_car = carno.strip().replace(" ", "")
#     bgndt = f"{start_date}T00:00:00"
#     enddt = f"{end_date}T23:59:59"

#     payload = {
#         "parkno": "",
#         "bgndt": bgndt,
#         "enddt": enddt,
#         "carno": clean_car,
#         "enextypeid": "",
#         "tkttypeid": "",
#         "eqno": "",
#     }

#     try:
#         r = requests.post(ENEX_URL, headers=headers, json=payload, timeout=10)
#         if r.status_code != 200:
#             return {
#                 "result": "error",
#                 "message": f"관제 서버 응답 에러 ({r.status_code})",
#             }

#         data = r.json()
#         if not isinstance(data, list) or len(data) == 0:
#             return {
#                 "result": "success",
#                 "count": 0,
#                 "data": [],
#                 "message": "해당 기간 내 입출차 기록이 없습니다.",
#             }

#         logs = []
#         for item in data:
#             io_name = str(
#                 item.get("enextypename") or item.get("etname") or item.get("io") or ""
#             )
#             io_id = str(item.get("enextypeid") or "")
#             is_out = (
#                 "출차" in io_name
#                 or io_id == "2"
#                 or "출" in str(item.get("eqname") or "")
#             )
#             ev_time = str(
#                 item.get("enexdt") or item.get("entdt") or item.get("io_time") or ""
#             ).replace("T", " ")
#             gate = item.get("eqname") or item.get("parkname") or "-"
#             tkt_name = str(
#                 item.get("tkttypename")
#                 or item.get("tktname")
#                 or item.get("enextypename")
#                 or "-"
#             )

#             logs.append(
#                 {
#                     "time": ev_time,
#                     "type": "출차" if is_out else "입차",
#                     "gate": gate,
#                     "tkt": tkt_name,
#                 }
#             )

#         logs.sort(key=lambda x: x["time"], reverse=True)
#         return {
#             "result": "success",
#             "carno": clean_car,
#             "count": len(logs),
#             "data": logs,
#         }

#     except Exception as e:
#         return {"result": "error", "message": f"조회 중 오류 발생: {e}"}


# if __name__ == "__main__":
#     import uvicorn

#     port = int(os.environ.get("PORT", 8000))
#     uvicorn.run("server:app", host="0.0.0.0", port=port)


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
