#!/usr/bin/env python3
"""
01b_crawl_dbpedia.py

本地 DBpedia 信息抽取（本阶段最终结果直接进入 02）：读取 01a 输出的
descriptions_a.json，使用预构建的 URI→偏移量索引从本地 dump 中补充
label、abstract、types、categories、relations 等信息，并按
mapped / abstract_only / struct_only / label_only / failed / no_info / no_uri
标准打标签。

输出：
  - descriptions_b.json：去重后的实体描述（2624 个唯一 URI）
  - descriptions.json：如果配置了 expand_map，则展开为原始 item ID 空间
                      （dbbook2014-mine-main 为 2680 个），供 02/03 使用
"""
import os
import json
import copy
import logging
import argparse
from collections import Counter
from tqdm import tqdm
from typing import Dict, List
from rdflib import URIRef, Literal
from utils import (
    load_config, get_dataset_paths, ensure_dir,
    setup_logging, shorten_uri, is_known_uri, load_index, parse_ttl_line,
    NO_INFO_PREFIXES,
)


# 处理 rdflib 对非法 xsd:date 的警告
logging.getLogger("rdflib.term").setLevel(logging.ERROR)
import rdflib.xsd_datetime as xsd_dt

_original_parse_xsd_date = xsd_dt.parse_xsd_date


def _safe_parse_xsd_date(value):
    try:
        return _original_parse_xsd_date(value)
    except ValueError:
        return None


xsd_dt.parse_xsd_date = _safe_parse_xsd_date



# 文件名 -> (字段名, 是否为关系/属性文件)
FILE_CONFIG = {
    "labels_en.ttl": ("label", False),
    "long_abstracts_en.ttl": ("long_abstract", False),
    "instance_types_en.ttl": ("types", False),
    "instance_types_transitive_en.ttl": ("types", False),
    "article_categories_en.ttl": ("categories", False),
    "mappingbased_objects_en.ttl": ("object_properties", True),
    "mappingbased_literals_en.ttl": ("literal_properties", True),
    "redirects_en.ttl": ("redirect_uri", True),
}


def merge_core_value(entity_data: Dict, field: str, obj):
    """把核心字段值合并到实体数据中。"""
    if isinstance(obj, Literal):
        value = str(obj)
    elif isinstance(obj, URIRef):
        value = shorten_uri(str(obj))
    else:
        return
    if field == "label" and value:
        entity_data["label"] = value
    elif field == "long_abstract" and value:
        entity_data["long_abstract"] = value
    elif field == "types" and value and value not in entity_data["types"]:
        entity_data["types"].append(value)
    elif field == "categories" and value and value not in entity_data["categories"]:
        entity_data["categories"].append(value)


def merge_relation_value(entity_data: Dict, field: str, pred: str, obj,
                         max_relations: int):
    """把关系/属性字段合并到实体数据中。"""
    if field == "object_properties":
        if isinstance(obj, URIRef) and is_known_uri(str(obj)):
            if len(entity_data["object_properties"]) < max_relations:
                entity_data["object_properties"].append({
                    "predicate": pred,
                    "object": shorten_uri(str(obj)),
                })
    elif field == "literal_properties":
        if isinstance(obj, Literal):
            val = str(obj)
            if len(val) <= 500 and len(entity_data["literal_properties"]) < max_relations:
                entity_data["literal_properties"][pred] = val
    elif field == "redirect_uri":
        if isinstance(obj, URIRef) and is_known_uri(str(obj)):
            # 只填充 redirect_uri，不替换当前 uri
            entity_data["redirect_uri"] = shorten_uri(str(obj))


