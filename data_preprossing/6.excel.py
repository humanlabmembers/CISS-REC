# -*- coding: utf-8 -*-
"""
功能：
1) 从文件夹A收集所有文件名（去扩展名）
2) 在文件夹B中查找同名Excel（.xlsx/.xls/.xlsb/或误后缀）
3) 读取Excel，仅保留：
   - Crash: Summary
   - Vehicle: Initial Travel Lane, Posted Speed Limit, Event #,
              Pre-Event Movement (Prior to Recognition of Critical Event),
              Attempted Avoidance Maneuver
4) 输出到文件夹C（同名xlsx），仅含上述两张表与指定列
5) 宽松匹配表名与列名；记录详细日志与缺失清单

修改下方三条路径即可运行。
"""
import os
import sys
import csv
import json
import zipfile
from typing import Dict, List, Tuple
import pandas as pd

# ========== 修改这三行 ==========
FOLDER_A = r"D:\DATA\CISS\roads_EP_CB"        # 读取文件名（去扩展名）
FOLDER_B = r"D:\DATA\CISS\excels" # 查找同名 Excel
FOLDER_C = r"D:\DATA\CISS\道路对应的excels"    # 写出精简后的 Excel
# ===============================

# 需要保留的表与列
KEEP_SPEC = {
    "Crash": ["Summary"],
    "Vehicle": [
        "VEHNUM",
        "Initial Travel Lane",
        "Posted Speed Limit",
        "Event #",
        "Pre-Event Movement (Prior to Recognition of Critical Event)",
        "Attempted Avoidance Maneuver",
    ],
}

# --------- 工具函数 ---------
def norm(s: str) -> str:
    """宽松标准化：小写、去首尾空白、压缩多空格为单空格"""
    if s is None:
        return ""
    return " ".join(str(s).strip().lower().split())

def select_sheet_name(sheet_names: List[str], target: str) -> str:
    """先宽松相等，再包含匹配；返回真实sheet名或空串"""
    t = norm(target)
    # 相等匹配
    for s in sheet_names:
        if norm(s) == t:
            return s
    # 包含匹配
    for s in sheet_names:
        if t and t in norm(s):
            return s
    return ""

def select_columns(df: pd.DataFrame, wanted_cols: List[str]) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """
    在 df 中按宽松匹配选择列：
    - 先宽松相等，再包含匹配
    返回：筛选后的df、命中的原列名列表、未命中的目标列名列表
    """
    if df is None or df.empty:
        return df.iloc[0:0], [], wanted_cols[:]

    # 建立映射：标准化列名 -> 原列名（若重复取先见）
    norm_map: Dict[str, str] = {}
    for c in df.columns:
        nc = norm(c)
        if nc and nc not in norm_map:
            norm_map[nc] = c

    selected_orig = []
    missed = []
    for wc in wanted_cols:
        w = norm(wc)
        if not w:
            continue
        # 相等匹配
        if w in norm_map:
            selected_orig.append(norm_map[w])
            continue
        # 包含匹配
        cands = [orig for nc, orig in norm_map.items() if w in nc]
        if cands:
            selected_orig.append(cands[0])
        else:
            missed.append(wc)

    if not selected_orig:
        return df.iloc[0:0], [], wanted_cols[:]
    return df[selected_orig], selected_orig, missed

def detect_and_read_excel(path: str) -> Tuple[Dict[str, pd.DataFrame], str]:
    """
    尝试读取Excel，返回 (sheet_name -> DataFrame, flavor)
    flavor: 'xlsx' | 'xls' | 'xlsb'
    兼容：.xlsx（zip容器）、误后缀的.xls、.xlsb
    """
    ext = os.path.splitext(path)[1].lower()
    # 优先 xlsx（zip容器）
    is_zip = False
    try:
        is_zip = zipfile.is_zipfile(path)
    except Exception:
        is_zip = False

    # 1) 试 openpyxl （xlsx）
    if is_zip or ext == ".xlsx":
        try:
            xl = pd.ExcelFile(path, engine="openpyxl")
            frames = {s: xl.parse(s) for s in xl.sheet_names}
            return frames, "xlsx"
        except Exception:
            pass

    # 2) 试 xlrd （xls 或误后缀的xls）
    if ext in (".xls", ".xlsx", ".xlsm", ".xlt", ".xla"):
        try:
            xl = pd.ExcelFile(path, engine="xlrd")  # 需要 xlrd==1.2.0
            frames = {s: xl.parse(s) for s in xl.sheet_names}
            return frames, "xls"
        except Exception:
            pass

    # 3) 试 pyxlsb
    if ext == ".xlsb":
        try:
            xl = pd.ExcelFile(path, engine="pyxlsb")
            frames = {s: xl.parse(s) for s in xl.sheet_names}
            return frames, "xlsb"
        except Exception:
            pass

    # 全部失败
    raise RuntimeError("无法作为 xlsx/xls/xlsb 打开，文件可能损坏、加密或并非Excel。")

