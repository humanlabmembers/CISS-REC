# -*- coding: utf-8 -*-
"""
Windows：CSV 中 XEP/XLLS/XLLD（大小写不敏感，且至少包含 XEP*）世界坐标 与 BLZ 曲线匹配。
输出：
  1) *_match_XEP_XLLS_XLLD.csv（含最近线段、t、投影点、距离；安全格式化）
  2) *_matched_curves.geojson（仅被用到的曲线，附形状度量）
  3) *_match_links.geojson（点到投影点的短连线，质检用）
"""

import re
import sys
import math
from pathlib import Path
import csv
import json

# ---- 配置 ----

# 名称前缀：大小写不敏感
# REG_NAME_PREFIX = re.compile(r'^(xep|xlls|zep|zlls|xcb|zcb)', re.IGNORECASE)
REG_NAME_PREFIX = re.compile(r'^(xep|zep|xcb|zcb|xlls|zlls|xlld|zlld|xdy|zdy)', re.IGNORECASE)
# BLZ 曲线正则
CURVE_ITEM_RE = re.compile(
    r'<item\s+type="(poly-curve|poly|line)"[^>]*>(.*?)</item>',
    re.IGNORECASE | re.DOTALL
)
VERTEX_RE = re.compile(
    r'X="(-?\d+(?:\.\d+)?)"\s+Y="(-?\d+(?:\.\d+)?)"',
    re.IGNORECASE
)
D_ATTR_RE = re.compile(r'\sd="([^"]+)"')

# ---- 通用小函数 ----
def extract_category(name: str):
    """从点名（如 XEP01, ZLLS2）提取类别：ep, cb, lls, lld, dy"""
    name_upper = name.upper()
    if name_upper.startswith(('XEP', 'ZEP')):
        return 'ep'
    elif name_upper.startswith(('XCB', 'ZCB')):
        return 'cb'
    elif name_upper.startswith(('XLLS', 'ZLLS')):
        return 'lls'
    elif name_upper.startswith(('XLLD', 'ZLLD')):
        return 'lld'
    elif name_upper.startswith(('XDY', 'ZDY')):
        return 'dy'
    else:
        return None  # 理论上不会发生，因已过滤
    
def _fmt(v):
    """安全格式化：None/NaN -> 空串；其余按 6 位小数输出。"""
    if v is None:
        return ""
    try:
        fv = float(v)
        if math.isnan(fv):
            return ""
        return f"{fv:.6f}"
    except Exception:
        return str(v)

def sniff_csv(path: Path):
    with path.open('r', encoding='utf-8', errors='ignore', newline='') as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[',','\t',';','|'])
            delim = dialect.delimiter
        except Exception:
            delim = ',' if sample.count(',') >= sample.count('\t') else '\t'
    return delim

def read_points_csv(csv_path: Path):
    """
    读取点 CSV -> [{'name', 'x_world', 'y_world'}...]
    仅保留名字前缀为 XEP/XLLS/XLLD（大小写不敏感）。
    """
    delim = sniff_csv(csv_path)
    rows = []
    with csv_path.open('r', encoding='utf-8', errors='ignore', newline='') as f:
        reader = csv.DictReader(f, delimiter=delim)
        if not reader.fieldnames:
            return rows
        fields = { (k or '').strip().lower(): k for k in reader.fieldnames }
        col_name = fields.get('name') or fields.get('点名') or fields.get('id') or list(reader.fieldnames)[0]
        col_x = fields.get('x_world') or fields.get('x') or fields.get('x坐标') or 'x'
        col_y = fields.get('y_world') or fields.get('y') or fields.get('y坐标') or 'y'

        for r in reader:
            try:
                name = str(r[col_name]).strip()
                if not REG_NAME_PREFIX.match(name):
                    continue
                xw = float(str(r[col_x]).strip())
                yw = float(str(r[col_y]).strip())
                rows.append({'name': name, 'x_world': xw, 'y_world': yw})
            except Exception:
                continue
    return rows

def parse_curves_from_blz(blz_text: str):
    """提取曲线（poly-curve / poly / line）的顶点（世界坐标）与可选名字 d。"""
    curves = []
    for i, m in enumerate(CURVE_ITEM_RE.finditer(blz_text)):
        typ = m.group(1).lower()
        block = m.group(0)
        pts = [(float(x), float(y)) for x,y in VERTEX_RE.findall(block)]
        nm = None
        d_m = D_ATTR_RE.search(block)
        if d_m:
            nm = d_m.group(1)
        if len(pts) >= 2:  # 过滤退化
            curves.append({'idx': i, 'type': typ, 'name': nm, 'pts': pts})
    return curves

