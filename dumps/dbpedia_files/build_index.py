#!/usr/bin/env python3
"""
DBpedia TTL 文件 URI→偏移量索引构建脚本（rdflib 精确解析版）。

为每个 TTL 文件生成 3 个 Pickle 索引：
- {fn}_s_idx.pkl：主语 URI → 偏移量列表
- {fn}_p_idx.pkl：谓语 URI → 偏移量列表
- {fn}_o_idx.pkl：宾语 URI → 偏移量列表（仅当宾语是 URI 时）

输出：index/{fn}_{s/p/o}_idx.pkl
"""

import os
import pickle
import argparse
from tqdm import tqdm
from collections import defaultdict
from rdflib import Graph, URIRef, Literal


# ==================== 可选超参（文件顶部） ====================

# 输入：TTL 文件所在目录
INPUT_DIR = "."

# 输出：索引文件存放目录
OUTPUT_DIR = "./index"

# 要处理的 7 个 TTL 文件
FILE_LIST = [                            #   行数
    "labels_en.ttl",                     # 1284,5254
    "short_abstracts_en.ttl",            #  493,5281
    "long_abstracts_en.ttl",             #  493,5281
    "instance_types_en.ttl",             #  515,0434
    "instance_types_transitive_en.ttl",  # 3125,4272
    "mappingbased_objects_en.ttl",       # 1874,6176
    "mappingbased_literals_en.ttl",      # 1438,8539
    "article_categories_en.ttl",         # 2399,0516
    "redirects_en.ttl",                  #  769,9478
    "disambiguations_en.ttl",            #  153,7182
]

# ============================================================


def parse_triple(line: str, build_obj: bool = False):
    """
    用 rdflib 解析单行 TTL，返回 (s_uri, p_uri, o_uri_or_none)。

    如果 build_obj=False，不提取宾语 URI（节省解析开销）。
    如果 build_obj=True 且宾语是 URIRef，返回 o_uri；否则 o_uri=None。
    """
    g = Graph()
    try:
        g.parse(data=line, format="turtle")
    except Exception:
        return None, None, None

    for s, p, o in g:
        s_uri = str(s) if isinstance(s, URIRef) else None
        p_uri = str(p) if isinstance(p, URIRef) else None

        o_uri = None
        if build_obj and isinstance(o, URIRef):
            o_uri = str(o)
        # 如果宾语是 Literal，o_uri 保持 None

        return s_uri, p_uri, o_uri

    return None, None, None


def build_index_for_file(fname: str, input_dir: str, output_dir: str) -> None:
    """
    为单个 TTL 文件构建并输出 3 个 Pickle 索引（s/p/o）。
    """
    fpath = os.path.join(input_dir, fname)
    if not os.path.exists(fpath):
        print(f"[跳过] 文件不存在: {fpath}")
        return

    print(f"\n{'='*50}")
    print(f"构建索引: {fname}")
    print(f"{'='*50}")

    # 三个索引
    s_idx = defaultdict(list)  # 主语
    p_idx = defaultdict(list)  # 谓语
    o_idx = defaultdict(list)  # 宾语（仅 URI）

    # 只有这六个文件的宾语一般是uri，所以可以构建宾语索引
    build_obj = any(x in fname for x in [
        "mappingbased_objects", "instance_types", "article_categories", "redirects", "disambiguations"
    ])

    total_lines = 0
    total_bytes = os.path.getsize(fpath)

    with open(fpath, "rb") as f:
        offset = 0
        for line in tqdm(f):
            total_lines += 1
            line_str = line.decode("utf-8", errors="replace").strip()

            if not line_str or line_str.startswith("#"):
                offset += len(line)
                continue

            s_uri, p_uri, o_uri = parse_triple(line_str, build_obj=build_obj)

            if s_uri:
                s_idx[s_uri].append(offset)
            if p_uri:
                p_idx[p_uri].append(offset)
            if o_uri:
                o_idx[o_uri].append(offset)

            offset += len(line)

    # 输出目录
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(fname)[0]

    # 保存三个索引
    indices = [
        (s_idx, f"{base_name}_s_idx.pkl", "主语"),
        (p_idx, f"{base_name}_p_idx.pkl", "谓语"),
        (o_idx, f"{base_name}_o_idx.pkl", "宾语"),
    ]

    for idx_dict, out_name, desc in indices:
        if not idx_dict:
            continue
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "wb") as f_out:
            pickle.dump(dict(idx_dict), f_out, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"  {desc}索引: {len(idx_dict):,} 个 URI → {out_path}")

    print(f"  总行数: {total_lines:,}")
    print(f"  文件大小: {total_bytes / (1024**3):.2f} GB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=INPUT_DIR, help="TTL files directory")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Index output directory")
    parser.add_argument("--files", nargs="+", default=FILE_LIST, help="Files to index")
    args = parser.parse_args()

    for fname in args.files:
        build_index_for_file(fname, args.input_dir, args.output_dir)

    print(f"\n{'='*50}")
    print("全部索引构建完成")
    print(f"{'='*50}")



if __name__ == "__main__":  
    # 使用方法：python build_index.py
    # 本地配置不太行，最后到云端去开了多终端，每一个终端都 python build_index.py --files XXX.ttl 并行处理
    # 还没抢到 CPU，直接用的 GPU 环境的 CPU，但这样也比我本地的小破电脑快多了
    # 保存压缩包是个好习惯
    # bzip2 -dc XXX.ttl.bz2 > XXX.ttl  ← 解压命令
    # zip -r /root/autodl-tmp/dbpedia_indexes.zip . -i *.pkl ← 这个命令在 autodl-tmp 文件夹下执行，可以保持目录结构
    main()
    