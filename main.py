import json
from datetime import datetime, timedelta
import requests

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
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


def run_sync():
    print("📋 1. 정기차량 명부(/scs/get) 수신 중...")
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
    }
    try:
        res_scs = requests.post(SCS_URL, headers=headers, json=scs_payload, timeout=30)
        scs_data = (
            res_scs.json()
            if res_scs.status_code == 200 and len(res_scs.text) > 100
            else []
        )
        print(f"   👉 정기차량 명부 총 {len(scs_data)}건 확보!")
    except Exception as e:
        print(f"   ❌ 명부 수신 에러: {e}")
        scs_data = []

    print("🚗 2. 실시간 입출차 로그(/enexrcg) 수신 중...")
    now_str = datetime.now().strftime("%Y-%m-%dT23:59:59")
    enex_payload = {
        "parkno": "",
        "bgndt": "2026-09-10T00:00:00",
        "enddt": now_str,
        "carno": "",
        "enextypeid": "",
        "tkttypeid": "",
        "eqno": "",
    }
    try:
        res_enex = requests.post(
            ENEX_URL, headers=headers, json=enex_payload, timeout=30
        )
        enex_data = (
            res_enex.json()
            if res_enex.status_code == 200 and len(res_enex.text) > 100
            else []
        )
        print(f"   👉 입출차 로그 총 {len(enex_data)}건 확보!")
    except Exception as e:
        print(f"   ❌ 입출차 수신 에러: {e}")
        enex_data = []

    print("🔄 3. 명부 + 입출차 데이터 결합 중...")
    # 입출차 내역 정렬 (시간 오름차순)
    enex_map = {}
    for item in sorted(
        enex_data,
        key=lambda x: str(x.get("enexdt") or x.get("entdt") or x.get("io_time") or ""),
    ):
        carno_clean = str(item.get("carno") or "").strip().replace(" ", "")
        if not carno_clean:
            continue

        io_name = str(
            item.get("enextypename") or item.get("etname") or item.get("io") or ""
        )
        io_id = str(item.get("enextypeid") or "")
        is_out = (
            "출차" in io_name or io_id == "2" or "출" in str(item.get("eqname") or "")
        )
        ev_time = str(
            item.get("enexdt") or item.get("entdt") or item.get("io_time") or ""
        ).replace("T", " ")
        gate = item.get("eqname") or item.get("parkname") or "-"

        if carno_clean not in enex_map:
            enex_map[carno_clean] = {
                "last_in_time": "-",
                "last_out_time": "-",
                "is_out": True,
                "last_event": "-",
                "last_time": "-",
            }

        if is_out:
            enex_map[carno_clean]["last_out_time"] = ev_time
            enex_map[carno_clean]["is_out"] = True
            enex_map[carno_clean]["last_event"] = f"출차 ({gate})"
        else:
            enex_map[carno_clean]["last_in_time"] = ev_time
            enex_map[carno_clean]["is_out"] = False
            enex_map[carno_clean]["last_event"] = f"입차 ({gate})"
        enex_map[carno_clean]["last_time"] = ev_time

    # 최종 통합 레코드 생성
    final_records = []
    seen_cars = set()

    # A. 정기차량 명부 기준 통합
    for s in scs_data:
        raw_carno = str(s.get("carno") or "").strip()
        c_clean = raw_carno.replace(" ", "")
        if not c_clean:
            continue
        seen_cars.add(c_clean)

        dong = str(s.get("part") or "").strip()
        ho = str(s.get("pos") or "").strip()
        dong_ho = f"{dong}동 {ho}호".strip() if (dong or ho) else "-"
        log = enex_map.get(c_clean, {})

        final_records.append(
            {
                "carno": raw_carno,
                "name": str(s.get("name") or s.get("username") or "-").strip(),
                "dong_ho": dong_ho,
                "phone": (
                    str(s.get("tel") or s.get("hp") or s.get("phone") or "-")
                    .replace("-", "")
                    .strip()
                ),
                "parking_status": (
                    "⚪ 출차 완료" if log.get("is_out", True) else "🟢 주차 중"
                ),
                "last_event": log.get("last_event", "-"),
                "last_in_time": log.get("last_in_time", "-"),
                "last_out_time": log.get("last_out_time", "-"),
                "last_time": log.get("last_time", "-"),
                "is_regular": True,
            }
        )

    # B. 명부에는 없지만 최근 입출차한 일반/방문 차량도 추가
    for c_clean, log in enex_map.items():
        if c_clean not in seen_cars:
            final_records.append(
                {
                    "carno": c_clean,
                    "name": "-",
                    "dong_ho": "-",
                    "phone": "-",
                    "parking_status": "⚪ 출차 완료" if log["is_out"] else "🟢 주차 중",
                    "last_event": log["last_event"],
                    "last_in_time": log["last_in_time"],
                    "last_out_time": log["last_out_time"],
                    "last_time": log["last_time"],
                    "is_regular": False,
                }
            )

    with open("enex_log.json", "w", encoding="utf-8") as f:
        json.dump(final_records, f, ensure_ascii=False, indent=2)

    print(
        f"💾 총 {len(final_records)}건의 완전체 데이터가 enex_log.json에 저장되었습니다!"
    )


