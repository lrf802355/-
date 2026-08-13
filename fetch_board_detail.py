#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取AMS包住完整明细（存原始字段：身份证/手机号/房间号/财务标记等）
用法: python3 fetch_board_detail.py [起始月] [结束月]  默认4-8月
"""
import json
import concurrent.futures
import sqlite3
import urllib.request
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TOKEN = open(os.path.join(BASE_DIR, 'cache', 'ams_token.txt')).read().strip()
AMS_BASE = "https://ams.xintujing.online"
DB = os.path.join(BASE_DIR, "finance.db")

CAMPUSES = [
    ("10138", "嵘泰校区"), ("10139", "塔利北校区"), ("10140", "塔利南校区"),
    ("10144", "上岸公寓B座"), ("10143", "上岸公寓D座"), ("10145", "小新公寓"),
    ("10148", "景然力沃校区"), ("10137", "上岸公寓C座"), ("10163", "城际酒店"),
]


def ams_get(path, params):
    url = f"{AMS_BASE}{path}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def decrypt_one(args):
    cipher, hotel_id = args
    if not cipher:
        return (cipher, "")
    url = f"{AMS_BASE}/hotel/web/common/sm4Decrypt/{hotel_id}"
    req = urllib.request.Request(url, data=cipher.encode(), method='POST', headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "text/plain", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode())
        return (cipher, d.get("data", ""))
    except Exception:
        return (cipher, "")


def main():
    import sys
    start_month = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    end_month = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    print(f"拉取范围: {start_month}月 - {end_month}月")

    conn = sqlite3.connect(DB, timeout=30)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS board_ams_detail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id TEXT, hotel_name TEXT, month TEXT,
        name TEXT, cert TEXT, mobile TEXT,
        room_name TEXT, room_price_code TEXT, medi_code TEXT,
        free_days INTEGER, free_days_list TEXT, remark TEXT,
        check_in_time TEXT, due_check_out_time TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    c.execute("DELETE FROM board_ams_detail")

    # 1. 拉原始记录
    raw = []  # (hotel_id, hotel_name, month, name, cert_enc, mobile_enc, room, price, medi, days, free_list, remark, cin, cout)
    for hid, hname in CAMPUSES:
        for month in range(start_month, end_month + 1):
            d = ams_get(f"/hotel/web/reports/freeStayDataList/{hid}",
                        {"hotelId": hid, "year": "2026", "month": str(month), "months": f"2026-{month:02d}"})
            for r in d.get("rows") or []:
                raw.append((hid, hname, f"2026-{month:02d}", r.get("name", ""),
                            r.get("certNoEnc", ""), r.get("mobileEnc", ""),
                            r.get("roomName", ""), r.get("roomPriceCode", ""), r.get("mediCode", ""),
                            r.get("freeDays") or 0, r.get("freeDaysList", ""), r.get("remark", ""),
                            r.get("checkInTime", ""), r.get("dueCheckOutTime", "")))
        print(f"  {hname} 完成")

    print(f"共{len(raw)}条，解密身份证+手机号...")

    # 2. 并发解密
    cert_pairs = list(set((r[4], r[0]) for r in raw if r[4]))
    mobile_pairs = list(set((r[5], r[0]) for r in raw if r[5]))
    cert_map = {}
    mobile_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        f2k = {ex.submit(decrypt_one, (cp, hid)): (cp, hid) for cp, hid in cert_pairs}
        for fut in concurrent.futures.as_completed(f2k):
            cipher, plain = fut.result()
            cert_map[(cipher, f2k[fut][1])] = plain
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        f2k = {ex.submit(decrypt_one, (mp, hid)): (mp, hid) for mp, hid in mobile_pairs}
        for fut in concurrent.futures.as_completed(f2k):
            cipher, plain = fut.result()
            mobile_map[(cipher, f2k[fut][1])] = plain
    print(f"  解密完成: cert {len(cert_map)}, mobile {len(mobile_map)}")

    # 3. 入库
    for (hid, hname, month, name, cert_enc, mobile_enc, room, price, medi, days, free_list, remark, cin, cout) in raw:
        cert = cert_map.get((cert_enc, hid), "")
        mobile = mobile_map.get((mobile_enc, hid), "")
        c.execute("""INSERT INTO board_ams_detail (hotel_id, hotel_name, month, name, cert, mobile,
                     room_name, room_price_code, medi_code, free_days, free_days_list, remark,
                     check_in_time, due_check_out_time) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (hid, hname, month, name, cert, mobile, room, price, medi, days, free_list, remark, cin, cout))
    conn.commit()
    c.execute("SELECT COUNT(*) FROM board_ams_detail")
    print(f"✅ 已存 {c.fetchone()[0]}条到 board_ams_detail")
    conn.close()


if __name__ == "__main__":
    main()
