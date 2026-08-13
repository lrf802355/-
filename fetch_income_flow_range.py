#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量拉取收入流水（指定日期范围，按周分片，避免超时）
用法: python3 fetch_income_flow_range.py 2026-08-06 2026-08-11
"""
import json
import sqlite3
import sys
import urllib.request
import os
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BASE = "http://localhost:8899"
DB = os.path.join(BASE_DIR, "finance.db")

CAMPUSES = [
    ("10144", "上岸公寓B座"),
    ("10137", "上岸公寓C座"),
    ("10143", "上岸公寓D座"),
    ("10145", "小新公寓"),
    ("10148", "景然力沃校区"),
    ("10138", "嵘泰校区"),
    ("10139", "塔利北校区"),
    ("10140", "塔利南校区"),
    ("10163", "城际酒店"),
]

def fetch_week(hotel_id, s, e, retries=3):
    rows = []
    page = 1
    while True:
        url = f"{BASE}/api/hotel/web/reports/incomeFlowStatementList/{hotel_id}?startDate={s}&endDate={e}&pageNum={page}&pageSize=500"
        ok = False
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(url, timeout=120) as resp:
                    d = json.loads(resp.read().decode())
                ok = True
                break
            except Exception as ex:
                print(f"    ⚠️ 重试{attempt+1}: {ex}")
                time.sleep(5)
        if not ok:
            print(f"    ❌ 拉取失败 p{page}")
            return "FETCH_FAILED"
        if d.get("code") == 401:
            print("    ❌ TOKEN过期")
            return "TOKEN_EXPIRED"
        batch = d.get("rows") or []
        rows.extend(batch)
        if len(batch) < 500:
            break
        page += 1
    return rows

def main():
    start_date = sys.argv[1] if len(sys.argv) > 1 else "2026-08-06"
    end_date = sys.argv[2] if len(sys.argv) > 2 else datetime.now().strftime("%Y-%m-%d")
    print(f"增量拉取 {start_date} ~ {end_date} 流水...")

    # 按周分片
    weeks = []
    d = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while d <= end:
        we = min(d + timedelta(days=6), end)
        weeks.append((d.strftime("%Y-%m-%d"), we.strftime("%Y-%m-%d")))
        d = we + timedelta(days=1)

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    total = 0
    for hid, hname in CAMPUSES:
        # 删除该校区该日期范围的旧数据（避免重复）
        c.execute("DELETE FROM income_flow WHERE hotel_id=? AND create_time >= ? AND create_time < ?",
                  (hid, start_date, (end + timedelta(days=1)).strftime("%Y-%m-%d")))
        campus_total = 0
        for ws, we in weeks:
            rows = fetch_week(hid, ws, we)
            if rows in ("TOKEN_EXPIRED", "FETCH_FAILED"):
                reason = "TOKEN过期" if rows == "TOKEN_EXPIRED" else "拉取失败"
                print(f"❌ {hname}: {reason}，本次不写入数据库")
                conn.rollback()
                conn.close()
                return 1
            for r in rows:
                c.execute(
                    "INSERT INTO income_flow (hotel_id, hotel_name, create_time, business_type, business_type_name, real_money, room_name, medi_code_name, order_no, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (hid, hname,
                     r.get("createTime"), r.get("businessType"), r.get("businessTypeName"),
                     r.get("realMoney"), r.get("roomName"), r.get("mediCodeName"),
                     r.get("orderNo"), r.get("source"))
                )
            campus_total += len(rows)
            print(f"    {hname} {ws}~{we}: {len(rows)}条")
        total += campus_total
        print(f"  ✅ {hname}: {campus_total}条")
    conn.commit()
    conn.close()
    print(f"\n✅ 增量拉取完成！共{total}条入库")

if __name__ == "__main__":
    raise SystemExit(main() or 0)