def dist_point_to_segment(px, py, ax, ay, bx, by):
    """点到线段距离、投影参数 t∈[0,1]、投影点坐标。"""
    vx = bx - ax; vy = by - ay
    wx = px - ax; wy = py - ay
    L2 = vx*vx + vy*vy
    if L2 <= 1e-12:
        return math.hypot(px - ax, py - ay), 0.0, ax, ay
    t = (wx*vx + wy*vy) / L2
    t = max(0.0, min(1.0, t))
    projx = ax + t * vx
    projy = ay + t * vy
    return math.hypot(px - projx, py - projy), t, projx, projy

def match_points_to_curves(points, curves):
    matches = []
    curve_usage = {}  # curve_idx -> set of categories

    for p in points:
        px, py = p['x_world'], p['y_world']
        best = (float('inf'), None, -1, float('nan'), float('nan'), float('nan'))
        for c in curves:
            pts = c['pts']
            for si in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[si], pts[si+1]
                d, t, qx, qy = dist_point_to_segment(px, py, ax, ay, bx, by)
                if d < best[0]:
                    best = (d, c, si, t, qx, qy)

        dmin, cbest, si, t, qx, qy = best
        match = {
            'name': p['name'],
            'x_world': px,
            'y_world': py,
            'curve_idx': None if cbest is None else cbest['idx'],
            'curve_type': None if cbest is None else cbest['type'],
            'curve_name': None if cbest is None else cbest['name'],
            'seg_idx': si,
            't_on_seg': t,
            'distance': dmin,
            'proj_x': qx,
            'proj_y': qy
        }
        matches.append(match)

        # 记录曲线使用情况
        if cbest is not None:
            cat = extract_category(p['name'])
            if cat:
                idx = cbest['idx']
                if idx not in curve_usage:
                    curve_usage[idx] = set()
                curve_usage[idx].add(cat)

    return matches, curve_usage

def curve_metrics(pts):
    """曲线形状信息：顶点数、总长度、包围盒、质心（顶点均值）。"""
    n = len(pts)
    length = 0.0
    for i in range(n-1):
        (ax, ay), (bx, by) = pts[i], pts[i+1]
        length += math.hypot(bx-ax, by-ay)
    xs = [x for x,_ in pts] if n else [0.0]
    ys = [y for _,y in pts] if n else [0.0]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    cx = sum(xs)/n if n else 0.0
    cy = sum(ys)/n if n else 0.0
    return {
        'vertex_count': n,
        'length': length,
        'bbox_minx': bbox[0],
        'bbox_miny': bbox[1],
        'bbox_maxx': bbox[2],
        'bbox_maxy': bbox[3],
        'centroid_x': cx,
        'centroid_y': cy
    }