if __name__ == "__main__":
    run_sync()


# import json
# import requests

# EXTERNAL_IP = "121.144.101.67"
# URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/enexrcg"

# AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# headers = {
#     "Accept": "application/json, text/javascript, */*; q=0.01",
#     "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
#     "Authorization": AUTH_TOKEN,
#     "Connection": "keep-alive",
#     "Content-Type": "application/json",
#     "Origin": "http://192.168.100.10:84",
#     "Referer": "http://192.168.100.10:84/",
#     "User-Agent": (
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
#         " like Gecko) Chrome/131.0.0.0 Safari/537.36"
#     ),
# }

# # 9월 11일 ~ 오늘(9월 13일 23:59:59)까지 전체 입출차 조회
# payload = {
#     "parkno": "",
#     "bgndt": "2026-09-11T00:00:00",
#     "enddt": "2026-09-13T23:59:59",
#     "carno": "",
#     "enextypeid": "",
#     "tkttypeid": "",
#     "eqno": "",
# }

# print("🚗 실시간 입출차 로그 수신 중...")
# res = requests.post(URL, headers=headers, json=payload, timeout=30)

# if res.status_code == 200 and len(res.text) > 100:
#     data = res.json()
#     print(f"🎉 성공!! 총 {len(data)}건의 최신 입출차 로그를 확보했습니다!\n")

#     with open("enex_log.json", "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)
#     print("💾 최신 enex_log.json 파일로 갱신 완료!")
# else:
#     print(f"❌ 실패 (상태 코드: {res.status_code})")


# import json
# import os
# import requests
# from fastapi import FastAPI, Query

# app = FastAPI()
# LOCAL_FILE = "enex_log.json"
# TARGET_URL = "http://192.168.100.10:9935/enexrcg"


# @app.get("/search")
# def search_car(q: str = Query(..., description="검색어")):
#     q = q.strip().replace(" ", "")
#     records = []

#     # 1. 실시간 관제 접속 시도
#     try:
#         res = requests.get(TARGET_URL, timeout=1)
#         if res.status_code == 200:
#             records = res.json()
#     except Exception:
#         records = []

#     # 2. 관제 접속 실패 시 (집/외부/네트워크 미연결), 로컬 JSON 파일 자동 로드
#     if not records and os.path.exists(LOCAL_FILE):
#         try:
#             with open(LOCAL_FILE, "r", encoding="utf-8") as f:
#                 raw = json.load(f)
#                 records = (
#                     raw
#                     if isinstance(raw, list)
#                     else (raw.get("rows") or raw.get("data") or raw.get("list") or [])
#                 )
#         except Exception:
#             records = []

