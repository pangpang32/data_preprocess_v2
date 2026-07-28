#!/usr/bin/env python3
"""
02c_build_full_kg.py

在目标跳数 KG 构建完成后，统一追加类别信息（dbo 类型 / dbc 类别）实体与三元组，
生成合并子划分（如 full）的最终 KG。类别节点（dbo/dbc）ID 从现有最大实体 ID
之后连续分配，status=no_info，后续可选择走 03/04/05 生成语义嵌入或按行数随机初始化。

输入（按 config 中 full 子划分的 seed_datasets 顺序读取）：
    各 seed 子划分的 entity_list / kg_hop_triples / kg_hop_meta / descriptions.json
    第一个配置了 relation_list 的 seed 子划分的关系映射（如 main 的 one_hop_relations.dat）
    resources/ontology.json（class_parents 叶子过滤与类层级、property_range 兜底推断、
        class_equivalents 类型归一化，来自 owl:equivalentClass）
    config["role_type_map"]（谓词 -> 兼容 dbo 类型的兜底推断表，与 03 共用）
    utils.CATEGORY_BLACKLIST（内联常量）

操作：
    1. 合并各 seed 子划分的实体 ID 空间与现有一跳三元组
    2. 类型边（rdf:type）：types -> class_equivalents 归一化 -> 仅保留 dbo -> 叶子过滤
       （ontology class_parents，丢弃是其他类型祖先的类）；没有叶子 dbo 类型的实体
       按 meta roles 兜底推断（role_type_map 优先，property_range 其次）
    3. 类层级边（rdfs:subClassOf）：沿 class_parents 链逐级连接，父类同样注册为节点
    4. 类别边（dct:subject）：全量实体频次统计 -> 频次阈值 + CATEGORY_BLACKLIST 过滤
    5. 合成 full 的 descriptions.json（seed descriptions 合并 + 类别节点合成条目），
       供 03 直接对 full 构造 prompt（no_info -> dbo/dbc 模板），无需经过 01ab

输出：
    {base_dir}/full_entities.dat / full_triples.dat / full_relations.dat / full_entity_meta.json
    {base_dir}/ontology_map.dat（dbo 类节点 id -> 类短 URI，供全局 ontology_embeddings 行映射）
    output/{dataset}/{label}/01_crawl/descriptions.json（合成）
    output/{dataset}/{label}/02_kg_build/kg_full_stats.json + build_full_kg.log

用法：
    python 02c_build_full_kg.py --dataset dbbook2014-mine --label full
"""
import os
import re
import json
import urllib.parse
import argparse
from collections import Counter, defaultdict
from typing import Dict, List, Set, Tuple

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    load_config, get_dataset_paths, ensure_dir, setup_logging,
    expand_uri, CATEGORY_BLACKLIST,
)

# 02c 引入的三个新关系（短 URI），ID 接续 seed 关系映射的最大值
REL_TYPE = "rdf:type"
REL_SUBCLASS = "rdfs:subClassOf"
REL_SUBJECT = "dct:subject"
NEW_RELATIONS = [REL_TYPE, REL_SUBCLASS, REL_SUBJECT]


# ------------------------------------------------------------------
# 读取工具
# ------------------------------------------------------------------

def load_entity_list(path: str) -> Dict[int, str]:
    """读取 entity_list：entity_id \\t full_uri。"""
    id_to_uri = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            id_to_uri[int(parts[0])] = urllib.parse.unquote(parts[1].strip())
    return id_to_uri


def load_relation_map(path: str) -> Dict[str, int]:
    """读取 relation_list（兼容 2 列或 3 列格式），与 02a 的 load_r_map 一致。"""
    r_map = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pred_candidates = [p for p in parts if ":" in p]
            if not pred_candidates:
                continue
            r_map[pred_candidates[0]] = int(parts[-1])
    return r_map