def write_matches_csv(out_path: Path, csv_file: Path, blz_file: Path, matches, tol: float):
    """输出匹配结果 CSV（安全格式化，避免 None/NaN 报错）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'csv_file','blz_file','name','x_world','y_world',
            'curve_idx','curve_type','curve_name','seg_idx','t_on_seg',
            'proj_x','proj_y','distance_m','within_tol'
        ])
        for m in matches:
            w.writerow([
                csv_file.name, blz_file.name, m.get('name', ''),
                _fmt(m.get('x_world')), _fmt(m.get('y_world')),
                m.get('curve_idx'), m.get('curve_type'), m.get('curve_name'),
                (m.get('seg_idx') if m.get('seg_idx') is not None else -1),
                _fmt(m.get('t_on_seg')),
                _fmt(m.get('proj_x')), _fmt(m.get('proj_y')),
                _fmt(m.get('distance')),
                1 if (isinstance(m.get('distance'), (int,float)) and m['distance'] <= tol) else 0
            ])

def write_curves_geojson(out_path: Path, curves, used_idx_set, csv_file: Path, blz_file: Path, curve_usage):
    """仅导出“被使用到的曲线”到 GeoJSON，附形状度量属性及匹配的点类别。"""
    feats = []
    for c in curves:
        idx = c['idx']
        if idx not in used_idx_set:
            continue
        if len(c['pts']) < 2:
            continue

        metrics = curve_metrics(c['pts'])

        # 获取匹配的类别列表，排序后转为字符串或列表
        cats = sorted(curve_usage.get(idx, []))
        # 可选：存为逗号分隔字符串 或 JSON 列表；这里用列表更规范
        props = {
            "curve_idx": idx,
            "curve_type": c['type'],
            "curve_name": c['name'],
            "matched_categories": cats,  # e.g., ["ep", "cb"]
            **metrics
        }

        feats.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "LineString",
                "coordinates": [[x, y] for x, y in c['pts']]
            }
        })
    fc = {"type": "FeatureCollection", "features": feats}
    out_path.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    # 固定路径（按你的需求）
    csv_dir = Path(r'D:\DATA\CISS\世界坐标全站仪数据')
    blz_dir = Path(r'D:\DATA\CISS\blz')
    out_dir = Path(r'D:\DATA\CISS\roads_EP_CB')
    out_dir_csv = Path(r'D:\DATA\CISS\roads_EP_CBcsv')
    tol = 0.50  # m，仅用于 within_tol/链接可视化判断

    if not csv_dir.is_dir():
        print('CSV 目录不存在：', csv_dir, file=sys.stderr); sys.exit(2)
    if not blz_dir.is_dir():
        print('BLZ 目录不存在：', blz_dir, file=sys.stderr); sys.exit(3)
    out_dir.mkdir(parents=True, exist_ok=True)

    blz_map = {p.stem.lower(): p for p in blz_dir.glob('*.blz')}
    if not blz_map:
        print('在 BLZ 目录未找到 .blz 文件。', file=sys.stderr); sys.exit(4)

    csv_files = list(csv_dir.glob('*.csv'))
    if not csv_files:
        print('在 CSV 目录未找到 .csv 文件。', file=sys.stderr); sys.exit(5)

    for csv_file in csv_files:
        base = csv_file.stem
        candidates = [
            base,
            re.sub(r'_points_world$', '', base, flags=re.IGNORECASE),
            re.sub(r'_points$', '', base, flags=re.IGNORECASE),
        ]
        blz_path = None
        for cand in candidates:
            p = blz_map.get(cand.lower())
            if p and p.exists():
                blz_path = p
                break
        if not blz_path:
            print(f'[SKIP] {csv_file.name}: 未找到同名 BLZ（{candidates[1]}.blz）。')
            continue

        # 读点（仅保留 XEP/XLLS/XLLD；大小写不敏感）
        points = read_points_csv(csv_file)
        if not points:
            print(f'[INFO] {csv_file.name}: 无 XEP/XLLS/XLLD 点，跳过。')
            continue

        # # 要求至少含有 XEP*
        # if not any(p['name'].upper().startswith('XEP') for p in points):
        #     print(f'[SKIP] {csv_file.name}: 不含 XEP* 点，按要求跳过。')
        #     continue

        # 读 BLZ 并解析曲线
        blz_text = blz_path.read_text(encoding='utf-8', errors='ignore')
        curves = parse_curves_from_blz(blz_text)
        if not curves:
            print(f'[WARN] {blz_path.name}: 未解析到曲线（poly-curve/poly/line）。')
            continue

        # 匹配
        matches, curve_usage = match_points_to_curves(points, curves)

        # 输出 1：点-曲线匹配 CSV（安全格式化）
        out_csv = out_dir_csv / f'{base}_curves.csv'
        write_matches_csv(out_csv, csv_file, blz_path, matches, tol)

        # 输出 2：被使用到的曲线 GeoJSON（附形状度量）
        used_idx = {m['curve_idx'] for m in matches if m.get('curve_idx') is not None}
        out_curves_geojson = out_dir / f'{base}.geojson'
        write_curves_geojson(out_curves_geojson, curves, used_idx, csv_file, blz_path, curve_usage)

        # 输出 3：点-投影 质检链接 GeoJSON
        # out_links_geojson = out_dir / f'{base}_match_links.geojson'
        # write_links_geojson(out_links_geojson, matches, csv_file, blz_path, tol)

        print(f'[OK] {csv_file.name} ->')
        # print(f'     - {out_csv.name}')
        print(f'     - {out_curves_geojson.name}')
        # print(f'     - {out_links_geojson.name}（点数 {len(points)}，曲线 {len(curves)}，命中曲线 {len(used_idx)}）')

if __name__ == '__main__':
    main()
