"""
probe_predicates.py

分析 descriptions.json 中谓词分布。

对于 label > 0 的子划分（如 one-hop 邻居），会自动加载上一级 seed 子划分的
kg_hop_meta.json，并按邻居实体在上一级 KG 中扮演的 role（连接谓词）分组统计谓词分布。
一个邻居实体可能通过多个谓词与种子实体相连，因此可能同时出现在多个 role 组中。

执行位置：项目根目录（data_preprocess/）
示例：python output/probe_predicates.py --dataset dbbook2014-mine --label one-hop

输出：
    output/probe/{dataset}/{label}/probe_predicates_report.md
    output/probe/{dataset}/{label}/probe_predicates_stats.json
"""
import os
import json
import argparse
from collections import Counter
from typing import Dict, List, Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, get_dataset_paths


def load_data(path: str) -> Dict[int, Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def load_kg_hop_meta(path: str) -> Dict[int, Dict]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def resolve_seed_dataset(config: Dict, dataset_name: str, sub_label: str) -> Optional[str]:
    """根据当前子划分的 label 与 seed_datasets 推断直接上游子划分名。"""
    ds = config["datasets"].get(dataset_name, {}).get(sub_label)
    if ds is None:
        raise ValueError(f"config 中未找到数据集: {dataset_name}/{sub_label}")
    label = ds.get("label", 0)
    seed_datasets = ds.get("seed_datasets", [])
    if label == 0:
        return None
    if not seed_datasets:
        raise ValueError(f"数据集 {dataset_name}/{sub_label} 缺少 seed_datasets 配置")
    if label - 1 >= len(seed_datasets):
        raise ValueError(
            f"数据集 {dataset_name}/{sub_label} 的 label={label} 超出 seed_datasets 长度 {len(seed_datasets)}"
        )
    return seed_datasets[label - 1]


def analyze(descriptions: Dict[int, Dict], dataset_name: str, out_dir: str,
            meta: Optional[Dict[int, Dict]] = None):
    pred_counter = Counter()
    literal_pred_counter = Counter()
    object_refs_total = 0

    for entity in descriptions.values():
        for op in entity.get("object_properties", []):
            pred = op.get("predicate", "")
            if pred:
                pred_counter[pred] += 1
                object_refs_total += 1

        for pred in entity.get("literal_properties", {}).keys():
            if pred:
                literal_pred_counter[pred] += 1

    stats = {
        "n_entities": len(descriptions),
        "object_predicates": dict(pred_counter.most_common()),
        "literal_predicates": dict(literal_pred_counter.most_common()),
        "object_refs_total": object_refs_total,
    }

    # 按上一级 role 分组统计（仅对 label > 0 的数据集有效）
    role_stats: Dict[str, Dict] = {}
    if meta:
        role_to_entities: Dict[str, List[int]] = {}
        for eid, m in meta.items():
            for role in m.get("roles", []):
                role_to_entities.setdefault(role, []).append(eid)

        for role, eids in sorted(role_to_entities.items()):
            role_pred_counter = Counter()
            role_literal_counter = Counter()
            valid = 0
            for eid in eids:
                entity = descriptions.get(eid)
                if entity is None:
                    continue
                valid += 1
                for op in entity.get("object_properties", []):
                    pred = op.get("predicate", "")
                    if pred:
                        role_pred_counter[pred] += 1
                for pred in entity.get("literal_properties", {}).keys():
                    if pred:
                        role_literal_counter[pred] += 1

            role_stats[role] = {
                "n_entities_total": len(eids),
                "n_entities_in_descriptions": valid,
                "object_predicates": role_pred_counter.most_common(),
                "literal_predicates": role_literal_counter.most_common(),
            }

    stats["role_stats"] = role_stats

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "probe_predicates_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    report = f"""# 谓词分布分析报告

## 1. 总体统计

- 实体总数：{len(descriptions)}
- 不同 object 谓词数：{len(pred_counter)}
- 不同 literal 谓词数：{len(literal_pred_counter)}
- object_properties 引用总次数：{object_refs_total}

## 2. Object 谓词分布

| 谓词 | 出现次数 |
|---|---|
"""
    for pred, cnt in pred_counter.most_common():
        report += f"| {pred} | {cnt} |\n"

    report += f"""
## 3. Literal 谓词分布

| 谓词 | 出现次数 |
|---|---|
"""
    for pred, cnt in literal_pred_counter.most_common():
        report += f"| {pred} | {cnt} |\n"

    if role_stats:
        report += """\n## 4. 按上一级连接谓词（role）分组统计

> 每个 role 表示当前数据集中的邻居实体通过该谓词与上一级种子实体相连。
> 一个邻居实体可能通过多个谓词与种子实体相连，因此可能同时出现在多个 role 组中。
> 分组统计有助于为不同来源的邻居实体设计差异化的 relation_priority。

"""
        for role, rstats in role_stats.items():
            report += f"### role: `{role}`\n\n"
            report += f"- 通过该 role 连接的实体数：{rstats['n_entities_total']}\n"
            report += f"- 在当前 descriptions.json 中找到的实体数：{rstats['n_entities_in_descriptions']}\n\n"
            report += "**Object 谓词分布（前 30）**\n\n| 谓词 | 出现次数 |\n|---|---|\n"
            for pred, cnt in rstats["object_predicates"][:30]:
                report += f"| {pred} | {cnt} |\n"
            report += "\n**Literal 谓词分布（前 20）**\n\n| 谓词 | 出现次数 |\n|---|---|\n"
            for pred, cnt in rstats["literal_predicates"][:20]:
                report += f"| {pred} | {cnt} |\n"
            report += "\n"

    with open(os.path.join(out_dir, "probe_predicates_report.md"), "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report: {os.path.join(out_dir, 'probe_predicates_report.md')}")
    print(f"Stats:  {os.path.join(out_dir, 'probe_predicates_stats.json')}")
    if role_stats:
        print(f"Role groups: {len(role_stats)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--descriptions", type=str, default=None,
                        help="覆盖默认的 descriptions.json 路径（调试用）")
    parser.add_argument("--meta", type=str, default=None,
                        help="覆盖上一级 seed 子划分的 kg_hop_meta.json 路径（用于 role 分组统计）")
    args = parser.parse_args()

    config = load_config(args.config)
    paths = get_dataset_paths(config, args.dataset, args.label)
    descriptions = load_data(args.descriptions or paths["descriptions_json"])

    # 对 label > 0 的子划分自动加载上一级 seed 子划分的 kg_hop_meta
    meta = None
    if args.meta:
        meta = load_kg_hop_meta(args.meta)
        print(f"Loaded seed meta from '{args.meta}': {len(meta)} entities")
    else:
        seed_label = resolve_seed_dataset(config, args.dataset, args.label)
        if seed_label:
            seed_paths = get_dataset_paths(config, args.dataset, seed_label)
            meta = load_kg_hop_meta(seed_paths.get("kg_hop_meta", ""))
            print(f"Loaded seed meta from '{args.dataset}/{seed_label}': {len(meta)} entities")

    out_dir = os.path.join(config["output_base"], "probe", args.dataset, args.label)
    analyze(descriptions, f"{args.dataset}/{args.label}", out_dir, meta)


if __name__ == "__main__":
    # python output/probe_predicates.py --dataset dbbook2014-mine --label one-hop
    main()
