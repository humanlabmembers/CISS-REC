#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量提取 BLZ 文件中的旋转弧度，并汇总到一个 CSV 中。

优先级：
  1. 若 Geo Objects 中存在 name 包含 "North Arrow" 且包含 "07" 的对象，
     使用其 t（弧度）作为第二列；
  2. 否则，使用 BPntList 头部的 rot（弧度）；

输出 CSV 格式：
    file,bp_rot_rad
    <文件名(无后缀)>,<最终使用的弧度值>
"""
import re
import sys
from pathlib import Path
import csv

# 匹配 BPntList 头
BPNTLIST_HEAD_RE = re.compile(
    r'<item\s+type="BPntList"[^>]*?>',
    re.IGNORECASE
)

def ATTR_RE(key: str):
    """通用属性匹配：key="数字"（支持负号和小数）"""
    return re.compile(rf'\b{key}\s*=\s*"(-?\d+(?:\.\d+)?)"', re.IGNORECASE)

def parse_bpntlist_rot(text: str):
    """
    从 <item type="BPntList"...> 标签头中抓取 rot（弧度）。
    若找不到则返回 None。
    """
    m = BPNTLIST_HEAD_RE.search(text)
    if not m:
        return None
    head = m.group(0)
    mm = ATTR_RE("rot").search(head)
    if not mm:
        return None
    return float(mm.group(1))

# =========================
# 解析 North Arrow
# =========================

# 简单匹配 Geo Object item 头（不限 type，只看 <item ...>）
ITEM_HEAD_RE = re.compile(
    r'<item\b[^>]*?>',
    re.IGNORECASE
)

NAME_ATTR_RE = re.compile(
    r'\bname\s*=\s*"([^"]*)"',  # name="xxx"
    re.IGNORECASE
)

def parse_north_arrow_rot(text: str):
    """
    在 Geo Objects（通用 <item ...>）中查找：
        name 同时满足：
          - 含 "north arrow"（不区分大小写）
          - 含 "07"
    的对象，并从其中读取属性 t（弧度）。

    找到则返回 float(t)，否则返回 None。
    """
    for m in ITEM_HEAD_RE.finditer(text):
        head = m.group(0)

        # 取 name
        nm_m = NAME_ATTR_RE.search(head)
        if not nm_m:
            continue

        nm = nm_m.group(1) or ""
        nm_l = nm.lower()

        # 必须包含 "north arrow"（不区分大小写）
        if "north arrow" not in nm_l:
            continue

        # 并且包含 "07"（大小写无关，这里数字不受影响）
        if "07" not in nm:
            continue

        # 读取 t 属性（弧度）
        t_m = ATTR_RE("t").search(head)
        if not t_m:
            continue
        try:
            t_val = float(t_m.group(1))
            return t_val
        except ValueError:
            continue

    return None

# =========================
# 主处理逻辑
# =========================

def process_folder(in_dir: Path, out_csv: Path):
    if not in_dir.is_dir():
        print("输入目录不存在：", in_dir, file=sys.stderr)
        sys.exit(2)

    files = sorted(in_dir.glob("*.blz"))
    if not files:
        print("未在输入目录找到 .blz 文件。", file=sys.stderr)
        sys.exit(3)

    rows = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")

            # 1) 先解析 BPntList rot
            bp_rot = parse_bpntlist_rot(text)

            # 2) 尝试解析 North Arrow 07 的 t
            north_rot = parse_north_arrow_rot(text)

            # 3) 选择最终使用的角度
            if north_rot is not None:
                final_rot = north_rot
                src = "NorthArrow_07"
            else:
                final_rot = bp_rot
                src = "BPntList"

            if final_rot is None:
                print(f"[WARN] {f.name}: 没有找到 BPntList.rot 且没有 North Arrow 07 的 t，跳过。")
                continue

            base = f.stem
            rows.append({"file": base, "bp_rot_rad": final_rot})

            if src == "NorthArrow_07":
                print(f"[OK] {f.name}: 使用 NorthArrow 07 t = {final_rot}")
            else:
                print(f"[OK] {f.name}: 使用 BPntList.rot = {final_rot}")

        except Exception as e:
            print(f"[ERROR] 处理 {f.name} 失败：{e}", file=sys.stderr)

    if not rows:
        print("没有任何文件成功解析角度，未生成 CSV。", file=sys.stderr)
        return

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "bp_rot_rad"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"[DONE] 共写入 {len(rows)} 条记录 -> {out_csv}")

def main():
    # 当前使用硬编码路径（按需修改）
    in_dir = Path(r"D:\DATA\CISS\blz")
    out_csv = Path(r"D:\DATA\CISS\north汇总.csv")

    process_folder(in_dir, out_csv)

if __name__ == "__main__":
    main()
