"""
probe_objects.py

分析 descriptions.json 中 `types` 与 `categories` 字段的宾语（object）分布，
为把 rdf:type（dbo 类）与 dct:subject（dbc 类别）引入 KG 边的构建策略提供数据依据：

- categories：每个 dbc 类别被多少实体共享；按频次阈值统计保留的类别数与边数，
  用于决定类别边的过滤阈值（类别是用户自由打标，低频类别噪声大）。
- types：按命名空间前缀分组统计（dbo / schema / bibo / wd / yago / owl / ...），
  并统计"没有任何 dbo 类"与"仅有 owl:Thing"的实体数，
  用于评估非 dbo 类型映射到 dbo counterpart 的覆盖率与兜底需求。

执行位置：项目根目录（data_preprocess/）
示例：python output/probe_objects.py --dataset dbbook2014-mine --label main
      python output/probe_objects.py --dataset dbbook2014-mine --label one-hop

输出：
    output/probe/{dataset}/{label}/probe_objects_report.md
    output/probe/{dataset}/{label}/probe_objects_stats.json
"""
import os
import json
import argparse
from collections import Counter
from typing import Dict, List, Tuple

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, get_dataset_paths

# 频次阈值表：类别/类型至少被 k 个实体共享时才保留
FREQ_THRESHOLDS = [1, 2, 3, 5, 10, 20, 50, 100]

# 报告中展示的高频宾语数量
TOP_N = 50