#     if not records:
#         return {
#             "result": "error",
#             "message": "관제 서버 및 로컬 데이터 모두 접근 불가",
#         }

#     # 3. 검색 로직 수행 (차량번호, 이름, 동호수, 전화번호)
#     matched = []
#     for item in records:
#         carno = str(item.get("carno", "")).replace(" ", "")
#         name = str(item.get("siname", "")).strip()
#         dong = str(item.get("part", "")).strip()
#         ho = str(item.get("pos", "")).strip()
#         dong_ho = f"{dong}동 {ho}호"
#         phone = (
#             str(item.get("tel") or item.get("hp") or item.get("phone") or "")
#             .replace("-", "")
#             .strip()
#         )

#         if (
#             (q in carno)
#             or (q == name)
#             or (q in dong_ho.replace(" ", ""))
#             or (phone and q in phone)
#         ):
#             matched.append(
#                 {
#                     "carno": item.get("carno"),
#                     "dong_ho": dong_ho,
#                     "name": name,
#                     "phone": phone,
#                     "parking_status": (
#                         "🟢 주차 중" if item.get("io") == "입차" else "⚪ 출차 완료"
#                     ),
#                     "last_time": item.get("io_time", ""),
#                 }
#             )

#     return {"result": "success", "count": len(matched), "data": matched}


# import json

# with open("enex_log.json", "r", encoding="utf-8") as f:
#     data = json.load(f)

# # 첫 번째 데이터의 모든 필드(Key, Value) 출력
# print("첫 번째 로그의 전체 데이터 구조:")
# for k, v in data[0].items():
#     print(f"  {k}: {v}")


# import json

# with open("enex_log.json", "r", encoding="utf-8") as f:
#     data = json.load(f)

# # 데이터에 들어있는 차량 구분 종류(유형) 전수 조사
# ticket_types = set()
# for item in data:
#     # 관제 시스템 필드명 확인
#     t_name = (
#         item.get("tkttypename")
#         or item.get("tkttypeid")
#         or item.get("carstatus")
#         or "기타"
#     )
#     ticket_types.add(str(t_name))

# print(f"총 수집된 차량 유형 목록: {ticket_types}\n")

# # 유형별 샘플 출력
# print(f"{'차량번호':<12} | {'게이트명':<15} | {'권한/유형':<15} | {'통과일시'}")
# print("-" * 65)
# for item in data[:10]:
#     carno = item.get("carno") or "-"
#     gate = item.get("eqname") or "-"
#     tkttype = (
#         item.get("tkttypename")
#         or item.get("tkttypeid")
#         or item.get("parktypename")
#         or "-"
#     )
#     dt = item.get("enexdt") or item.get("entdt") or "-"
#     print(f"{carno:<12} | {gate:<15} | {tkttype:<15} | {dt}")


# import json
# import requests

# EXTERNAL_IP = "121.144.101.67"
# URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/enexrcg"

# # 검증 완료된 100% 정답 토큰
# AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# headers = {
#     "Accept": "application/json, text/javascript, */*; q=0.01",
#     "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
#     "Authorization": AUTH_TOKEN,
#     "Connection": "keep-alive",
#     "Content-Type": "application/json",
#     "Origin": "http://192.168.100.10:84",
#     "Referer": "http://192.168.100.10:84/",
#     "User-Agent": (
#         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
#         " like Gecko) Chrome/131.0.0.0 Safari/537.36"
#     ),
# }

# # 9월 11일 ~ 9월 12일 전체 입출차 조회
# payload = {
#     "parkno": "",
#     "bgndt": "2026-09-11T00:00:00",
#     "enddt": "2026-09-12T23:59:59",
#     "carno": "",
#     "enextypeid": "",
#     "tkttypeid": "",
#     "eqno": "",
# }

# print("🚗 실시간 입출차 로그 수신 중...")
# res = requests.post(URL, headers=headers, json=payload, timeout=30)

