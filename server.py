import os
import re
import requests
import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TARGET_URL = "http://192.168.100.10:9935/enexrcg"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "http://192.168.100.10:84",
    "Referer": "http://192.168.100.10:84/",
}


@app.get("/search")
def search_car(q: str = Query(..., description="차량번호, 이름, 동호수, 전화번호")):
    q = q.strip().replace(" ", "")

    try:
        # 1. 관제 데이터 요청
        res = requests.get(TARGET_URL, headers=HEADERS, timeout=5)
        raw_data = res.json()
    except Exception as e:
        return {"result": "error", "message": f"관제 서버 통신 실패: {str(e)}"}

    # 리스트 구조 확인
    records = []
    if isinstance(raw_data, list):
        records = raw_data
    elif isinstance(raw_data, dict):
        records = (
            raw_data.get("rows")
            or raw_data.get("data")
            or raw_data.get("list")
            or []
        )

    # 2. 최신 상태 기준 중복 제거 (carno 기준 최신 1건)
    latest_status = {}
    for item in records:
        carno = str(item.get("carno", "")).strip().replace(" ", "")
        if not carno:
            continue

        dong = str(item.get("part", "")).strip()
        ho = str(item.get("pos", "")).strip()
        dong_ho = f"{dong}동 {ho}호" if dong and ho else ""
        io_type = str(item.get("io", "")).strip()

        # 전화번호 필드 감지 (tel, hp, phone 등)
        phone = (
            str(
                item.get("tel")
                or item.get("hp")
                or item.get("phone")
                or item.get("handphone")
                or ""
            )
            .strip()
            .replace("-", "")
            .replace(" ", "")
        )

        status_info = {
            "carno": item.get("carno"),
            "dong": dong,
            "ho": ho,
            "dong_ho": dong_ho,
            "name": str(item.get("siname", "")).strip(),
            "phone": phone,
            "io_type": io_type,
            "parking_status": "🟢 주차 중" if io_type == "입차" else "⚪ 출차 완료",
            "last_time": item.get("io_time", ""),
            "gate": item.get("gatename", ""),
            "car_type": item.get("cartype", ""),
        }

        # 최신 시각 우선 덮어쓰기
        if carno not in latest_status:
            latest_status[carno] = status_info
        else:
            if str(item.get("io_time", "")) > str(
                latest_status[carno]["last_time"]
            ):
                latest_status[carno] = status_info

    # 3. 통합 검색 (차량번호, 이름, 동호수, 전화번호)
    matched = []
    for carno, data in latest_status.items():
        dong_ho_clean = data["dong_ho"].replace(" ", "")
        dong_dash_ho = f"{data['dong']}-{data['ho']}"
        user_phone = data["phone"]

        if (
            (q in carno)
            or (q == data["name"])
            or (q in dong_ho_clean)
            or (q in dong_dash_ho)
            or (user_phone and q in user_phone)  # 🌟 전화번호 뒷자리 또는 전체 검색
        ):
            matched.append(data)

    return {"result": "success", "count": len(matched), "data": matched}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)