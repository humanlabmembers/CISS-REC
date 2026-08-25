#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BLZ 批处理脚本（增强版，veh_id 来自同名 Excel 的 Vehicle 分表）

- 自动清理 XML 1.0 不允许的控制字符与裸 &，修复解析错误
- 遍历文件夹内所有 .blz
- 提取 item type="gosmodel": name, matLclr, make, pX, pY, t（与 t 的角度制）
- 先识别 North Arrow（记录角度），其余按 (name, make) 分组并按出现顺序标注 occurrence_index
- 车辆 ID 不再自增：从 “同名 Excel 的 Vehicle 分表” 中按不区分大小写匹配 Make，取 VEHNUM 作为 veh_id
- 每个 .blz 输出一个同名 .csv 到 out_dir
- ✅ 新增：写出前检查同一 veh_id 是否对应多个 (name, make)；若有冲突，则将除第一组外的其余组拆分并分配未占用的最小正整数 veh_id，同时更新 group_name

用法（示例，路径按需改）:
    python blz_extract.py --blz-dir "C:/.../BLZ/blz文件" --xls-dir "C:/.../BLZ/表格" --out-dir "C:/.../BLZ/BLZ_vehicles"
"""

import argparse
import math
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import csv
import re

# ---------- XML 清理 ----------
INVALID_XML_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x84\x86-\x9F]')
BARE_AMP_RE = re.compile(r'&(?![a-zA-Z#])')

def sanitize_xml(text: str) -> str:
    text = INVALID_XML_RE.sub('', text)
    text = BARE_AMP_RE.sub('&amp;', text)

    def _is_xml10_char(cp: int) -> bool:
        return (cp in (0x9, 0xA, 0xD) or
                0x20 <= cp <= 0xD7FF or
                0xE000 <= cp <= 0xFFFD or
                0x10000 <= cp <= 0x10FFFF)

    def _replace_numeric_entity(m):
        s = m.group(0)
        try:
            if s.startswith('&#x') or s.startswith('&#X'):
                cp = int(s[3:-1], 16)
            else:
                cp = int(s[2:-1], 10)
        except Exception:
            return ''
        return s if _is_xml10_char(cp) else ''

    text = re.sub(r'&#x[0-9A-Fa-f]+;|&#\d+;', _replace_numeric_entity, text)
    return text

def _to_float(v, default=None):
    try:
        return float(v)
    except Exception:
        return default

def extract_speed_limit_kmph(root) -> float | None:
    s = ET.tostring(root, encoding='unicode')
    m = re.search(
        r'speed\s*limit[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*(?:kmph|km/h|kph)',
        s, flags=re.I
    )
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None

# ---------- Excel 读取（支持 .xlsx / .xls） ----------
def _is_ole2_xls(path: Path) -> bool:
    try:
        with path.open('rb') as f:
            sig = f.read(8)
        return sig == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'
    except Exception:
        return False

def _read_excel_all_sheets(path: Path):
    """
    返回 {sheet_name: DataFrame}；优先 openpyxl（xlsx），
    若检测为 OLE2（xls），尝试 xlrd（需要 xlrd<=1.2.0）。
    """
    import pandas as pd
    if not path.exists():
        raise FileNotFoundError(path)

    # OLE2 BIFF（.xls）
    if _is_ole2_xls(path):
        try:
            import xlrd  # 需要本地安装 xlrd==1.2.0
        except Exception as e:
            raise RuntimeError(
                f"检测到老版 Excel (.xls/OLE2)：{path.name}。请安装 xlrd==1.2.0 或将其另存为 .xlsx 后再试。原始错误：{e}"
            )
        return pd.read_excel(path, sheet_name=None, header=0, engine="xlrd")

    # 现代 .xlsx
    try:
        return pd.read_excel(path, sheet_name=None, header=0, engine="openpyxl")
    except Exception:
        # 回退自动引擎
        return pd.read_excel(path, sheet_name=None, header=0)

def _find_vehicle_sheet_name(all_sheets: dict[str, 'pd.DataFrame']) -> str | None:
    for nm in all_sheets.keys():
        if nm and nm.strip().lower() == "vehicle":
            return nm
    for nm in all_sheets.keys():
        if nm and "vehicle" in nm.strip().lower():
            return nm
    return None

def _normalize_col(c: str) -> str:
    return re.sub(r'\s+', '', c or '').strip().lower()

def load_vehicle_map_from_workbook(xls_path: Path) -> dict[str, str]:
    """
    读取工作簿的 Vehicle 分表，构建 { make_lower: vehnum_str }。
    - Make/VEHNUM 列名大小写与空格均自适应
    - 多行同一 Make：取第一条
    """
    import pandas as pd
    frames = _read_excel_all_sheets(xls_path)
    sheet = _find_vehicle_sheet_name(frames)
    if sheet is None:
        raise RuntimeError(f"{xls_path.name} 内未找到 'Vehicle' 分表")

    df = frames[sheet].copy()
    if df is None or df.empty:
        raise RuntimeError(f"{xls_path.name} 的 Vehicle 表为空")

    cols = { _normalize_col(c): c for c in df.columns if isinstance(c, str) }

    make_key = None
    for cand in ["make", "vehmake", "vehiclemake"]:
        if cand in cols: make_key = cols[cand]; break
    if make_key is None:
        for k, raw in cols.items():
            if "make" in k:
                make_key = raw; break

    vehnum_key = None
    for cand in ["vehnum", "veh#", "vehicle#", "vehno", "veh_num", "vehicleid", "vehid"]:
        if cand in cols: vehnum_key = cols[cand]; break
    if vehnum_key is None:
        for k, raw in cols.items():
            if "veh" in k and ("num" in k or "id" in k or "#" in k):
                vehnum_key = raw; break

    if make_key is None or vehnum_key is None:
        raise RuntimeError(
            f"{xls_path.name} 的 Vehicle 表未找到 Make/VEHNUM 列（检测到的列：{list(df.columns)}）"
        )

    vehicle_map: dict[str, str] = {}
    for _, row in df.iterrows():
        mk = str(row.get(make_key, "")).strip()
        if not mk or mk.lower() == 'nan':
            continue
        mk_key = mk.casefold()
        if mk_key in vehicle_map:
            continue
        vehnum_val = row.get(vehnum_key, "")
        vehnum_str = str(vehnum_val).strip()
        if vehnum_str.lower() in ("nan", ""):
            continue
        vehicle_map[mk_key] = vehnum_str
    return vehicle_map

def resolve_veh_id_by_make(vehicle_map: dict[str, str], vehicle_make: str | None) -> str | None:
    """
    先精确匹配（casefold），否则退化为包含匹配（table_make 包含 vehicle_make）。
    多个包含匹配时，取 table_make 最长的一条。
    """
    if not vehicle_make:
        return None
    mkv = vehicle_make.strip().casefold()
    if not mkv:
        return None

    if mkv in vehicle_map:
        return vehicle_map[mkv]

    candidates = [(k, vehicle_map[k]) for k in vehicle_map.keys() if mkv in k]
    if not candidates:
        return None
    candidates.sort(key=lambda kv: len(kv[0]), reverse=True)
    return candidates[0][1]

# ---------- BLZ 解析 ----------
def parse_blz(blz_path: Path, vehicle_map: dict[str, str]):
    raw = blz_path.read_text(encoding='utf-8', errors='replace')
    try:
        root = ET.fromstring(raw)
    except Exception:
        cleaned = sanitize_xml(raw)
        root = ET.fromstring(cleaned)

    scene = root.find('scene')
    if scene is None:
        return []
    layers = scene.find('layers')
    if layers is None:
        return []

    speed_limit_kmph = extract_speed_limit_kmph(root)

    # 选 Default 图层或首个含 items 的图层
    default_layer = None
    for layer in layers.findall('layer'):
        if layer.get('name') == 'Default':
            default_layer = layer
            break
    if default_layer is None:
        for layer in layers.findall('layer'):
            if layer.find('items') is not None:
                default_layer = layer
                break
    if default_layer is None:
        return []
    items = default_layer.find('items')
    if items is None:
        return []

    gos = []
    for layer in layers.findall('layer'):
        items = layer.find('items')
        if items is None:
            continue
        gos.extend([it for it in items.findall('item') if it.get('type') == 'gosmodel'])

    if not gos:
        return []

    # 识别 North Arrow
    north_angle_t = None
    north_angle_deg = None
    for e in gos:
        nm = e.get('name', '') or ''
        if (not nm) or ('north arrow' in nm.lower()):
            t_raw = e.get('t')
            if t_raw is not None:
                north_angle_t = _to_float(t_raw, 0.0)
            if north_angle_t is not None:
                north_angle_deg = north_angle_t * 180.0 / math.pi
            break

    # 提取 make（从子树属性里）
    def extract_make(elem):
        s = ET.tostring(elem, encoding='unicode')
        m = re.search(r'make="([^"]+)"', s)
        return m.group(1) if m else None

    rows = []
    # occurrence_index 计数器（按 (name, make)）
    counters = {}

    for e in gos:
        name = e.get('name', '') or ''
        matLclr = e.get('matLclr')
        px = _to_float(e.get('pX'))
        py = _to_float(e.get('pY'))
        t = _to_float(e.get('t'))
        theta_deg = t * 180.0 / math.pi if t is not None else None

        # North Arrow 不参与分组和 veh_id
        if (not name) or ('north arrow' in name.lower()):
            rows.append({
                'file': blz_path.name,
                'north_angle_deg': north_angle_deg,
                'north_angle_t': north_angle_t,
                'veh_id': None,
                'group_name': 'North Arrow',
                'name': name,
                'matLclr': matLclr,
                'make': None,
                'occurrence_index': None,
                'x': px,
                'y': py,
                'theta_t': t,
                'theta_deg': theta_deg,
                'speed_limit_kmph': speed_limit_kmph,
            })
            continue

        make = extract_make(e)
        veh_id = resolve_veh_id_by_make(vehicle_map, make)

        # occurrence_index：按 (name, make) 计数
        cnt_key = (name, make)
        counters[cnt_key] = counters.get(cnt_key, 0) + 1
        occ_idx = counters[cnt_key]

        rows.append({
            'file': blz_path.name,
            'north_angle_deg': north_angle_deg,
            'north_angle_t': north_angle_t,
            'veh_id': veh_id,
            'group_name': (f'[veh:{veh_id}] {name} | make={make}'
                           if veh_id is not None else
                           f'[veh:?] {name} | make={make}'),
            'name': name,
            'matLclr': matLclr,
            'make': make,
            'occurrence_index': occ_idx,
            'x': px,
            'y': py,
            'theta_t': t,
            'theta_deg': theta_deg,
            'speed_limit_kmph': speed_limit_kmph,
        })

    return rows

# ---------- 冲突分离与重新编号 ----------
def _parse_int_or_none(v):
    try:
        if v is None: 
            return None
        s = str(v).strip()
        if s == "": 
            return None
        return int(float(s))
    except Exception:
        return None

def _format_group_name(veh_id, name, make):
    return (f'[veh:{veh_id}] {name} | make={make}'
            if veh_id is not None else
            f'[veh:?] {name} | make={make}')

def split_conflicting_veh_ids(rows):
    """
    同一文件内：若同一 veh_id 对应多个 (name, make)，则把除第一组外的组拆分为新 veh_id。
    规则：
      - 以 (name, make) 为“车辆定义”，同一 veh_id 出现多个不同 (name, make) 即判冲突
      - 新 veh_id 取“最小未被占用的正整数”
      - 维持各组在原 rows 中首次出现的顺序，第一组保留原 veh_id，其它组依次分配新 id
      - 同时更新 group_name 中的 [veh:xxx]
    返回更新后的 rows。
    """
    # 收集已占用的数值型 veh_id
    used_numeric_ids = set()
    for r in rows:
        vid = _parse_int_or_none(r.get('veh_id'))
        if vid is not None and vid > 0:
            used_numeric_ids.add(vid)

    def next_free_id():
        i = 1
        while i in used_numeric_ids:
            i += 1
        used_numeric_ids.add(i)
        return i

    # 建立 veh_id -> 组(key=(name,make)) -> 行索引列表；并记录每组首次出现顺序
    by_vid = {}
    group_first_pos = {}  # (veh_id, (name,make)) -> first_index
    for idx, r in enumerate(rows):
        vid = r.get('veh_id')
        if vid is None or str(vid).strip() == "":
            continue  # 无 veh_id（如 North Arrow）跳过
        key = (r.get('name', ''), r.get('make', None))
        by_vid.setdefault(vid, {})
        by_vid[vid].setdefault(key, [])
        by_vid[vid][key].append(idx)
        group_first_pos.setdefault((vid, key), idx)

    # 对每个 veh_id 检查是否有多个不同的 (name,make)
    for vid, groups in by_vid.items():
        if len(groups) <= 1:
            continue  # 无冲突

        # 按首次出现顺序对组排序；第一组保留原 veh_id
        ordered_groups = sorted(groups.items(), key=lambda kv: group_first_pos[(vid, kv[0])])

        # 第一组保持原样
        # 其余组依次分配新 id，并回写 rows
        for _, idx_list in ordered_groups[1:]:
            new_id = next_free_id()  # 数值型新 id
            new_id_str = str(new_id)

            for i in idx_list:
                rows[i]['veh_id'] = new_id_str
                rows[i]['group_name'] = _format_group_name(new_id_str, rows[i].get('name', ''), rows[i].get('make', None))

    return rows

# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--blz-dir', type=str, required=False,
                    default=r'D:\DATA\CISS\blz')
    ap.add_argument('--xls-dir', type=str, required=False,
                    default=r'D:\DATA\CISS\excels')
    ap.add_argument('--out-dir', type=str, required=False,
                    default=r'D:\DATA\CISS\vehicles_new')
    args = ap.parse_args()

    blz_dir = Path(args.blz_dir)
    xls_dir = Path(args.xls_dir)
    out_dir = Path(args.out_dir)

    if not blz_dir.exists():
        print(f'[ERROR] BLZ folder not found: {blz_dir}', file=sys.stderr)
        sys.exit(1)
    out_dir.mkdir(parents=True, exist_ok=True)

    blz_files = sorted(blz_dir.glob('*.blz'))
    if not blz_files:
        print('[WARN] No .blz files found under', blz_dir)
        sys.exit(0)

    fieldnames = [
        'file','north_angle_deg','north_angle_t','veh_id','group_name',
        'name','matLclr','make','occurrence_index','x','y',
        'theta_t','theta_deg','speed_limit_kmph'
    ]

    for blz in blz_files:
        # 寻找同名 Excel：优先 .xlsx，再 .xls
        candidates = [
            xls_dir / (blz.stem + '.xlsx'),
            xls_dir / (blz.stem + '.xls'),
        ]
        vehicle_map = {}
        excel_used = None
        for cand in candidates:
            if cand.exists():
                excel_used = cand
                try:
                    vehicle_map = load_vehicle_map_from_workbook(cand)
                    print(f'[INFO] Using vehicle table: {cand.name} (entries={len(vehicle_map)})')
                except Exception as e:
                    print(f'[WARN] Failed to load {cand.name}: {e}', file=sys.stderr)
                break
        if excel_used is None:
            print(f'[WARN] No matching Excel found for {blz.name} in {xls_dir}')

        try:
            rows = parse_blz(blz, vehicle_map)
        except Exception as e:
            print(f'[ERROR] Failed to parse {blz.name}: {e}', file=sys.stderr)
            continue

        # ✅ 新增：写出 CSV 前做冲突分离与重新编号
        rows = split_conflicting_veh_ids(rows)

        out_csv = out_dir / (blz.stem + '.csv')
        with out_csv.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f'[OK] {blz.name} -> {out_csv} ({len(rows)} rows)')

if __name__ == '__main__':
    main()
