#!/usr/bin/env python3
"""
01a_resolve_uris.py

预处理阶段：初始化实体描述结构，仅对本地 DBpedia dump 的 disambiguations
进行交互式消歧义（不再处理 redirects，避免错误地把书籍重定向到作者/系列页）。

输入：
    config.yaml 中指定的 entity_list
    dumps/dbpedia_files/index/disambiguations_en_s_idx.pkl

输出：
    output/{dataset}/<crawl_dir>/descriptions_a.json

本阶段状态只有 no_uri / has_uri 两种；消歧义只更新 uri / original_uri_d。
"""
import os
import json
import argparse
import logging
import urllib.parse
from collections import OrderedDict
from typing import Dict, List, Tuple
from tqdm import tqdm
from rdflib import URIRef

from utils import (
    load_config, get_dataset_paths, ensure_dir, setup_logging,
    read_mine_entity_mapping, shorten_uri, expand_uri,
    is_known_uri, load_index, parse_ttl_line,
    NO_INFO_PREFIXES,
)


def init_entities(entities: List[Dict]) -> Dict[int, Dict]:
    """初始化所有实体的描述数据结构。"""
    return {
        e["entity_id"]: {
            "entity_id": e["entity_id"],
            "uri": e["uri"] if e["has_uri"] else "",
            "shorten_uri": shorten_uri(e["uri"]) if e["has_uri"] else "",
            "prefix": (
                shorten_uri(e["uri"]).split(":")[0]
                if e["has_uri"] and ":" in shorten_uri(e["uri"]) else ""
            ),
            "label": "",
            "description": "",
            "long_abstract": "",
            "types": [],
            "categories": [],
            "object_properties": [],
            "literal_properties": {},
            "ambiguous": {},
            "redirect_uri": "",
            "original_uri_d": "",
            "status": "has_uri" if e["has_uri"] else "no_uri",
        }
        for e in entities
    }


def merge_preprocess_value(entity_data: Dict, pred: str, obj):
    """预处理阶段把消歧义候选合并到 entity_data。"""
    if isinstance(obj, URIRef) and is_known_uri(str(obj)):
        if pred not in entity_data["ambiguous"]:
            entity_data["ambiguous"][pred] = []
        short_obj = shorten_uri(str(obj))
        if short_obj not in entity_data["ambiguous"][pred]:
            entity_data["ambiguous"][pred].append(short_obj)


def preprocess_disambiguations(ttl_path: str, index_path: str, target_uris: set,
                               uri2id: Dict[str, int], data: Dict[int, Dict],
                               logger):
    """处理 disambiguations_en.ttl。"""
    index = load_index(index_path)

    tasks = []
    for uri, offsets in index.items():
        if uri in target_uris:
            for offset in offsets:
                tasks.append((offset, uri))
    tasks.sort()
    logger.info("  处理 %s: %d 个目标行", os.path.basename(ttl_path), len(tasks))

    with open(ttl_path, "rb") as f:
        for offset, uri in tqdm(tasks, desc="Preprocess ambiguous"):
            f.seek(offset)
            line = f.readline().decode("utf-8", errors="ignore")
            triple = parse_ttl_line(line)
            if triple is None:
                continue

            s, p, o = triple
            entity_id = uri2id[uri]
            entity_data = data[entity_id]
            pred_short = shorten_uri(str(p))
            merge_preprocess_value(entity_data, pred_short, o)


def interactive_resolve(
    descriptions: Dict[int, Dict],
    problem_ids: List[int],
    logger: logging.Logger,
) -> Dict[int, str]:
    """交互式消歧义。返回 entity_id -> 选中的完整 URI 字典（未选择保持空串）。"""
    to_resolve: Dict[int, str] = OrderedDict()
    for eid in problem_ids:
        entity = descriptions.get(eid)
        if entity is None:
            continue
        if entity.get("ambiguous"):
            to_resolve[eid] = ""

    if not to_resolve:
        print("没有需要交互消歧义的实体。")
        logger.info("No ambiguous entities need resolution.")
        return to_resolve

    keys = list(to_resolve.keys())
    resolved_stack: List[int] = []
    i = 0

    while i < len(keys):
        eid = keys[i]
        entity = descriptions[eid]
        ambiguous = entity.get("ambiguous", {})

        candidates: List[Tuple[str, str, str]] = []  # (predicate, 短 URI, 完整 URI)
        print(f"\n[{i + 1}/{len(keys)}] Entity ID: {eid}")
        print(f"  当前 URI: {entity.get('uri', '')}")
        print(f"  短 URI:   {entity.get('shorten_uri', '')}")
        print(f"  Label:    {entity.get('label', '')}")
        print("  消歧义候选：")
        idx = 0
        for pred, objects in ambiguous.items():
            for obj in objects:
                full_uri = expand_uri(obj)
                candidates.append((pred, obj, full_uri))
                display_obj = urllib.parse.unquote(obj)
                print(f"    {idx}: [{pred}] -> {display_obj}")
                idx += 1

        if not candidates:
            print("  （该实体没有候选，将跳过）")
            to_resolve[eid] = ""
            resolved_stack.append(eid)
            i += 1
            continue

        try:
            choice = input("  请选择候选编号（-1 保存并退出，-2 撤回上一条）：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n检测到中断，保存当前进度并退出。")
            break

        if choice == "-1":
            print("保存并退出。")
            break

        if choice == "-2":
            if not resolved_stack:
                print("没有可撤回的选择。")
                continue
            last_eid = resolved_stack.pop()
            to_resolve[last_eid] = ""
            i = keys.index(last_eid)
            print(f"已撤回实体 {last_eid} 的选择，重新选择。")
            continue

        try:
            choice_idx = int(choice)
            if 0 <= choice_idx < len(candidates):
                _, _, full_uri = candidates[choice_idx]
                to_resolve[eid] = full_uri
                resolved_stack.append(eid)
                i += 1
            else:
                print("编号超出范围，请重新输入。")
        except ValueError:
            print("无效输入，请输入数字、-1 或 -2。")

    return to_resolve


