#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量绘制文件夹内的 GeoJSON 为 PNG。
- 支持 LineString / MultiLineString（忽略 Polygon）
- 以 LLD 开头（不区分大小写）的线用虚线绘制
- 同名输出到目标文件夹：<name>.png

用法示例：
  python geojson_batch_plot.py --in "D:/data/geo" --out "D:/data/png" --glob "*.geojson" --dpi 150
"""

import argparse
import json
from pathlib import Path
from typing import List, Tuple, Dict, Union

import numpy as np
import matplotlib
import matplotlib.pyplot as plt

# 可选：尽量减少中文显示问题（系统需安装相应字体）
def _setup_fonts():
    try:
        matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
        matplotlib.rcParams['axes.unicode_minus'] = False
    except Exception:
        pass

def _extract_lines(feature: Dict) -> List[Tuple[str, np.ndarray]]:
    """从一个 GeoJSON Feature 提取 (name, Nx2 array) 的折线集合。"""
    geom = feature.get("geometry") or {}
    gtype = (geom.get("type") or "").lower()
    props = feature.get("properties") or {}
    name = str(props.get("name") or props.get("Name") or props.get("NAME") or "")

    def to_xy(coords: List) -> np.ndarray:
        arr = []
        for c in coords:
            # 支持 [x,y] 或 [x,y,z]
            if isinstance(c, (list, tuple)) and len(c) >= 2:
                x, y = c[0], c[1]
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    arr.append((float(x), float(y)))
        return np.array(arr, dtype=float) if arr else np.empty((0, 2), dtype=float)

    lines = []
    if gtype == "linestring":
        xy = to_xy(geom.get("coordinates", []))
        if len(xy) >= 2:
            lines.append((name, xy))
    elif gtype == "multilinestring":
        for seg in geom.get("coordinates", []):
            xy = to_xy(seg)
            if len(xy) >= 2:
                lines.append((name, xy))
    # 如需 polygon 外轮廓，可自行扩展
    return lines

def _load_geojson_lines(path: Path) -> List[Tuple[str, np.ndarray]]:
    """读取单个 GeoJSON，返回所有 (name, Nx2) 折线。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    feats = data.get("features") or []
    all_lines: List[Tuple[str, np.ndarray]] = []
    for ft in feats:
        all_lines.extend(_extract_lines(ft))
    return all_lines

def _plot_one_geojson(geo_path: Path,
                      out_dir: Path,
                      dpi: int = 150,
                      figw: float = 9.0,
                      figh: float = 7.0,
                      max_legend_items: int = 18,
                      show_legend: bool = True) -> bool:
    """将单个 GeoJSON 绘制为 PNG。"""
    lines = _load_geojson_lines(geo_path)
    if not lines:
        print(f"[INFO] 无可绘制线段：{geo_path.name}")
        return False

    plt.figure(figsize=(figw, figh), dpi=dpi)
    n_labelled = 0

    for nm, xy in lines:
        if len(xy) < 2:
            continue
        # LLD 系列虚线
        ls = "--" if str(nm).upper().startswith("LLD") else "-"
        # 默认颜色，不指定
        # 图例项过多会遮挡，这里限制数量
        label = nm if (show_legend and n_labelled < max_legend_items and nm) else None
        if label is not None:
            n_labelled += 1
        plt.plot(xy[:, 0], xy[:, 1], ls=ls, linewidth=1.8, alpha=0.95, label=label)

    ax = plt.gca()
    ax.set_aspect("equal", adjustable="box")
    plt.xlabel("X")
    plt.ylabel("Y")
    plt.title(geo_path.stem)

    if show_legend and n_labelled > 0:
        plt.legend(fontsize=8, title="name (部分显示)")

    plt.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)
    plt.tight_layout()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / f"{geo_path.stem}.png"
    try:
        plt.savefig(out_png, bbox_inches="tight", dpi=dpi)
    finally:
        plt.close()

    print(f"[OK] {geo_path.name} -> {out_png.name}")
    return True

def main():
    _setup_fonts()

    ap = argparse.ArgumentParser(description="批量绘制 GeoJSON 为 PNG。")
    # ap.add_argument("--in",  dest="in_dir",  required=True, help="输入 GeoJSON 文件夹")
    # ap.add_argument("--out", dest="out_dir", required=True, help="输出 PNG 文件夹")
    ap.add_argument("--glob", default="*.geojson", help="文件匹配模式（默认：*.geojson）")
    ap.add_argument("--dpi", type=int, default=150, help="图片 DPI（默认 150）")
    ap.add_argument("--figw", type=float, default=9.0, help="图宽（英寸，默认 9）")
    ap.add_argument("--figh", type=float, default=7.0, help="图高（英寸，默认 7）")
    ap.add_argument("--max-legend-items", type=int, default=50, help="图例最多显示的线条数（默认 18）")
    ap.add_argument("--no-legend", action="store_true", help="不显示图例")
    args = ap.parse_args()

    in_dir  = Path(r'D:\DATA\CISS\roads_EP_CB')
    out_dir = Path(r'D:\DATA\CISS\geojson_EP_CB_png')
    if not in_dir.is_dir():
        raise SystemExit(f"[ERROR] 输入目录不存在：{in_dir}")

    files = sorted(in_dir.glob(args.glob))
    if not files:
        raise SystemExit(f"[ERROR] 未在 {in_dir} 匹配到文件：{args.glob}")

    n_ok = 0
    for g in files:
        try:
            if _plot_one_geojson(
                geo_path=g,
                out_dir=out_dir,
                dpi=args.dpi,
                figw=args.figw,
                figh=args.figh,
                max_legend_items=args.max_legend_items,
                show_legend=not args.no_legend,
            ):
                n_ok += 1
        except Exception as e:
            print(f"[ERROR] 处理失败：{g.name} -> {e}")

    print(f"[DONE] 成功输出 {n_ok}/{len(files)} 个 PNG 到：{out_dir}")

if __name__ == "__main__":
    main()
