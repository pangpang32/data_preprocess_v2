#!/usr/bin/env python3
"""
02b_backfill_entity_meta.py

读取 KG 邻居数据集跑完 01b 后产生的 descriptions.json，
把每个邻居实体的真实 status 和 label 回填到 kg_hop_meta.json 中。

种子子划分不再通过 CLI 传入，而是根据当前子划分的 label 与 seed_datasets 推断：
    seed_label = config["datasets"][dataset][kg_label]["seed_datasets"][label - 1]

输入：
    config 中上游种子子划分的 kg_hop_meta
    config 中当前 KG 邻居子划分的 descriptions.json

输出：
    直接覆盖 kg_hop_meta.json（原文件备份为 .bak）
"""
import os
import json
import shutil
import argparse
from collections import Counter
from typing import Dict

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import load_config, get_dataset_paths


def resolve_seed_dataset(config: Dict, dataset_name: str, kg_label: str) -> str:
    """根据当前子划分的 label 和 seed_datasets 列表推断直接上游子划分名。"""
    ds = config["datasets"].get(dataset_name, {}).get(kg_label)
    if ds is None:
        raise ValueError(f"config 中未找到数据集: {dataset_name}/{kg_label}")
    label = ds.get("label", 0)
    seed_datasets = ds.get("seed_datasets", [])
    if label == 0:
        raise ValueError(f"数据集 {dataset_name}/{kg_label} 是种子子划分（label=0），无需回填")
    if not seed_datasets:
        raise ValueError(f"数据集 {dataset_name}/{kg_label} 缺少 seed_datasets 配置")
    if label - 1 >= len(seed_datasets):
        raise ValueError(
            f"数据集 {dataset_name}/{kg_label} 的 label={label} 超出 seed_datasets 长度 {len(seed_datasets)}"
        )
    return seed_datasets[label - 1]


def backfill_meta(dataset_name: str, seed_label: str, kg_label: str, config_path: str):
    config = load_config(config_path)
    seed_paths = get_dataset_paths(config, dataset_name, seed_label)
    kg_paths = get_dataset_paths(config, dataset_name, kg_label)

    meta_path = seed_paths["kg_hop_meta"]
    desc_path = kg_paths["descriptions_json"]

    if not os.path.exists(meta_path):
        raise FileNotFoundError(f"meta file not found: {meta_path}")
    if not os.path.exists(desc_path):
        raise FileNotFoundError(f"neighbor descriptions.json not found: {desc_path}")

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    with open(desc_path, "r", encoding="utf-8") as f:
        descriptions = {int(k): v for k, v in json.load(f).items()}

    # 备份原 meta
    shutil.copy2(meta_path, meta_path + ".bak")

    status_counter = Counter()
    updated = 0
    for eid_str, m in meta.items():
        eid = int(eid_str)
        if eid in descriptions:
            desc = descriptions[eid]
            m["label"] = desc.get("label", m.get("label", ""))
            m["status"] = desc.get("status", "unknown")
            updated += 1
        else:
            m["status"] = m.get("status") or "missing_in_descriptions_json"
        status_counter[m["status"]] += 1

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[02b] Backfilled {updated}/{len(meta)} neighbor entities")
    print(f"  meta: {meta_path}")
    print(f"  backup: {meta_path}.bak")
    print("  status distribution:")
    for status, cnt in status_counter.most_common():
        print(f"    {status}: {cnt}")


def main():
    parser = argparse.ArgumentParser(description="Backfill neighbor entity status from descriptions.json to meta.")
    parser.add_argument("--dataset", type=str, required=True,
                        help="数据集名称")
    parser.add_argument("--label", type=str, required=True,
                        help="KG 邻居子划分（用于读取 descriptions.json）")
    parser.add_argument("--config", type=str, default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    seed_label = resolve_seed_dataset(config, args.dataset, args.label)
    backfill_meta(args.dataset, seed_label, args.label, args.config)


if __name__ == "__main__":
    # python 02b_backfill_entity_meta.py --dataset dbbook2014-mine --label one-hop
    main()