def find_source_excel(folder_b: str, stem: str) -> str:
    """
    在B中寻找与stem同名的Excel文件；优先 .xlsx，
    若不存在，则尝试 .xlsb / .xls / 以及“误后缀”的同名文件（仍以 .xlsx 名称但实际非zip）。
    """
    # 直查常见扩展名
    candidates = [
        os.path.join(folder_b, f"{stem}.xlsx"),
        os.path.join(folder_b, f"{stem}.xlsb"),
        os.path.join(folder_b, f"{stem}.xls"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p

    # 退而求其次：在B中列举所有文件，寻找以stem开头的Excel样式文件
    for f in os.listdir(folder_b):
        base, ext = os.path.splitext(f)
        if base == stem and ext.lower() in [".xlsx", ".xls", ".xlsb"]:
            p = os.path.join(folder_b, f)
            if os.path.isfile(p):
                return p
    return ""  # 未找到

# --------- 主流程 ---------
def main():
    if not os.path.isdir(FOLDER_A):
        print(f"[FATAL] FOLDER_A 不存在：{FOLDER_A}")
        sys.exit(1)
    if not os.path.isdir(FOLDER_B):
        print(f"[FATAL] FOLDER_B 不存在：{FOLDER_B}")
        sys.exit(1)
    os.makedirs(FOLDER_C, exist_ok=True)

    # 读取A的去扩展名文件名集合
    stems = []
    for f in os.listdir(FOLDER_A):
        p = os.path.join(FOLDER_A, f)
        if os.path.isfile(p):
            stem, _ = os.path.splitext(f)
            if stem:
                stems.append(stem)
    stems = sorted(set(stems))
    if not stems:
        print("[WARN] A 中未发现任何文件名，结束。")
        return

    # 日志与缺失记录
    summary_rows = []
    miss_excels = []     # B 中找不到的
    read_errors = []     # 打不开/损坏
    sheet_missing = []   # 缺表
    col_missing_rows = []  # 缺列明细

    ok_count = 0

    for stem in stems:
        src = find_source_excel(FOLDER_B, stem)
        if not src:
            print(f"[MISS] B 中找不到：{stem}.xlsx")
            miss_excels.append(stem)
            continue

        try:
            frames, flavor = detect_and_read_excel(src)
        except Exception as e:
            print(f"[ERR] 打不开文件：{src} -> {e}")
            read_errors.append({"name": stem, "path": src, "err": str(e)})
            continue

        sheet_names = list(frames.keys())
        out_frames = {}

        # 逐表处理
        for target_sheet, wanted_cols in KEEP_SPEC.items():
            real = select_sheet_name(sheet_names, target_sheet)
            if not real:
                print(f"[WARN] {os.path.basename(src)} 缺少表：{target_sheet}")
                sheet_missing.append({"name": stem, "sheet": target_sheet})
                continue

            df = frames.get(real, pd.DataFrame())
            df_sel, hit_cols, missed_cols = select_columns(df, wanted_cols)

            if len(hit_cols) == 0:
                print(f"[WARN] {os.path.basename(src)}::{target_sheet} 未命中任何目标列。")
                # 仍创建空表框架（保持表存在）
                out_frames[target_sheet] = df_sel
            else:
                out_frames[target_sheet] = df_sel

            if missed_cols:
                col_missing_rows.append({
                    "name": stem,
                    "sheet": target_sheet,
                    "missed_cols": missed_cols,
                    "hit_cols": hit_cols
                })
                print(f"[INFO] {os.path.basename(src)}::{target_sheet} 命中列: {hit_cols}；缺失: {missed_cols}")

        if not out_frames:
            print(f"[WARN] {os.path.basename(src)} 未提取到任何内容，跳过写出。")
            continue

        # 写出到C
        dst = os.path.join(FOLDER_C, f"{stem}.xlsx")
        try:
            with pd.ExcelWriter(dst, engine="openpyxl", mode="w") as writer:
                # 统一写出为规范表名：Crash、Vehicle
                for sheet_name in ["Crash", "Vehicle"]:
                    df_out = out_frames.get(sheet_name, pd.DataFrame().iloc[0:0])
                    df_out.to_excel(writer, index=False, sheet_name=sheet_name)
            ok_count += 1
        except Exception as e:
            print(f"[ERR] 写出失败：{dst} -> {e}")
            read_errors.append({"name": stem, "path": dst, "err": f"write_fail: {e}"})
            continue

        summary_rows.append({
            "name": stem,
            "source": src,
            "flavor": flavor,
            "dst": dst
        })

    # 汇总/导出日志
    report_dir = os.path.join(FOLDER_C, "_report")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary_rows, f, ensure_ascii=False, indent=2)
    with open(os.path.join(report_dir, "missing_excels.txt"), "w", encoding="utf-8") as f:
        for n in miss_excels:
            f.write(n + "\n")
    with open(os.path.join(report_dir, "read_errors.json"), "w", encoding="utf-8") as f:
        json.dump(read_errors, f, ensure_ascii=False, indent=2)
    # 缺表明细
    with open(os.path.join(report_dir, "missing_sheets.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "sheet"])
        for r in sheet_missing:
            w.writerow([r["name"], r["sheet"]])
    # 缺列明细
    with open(os.path.join(report_dir, "missing_columns.json"), "w", encoding="utf-8") as f:
        json.dump(col_missing_rows, f, ensure_ascii=False, indent=2)

    # 终端统计
    total = len(stems)
    print("\n========== 汇总 ==========")
    print(f"A 中文件名数：{total}")
    print(f"成功生成至 C：{ok_count}")
    print(f"B 中找不到：{len(miss_excels)}")
    print(f"读取/写出错误：{len(read_errors)}")
    print(f"缺表记录：{len(sheet_missing)}")
    print(f"缺列记录：{len(col_missing_rows)}")
    print(f"输出目录：{FOLDER_C}")
    print(f"报告目录：{report_dir}")

if __name__ == "__main__":
    main()
