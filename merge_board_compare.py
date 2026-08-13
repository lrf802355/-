#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建board_compare：按cert合并多校区（天数加总，校区=天数最多）
对比逻辑：同人多校区天数合并 vs 对方；导出时按cert+校区分行
"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB = os.path.join(BASE_DIR, 'finance.db')

conn = sqlite3.connect(DB, timeout=60)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. 建新表（按cert合并后）
c.execute("""CREATE TABLE board_compare_new (
    cert TEXT NOT NULL, campus TEXT NOT NULL DEFAULT '', name TEXT,
    ams_days INTEGER DEFAULT 0, other_days INTEGER DEFAULT 0,
    ams_amt REAL DEFAULT 0, other_amt REAL DEFAULT 0,
    ams_zt INTEGER DEFAULT 0, other_zt INTEGER DEFAULT 0,
    other_exist INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (cert, campus)
)""")

# 2. 按cert分组合并（保留多校区明细在monthly表，这里只存主校区汇总）
c.execute("""SELECT cert FROM board_compare GROUP BY cert""")
certs = c.fetchall()
print(f"总人数: {len(certs)}")

merged = 0
for row in certs:
    cert = row['cert']
    # 该cert的所有记录
    c.execute("""SELECT * FROM board_compare WHERE cert=?""", (cert,))
    recs = c.fetchall()
    if not recs:
        continue
    name = recs[0]['name'] or ''
    other_days = max(r['other_days'] or 0 for r in recs)
    other_amt = max(r['other_amt'] or 0 for r in recs)
    other_zt = max(r['other_zt'] or 0 for r in recs)
    other_exist = max(r['other_exist'] or 0 for r in recs)
    ams_zt = max(r['ams_zt'] or 0 for r in recs)

    # 有AMS天数的记录（非空校区）
    ams_recs = [r for r in recs if r['campus'] and (r['ams_days'] or 0) > 0]
    if ams_recs:
        ams_days = sum(r['ams_days'] or 0 for r in ams_recs)  # 合并总天数
        ams_amt = sum(r['ams_amt'] or 0 for r in ams_recs)    # 合并总金额
        main_campus = max(ams_recs, key=lambda r: r['ams_days'] or 0)['campus']  # 天数最多校区
        merged += 1
    else:
        # 仅对方有（无AMS天数）
        ams_days = 0
        ams_amt = 0
        main_campus = recs[0]['campus'] or ''

    c.execute("""INSERT OR REPLACE INTO board_compare_new 
                 (cert, campus, name, ams_days, other_days, ams_amt, other_amt, ams_zt, other_zt, other_exist)
                 VALUES (?,?,?,?,?,?,?,?,?,?)""",
              (cert, main_campus, name, ams_days, other_days, ams_amt, other_amt, ams_zt, other_zt, other_exist))

conn.commit()

# 3. 替换旧表
c.execute("DROP TABLE board_compare")
c.execute("ALTER TABLE board_compare_new RENAME TO board_compare")
conn.commit()

# 4. 验证
c.execute("SELECT COUNT(*) FROM board_compare")
total = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM board_compare WHERE cert IN (SELECT cert FROM board_compare GROUP BY cert HAVING COUNT(*)>1)")
dup = c.fetchone()[0]
print(f"新表: {total}人, 同cert多行: {dup}（应0）")

# 刘梦欣验证
c.execute("SELECT name, campus, ams_days, other_days FROM board_compare WHERE name='刘梦欣'")
for r in c.fetchall():
    print(f"  刘梦欣: {r['campus']} AMS{r['ams_days']} vs 对方{r['other_days']}")
conn.close()
print("✅ 合并完成")