def save_descriptions_a(descriptions: Dict[int, Dict], path: str, resolved: Dict[int, str]):
    """把已解析的 URI 写回 descriptions，并保存为 descriptions_a.json。"""
    for eid, resolved_uri in resolved.items():
        if not resolved_uri:
            continue
        entity = descriptions[eid]
        if not entity.get("original_uri_d"):
            entity["original_uri_d"] = entity.get("uri", "")
        entity["uri"] = resolved_uri
        entity["shorten_uri"] = shorten_uri(resolved_uri)
        entity["prefix"] = (
            entity["shorten_uri"].split(":")[0]
            if ":" in entity["shorten_uri"] else ""
        )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(descriptions, f, ensure_ascii=False, indent=2)


def run_full(dataset_name: str, label: str, config_path: str = "config.yaml", resume: bool = False):
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)
    logger_prefix = f"[01a PREPROCESS] {dataset_name}/{label}"

    out_dir = paths["crawl_dir"]
    ensure_dir(out_dir)
    logger = setup_logging(paths["crawl_log"])
    logger.info("\n" * 3 + "=" * 50)
    logger.info("%s", logger_prefix)

    a_path = paths["descriptions_a"]

    # 断点续传：直接加载已有的 descriptions_a.json，跳过索引扫描
    if resume and os.path.exists(a_path):
        logger.info("  resume from %s", a_path)
        with open(a_path, "r", encoding="utf-8") as f:
            data = {int(k): v for k, v in json.load(f).items()}
        logger.info("  loaded entities: %d", len(data))
    else:
        # 1. 初始化实体结构
        entities = read_mine_entity_mapping(paths["entity_list"])
        logger.info("  entities: %d", len(entities))
        data = init_entities(entities)

        target_uris = {e["uri"] for e in entities if e["has_uri"]}
        uri2id = {e["uri"]: e["entity_id"] for e in entities if e["has_uri"]}
        logger.info("  target URIs: %d", len(target_uris))

        # 2. 处理 disambiguations（仅对非 no_info 实体）
        dump_dir = paths["dbpedia_dump_dir"]
        index_dir = paths["dbpedia_idx_dir"]

        disambig_ttl = os.path.join(dump_dir, "disambiguations_en.ttl")
        disambig_idx = os.path.join(index_dir, "disambiguations_en_s_idx.pkl")
        if os.path.exists(disambig_ttl) and os.path.exists(disambig_idx):
            logger.info("开始处理文件：disambiguations_en.ttl...")
            preprocess_disambiguations(disambig_ttl, disambig_idx, target_uris, uri2id, data, logger)
            logger.info("单个文件处理完毕：disambiguations_en.ttl.")
        else:
            logger.info("[跳过] disambiguations 文件/索引不存在")

    # 3. 交互式消歧义（跳过 no_info 实体与已解析实体）
    ambiguous_ids = [
        eid for eid, entity in data.items()
        if entity.get("status") == "has_uri"
        and entity.get("prefix") not in NO_INFO_PREFIXES
        and entity.get("ambiguous")
        and not entity.get("original_uri_d")
    ]
    already_resolved = sum(1 for e in data.values() if e.get("original_uri_d"))
    if resume:
        print(f"\n断点续传：已跳过 {already_resolved} 个已解析实体，剩余 {len(ambiguous_ids)} 个待处理。")
    logger.info("  ambiguous entities to resolve: %d", len(ambiguous_ids))
    resolved = interactive_resolve(data, ambiguous_ids, logger)

    # 4. 保存 descriptions_a.json
    save_descriptions_a(data, a_path, resolved)
    resolved_count = sum(1 for v in resolved.values() if v)
    logger.info("  resolved %d / %d ambiguous entities", resolved_count, len(ambiguous_ids))
    logger.info("  saved: %s", a_path)

    expected = paths.get("n_entities")
    if expected is not None and len(data) != expected:
        logger.warning("  descriptions_a count mismatch: got %d, expected %d (from n_entities)",
                       len(data), expected)
    elif expected is not None:
        logger.info("  descriptions_a count check passed: %d == %d", len(data), expected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--resume", action="store_true",
                        help="从已有的 descriptions_a.json 继续交互消歧义")
    args = parser.parse_args()
    run_full(args.dataset, args.label, args.config, args.resume)


if __name__ == "__main__":
    # python 01a_resolve_uris.py --dataset dbbook2014-mine --label main
    # python 01a_resolve_uris.py --dataset dbbook2014-mine --label one-hop
    main()
