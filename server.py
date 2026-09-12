from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI(title="Apartment Car Search API")

# 플러터 앱 통신을 위한 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTERNAL_IP = "121.144.101.67"
URL = f"http://{EXTERNAL_IP}:8080/http://192.168.100.10:9935/enexrcg"

AUTH_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMjQyMDY0ODgiLCJuYW1lIjoiaHR0cDovL3d3dy5keWlrMjEuY28ua3IvIiwidmlzaW9uIjoidjQifQ.FWrZJsSj3ElO7tSp4QHMDM5TJ5HsvTyuJK0ByzSv1Q8"


def fetch_car_status(target_carno: str = ""):
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Authorization": AUTH_TOKEN,
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": "http://192.168.100.10:84",
        "Referer": "http://192.168.100.10:84/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
    }

    # 최근 3일치 로그 조회
    payload = {
        "parkno": "",
        "bgndt": "2026-09-10T00:00:00",
        "enddt": "2026-09-12T23:59:59",
        "carno": target_carno,
        "enextypeid": "",
        "tkttypeid": "",
        "eqno": "",
    }

    try:
        res = requests.post(URL, headers=headers, json=payload, timeout=12)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"API 호출 에러: {e}")
    return []


@app.get("/search")
def search(q: str = Query(..., description="성명, 번호뒤4자리, 동호수")):
    q = q.strip()
    logs = fetch_car_status()

    if not logs:
        return {"result": "fail", "message": "데이터를 불러올 수 없습니다."}

    logs_sorted = sorted(logs, key=lambda x: x.get("enexdt", ""))

    latest_status = {}
    for item in logs_sorted:
        carno = item.get("carno")
        if not carno or carno == "미인식":
            continue

        dong = str(item.get("part") or "")
        ho = str(item.get("pos") or "")
        name = str(item.get("siname") or "")
        io_type = "입차" if str(item.get("enextypeid")) == "1" else "출차"

        latest_status[carno] = {
            "carno": carno,
            "dong": dong,
            "ho": ho,
            "dong_ho": f"{dong}동 {ho}호" if dong and ho else "미등록/방문",
            "name": name,
            "io_type": io_type,
            "parking_status": (
                "🟢 주차 중" if io_type == "입차" else "🔴 출차 완료"
            ),
            "last_time": item.get("enexdt"),  # 핵심: 최종 입출차 시각
            "gate": item.get("eqname"),
            "car_type": item.get("ttname") or "일반",
        }

    matched = []
    for carno, data in latest_status.items():
        if (
            (q in carno)
            or (q == data["name"])
            or (q in data["dong_ho"])
            or (q in f"{data['dong']}-{data['ho']}")
        ):
            matched.append(data)

    return {"result": "success", "count": len(matched), "data": matched}



import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)