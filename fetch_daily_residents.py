#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日在住名单抓取：每天早上7点抓8校区在住名单，存SQLite
用法: python3 fetch_daily_residents.py [YYYY-MM-DD]（默认今天）
"""
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE = "http://localhost:8899"
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

DATE = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
DB = os.path.join(BASE_DIR, "finance.db")

def fetch_residents(hotel_id, retries=3):
    """抓取某校区当前在住名单，网络异常时自动重试。"""
    url = f"{BASE}/api/hotel/web/business/checkOrder/listAcc/{hotel_id}?pageSize=9999"
    last_error = "未知错误"
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                d = json.loads(resp.read().decode())
            if d.get("code") == 401:
                return None, "TOKEN_EXPIRED"
            rows = d.get("rows")
            if rows is None:
                return None, "接口未返回rows"
            return rows, None
        except Exception as e:
            last_error = str(e)
            if attempt < retries:
                print(f"    ⚠️ 在住名单重试 {attempt}/{retries}: {last_error}")
                import time
                time.sleep(5 * attempt)
    return None, last_error

def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # 每日在住快照表
    c.execute("""CREATE TABLE IF NOT EXISTS daily_residents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snap_date TEXT NOT NULL,
        hotel_id TEXT NOT NULL,
        hotel_name TEXT NOT NULL,
        resident_count INTEGER NOT NULL,
        raw_json TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        UNIQUE(snap_date, hotel_id)
    )""")

    total = 0
    failed = []
    for hid, hname in CAMPUSES:
        rows, err = fetch_residents(hid)
        if err == "TOKEN_EXPIRED":
            print(f"❌ {hname}: TOKEN过期，停止")
            failed.append(hname)
            break
        if err:
            print(f"⚠️ {hname}: {err}")
            failed.append(hname)
            continue
        count = len(rows or [])
        raw = json.dumps(rows, ensure_ascii=False) if rows else "[]"
        c.execute("""INSERT OR REPLACE INTO daily_residents
                     (snap_date, hotel_id, hotel_name, resident_count, raw_json)
                     VALUES (?,?,?,?,?)""",
                  (DATE, hid, hname, count, raw))
        total += count
        print(f"✅ {hname}: {count}人")
    conn.commit()
    conn.close()
    print(f"\n📊 {DATE} 抓取完成: 共{total}人在住")
    if failed:
        print(f"⚠️ 失败校区: {failed}")

if __name__ == "__main__":
    main()
