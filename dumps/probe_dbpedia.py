#!/usr/bin/env python3
"""
DBpedia 本地转储文件探查脚本（索引加速、单索引内存版）。

用途：
1. 根据给定的 DBpedia URI，从 TTL 文件中提取该实体的所有三元组。
2. 展示某个文件的前几个三元组，帮助理解数据结构。

特点：
- 一次只加载一个文件的 subject 索引，处理完后立即释放，不占用大量内存。
- 不依赖项目外的 utils/config。

用法示例：
    python probe_dbpedia.py --entity "Animalia_(book)"
    python probe_dbpedia.py --uri "http://dbpedia.org/resource/Animalia_(book)"
    python probe_dbpedia.py --file labels_en.ttl --head 3
"""

import os
import pickle
import urllib.parse
import argparse
from rdflib import Graph, URIRef, Literal

# 转储文件所在目录（相对于本脚本）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DUMP_DIR = os.path.join(SCRIPT_DIR, "dbpedia_files")
INDEX_DIR = os.path.join(DUMP_DIR, "index")

# 常用前缀，用于缩短输出
PREFIXES = [
    ("http://dbpedia.org/resource/", "dbr:"),
    ("http://dbpedia.org/ontology/", "dbo:"),
    ("http://dbpedia.org/property/", "dbp:"),
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
    ("http://xmlns.com/foaf/0.1/", "foaf:"),
    ("http://www.w3.org/2001/XMLSchema#", "xsd:"),
    ("http://purl.org/dc/elements/1.1/", "dc:"),
    ("http://purl.org/linguistics/gold/", "gold:"),
    ("http://www.w3.org/2002/07/owl#", "owl:"),
]

ALL_FILES = {
    "labels_en.ttl": "实体名称 (rdfs:label)",
    "short_abstracts_en.ttl": "短摘要 (rdfs:comment)",
    "long_abstracts_en.ttl": "长摘要 (dbo:abstract)",
    "instance_types_en.ttl": "直接类型 (rdf:type)",
    "instance_types_transitive_en.ttl": "传递闭包类型 (rdf:type)",
    "mappingbased_objects_en.ttl": "对象属性 / 关系",
    "mappingbased_literals_en.ttl": "数据属性 / 字面量",
    "article_categories_en.ttl": "dbc:",
    "redirects_en.ttl": "重定向",
    "disambiguations_en.ttl": "消歧义",
}

# 在这里注释掉你不需要探查的文件
DEFAULT_FILES = {
    # "labels_en.ttl": "实体名称 (rdfs:label)",
    "long_abstracts_en.ttl": "长摘要 (dbo:abstract)",
    "instance_types_en.ttl": "直接类型 (rdf:type)",
    "instance_types_transitive_en.ttl": "传递闭包类型 (rdf:type)",
    "mappingbased_objects_en.ttl": "对象属性 / 关系",
    "mappingbased_literals_en.ttl": "数据属性 / 字面量",
    "article_categories_en.ttl": "dbc:",
    "redirects_en.ttl": "重定向",
    "disambiguations_en.ttl": "消歧义",
}


def shorten_uri(uri: str) -> str:
    for full, short in PREFIXES:
        if uri.startswith(full):
            return short + uri[len(full):]
    return uri


def parse_ttl_line(line: str):
    """用 rdflib 解析单行 TTL，返回 (s, p, o) 或 None。"""
    g = Graph()
    try:
        g.parse(data=line, format="turtle")
    except Exception:
        return None
    for s, p, o in g:
        return s, p, o
    return None


def load_index(index_path: str):
    """加载 Pickle 索引，key 做 URL decode 归一化。"""
    with open(index_path, "rb") as f:
        raw = pickle.load(f)
    return {urllib.parse.unquote(k): v for k, v in raw.items()}


def format_object(obj) -> str:
    if isinstance(obj, URIRef):
        return shorten_uri(str(obj))
    elif isinstance(obj, Literal):
        if obj.language:
            return f'"{obj}"@{obj.language}'
        return f'"{obj}"'
    return str(obj)


def find_triples_for_entity(target_uri: str, files: dict, mode: str = "s", max_per_file: int = 20):
    print(f"\n{'='*60}")
    print(f"探查实体: {shorten_uri(target_uri)}")
    print(f"扫描文件数: {len(files)}")
    print(f"{'='*60}")

    for idx, (fname, desc) in enumerate(files.items(), 1):
        ttl_path = os.path.join(DUMP_DIR, fname)
        base_name = os.path.splitext(fname)[0]
        idx_path = os.path.join(INDEX_DIR, f"{base_name}_{mode}_idx.pkl")

        if not os.path.exists(ttl_path):
            print(f"\n[{idx}/{len(files)}] [跳过] TTL 文件不存在: {fname}")
            continue
        if not os.path.exists(idx_path):
            print(f"\n[{idx}/{len(files)}] [跳过] 索引不存在: {idx_path}")
            continue

        print(f"\n[{idx}/{len(files)}] 索引查找 {fname} ({desc}) ...")
        index = load_index(idx_path)
        offsets = index.get(target_uri, [])
        # 处理完立即释放该索引内存
        del index

        found_count = 0
        if not offsets:
            print("  （未找到该实体的数据）")
            continue

        with open(ttl_path, "rb") as f:
            for offset in offsets:
                f.seek(offset)
                line = f.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                triple = parse_ttl_line(line)
                if triple is None:
                    continue

                s, p, o = triple
                print(f"  {shorten_uri(str(s)):50} {shorten_uri(str(p)):50} {format_object(o)}")
                found_count += 1


        print(f"  索引命中行数: {len(offsets)}")


def show_file_head(fname: str, n: int = 3):
    fpath = os.path.join(DUMP_DIR, fname)
    if not os.path.exists(fpath):
        print(f"文件不存在: {fpath}")
        return

    print(f"\n{'='*60}")
    print(f"文件: {fname}")
    print(f"{'='*60}")

    count = 0
    with open(fpath, "rb") as f:
        for line in f:
            line = line.decode("utf-8", errors="ignore").strip()
            if not line or line.startswith("#"):
                continue

            triple = parse_ttl_line(line)
            if triple is None:
                continue

            s, p, o = triple
            print(f"  {shorten_uri(str(s)):35} {shorten_uri(str(p)):35} {format_object(o)}")
            count += 1
            if count >= n:
                break


def main():
    parser = argparse.ArgumentParser(description="Probe DBpedia dump files using indexes.")
    parser.add_argument("--entity", type=str, help="Entity resource name, e.g., Animalia_(book)")
    parser.add_argument("--uri", type=str, help="Full DBpedia URI")
    parser.add_argument("--file", type=str, help="Show first N triples of a specific file")
    parser.add_argument("--head", type=int, default=5, help="Number of triples to show for --file")
    parser.add_argument("--max_per_file", type=int, default=20,
                        help="Max triples per file when probing an entity")
    parser.add_argument("--all-files", action="store_true", help="Scan all files")
    parser.add_argument("--mode", type=str, default="s", help="s/p/o")
    args = parser.parse_args()

    if args.file:
        show_file_head(args.file, n=args.head)
    elif args.uri or args.entity:
        target_uri = args.uri
        if not target_uri:
            target_uri = f"http://dbpedia.org/resource/{args.entity}"

        files_to_scan = ALL_FILES if args.all_files else DEFAULT_FILES
        find_triples_for_entity(target_uri, files=files_to_scan, mode=args.mode, max_per_file=args.max_per_file)
    else:
        parser.print_help()


if __name__ == "__main__":
    # 执行此脚本会占用1.5~4GB内存
    main()
