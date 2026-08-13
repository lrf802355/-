#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仅更新AMS包住数据，不读取、不覆盖对方Excel数据。
用法:
  python update_ams_board.py              # 默认抓取上一个完整月份
  python update_ams_board.py 1 7 2026     # 补抓指定月份范围
"""
import concurrent.futures
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BASE_DIR, "cache", "ams_token.txt")
DB = os.path.join(BASE_DIR, "finance.db")
AMS_BASE = "https://ams.xintujing.online"
CAMPUSES = [
    ("10138", "嵘泰校区"), ("10139", "塔利北校区"), ("10140", "塔利南校区"),
    ("10144", "上岸公寓B座"), ("10143", "上岸公寓D座"), ("10145", "小新公寓"),
    ("10148", "景然力沃校区"), ("10137", "上岸公寓C座"), ("10163", "城际酒店"),
]

def read_token():
    with open(TOKEN_PATH, encoding="utf-8") as f:
        return f.read().strip()

def ams_get(path, params, token):
    url = f"{AMS_BASE}{path}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") == 401:
        raise RuntimeError("AMS token已过期")
    return data

def decrypt_one(args):
    cipher, hotel_id, token = args
    if not cipher:
        return cipher, ""
    req = urllib.request.Request(
        f"{AMS_BASE}/hotel/web/common/sm4Decrypt/{hotel_id}",
        data=cipher.encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return cipher, json.loads(resp.read().decode()).get("data", "")
    except Exception:
        return cipher, ""

def month_range():
    current = date.today()
    if len(sys.argv) >= 3:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        year = int(sys.argv[3]) if len(sys.argv) >= 4 else current.year
    else:
        if current.month == 1:
            return None
        year = current.year
        start = end = current.month - 1
    if not 1 <= start <= end <= 12:
        raise ValueError(f"月份范围无效: {start}-{end}")
    return year, start, end

def main():
    selected = month_range()
    if selected is None:
        print("1月没有上一个完整月份，跳过")
        return 0
    year, start_month, end_month = selected
    token = read_token()
    print(f"仅更新AMS：{year}年{start_month}月-{end_month}月；对方数据保持不变")

    raw = []
    for hid, campus in CAMPUSES:
        for month in range(start_month, end_month + 1):
            data = ams_get(f"/hotel/web/reports/freeStayDataList/{hid}", {
                "hotelId": hid, "year": str(year), "month": str(month), "months": f"{year}-{month:02d}"
            }, token)
            for row in data.get("rows") or []:
                raw.append((hid, campus, f"{year}-{month:02d}", row.get("name", ""), row.get("certNoEnc", ""), row.get("freeDays") or 0, "直通班" in (row.get("remark") or "")))
            print(f"  {campus} {year}-{month:02d}: {len(data.get('rows') or [])}条")

    pairs = list({(r[4], r[0]) for r in raw if r[4]})
    decoded = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(decrypt_one, (cipher, hid, token)): (cipher, hid) for cipher, hid in pairs}
        for future in concurrent.futures.as_completed(futures):
            cipher, plain = future.result()
            decoded[futures[future]] = plain

    conn = sqlite3.connect(DB, timeout=60)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS board_compare_monthly (
        cert TEXT, month TEXT, name TEXT, ams_days INTEGER DEFAULT 0, campus TEXT,
        PRIMARY KEY (cert, month, campus)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS board_compare (
        cert TEXT NOT NULL, campus TEXT NOT NULL DEFAULT '', name TEXT,
        ams_days INTEGER DEFAULT 0, other_days INTEGER DEFAULT 0,
        ams_amt REAL DEFAULT 0, other_amt REAL DEFAULT 0,
        ams_zt INTEGER DEFAULT 0, other_zt INTEGER DEFAULT 0,
        other_exist INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        PRIMARY KEY (cert, campus)
    )""")

    # 只替换本次月份的AMS月度数据，不碰对方记录。
    for month in range(start_month, end_month + 1):
        c.execute("DELETE FROM board_compare_monthly WHERE month=?", (f"{year}-{month:02d}",))

    for hid, campus, month, name, cert_enc, days, is_zt in raw:
        cert = decoded.get((cert_enc, hid), "")
        if not cert:
            continue
        c.execute("SELECT ams_days FROM board_compare_monthly WHERE cert=? AND month=? AND campus=?", (cert, month, campus))
        old = c.fetchone()
        if old:
            c.execute("UPDATE board_compare_monthly SET ams_days=ams_days+? WHERE cert=? AND month=? AND campus=?", (days, cert, month, campus))
        else:
            c.execute("INSERT INTO board_compare_monthly(cert,month,name,ams_days,campus) VALUES(?,?,?,?,?)", (cert, month, name, days, campus))

    # 从完整月度表重算AMS累计；对方字段只从原有board_compare中保留。
    c.execute("SELECT cert,campus,MAX(name),SUM(ams_days) FROM board_compare_monthly GROUP BY cert,campus")
    totals = {(r[0], r[1]): {"name": r[2], "days": r[3]} for r in c.fetchall()}
    c.execute("SELECT cert,campus,name,other_days,other_amt,other_zt,other_exist,ams_zt FROM board_compare")
    existing = {(r[0], r[1]): r for r in c.fetchall()}

    for key, old in existing.items():
        if key in totals:
            info = totals.pop(key)
            campus = key[1]
            amt = 0 if campus == "小新公寓" else info["days"] * 25
            c.execute("UPDATE board_compare SET name=?,ams_days=?,ams_amt=? WHERE cert=? AND campus=?", (info["name"], info["days"], amt, key[0], campus))
        else:
            c.execute("UPDATE board_compare SET ams_days=0,ams_amt=0,ams_zt=0 WHERE cert=? AND campus=?", key)

    for (cert, campus), info in totals.items():
        old = existing.get((cert, campus))
        other_days = old[3] if old else 0
        other_amt = old[4] if old else 0
        other_zt = old[5] if old else 0
        other_exist = old[6] if old else 0
        amt = 0 if campus == "小新公寓" else info["days"] * 25
        c.execute("INSERT OR REPLACE INTO board_compare(cert,campus,name,ams_days,other_days,ams_amt,other_amt,ams_zt,other_zt,other_exist) VALUES(?,?,?,?,?,?,?,?,?,?)", (cert,campus,info["name"],info["days"],other_days,amt,other_amt,0,other_zt,other_exist))

    conn.commit()
    conn.close()
    print("AMS更新完成；对方数据未读取、未删除、未覆盖")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())