def process_file(ttl_path: str, index_path: str, target_uris: set,
                 uri2ids: Dict[str, List[int]], data: Dict[int, Dict],
                 field: str, is_relation: bool, max_relations: int, logger):
    """处理单个 TTL 文件。支持多个 entity_id 共享同一个 URI。"""
    index = load_index(index_path)

    tasks = []
    for uri, offsets in index.items():
        if uri in target_uris:
            for offset in offsets:
                tasks.append((offset, uri))
    tasks.sort()
    logger.info("  处理 %s: %d 个目标行", os.path.basename(ttl_path), len(tasks))

    with open(ttl_path, "rb") as f:
        for offset, uri in tqdm(tasks):
            f.seek(offset)
            line = f.readline().decode("utf-8", errors="ignore")
            triple = parse_ttl_line(line)
            if triple is None:
                continue

            s, p, o = triple
            pred_short = shorten_uri(str(p))

            for entity_id in uri2ids.get(uri, []):
                entity_data = data[entity_id]
                if is_relation:
                    merge_relation_value(entity_data, field, pred_short, o, max_relations)
                else:
                    merge_core_value(entity_data, field, o)


def run_full(dataset_name: str, label: str, config_path: str = "config.yaml",
             max_relations: int = 50, skip_relations: bool = False,):
    """全量提取。"""
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)
    logger_prefix = f"[01b CRAWL] {dataset_name}/{label}"

    ensure_dir(paths["crawl_dir"])
    logger = setup_logging(paths["crawl_log"])
    logger.info("\n" * 3 + "=" * 50)

    logger.info("%s", logger_prefix)

    # 读取 01a 输出的 descriptions_a.json
    a_path = paths["descriptions_a"]
    if not os.path.exists(a_path):
        logger.error("  descriptions_a.json not found: %s", a_path)
        return
    with open(a_path, "r", encoding="utf-8") as f:
        data = {int(k): v for k, v in json.load(f).items()}
    logger.info("  loaded descriptions_a: %d", len(data))

    from collections import defaultdict
    target_uris = {v["uri"] for v in data.values() if v.get("uri")}
    uri2ids: Dict[str, List[int]] = defaultdict(list)
    for k, v in data.items():
        if v.get("uri"):
            uri2ids[v["uri"]].append(k)
    duplicate_groups = sum(1 for ids in uri2ids.values() if len(ids) > 1)
    duplicate_entities = sum(len(ids) - 1 for ids in uri2ids.values() if len(ids) > 1)
    logger.info("  target URIs: %d (entities: %d, duplicate URI groups: %d, duplicate entities: %d)",
                len(target_uris), len(data), duplicate_groups, duplicate_entities)

    dump_dir = paths["dbpedia_dump_dir"]
    index_dir = paths["dbpedia_idx_dir"]

    files_to_process = dict(FILE_CONFIG)
    if skip_relations:
        files_to_process = {k: v for k, v in files_to_process.items() if not v[1]}

    for fname, (field, is_relation) in files_to_process.items():
        ttl_path = os.path.join(dump_dir, fname)
        base_name = os.path.splitext(fname)[0]
        index_path = os.path.join(index_dir, f"{base_name}_s_idx.pkl")

        if not os.path.exists(ttl_path):
            logger.info("[跳过] TTL 文件不存在: %s", ttl_path)
            continue
        if not os.path.exists(index_path):
            logger.info("[跳过] 索引不存在: %s", index_path)
            continue

        logger.info("开始处理文件：%s...", fname)
        process_file(ttl_path, index_path, target_uris, uri2ids, data,
                     field, is_relation, max_relations, logger)
        logger.info("单个文件处理完毕：%s.", fname)

    logger.info("%s 所有文件处理结束，开始标记实体状态...", dataset_name)

    # 状态标记：mapped / abstract_only / struct_only / label_only / failed / no_info / no_uri
    # 由于不再进行 01c 在线补充，这里直接按完整标准打标签
    problem_b = {
        "abstract_only": [],
        "struct_only": [],
        "label_only": [],
        "failed": [],
    }
    for entity_id, entity_data in data.items():
        if not entity_data.get("uri"):
            entity_data["status"] = "no_uri"
            continue

        if entity_data.get("prefix") in NO_INFO_PREFIXES:
            entity_data["status"] = "no_info"
            continue

        has_label = bool(entity_data["label"])
        has_abstract = bool(entity_data["long_abstract"])
        has_struct = bool(
            entity_data["types"] or entity_data["categories"]
            or entity_data["object_properties"] or entity_data["literal_properties"]
        )

        if has_abstract and has_struct:
            entity_data["status"] = "mapped"
        elif has_abstract:
            entity_data["status"] = "abstract_only"
            problem_b["abstract_only"].append(entity_id)
        elif has_struct:
            entity_data["status"] = "struct_only"
            problem_b["struct_only"].append(entity_id)
        elif has_label:
            entity_data["status"] = "label_only"
            problem_b["label_only"].append(entity_id)
        else:
            entity_data["status"] = "failed"
            problem_b["failed"].append(entity_id)

    # 保留 problem_entities_b.dat 供调试参考（不再进入 01c）
    # 按状态分组输出，每段前加一行表头：字段名 + 数量
    with open(paths["problem_entities_b"], "w", encoding="utf-8") as f:
        for field, eids in problem_b.items():
            f.write(f"{field}: {len(eids)}\n")
            for eid in eids:
                f.write(f"{eid}\n")

    # 保存 descriptions_b.json，作为进入 02 阶段的中间结果
    with open(paths["descriptions_b"], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    status_counter = Counter(v["status"] for v in data.values())
    logger.info("  saved: %s", paths["descriptions_b"])
    logger.info("  total=%d, status counts: %s",
                len(data), dict(sorted(status_counter.items())))

    expected_unique = paths.get("n_entities")
    if expected_unique is not None and len(data) != expected_unique:
        logger.warning("  descriptions_b count mismatch: got %d, expected %d (from n_entities)",
                       len(data), expected_unique)
    elif expected_unique is not None:
        logger.info("  descriptions_b count check passed: %d == %d", len(data), expected_unique)

    # 如果配置了 expand_map，把去重后的 descriptions_b.json 展开为原始 ID 空间的 descriptions.json
    expand_to_original(data, paths, logger)


def expand_to_original(data: Dict[int, Dict], paths: Dict, logger):
    """根据 expand_map 将去重 descriptions 展开到原始 item ID 空间。"""
    expand_map_path = paths.get("expand_map")
    out_path = paths["descriptions_json"]
    if not expand_map_path or not os.path.exists(expand_map_path):
        # 无展开映射时，descriptions.json 与 descriptions_b.json 保持一致
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("  no expand_map, descriptions_json same as descriptions_b: %s", out_path)
        return

    i2i_map = {}
    with open(expand_map_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            original_id = int(parts[0])
            unique_id = int(parts[1])
            i2i_map[original_id] = unique_id

    expanded = {}
    for original_id in sorted(i2i_map.keys()):
        unique_id = i2i_map[original_id]
        if unique_id not in data:
            logger.warning("  original_id %d maps to missing unique_id %d", original_id, unique_id)
            continue
        record = copy.deepcopy(data[unique_id])
        record["entity_id"] = original_id
        expanded[original_id] = record

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(expanded, f, ensure_ascii=False, indent=2)
    logger.info("  expanded %d unique -> %d original descriptions -> %s",
                len(data), len(expanded), out_path)

    expected_original = paths.get("n_original_entities")
    if expected_original is not None and len(expanded) != expected_original:
        logger.warning("  descriptions.json count mismatch: got %d, expected %d (from n_original_entities)",
                       len(expanded), expected_original)
    elif expected_original is not None:
        logger.info("  descriptions.json count check passed: %d == %d", len(expanded), expected_original)


def main():
    parser = argparse.ArgumentParser(description="Extract DBpedia entity info using pre-built indexes.")
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--max_relations", type=int, default=50)
    parser.add_argument("--skip_relations", action="store_true")
    args = parser.parse_args()

    run_full(args.dataset, args.label, args.config, args.max_relations, args.skip_relations)


if __name__ == "__main__":
    # python 01b_crawl_dbpedia.py --dataset dbbook2014-mine --label main
    # python 01b_crawl_dbpedia.py --dataset dbbook2014-mine --label one-hop
    main()