def load_data(path: str) -> Dict[int, Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def prefix_of(short_uri: str) -> str:
    return short_uri.split(":", 1)[0] if ":" in short_uri else "(no_prefix)"


def threshold_table(counter: Counter) -> List[Tuple[int, int, int]]:
    """对每个阈值 k 返回 (k, 保留宾语数, 保留边数)。"""
    rows = []
    for k in FREQ_THRESHOLDS:
        kept = {obj: c for obj, c in counter.items() if c >= k}
        rows.append((k, len(kept), sum(kept.values())))
    return rows


def analyze(descriptions: Dict[int, Dict], dataset_name: str, out_dir: str):
    cat_counter = Counter()          # dbc 类别 -> 出现该类别的实体数
    type_counter = Counter()         # 类型（全前缀）-> 实体数
    type_prefix_counter = Counter()  # 类型前缀 -> 类型实例总次数
    type_prefix_distinct = {}        # 类型前缀 -> 去重类型集合

    n_entities = len(descriptions)
    n_with_categories = 0
    n_with_types = 0
    n_no_dbo_type = 0       # 没有任何 dbo: 类型的实体
    n_only_owl_thing = 0    # 类型只有 owl:Thing 的实体
    cat_per_entity = []
    type_per_entity = []

    for entity in descriptions.values():
        cats = [c for c in entity.get("categories", []) if c]
        types = [t for t in entity.get("types", []) if t]

        if cats:
            n_with_categories += 1
            cat_per_entity.append(len(cats))
            for c in set(cats):
                cat_counter[c] += 1

        if types:
            n_with_types += 1
            type_per_entity.append(len(types))
            uniq_types = set(types)
            for t in uniq_types:
                type_counter[t] += 1
                p = prefix_of(t)
                type_prefix_counter[p] += 1
                type_prefix_distinct.setdefault(p, set()).add(t)
            if not any(t.startswith("dbo:") for t in uniq_types):
                n_no_dbo_type += 1
            if uniq_types == {"owl:Thing"}:
                n_only_owl_thing += 1

    prefix_distinct_counts = {p: len(s) for p, s in type_prefix_distinct.items()}
    # 转为可序列化
    type_prefix_distinct = {p: sorted(s) for p, s in type_prefix_distinct.items()}

    cat_thresholds = threshold_table(cat_counter)
    type_thresholds = threshold_table(type_counter)
    dbo_type_counter = Counter({t: c for t, c in type_counter.items() if t.startswith("dbo:")})
    dbo_thresholds = threshold_table(dbo_type_counter)

    stats = {
        "n_entities": n_entities,
        "n_with_categories": n_with_categories,
        "n_with_types": n_with_types,
        "n_no_dbo_type": n_no_dbo_type,
        "n_only_owl_thing": n_only_owl_thing,
        "categories": {
            "n_distinct": len(cat_counter),
            "refs_total": sum(cat_counter.values()),
            "avg_per_entity": round(sum(cat_per_entity) / max(len(cat_per_entity), 1), 2),
            "thresholds": [
                {"min_freq": k, "kept_objects": n_obj, "kept_edges": n_edges}
                for k, n_obj, n_edges in cat_thresholds
            ],
            "top": cat_counter.most_common(TOP_N),
        },
        "types": {
            "n_distinct": len(type_counter),
            "refs_total": sum(type_counter.values()),
            "avg_per_entity": round(sum(type_per_entity) / max(len(type_per_entity), 1), 2),
            "prefix_instance_counts": dict(type_prefix_counter.most_common()),
            "prefix_distinct_counts": dict(sorted(prefix_distinct_counts.items(),
                                                  key=lambda x: -x[1])),
            "thresholds_all": [
                {"min_freq": k, "kept_objects": n_obj, "kept_edges": n_edges}
                for k, n_obj, n_edges in type_thresholds
            ],
            "thresholds_dbo_only": [
                {"min_freq": k, "kept_objects": n_obj, "kept_edges": n_edges}
                for k, n_obj, n_edges in dbo_thresholds
            ],
            "top": type_counter.most_common(TOP_N),
        },
    }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "probe_objects_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # ---------------- 报告 ----------------
    report = f"""# 宾语（types / categories）分布分析报告

数据集：`{dataset_name}`

## 1. 总体统计

- 实体总数：{n_entities}
- 含 categories 的实体数：{n_with_categories}（平均 {stats['categories']['avg_per_entity']} 个/实体）
- 含 types 的实体数：{n_with_types}（平均 {stats['types']['avg_per_entity']} 个/实体）
- 不同 dbc 类别数：{len(cat_counter)}，引用总次数：{sum(cat_counter.values())}
- 不同类型数（全前缀）：{len(type_counter)}，引用总次数：{sum(type_counter.values())}
- 没有任何 dbo: 类型的实体数：{n_no_dbo_type}
- 类型仅有 owl:Thing 的实体数：{n_only_owl_thing}

## 2. categories（dbc）频次阈值表

> 行含义：仅保留至少被 k 个实体共享的类别时，剩下的类别节点数与类别边总数。
> 用于权衡"类别节点的共享度"与"引入的边数/噪声"。

| 最小共享实体数 k | 保留类别数 | 保留类别边数 |
|---|---|---|
"""
    for k, n_obj, n_edges in cat_thresholds:
        report += f"| {k} | {n_obj} | {n_edges} |\n"

    report += f"""
## 3. categories（dbc）Top {TOP_N}

| 类别 | 共享实体数 |
|---|---|
"""
    for cat, cnt in cat_counter.most_common(TOP_N):
        report += f"| {cat} | {cnt} |\n"

    report += """
## 4. types 按命名空间前缀统计

| 前缀 | 类型实例次数 | 去重类型数 |
|---|---|
"""
    for p, cnt in type_prefix_counter.most_common():
        report += f"| {p} | {cnt} | {prefix_distinct_counts[p]} |\n"

    report += """
## 5. types 频次阈值表（全前缀 vs 仅 dbo）

| 最小共享实体数 k | 保留类型数（全前缀） | 保留边数（全前缀） | 保留类型数（仅 dbo） | 保留边数（仅 dbo） |
|---|---|---|---|---|
"""
    for (k, n_obj, n_edges), (_, n_obj_d, n_edges_d) in zip(type_thresholds, dbo_thresholds):
        report += f"| {k} | {n_obj} | {n_edges} | {n_obj_d} | {n_edges_d} |\n"

    report += f"""
## 6. types Top {TOP_N}（全前缀）

| 类型 | 共享实体数 |
|---|---|
"""
    for t, cnt in type_counter.most_common(TOP_N):
        report += f"| {t} | {cnt} |\n"

    with open(os.path.join(out_dir, "probe_objects_report.md"), "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report: {os.path.join(out_dir, 'probe_objects_report.md')}")
    print(f"Stats:  {os.path.join(out_dir, 'probe_objects_stats.json')}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--descriptions", type=str, default=None,
                        help="覆盖默认的 descriptions.json 路径（调试用）")
    args = parser.parse_args()

    config = load_config(args.config)
    paths = get_dataset_paths(config, args.dataset, args.label)
    descriptions_path = args.descriptions or paths["descriptions_json"]
    descriptions = load_data(descriptions_path)
    print(f"Loaded descriptions from '{descriptions_path}': {len(descriptions)} entities")

    out_dir = os.path.join(config["output_base"], "probe", args.dataset, args.label)
    analyze(descriptions, f"{args.dataset}/{args.label}", out_dir)


if __name__ == "__main__":
    # python output/probe_objects.py --dataset dbbook2014-mine --label main
    main()