# if res.status_code == 200 and len(res.text) > 100:
#     data = res.json()
#     print(f"🎉 성공!! 총 {len(data)}건의 입출차 로그를 확보했습니다!\n")

#     print("=" * 65)
#     print(f"{'차량번호':<12} | {'입출차 구분':<10} | {'통과 일시':<20} | {'게이트명'}")
#     print("=" * 65)

#     for item in data[:5]:
#         carno = item.get("carno") or "-"
#         enextype = item.get("enextypename") or item.get("enextypeid") or "-"
#         time_val = item.get("enexdt") or item.get("entdt") or "-"
#         eqname = item.get("eqname") or item.get("parkname") or "-"
#         print(f"{carno:<12} | {enextype:<10} | {time_val:<20} | {eqname}")
#     print("=" * 65)

#     # 로컬에 JSON 파일로 저장
#     with open("enex_log.json", "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)
#     print("💾 enex_log.json 파일로 저장 완료!")


# import requests

# EXTERNAL_IP = "121.144.101.67"
# URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/enexrcg"

# base = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ."

# # 의심되는 서명부 조합 3가지
# sigs = [
#     "FWrZJsSj3ElO7tSp4QHMDMSTJ5HsvTyuJK0ByzSvtQ8",  # 1. 사진상 가장 유력 (STJ5, 끝자리 t)
#     "FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8",  # 2. 방금 올려주신 값 그대로
#     "FWrZJsSj3ElO7tSp4QHMDMSTJSHsvTyuJK0ByzSvtQ8",  # 3. STJSH 형태
# ]

# payload = {
#     "parkno": "",
#     "bgndt": "2026-09-11T00:00:00",
#     "enddt": "2026-09-12T23:59:59",
#     "carno": "",
#     "enextypeid": "",
#     "tkttypeid": "",
#     "eqno": "",
# }

# for i, sig in enumerate(sigs, 1):
#     token = base + sig
#     headers = {
#         "Accept": "application/json, text/javascript, */*; q=0.01",
#         "Authorization": token,
#         "Connection": "keep-alive",
#         "Content-Type": "application/json",
#         "Origin": "http://192.168.100.10:84",
#         "Referer": "http://192.168.100.10:84/",
#         "User-Agent": (
#             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
#         ),
#     }

#     res = requests.post(URL, headers=headers, json=payload, timeout=5)
#     print(f"[{i}번 토큰 시도] 응답 코드: {res.status_code}, 수신: {len(res.text)}바이트")
#     if res.status_code == 200 and len(res.text) > 100:
#         print(f"🎉 뚫렸다!! 정답 토큰 번호: {i}번 ({len(res.json())}건 수신)")
#         break


# import requests

# EXTERNAL_IP = "121.144.101.67"
# URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/enexrcg"

# # 헤더와 페이로드 고정부
# base_token_prefix = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ."

# # 사진 판독상 의심되는 서명부 후보군
# signatures = [
#     # 1. 5와 H 조합
#     "FWrZJsSj3ElO7tSp4QHMDMSTJSH5vTyuJK0ByzSvtQ8",
#     "FWrZJsSj3ElO7tSp4QHMDMSTJ5hsvTyuJK0ByzSvtQ8",
#     # 2. 끝자리 tQ8 / 1Q8 / v1Q8
#     "FWrZJsSj3ElO7tSp4QHMDMSTJ5HsvTyuJK0ByzSv1Q8",
#     "FWrZJsSj3ElO7tSp4QHMDMSTJSHsvTyuJK0ByzSv1Q8",
#     # 3. 소문자 l / 대문자 I 차이
#     "FWrZJsSj3EIO7tSp4QHMDMSTJ5HsvTyuJK0ByzSvtQ8",
#     "FWrZJsSj3ElO7tSp4QHMDMSTJ5HsvTyuJK0ByzSvtO8",
# ]

