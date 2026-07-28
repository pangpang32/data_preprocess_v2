#!/usr/bin/env python3
"""
02a_split_kg_entities.py

从 descriptions.json 与 r_map.dat 直接抽取最终的一跳 KG：
  - one_hop_triples.dat：head_id \t tail_id \t relation_id
  - one_hop_entities.dat：tail_id \t full_uri（去重后的邻居实体，作为 01ab 输入）
  - one_hop_entity_meta.json：每个邻居实体的角色、相连物品、状态占位等元数据

邻居实体 ID 从 config 中的 n_original_entities 开始（dbbook2014-mine 为 2680），
与种子实体共享统一 ID 空间，避免与 item ID 冲突。

同时输出没有选中关系的种子实体列表：
  - output/{dataset}/02_kg_build/no_selected_relation_entities.dat
"""
import os
import json
import urllib.parse
import argparse
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import load_config, get_dataset_paths, ensure_dir, setup_logging, expand_uri


def load_r_map(path: str) -> Dict[str, int]:
    """读取 r_map.dat，兼容 2 列或 3 列格式。"""
    r_map = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            # 谓词必须包含 ':'；ID 取最后一个整数 token
            pred_candidates = [p for p in parts if ":" in p]
            if not pred_candidates:
                continue
            predicate = pred_candidates[0]
            rid = int(parts[-1])
            r_map[predicate] = rid
    return r_map


def load_descriptions(path: str) -> Dict[int, Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def extract_final_kg(dataset_name: str, label: str, config_path: str):
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)

    ensure_dir(paths["kg_build_dir"])
    ensure_dir(os.path.dirname(paths["kg_hop_triples"]))
    logger = setup_logging(paths["kg_build_log"])
    logger.info("[02a] Start extracting final one-hop KG for %s/%s", dataset_name, label)

    r_map = load_r_map(paths["kg_r_map"])
    if not r_map:
        raise ValueError(f"r_map 为空: {paths['kg_r_map']}")
    logger.info("Loaded r_map: %d relations from %s", len(r_map), paths["kg_r_map"])

    descriptions = load_descriptions(paths["descriptions_json"])
    logger.info("Loaded descriptions_json: %d entities", len(descriptions))

    # 邻居实体 ID 从 n_original_entities 开始；未配置则默认从种子实体最大 ID 之后开始
    id_offset = paths.get("n_original_entities")
    if id_offset is None:
        id_offset = max(descriptions.keys()) + 1 if descriptions else 0
    logger.info("Neighbor ID offset: %d", id_offset)

    uri_to_id: Dict[str, int] = {}
    id_to_uri: Dict[int, str] = {}
    next_id = id_offset

    # 邻居实体元数据：roles / connected_items / label / status
    entity_meta: Dict[int, Dict] = {}

    pred_counter = Counter()
    no_edge_entities: List[Tuple[int, str, str]] = []
    skipped_no_head = 0
    skipped_no_tail = 0

    triples_path = paths["kg_hop_triples"]
    entities_path = paths["kg_hop_entities"]
    meta_path = paths["kg_hop_meta"]

    with open(triples_path, "w", encoding="utf-8") as f_triples:
        for eid, entity in descriptions.items():
            head = entity.get("shorten_uri", "")
            label = entity.get("label", "")
            if not head:
                skipped_no_head += 1
                continue

            has_edge = False
            for op in entity.get("object_properties", []):
                pred = op.get("predicate", "")
                tail_short = op.get("object", "")
                if not pred or not tail_short:
                    skipped_no_tail += 1
                    continue
                if pred not in r_map:
                    continue

                rid = r_map[pred]
                full_uri = urllib.parse.unquote(expand_uri(tail_short))

                if full_uri not in uri_to_id:
                    uri_to_id[full_uri] = next_id
                    id_to_uri[next_id] = full_uri
                    entity_meta[next_id] = {
                        "roles": set(),
                        "connected_items": defaultdict(list),
                        "label": "",
                        "status": None,  # 由 02b 根据 01b 输出的 descriptions.json 回填
                    }
                    next_id += 1

                tail_id = uri_to_id[full_uri]
                f_triples.write(f"{eid}\t{tail_id}\t{rid}\n")
                pred_counter[pred] += 1
                has_edge = True

                # 记录邻居实体的角色与相连物品
                meta = entity_meta[tail_id]
                meta["roles"].add(pred)
                meta["connected_items"][pred].append(eid)

            if not has_edge:
                no_edge_entities.append((eid, head, label))

    # 写入去重后的邻居实体列表（按 ID 排序）
    with open(entities_path, "w", encoding="utf-8") as f_entities:
        for tail_id in sorted(id_to_uri.keys()):
            f_entities.write(f"{tail_id}\t{id_to_uri[tail_id]}\n")

    # 整理并写入元数据
    meta_out = {}
    for tail_id in sorted(entity_meta.keys()):
        meta = entity_meta[tail_id]
        meta_out[str(tail_id)] = {
            "roles": sorted(meta["roles"]),
            "connected_items": {
                pred: sorted(set(item_ids))
                for pred, item_ids in sorted(meta["connected_items"].items())
            },
            "label": meta["label"],
            "status": meta["status"],
        }

    with open(meta_path, "w", encoding="utf-8") as f_meta:
        json.dump(meta_out, f_meta, ensure_ascii=False, indent=2)

    # 输出无边实体列表
    no_edge_path = os.path.join(paths["kg_build_dir"], "no_selected_relation_entities.dat")
    with open(no_edge_path, "w", encoding="utf-8") as f:
        for eid, head, label in no_edge_entities:
            f.write(f"{eid}\t{head}\t{label}\n")

    stats = {
        "n_seed_entities": len(descriptions),
        "id_offset": id_offset,
        "n_relations": len(r_map),
        "n_triples": sum(pred_counter.values()),
        "n_unique_neighbor_entities": len(uri_to_id),
        "n_entities_no_selected_edge": len(no_edge_entities),
        "skipped_no_head_uri": skipped_no_head,
        "skipped_no_tail_obj": skipped_no_tail,
        "relation_counts": {pred: pred_counter[pred] for pred in r_map},
    }

    stats_path = os.path.join(paths["kg_build_dir"], "kg_hop_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    logger.info("Wrote %d triples -> %s", stats["n_triples"], triples_path)
    logger.info("Wrote %d unique neighbor entities -> %s", stats["n_unique_neighbor_entities"], entities_path)
    logger.info("Wrote entity meta -> %s", meta_path)
    logger.info("Seed entities with no selected edge: %d -> %s", len(no_edge_entities), no_edge_path)
    for pred, cnt in stats["relation_counts"].items():
        logger.info("  %s: %d", pred, cnt)


def main():
    parser = argparse.ArgumentParser(description="Extract final one-hop KG triples, neighbor entities and metadata.")
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    args = parser.parse_args()

    extract_final_kg(args.dataset, args.label, args.config)


if __name__ == "__main__":
    # python 02a_split_kg_entities.py --dataset dbbook2014-mine --label main
    main()
