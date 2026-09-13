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
            "parkno": "",
            "bgndt": b_date,
            "enddt": e_date,
            "carno": "",
            "enextypeid": "",
            "tkttypeid": "",
            "eqno": "",
        }
        res_enex = requests.post(
            enex_url, json=enex_payload, headers=HEADERS, timeout=25
        )
        enex_list = []
        if res_enex.status_code == 200 and len(res_enex.text) > 10:
            try:
                parsed = res_enex.json()
                enex_list = (
                    parsed
                    if isinstance(parsed, list)
                    else (
                        parsed.get("rows")
                        or parsed.get("data")
                        or parsed.get("list")
                        or []
                    )
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


# 2. 통합 검색 (?q= 차량번호, siname 이름, 동호수, 전화번호)
@app.get("/search")
def search_car(
    q: str = Query("", description="검색어 (차량번호, 사람 이름, 동호수, 전화번호)"),
    carno: str = Query("", description="차량번호"),
    name: str = Query("", description="이름"),
):
    keyword = (q.strip() or carno.strip() or name.strip()).replace(" ", "")
    if not keyword:
        return {"result": "success", "count": 0, "data": []}

    scs_data = load_json_file(SCS_CACHE_FILE)
    enex_data = load_json_file(ENEX_CACHE_FILE)

    latest_logs = {}
    for item in enex_data:
        c = str(item.get("carno", "")).strip().replace(" ", "")
        if not c:
            continue

        s_name = str(item.get("siname", "") or item.get("username", "") or "").strip()
        dong = str(item.get("part", "")).strip()
        ho = str(item.get("pos", "")).strip()
        dong_ho = f"{dong}동 {ho}호" if dong and ho else ""
        phone = (
            str(item.get("tel") or item.get("hp") or item.get("phone") or "")
            .replace("-", "")
            .strip()
        )
        io_type = str(item.get("enextypename") or item.get("io") or "-").strip()
        event_time = str(
            item.get("enexdt") or item.get("entdt") or item.get("enextime") or "-"
        )
        gate = str(item.get("eqname") or item.get("parkname") or "-")

        if c not in latest_logs:
            latest_logs[c] = {
                "carno": item.get("carno"),
                "name": s_name,
                "dong_ho": dong_ho,
                "phone": phone,
                "parking_status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
                "last_event": f"{io_type} ({gate})",
                "last_time": event_time,
            }

    matched = []
    for c, log in latest_logs.items():
        if (
            (keyword in c)
            or (log["name"] and keyword in log["name"])
            or (keyword in log["dong_ho"].replace(" ", ""))
            or (log["phone"] and keyword in log["phone"])
        ):
            matched.append(log)

    scs_matched_carnos = {m["carno"] for m in matched}
    for item in scs_data:
        c = str(item.get("carno", "")).strip()
        if not c or c in scs_matched_carnos:
            continue

        u_name = str(
            item.get("siname", "")
            or item.get("username", "")
            or item.get("scusername", "")
        ).strip()
        dong = str(item.get("part", "") or item.get("dong", "")).strip()
        ho = str(item.get("pos", "") or item.get("ho", "")).strip()
        org = str(item.get("org", "")).strip()
        dong_ho = f"{dong}동 {ho}호" if dong and ho else (org if org else "-")
        tel = (
            str(item.get("tel") or item.get("usertel") or item.get("scusertel") or "")
            .replace("-", "")
            .strip()
        )

        if (
            (keyword in c.replace(" ", ""))
            or (u_name and keyword in u_name)
            or (keyword in dong_ho.replace(" ", ""))
            or (tel and keyword in tel)
        ):
            matched.append(
                {
                    "carno": c,
                    "name": u_name if u_name else "-",
                    "dong_ho": dong_ho,
                    "phone": tel if tel else "-",
                    "parking_status": "출차 완료",
                    "last_event": "-",
                    "last_time": "-",
                }
            )

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
        event_time = str(
            log.get("enexdt") or log.get("entdt") or log.get("enextime") or "-"
        )
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

            results.append(
                {
                    "carno": carno,
                    "car_type": "예약",
                    "name": "아파트너사전예약",
                    "phone": str(item.get("tel", "") or "-"),
                    "dong_ho": dong_ho,
                    "res_date": res_date,
                    "start_time": item.get("usebgndt", "-"),
                    "end_time": item.get("useenddt", "-"),
                    "registered_at": item.get("mkdt", "-"),
                    "parking_status": p_status,
                    "last_event": l_event,
                    "last_time": l_time,
                }
            )

    return {"result": "success", "count": len(results), "data": results}
