# -*- coding: utf-8 -*-
"""
删除文件夹中仅含一条 LineString 的 GeoJSON 文件。
"""

import json
from pathlib import Path
import sys

def is_single_linestring_geojson(file_path: Path) -> bool:
    """判断是否为只含一个 LineString 的 GeoJSON 文件。"""
    try:
        data = json.loads(file_path.read_text(encoding='utf-8'))
        if data.get('type') != 'FeatureCollection':
            return False
        features = data.get('features', [])
        if len(features) != 1:
            return False
        feat = features[0]
        geom = feat.get('geometry')
        if not geom:
            return False
        return geom.get('type') == 'LineString'
    except Exception:
        # 非法 JSON 或非 GeoJSON，不删除
        return False

def main():
    folder = Path(r'D:\DATA\CISS\roads_EP_CB')  # ← 修改为你自己的文件夹路径

    if not folder.is_dir():
        print(f"错误：目录不存在 {folder}", file=sys.stderr)
        sys.exit(1)

    geojson_files = list(folder.glob('*.geojson'))
    deleted = 0

    for f in geojson_files:
        if is_single_linestring_geojson(f):
            print(f"删除: {f.name}")
            f.unlink()  # 删除文件
            deleted += 1

    print(f"\n共删除 {deleted} 个仅含单条 LineString 的 GeoJSON 文件。")

if __name__ == '__main__':
    main()