#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""包住数据对比v2（全部校区，AMS分月+累计，对方累计，并发解密）
表结构：
  board_compare_monthly: cert+month 每人每月 (cert, month, name, ams_days, campus)
  board_compare: 累计 (cert, name, ams_days, other_days, campus)
用法: python3 compare_board_v2.py [起始月] [结束月] [年份]
默认：只拉取上一个完整月份；历史补齐可用 python3 compare_board_v2.py 1 7 2026
"""
import json
import concurrent.futures
import openpyxl
import sqlite3
import urllib.request
import os
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TOKEN = open(os.path.join(BASE_DIR, 'cache', 'ams_token.txt')).read().strip()
AMS_BASE = "https://ams.xintujing.online"
EXCEL_PATH = os.path.join(BASE_DIR, "documents", "doc_747192f942a6_4.1-8.9包住(1).xlsx")
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


def parse_price(price_code):
    """从房费规则提取单价（如'25元基础房费'→25）"""
    import re
    if not price_code:
        return 0
    m = re.search(r'(\d+\.?\d*)', price_code)
    return float(m.group(1)) if m else 0


def main():
    import sys
    # 月份参数：不传参时只拉取上一个完整月份；显式传参仍可补历史范围。
    # 例如 2026-09-01 默认只拉 2026年8月。
    current = date.today()
    year = int(sys.argv[3]) if len(sys.argv) > 3 else current.year
    if len(sys.argv) > 1:
        start_month = int(sys.argv[1])
        end_month = int(sys.argv[2]) if len(sys.argv) > 2 else start_month
    else:
        if current.month == 1 and year == current.year:
            print(f"{year}年1月没有上一个完整月份，跳过本次拉取")
            return
        start_month = end_month = current.month - 1 if year == current.year else 12
    if not 1 <= start_month <= end_month <= 12:
        raise ValueError(f"月份范围无效: {start_month}-{end_month}")
    print(f"拉取月份范围: {year}年{start_month}月 - {year}年{end_month}月")

    conn = sqlite3.connect(DB, timeout=30)
    c = conn.cursor()
    # 累计表（按cert+校区唯一，同人跨校区各自一行）
    c.execute("""CREATE TABLE IF NOT EXISTS board_compare (
        cert TEXT NOT NULL, campus TEXT NOT NULL DEFAULT '', name TEXT,
        ams_days INTEGER DEFAULT 0, other_days INTEGER DEFAULT 0,
        ams_amt REAL DEFAULT 0, other_amt REAL DEFAULT 0,
        ams_zt INTEGER DEFAULT 0, other_zt INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        PRIMARY KEY (cert, campus)
    )""")
    # 分月表（cert+month+campus唯一，不同校区分开）
    c.execute("""CREATE TABLE IF NOT EXISTS board_compare_monthly (
        cert TEXT, month TEXT, name TEXT, ams_days INTEGER DEFAULT 0, campus TEXT,
        PRIMARY KEY (cert, month, campus)
    )""")
    c.execute("DELETE FROM board_compare")
    c.execute("DELETE FROM board_compare_monthly")

    # 1. 拉全部校区AMS数据（先收集，后统一解密）
    print("=== 1. 拉取AMS数据 ===")
    raw_records = []  # (hotel_id, hotel_name, month, name, cert_enc, days, price, is_zt)
    for hid, hname in CAMPUSES:
        for month in range(start_month, end_month + 1):
            d = ams_get(f"/hotel/web/reports/freeStayDataList/{hid}",
                        {"hotelId": hid, "year": str(year), "month": str(month), "months": f"{year}-{month:02d}"})
            rows = d.get("rows") or []
            for r in rows:
                is_zt = 1 if '直通班' in (r.get("remark") or '') else 0
                raw_records.append((hid, hname, f"{year}-{month:02d}", r.get("name", ""),
                                    r.get("certNoEnc", ""), r.get("freeDays") or 0,
                                    parse_price(r.get("roomPriceCode", "")), is_zt))
        print(f"  {hname} 完成")

    print(f"  共{len(raw_records)}条，并发解密...")

    # 2. 并发解密（去重，raw_records: (hid, hname, month, name, cert_enc, days)）
    # r[4]=cert_enc, r[0]=hid；所有校区密钥相同，但按校区解密更稳
    unique_pairs = list(set((r[4], r[0]) for r in raw_records if r[4]))
    decrypt_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        future_to_key = {ex.submit(decrypt_one, (cipher, hid)): (cipher, hid) for cipher, hid in unique_pairs}
        for fut in concurrent.futures.as_completed(future_to_key):
            cipher, plain = fut.result()
            decrypt_map[(cipher, future_to_key[fut][1])] = plain
    print(f"  解密完成: {len(decrypt_map)}个")

    # 3. 分月入库
    ams_total = {}  # (cert, campus) -> {name, days, amt, is_zt}
    for hid, hname, month, name, cert_enc, days, price, is_zt in raw_records:
        cert = decrypt_map.get((cert_enc, hid), "")
        if not cert:
            continue
        # 金额：非小新校区按25元/天，小新(10145)不定价=0
        amt = days * 25 if hname != '小新公寓' else 0
        # 分月
        # 同一人同月多条（如邹珊珊4月两条：15天+3天），需累加（按cert+month+campus）
        c.execute("SELECT ams_days FROM board_compare_monthly WHERE cert=? AND month=? AND campus=?", (cert, month, hname))
        exist = c.fetchone()
        if exist:
            c.execute("UPDATE board_compare_monthly SET ams_days = ams_days + ? WHERE cert=? AND month=? AND campus=?", (days, cert, month, hname))
        else:
            c.execute("INSERT INTO board_compare_monthly (cert, month, name, ams_days, campus) VALUES (?,?,?,?,?)",
                      (cert, month, name, days, hname))
        # 累计（按cert+校区）
        key = (cert, hname)
        if key not in ams_total:
            ams_total[key] = {"name": name, "days": 0, "amt": 0, "is_zt": 0}
        ams_total[key]["days"] += days
        ams_total[key]["amt"] += amt
        if is_zt:
            ams_total[key]["is_zt"] = 1
    print(f"  AMS去重(按校区): {len(ams_total)}人")

    # 4. 对方Excel（排除直通班，只累计）
    print("\n=== 2. 对方Excel（累计）===")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb['Sheet1']
    other_people = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        cert = str(row[2]) if row[2] else ''
        name = row[3] if row[3] else ''
        days_raw = row[8]
        amt = row[7] or 0
        # 标记直通班（不排除，只标记，前端勾选时过滤）
        is_zt = 1 if (isinstance(days_raw, str) and '直通班' in days_raw) else 0
        days = int(days_raw) if isinstance(days_raw, (int, float)) else 0
        if cert:
            if cert not in other_people:
                other_people[cert] = {"name": name, "days": 0, "amt": 0, "is_zt": 0}
            other_people[cert]["days"] += days
            other_people[cert]["amt"] += amt if isinstance(amt, (int, float)) else 0
            if is_zt:
                other_people[cert]["is_zt"] = 1
    print(f"  对方去重: {len(other_people)}人")

    # 5. 对比入库（按cert+校区）
    print("\n=== 3. 对比入库 ===")
    # AMS按校区，对方按cert累计（无校区）→ 对方数据对到该cert的每个校区行
    for (cert, campus), info in ams_total.items():
        o = other_people.get(cert)
        c.execute("INSERT OR REPLACE INTO board_compare (cert, campus, name, ams_days, other_days, ams_amt, other_amt, ams_zt) VALUES (?,?,?,?,?,?,?,?)",
                  (cert, campus, info["name"], info["days"],
                   o["days"] if o else 0, info["amt"], o["amt"] if o else 0, info["is_zt"]))
    # 对方有但AMS没有的人
    ams_certs = set(k[0] for k in ams_total)
    for cert, info in other_people.items():
        if cert not in ams_certs:
            c.execute("INSERT OR REPLACE INTO board_compare (cert, campus, name, ams_days, other_days, ams_amt, other_amt, other_zt) VALUES (?,?,?,0,?,0,?,?)",
                      (cert, '', info["name"], info["days"], info["amt"], info.get("is_zt", 0)))
    conn.commit()

    both = sum(1 for k in ams_total if k[0] in other_people)
    only_ams = sum(1 for k in ams_total if k[0] not in other_people)
    only_other = len([x for x in other_people if x not in ams_certs])
    diff = sum(1 for k, v in ams_total.items() if k[0] in other_people and v["days"] != other_people[k[0]]["days"])
    print(f"  两边都有: {both} | 仅AMS: {only_ams} | 仅对方: {only_other} | 累计不一致: {diff}")
    conn.close()
    print("✅ 完成")


if __name__ == "__main__":
    main()