def load_descriptions(path: str) -> Dict[int, Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def load_kg_hop_meta(path: str) -> Dict[int, Dict]:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def load_role_type_map(config: Dict, config_path: str) -> Dict[str, str]:
    rtm_path = config.get("role_type_map")
    if not rtm_path:
        return {}
    if not os.path.isabs(rtm_path):
        rtm_path = os.path.join(os.path.dirname(config_path), rtm_path)
    if not os.path.exists(rtm_path):
        return {}
    with open(rtm_path, "r", encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


# ------------------------------------------------------------------
# 类型 / 类别处理
# ------------------------------------------------------------------

def is_valid_dbo_class(cls: str) -> bool:
    """合法的 dbo 类短 URI：恰好一个冒号。

    排除两类脏数据：祖先链中的外部上层类（dul: / schema: 等平行本体，
    与归一化目标一致）和 owl 中的遗留脏 URI（如 dbo:Wikidata:Q11424）。
    """
    return cls.startswith("dbo:") and cls.count(":") == 1


def leaf_dbo_types(types: List[str], class_parents: Dict[str, List[str]],
                   class_equivalents: Dict[str, str]) -> Set[str]:
    """types -> class_equivalents 归一化 -> 仅保留 dbo -> 叶子过滤。

    归一化：非 dbo 类型按 ontology 的 class_equivalents（owl:equivalentClass）映射为
    dbo counterpart，减少平行本体（schema/bibo/wd/dul/foaf）造成的冗余类节点。
    叶子过滤：若类型 t 是同实体另一类型 t2 的祖先（t 出现在 class_parents[t2] 中），
    则丢弃 t，只保留最具体的类。owl:Thing 等无 class_parents 信息的非 dbo 类自然被排除。
    """
    normed = set()
    for t in types:
        t = class_equivalents.get(t, t)
        if is_valid_dbo_class(t):
            normed.add(t)
    return {t for t in normed
            if not any(t in class_parents.get(u, []) for u in normed if u != t)}


def infer_fallback_types(roles: List[str], role_type_map: Dict[str, str],
                         property_range: Dict[str, List[str]]) -> Set[str]:
    """按 meta roles 兜底推断兼容类型：role_type_map 优先，property_range 其次。"""
    inferred = set()
    for pred in roles:
        if pred in role_type_map:
            inferred.add(role_type_map[pred])
        else:
            for cls in property_range.get(pred, []):
                if cls and is_valid_dbo_class(cls):
                    inferred.add(cls)
    return inferred


def is_blacklisted_category(cat: str) -> bool:
    """CATEGORY_BLACKLIST 匹配：'*' 后缀表示前缀匹配，否则精确匹配。"""
    for pat in CATEGORY_BLACKLIST:
        if pat.endswith("*"):
            if cat.startswith(pat[:-1]):
                return True
        elif cat == pat:
            return True
    return False


def humanize_class_label(short_uri: str) -> str:
    """dbo:WrittenWork -> 'Written Work'；dbc:American_fantasy_novels -> 'American fantasy novels'。"""
    name = short_uri.split(":", 1)[1] if ":" in short_uri else short_uri
    name = name.replace("_", " ")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return name


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def build_full_kg(dataset_name: str, label: str, config_path: str,
                  min_cat_freq: int, max_connected: int):
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)
    ds = config["datasets"][dataset_name][label]
    seed_labels = ds.get("seed_datasets", [])
    if not seed_labels:
        raise ValueError(f"数据集 {dataset_name}/{label} 缺少 seed_datasets 配置")

    ensure_dir(paths["kg_build_dir"])
    ensure_dir(os.path.dirname(paths["kg_hop_triples"]))
    logger = setup_logging(os.path.join(paths["kg_build_dir"], "build_full_kg.log"))
    logger.info("[02c] Start building full KG for %s/%s (seeds=%s)", dataset_name, label, seed_labels)

    # ---------------- 1. 读取并合并 seed 子划分 ----------------
    id_to_uri: Dict[int, str] = {}
    descriptions: Dict[int, Dict] = {}
    meta: Dict[int, Dict] = {}
    seed_triples: List[Tuple[int, int, int]] = []
    r_map: Dict[str, int] = {}

    for seed_label in seed_labels:
        seed_ds = config["datasets"][dataset_name][seed_label]
        seed_paths = get_dataset_paths(config, dataset_name, seed_label)

        # 实体列表
        for eid, uri in load_entity_list(seed_paths["entity_list"]).items():
            if eid in id_to_uri and id_to_uri[eid] != uri:
                raise ValueError(f"实体 ID 冲突: {eid} -> {id_to_uri[eid]} vs {uri} ({seed_label})")
            id_to_uri[eid] = uri

        # 描述（types / categories 的来源）
        seed_desc = load_descriptions(seed_paths["descriptions_json"])
        descriptions.update(seed_desc)

        # 用 descriptions 补齐实体空间：KG 三元组的 head 来自 descriptions 的原始 ID 空间
        # （如 main 经 expand_map 扩展回 2680），与 entity_list 的去重空间（2624）可能不一致
        for eid, ent in seed_desc.items():
            uri = ent.get("uri", "")
            if uri and eid not in id_to_uri:
                id_to_uri[eid] = uri

        # meta（roles / connected_items，兜底推断与 full meta 的基础）
        seed_meta = load_kg_hop_meta(seed_paths.get("kg_hop_meta"))
        meta.update(seed_meta)

        # 现有一跳三元组（配置了 kg_hop_triples 且文件存在的 seed）
        triples_path = seed_paths.get("kg_hop_triples")
        if seed_ds.get("kg_hop_triples") and triples_path and os.path.exists(triples_path):
            with open(triples_path, "r", encoding="utf-8") as f:
                for line in f:
                    h, t, r = line.split()
                    seed_triples.append((int(h), int(t), int(r)))
            logger.info("Loaded %d triples from seed '%s'", len(seed_triples), seed_label)

        # 关系映射：取第一个配置了 relation_list 的 seed
        if not r_map and seed_ds.get("relation_list"):
            r_map = load_relation_map(seed_paths["relation_list"])
            logger.info("Loaded relation map: %d relations from seed '%s'", len(r_map), seed_label)

        logger.info("Loaded seed '%s': entities=%d descriptions=%d meta=%d",
                    seed_label, len(id_to_uri), len(seed_desc), len(seed_meta))

    if not r_map:
        raise ValueError("所有 seed 子划分都未配置 relation_list")

    # 校验：所有三元组端点必须存在于实体空间中
    missing = sorted({e for h, t, _ in seed_triples for e in (h, t)} - set(id_to_uri.keys()))
    if missing:
        raise ValueError(f"三元组端点缺失于实体空间: {len(missing)} 个，如 {missing[:10]}")

    # 新关系 ID 接续现有最大值
    next_rid = max(r_map.values()) + 1
    for rel in NEW_RELATIONS:
        r_map[rel] = next_rid
        next_rid += 1
    logger.info("Relation IDs: %s", {r: r_map[r] for r in NEW_RELATIONS})

    # 类别节点 ID 从现有最大实体 ID 之后连续分配
    next_id = max(id_to_uri.keys()) + 1
    logger.info("Existing entities: %d (max id=%d), class node IDs start at %d",
                len(id_to_uri), next_id - 1, next_id)

    # ontology（路径取自 prompt_config，与 03 一致）与兜底推断表
    prompt_cfg_path = config["prompt_config"]
    if not os.path.isabs(prompt_cfg_path):
        prompt_cfg_path = os.path.join(os.path.dirname(config_path), prompt_cfg_path)
    with open(prompt_cfg_path, "r", encoding="utf-8") as f:
        ontology_path = json.load(f).get("ontology_path", "resources/ontology.json")
    if not os.path.isabs(ontology_path):
        ontology_path = os.path.join(os.path.dirname(config_path), ontology_path)
    with open(ontology_path, "r", encoding="utf-8") as f:
        ontology = json.load(f)
    class_parents = ontology.get("class_parents", {})
    property_range = ontology.get("property_range", {})
    class_equivalents = ontology.get("class_equivalents", {})
    role_type_map = load_role_type_map(config, config_path)
    logger.info("Loaded ontology (%d classes, %d equivalents) and role_type_map (%d entries)",
                len(class_parents), len(class_equivalents), len(role_type_map))

    # ---------------- 2. 类型边（rdf:type） ----------------
    class_id: Dict[str, int] = {}           # dbo/dbc 短 URI -> 新实体 ID
    type_edges: Set[Tuple[int, str]] = set()      # (entity_id, dbo 类短 URI)
    members: Dict[str, List[int]] = defaultdict(list)  # 类短 URI -> 成员实体 ID
    n_fallback_entities = 0
    n_no_type_entities = 0

    for eid in sorted(descriptions.keys()):
        entity = descriptions[eid]
        leaves = leaf_dbo_types(entity.get("types", []), class_parents, class_equivalents)
        if not leaves:
            # 兜底：按 roles 推断（服务只有 owl:Thing 或完全无类型的实体）
            roles = meta.get(eid, {}).get("roles", [])
            leaves = infer_fallback_types(roles, role_type_map, property_range)
            if leaves:
                n_fallback_entities += 1
        if not leaves:
            n_no_type_entities += 1
            continue
        for cls in sorted(leaves):
            type_edges.add((eid, cls))
            class_id.setdefault(cls, -1)  # 占位，统一在步骤 5 分配 ID
            members[cls].append(eid)

    logger.info("Type edges: %d (fallback-inferred entities: %d, no-type entities: %d)",
                len(type_edges), n_fallback_entities, n_no_type_entities)

    # ---------------- 3. 类层级边（rdfs:subClassOf） ----------------
    # 收集所有出现的类及其 class_parents 链上的祖先（仅注册合法 dbo 类节点：
    # 外部上层类 dul:/schema: 与 dbo:Wikidata:* 等脏数据不建节点、不建边）
    all_classes: Set[str] = set(class_id.keys())
    for cls in list(all_classes):
        all_classes.update(p for p in class_parents.get(cls, []) if is_valid_dbo_class(p))

    subclass_edges: Set[Tuple[str, str]] = set()  # (child, parent) 短 URI
    for cls in all_classes:
        chain = [cls] + [p for p in class_parents.get(cls, []) if is_valid_dbo_class(p)]
        for child, parent in zip(chain, chain[1:]):
            subclass_edges.add((child, parent))
    logger.info("dbo classes: %d leaf/inferred, %d with ancestors, %d subclass edges",
                len(class_id), len(all_classes), len(subclass_edges))

    # ---------------- 4. 类别边（dct:subject） ----------------
    cat_freq: Counter = Counter()
    for entity in descriptions.values():
        for cat in set(entity.get("categories", [])):
            if cat:
                cat_freq[cat] += 1
    kept_cats = sorted(
        [c for c, n in cat_freq.items() if n >= min_cat_freq and not is_blacklisted_category(c)],
        key=lambda c: (-cat_freq[c], c),
    )
    n_blacklisted = sum(1 for c, n in cat_freq.items()
                        if n >= min_cat_freq and is_blacklisted_category(c))
    kept_cat_set = set(kept_cats)

    subject_edges: Set[Tuple[int, str]] = set()  # (entity_id, cat 短 URI)
    for eid in sorted(descriptions.keys()):
        for cat in sorted(set(descriptions[eid].get("categories", []))):
            if cat in kept_cat_set:
                subject_edges.add((eid, cat))
                members[cat].append(eid)
    logger.info("Categories: %d distinct, kept %d (min_freq=%d, blacklisted %d), subject edges: %d",
                len(cat_freq), len(kept_cats), min_cat_freq, n_blacklisted, len(subject_edges))

    # ---------------- 5. 注册类别节点并写出 ----------------
    # ID 顺序：dbc 类别节点在前（按频次降序）；dbo 类节点在后，
    # 越具体（祖先链越长）越靠前、越抽象越靠后——抽象类（如 dbo:Work）位于 ID 空间末尾，
    # 便于后续用全局 ontology_embeddings 按行区间整体替换
    cat_id: Dict[str, int] = {}
    for cat in kept_cats:
        cat_id[cat] = next_id
        id_to_uri[next_id] = expand_uri(cat)
        next_id += 1
    dbo_sorted = sorted(all_classes, key=lambda c: (-len(class_parents.get(c, [])), c))
    for cls in dbo_sorted:
        class_id[cls] = next_id
        id_to_uri[next_id] = expand_uri(cls)
        next_id += 1
    logger.info("Registered %d dbo class nodes and %d dbc category nodes; total entities: %d",
                len(all_classes), len(kept_cats), len(id_to_uri))

    # full_entities.dat
    with open(paths["kg_hop_entities"], "w", encoding="utf-8") as f:
        for eid in sorted(id_to_uri.keys()):
            f.write(f"{eid}\t{id_to_uri[eid]}\n")

    # full_triples.dat：seed 三元组 + 类型/类层级/类别边
    with open(paths["kg_hop_triples"], "w", encoding="utf-8") as f:
        for h, t, r in seed_triples:
            f.write(f"{h}\t{t}\t{r}\n")
        for eid, cls in sorted(type_edges):
            f.write(f"{eid}\t{class_id[cls]}\t{r_map[REL_TYPE]}\n")
        for child, parent in sorted(subclass_edges):
            f.write(f"{class_id[child]}\t{class_id[parent]}\t{r_map[REL_SUBCLASS]}\n")
        for eid, cat in sorted(subject_edges):
            f.write(f"{eid}\t{cat_id[cat]}\t{r_map[REL_SUBJECT]}\n")
    n_triples_total = len(seed_triples) + len(type_edges) + len(subclass_edges) + len(subject_edges)

    # full_relations.dat
    with open(paths["relation_list"], "w", encoding="utf-8") as f:
        for rel, rid in sorted(r_map.items(), key=lambda x: x[1]):
            f.write(f"{rel}\t{rid}\n")

    # ontology_map.dat：KG 中 dbo 类节点 id -> 类短 URI（全局 ontology_embeddings 的行映射基础，
    # 格式对齐 original_i2i_map.dat；下游与 resources/embeddings/ontology_entities.dat
    # （行号 <-> 类 URI）join 后完成嵌入替换）
    ontology_map_path = os.path.join(os.path.dirname(paths["kg_hop_entities"]), "ontology_map.dat")
    with open(ontology_map_path, "w", encoding="utf-8") as f:
        f.write("# kg_entity_id\tdbo_class\n")
        for cls in dbo_sorted:
            f.write(f"{class_id[cls]}\t{cls}\n")

    # full_entity_meta.json：seed meta + 类别节点 meta
    for cls, cid in class_id.items():
        child_classes = sorted(ch for ch, pa in subclass_edges if pa == cls)
        connected = {}
        totals = {}
        # subClassOf 子类优先展示：对描述父类语义比成员样本更关键（03 按 dict 顺序截取）
        if child_classes:
            connected[REL_SUBCLASS] = [class_id[ch] for ch in child_classes]
            totals[REL_SUBCLASS] = len(child_classes)
        if members.get(cls):
            connected[REL_TYPE] = sorted(members[cls])[:max_connected]
            totals[REL_TYPE] = len(members[cls])
        roles = ([REL_TYPE] if connected.get(REL_TYPE) else []) \
            + ([REL_SUBCLASS] if child_classes else [])
        meta[cid] = {
            "roles": roles,
            "connected_items": connected,
            "connected_items_total": totals,  # 截断前的真实数量（03 报告 header 用）
            "label": humanize_class_label(cls),
            "status": "no_info",
        }
    for cat, cid in cat_id.items():
        meta[cid] = {
            "roles": [REL_SUBJECT],
            "connected_items": {REL_SUBJECT: sorted(members[cat])[:max_connected]},
            "connected_items_total": {REL_SUBJECT: len(members[cat])},
            "label": humanize_class_label(cat),
            "status": "no_info",
        }
    with open(paths["kg_hop_meta"], "w", encoding="utf-8") as f:
        json.dump({str(k): meta[k] for k in sorted(meta.keys())}, f, ensure_ascii=False, indent=2)

    # ---------------- 6. 合成 full 的 descriptions.json ----------------
    full_descriptions = dict(descriptions)
    for cls, cid in class_id.items():
        full_descriptions[cid] = _synthetic_class_description(
            cid, cls, "dbo", ancestors=class_parents.get(cls, []))
    for cat, cid in cat_id.items():
        full_descriptions[cid] = _synthetic_class_description(cid, cat, "dbc")
    ensure_dir(os.path.dirname(paths["descriptions_json"]))
    with open(paths["descriptions_json"], "w", encoding="utf-8") as f:
        json.dump({str(k): full_descriptions[k] for k in sorted(full_descriptions.keys())},
                  f, ensure_ascii=False, indent=2)

    # ---------------- 7. 统计 ----------------
    stats = {
        "n_seed_entities": max(descriptions.keys()) + 1 if descriptions else 0,
        "n_dbo_class_nodes": len(all_classes),
        "n_dbc_category_nodes": len(kept_cats),
        "n_entities_total": len(id_to_uri),
        "n_triples_seed": len(seed_triples),
        "n_triples_type": len(type_edges),
        "n_triples_subclass": len(subclass_edges),
        "n_triples_subject": len(subject_edges),
        "n_triples_total": n_triples_total,
        "min_cat_freq": min_cat_freq,
        "n_categories_distinct": len(cat_freq),
        "n_categories_blacklisted": n_blacklisted,
        "n_fallback_inferred_entities": n_fallback_entities,
        "n_entities_no_type_edge": n_no_type_entities,
        "relation_ids": {r: r_map[r] for r in NEW_RELATIONS},
    }
    stats_path = os.path.join(paths["kg_build_dir"], "kg_full_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    logger.info("Wrote %d entities -> %s", len(id_to_uri), paths["kg_hop_entities"])
    logger.info("Wrote %d triples -> %s", n_triples_total, paths["kg_hop_triples"])
    logger.info("Wrote %d relations -> %s", len(r_map), paths["relation_list"])
    logger.info("Wrote meta (%d entries) -> %s", len(meta), paths["kg_hop_meta"])
    logger.info("Wrote synthesized descriptions (%d) -> %s", len(full_descriptions), paths["descriptions_json"])
    logger.info("Stats -> %s", stats_path)
    logger.info("[02c] Done. 请将 config 中 %s/%s 的 n_entities 更新为 %d",
                dataset_name, label, len(id_to_uri))


def _synthetic_class_description(cid: int, short_uri: str, prefix: str,
                                 ancestors: List[str] = None) -> Dict:
    """为类别节点合成 descriptions 条目（status=no_info，供 03 按 prefix 分流到 dbo/dbc 模板）。

    dbo 类节点附带完整祖先链作为 rdfs:subClassOf 的 object_properties，
    使 03 的 format_relations 能把类层级渲染进 dbo 模板的 {relations} 占位符。
    """
    object_properties = [
        {"predicate": REL_SUBCLASS, "object": parent}
        for parent in (ancestors or [])
    ]
    return {
        "entity_id": cid,
        "uri": expand_uri(short_uri),
        "shorten_uri": short_uri,
        "prefix": prefix,
        "label": humanize_class_label(short_uri),
        "description": "",
        "long_abstract": "",
        "types": [],
        "categories": [],
        "object_properties": object_properties,
        "literal_properties": {},
        "status": "no_info",
    }


def main():
    parser = argparse.ArgumentParser(description="Build full KG by appending dbo type / dbc category nodes and edges.")
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="合并子划分（如 full），其 seed_datasets 指定输入来源")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--min_cat_freq", type=int, default=5,
                        help="dbc 类别保留的最小共享实体数（频次阈值）")
    parser.add_argument("--max_connected", type=int, default=50,
                        help="类别节点 meta 中 connected_items 的最大存储数量")
    args = parser.parse_args()

    build_full_kg(args.dataset, args.label, args.config, args.min_cat_freq, args.max_connected)


if __name__ == "__main__":
    # python 02c_build_full_kg.py --dataset dbbook2014-mine --label full --min_cat_freq 2
    main()