# payload = {
#     "parkno": "",
#     "bgndt": "2026-09-11T00:00:00",
#     "enddt": "2026-09-12T23:59:59",
#     "carno": "",
#     "enextypeid": "",
#     "tkttypeid": "",
#     "eqno": "",
# }

# for i, sig in enumerate(signatures, 1):
#     token = base_token_prefix + sig
#     headers = {
#         "Accept": "application/json, text/javascript, */*; q=0.01",
#         "Authorization": token,
#         "Connection": "keep-alive",
#         "Content-Type": "application/json",
#         "Origin": "http://192.168.100.10:84",
#         "Referer": "http://192.168.100.10:84/",
#         "User-Agent": (
#             "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
#         ),
#     }

#     try:
#         res = requests.post(URL, headers=headers, json=payload, timeout=8)
#         print(f"후보 {i}번 결과: 상태코드 {res.status_code}, 수신: {len(res.text)}바이트")
#         if res.status_code == 200 and len(res.text) > 100:
#             print(f"🎉 찾았다! 정답 서명: {sig}")
#             print(f"데이터 {len(res.json())}건 확보 성공!")
#             break
#     except Exception as e:
#         print(f"후보 {i}번 타임아웃/에러: {e}")


# # from datetime import datetime, timedelta
# # import time
# # import requests

# # EXTERNAL_IP = "121.144.101.67"
# # AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"

# # SCS_URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/scs/get"
# # ENEX_URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/enexrcg"
# # N8N_WEBHOOK_URL = "https://n8n-production-01e0.up.railway.app/webhook/car-sync"

# # headers = {
# #     "Accept": "application/json, text/javascript, */*; q=0.01",
# #     "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
# #     "Authorization": AUTH_TOKEN,
# #     "Connection": "close",
# #     "Content-Type": "application/json",
# #     "Origin": "http://192.168.100.10:84",
# #     "Referer": "http://192.168.100.10:84/",
# #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
# # }


# # def fetch_scs_data():
# #     print("📋 1. 정기차량 명부(/scs/get) 조회 중...")
# #     payload = {
# #         "parkname": "",
# #         "carno": "",
# #         "username": "",
# #         "org": "",
# #         "part": "",
# #         "pos": "",
# #         "scuserid": "",
# #         "scsttypeid": "",
# #         "shopid": "",
# #         "carexist": 0,
# #     }
# #     try:
# #         res = requests.post(SCS_URL, headers=headers, json=payload, timeout=20)
# #         if res.status_code == 200 and len(res.text.strip()) > 0:
# #             data = res.json()
# #             print(f"✅ 명부 총 {len(data)}건 확보 완료!")
# #             return data
# #     except Exception as e:
# #         print(f"❌ 명부 수신 에러: {e}")
# #     return []


# # def fetch_enex_data():
# #     # 최근 3일치 범위를 조회해 주차 중이거나 최근 통과한 내역까지 확보
# #     now = datetime.now()
# #     bgndt = (now - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00")
# #     enddt = now.strftime("%Y-%m-%dT23:59:59")

# #     print(f"🚗 2. 실시간 입출차 로그 조회 중 ({bgndt} ~ {enddt})...")
# #     payload = {
# #         "parkno": "",
# #         "bgndt": bgndt,
# #         "enddt": enddt,
# #         "carno": "",
# #         "enextypeid": "",
# #         "tkttypeid": "",
# #     }
# #     try:
# #         res = requests.post(ENEX_URL, headers=headers, json=payload, timeout=20)
# #         if res.status_code == 200 and len(res.text.strip()) > 0:
# #             data = res.json()
# #             print(f"✅ 입출차 기록 총 {len(data)}건 확보 완료!")
# #             return data
# #     except Exception as e:
# #         print(f"❌ 입출차 수신 에러: {e}")
# #     return []


# # def merge_data(scs_list, enex_list):
# #     print("🔄 3. 명부와 입출차 기록 크로스 결합 중...")

