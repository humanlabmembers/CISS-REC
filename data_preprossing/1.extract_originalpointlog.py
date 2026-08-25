#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量处理 BLZ：提取 <item type="point"> ... </item> 块中的点（必须具有 d="name" 属性），
并依据 BPntList 的 posX,posY,rot(θ) 变换为世界坐标。

用法（Windows 控制台）：
    python blz_extract_originalpointlog_to_world.py --in "D:\\data\\blz" --out "D:\\data\\out"

输出：每个输入文件会生成两份：
    <name>.csv
    <name>.geojson
"""
import argparse, re, json, os, math, sys
from pathlib import Path

POINT_ITEM_BLOCK_RE = re.compile(r'<item\s+type="point"[^>]*>(.*?)</item>', re.DOTALL | re.IGNORECASE)
# 仅提取具有 d="name" 的点；X/Y 为浮点（不支持科学计数法时可扩展）
POINT_ENTRY_RE = re.compile(
    r'X="(-?\d+(?:\.\d+)?)"[^>]{0,300}?Y="(-?\d+(?:\.\d+)?)"[^>]{0,400}?d="([^"]+)"',
    re.IGNORECASE
)
BPNTLIST_HEAD_RE = re.compile(r'<item\s+type="BPntList"[^>]*?>', re.IGNORECASE)
ATTR_RE = lambda key: re.compile(rf'\b{key}\s*=\s*"(-?\d+(?:\.\d+)?)"', re.IGNORECASE)

def parse_bpntlist(text: str):
    """从 <item type="BPntList"...> 标签头中抓 posX,posY,rot（弧度）。"""
    m = BPNTLIST_HEAD_RE.search(text)
    if not m:
        return None
    head = m.group(0)
    def getf(k, default=None):
        mm = ATTR_RE(k).search(head)
        return float(mm.group(1)) if mm else default
    posX = getf("posX", 0.0)
    posY = getf("posY", 0.0)
    rot  = getf("rot", 0.0)  # 弧度
    return {"posX": posX, "posY": posY, "rot": rot}

def extract_points(text: str):
    """提取所有 <item type="point">...</item> 内、且具有 d="name" 的点。"""
    pts = []
    blocks = POINT_ITEM_BLOCK_RE.findall(text)
    for blk in blocks:
        for x, y, name in POINT_ENTRY_RE.findall(blk):
            pts.append({"name": name, "x": float(x), "y": float(y)})
    return pts

def to_world(pts, bp):
    """按世界变换：先绕(0,0)旋转 θ，再平移 (posX,posY)。θ 为弧度。"""
    cos_t = math.cos(bp["rot"])
    sin_t = math.sin(bp["rot"])
    out = []
    for p in pts:
        x = p["x"]; y = p["y"]
        xr = cos_t * x - sin_t * y
        yr = sin_t * x + cos_t * y
        out.append({
            "name": p["name"],
            "x_local": x, "y_local": y,
            "x_world": bp["posX"] + xr,
            "y_world": bp["posY"] + yr
        })
    return out

def write_csv(path: Path, rows):
    import csv
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name","x_local","y_local","x_world","y_world"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

def write_geojson(path: Path, rows):
    """同名点按出现顺序连成 LineString（世界坐标）。"""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        groups[r["name"]].append([r["x_world"], r["y_world"]])
    fc = {"type":"FeatureCollection","features":[]}
    for name, coords in groups.items():
        fc["features"].append({
            "type":"Feature",
            "properties":{"name": name, "count": len(coords)},
            "geometry":{"type":"LineString","coordinates": coords}
        })
    path.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")

def process_file(fin: Path, fout_dir: Path,out_json_dir: Path):
    text = fin.read_text(encoding="utf-8", errors="ignore")

    # 1) 解析 BPntList（旋转/平移参数）
    bp = parse_bpntlist(text)
    if not bp:
        print(f"[WARN] {fin.name}: 未找到 BPntList，跳过。")
        return

    # 2) 提取所有具有 d="name" 的点
    all_points = extract_points(text)
    if not all_points:
        print(f"[WARN] {fin.name}: 未找到带 d=\"name\" 的 point，跳过。")
        return

    # 3) 局部 -> 世界坐标变换
    rows = to_world(all_points, bp)
    if not rows:
        print(f"[INFO] {fin.name}: 无可导出点。")
        return

    # 4) 写出 CSV / GeoJSON
    base = fin.stem
    fout_dir.mkdir(parents=True, exist_ok=True)
    csv_path = fout_dir / f"{base}.csv"
    geo_path = out_json_dir / f"{base}.geojson"
    write_csv(csv_path, rows)
    # 如需 GeoJSON，请取消下一行注释
    # write_geojson(geo_path, rows)
    print(f"[OK] {fin.name} -> {csv_path.name}, {geo_path.name}")

def main():
    ap = argparse.ArgumentParser()
    # 如需命令行传参，请取消注释：
    # ap.add_argument("--in", dest="in_dir", required=True, help="输入含 .blz 的文件夹")
    # ap.add_argument("--out", dest="out_dir", required=True, help="输出文件夹")
    # args = ap.parse_args()

    # 当前使用硬编码路径（请按需修改）
    in_dir = Path(r'D:\DATA\CISS\blz')
    out_csv_dir = Path(r'D:\DATA\CISS\世界坐标全站仪数据')
    out_json_dir = Path(r'D:\DATA\CISS\世界坐标全站仪数据顺序geojson')
    if not in_dir.is_dir():
        print("输入目录不存在：", in_dir, file=sys.stderr); sys.exit(2)
    files = list(in_dir.glob("*.blz"))
    if not files:
        print("未在输入目录找到 .blz 文件。", file=sys.stderr); sys.exit(3)

    for f in files:
        try:
            process_file(f, out_csv_dir,out_json_dir)
        except Exception as e:
            print(f"[ERROR] 处理 {f.name} 失败：{e}", file=sys.stderr)

if __name__ == "__main__":
    main()