# #     # 입출차 내역을 차량번호(공백제거) 기준으로 맵핑
# #     enex_map = {}
# #     for item in enex_list:
# #         carno = str(item.get("carno") or "").strip().replace(" ", "")
# #         if not carno:
# #             continue

# #         etname = str(item.get("etname") or "")
# #         enex_type = str(item.get("enextypeid") or "")
# #         event_time = str(item.get("enexdt") or item.get("entdt") or "").replace("T", " ")

# #         if carno not in enex_map:
# #             enex_map[carno] = {"in": "", "out": ""}

# #         if "출차" in etname or enex_type == "2":
# #             enex_map[carno]["out"] = event_time
# #         else:
# #             enex_map[carno]["in"] = event_time

# #     # 팀장님/표적 차량 로그 확인용
# #     target_targets = ["370더4586", "30고4376", "04수0572"]
# #     for t in target_targets:
# #         key = t.replace(" ", "")
# #         if key in enex_map:
# #             print(f"🎯 [표적 차량 매칭] {t} ➜ 입차: {enex_map[key]['in']} | 출차: {enex_map[key]['out']}")

# #     sheet_rows = []
# #     for item in scs_list:
# #         raw_carno = str(item.get("carno") or "").strip()
# #         c_key = raw_carno.replace(" ", "")

# #         # 입출차 기록 결합
# #         log = enex_map.get(c_key, {})
# #         in_time = log.get("in", "")
# #         out_time = log.get("out", "")

# #         scuser = str(item.get("scusername") or "")
# #         msg_str = str(item.get("msg") or "")
# #         combined = f"{scuser} {msg_str}".upper()

# #         if "아파트너" in combined or "APTNER" in combined or "사전예약" in combined or "예약" in combined:
# #             gubun = "아파트너사전예약"
# #         elif "정기" in scuser:
# #             gubun = "정기권"
# #         else:
# #             gubun = "일반권"

# #         sheet_rows.append({
# #             "입주사명": str(item.get("org") or ""),
# #             "차량번호": raw_carno,
# #             "구분": gubun,
# #             "입차일시": in_time,
# #             "출차일시": out_time,
# #             "그룹명": scuser,
# #             "차량명": str(item.get("carname") or ""),
# #             "성명": str(item.get("name") or ""),
# #             "전화번호": str(item.get("tel") or ""),
# #             "소속": str(item.get("org") or ""),
# #             "부서(동)": str(item.get("part") or ""),
# #             "직급(호)": str(item.get("pos") or ""),
# #             "상태구분": str(item.get("scsttypename") or "정상"),
# #             "시작일시": str(item.get("usebgndt") or "").replace("T", " "),
# #             "종료일시": str(item.get("useenddt") or "").replace("T", " "),
# #             "비고": msg_str,
# #             "월정기금액": str(item.get("issamt") or ""),
# #         })

# #     return sheet_rows


# # def send_to_n8n(sheet_rows, batch_size=200):
# #     total = len(sheet_rows)
# #     print(f"🚀 4. n8n 웹훅을 통해 구글 시트로 총 {total}건 전송 시작...")

# #     for i in range(0, total, batch_size):
# #         chunk = sheet_rows[i : i + batch_size]
# #         try:
# #             r = requests.post(N8N_WEBHOOK_URL, json=chunk, timeout=25)
# #             print(f"   ➜ [{i+1} ~ {min(i+batch_size, total)}건] 시트 반영 완료 ({r.status_code})")
# #         except Exception as e:
# #             print(f"   ❌ 전송 에러: {e}")
# #         time.sleep(1)

# #     print("🎉 구글 스프레드시트 동기화 완료!")


# # def main():
# #     scs_data = fetch_scs_data()
# #     if not scs_data:
# #         print("❌ 정기차량 명부를 가져오지 못했습니다.")
# #         return

# #     enex_data = fetch_enex_data()
# #     final_rows = merge_data(scs_data, enex_data)
# #     send_to_n8n(final_rows)


# # if __name__ == "__main__":
# #     main()
