#!/usr/bin/env python3
"""
03_build_prompts.py

为指定数据集的实体构造 LLM prompt。

输入：
    config.yaml 中配置的 prompt_config JSON 文件
    output/{dataset}/01_crawl/descriptions.json

输出：
    output/{dataset}/03_prompts/prompts.json              # 聚合后的 prompt 字典

prompt_config 文件按 status 分键，内部共享同一个 system prompt。

设计说明（当前阶段）：
- 一次处理整个数据集的 descriptions.json，根据每个实体自身的 status 自动选择对应模板。
- 上游 seed_datasets 默认从 config 中当前子划分的 label 与 seed_datasets 推断：
    seed_datasets = config["datasets"][dataset_name][sub_label]["seed_datasets"][:label]
  config 中的 seed_datasets 必须是有序列表（同一数据集内的上游子划分名）；label=0 表示种子子划分，无上游。
- 多个 seed 子划分的 meta 和 descriptions 会自动合并，为后续多跳 KG 留出扩展空间。
- relation 展示优先级从 prompt_config["relation_priority"][dataset_name][sub_label] 读取，
  未配置的标签按默认优先级和字母序排列，避免硬编码与特定数据集或多跳 KG 不兼容。
- 暂不实现 relation_list 泛化，留到真正需要时再引入。
"""
import os
import re
import json
import argparse
from typing import Dict, List, Optional, Set, Union, Iterable

from utils import load_config, get_dataset_paths, ensure_dir, setup_logging, shorten_uri


def load_prompt_config(config_path: str, template_path: str) -> Dict:
    """加载 prompt 模板 JSON 文件。"""
    if not os.path.isabs(template_path):
        base = os.path.dirname(os.path.abspath(config_path))
        template_path = os.path.join(base, template_path)
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_prompt_config_path(config: Dict, config_path: str) -> str:
    """根据全局 config 找到 prompt_config 文件路径。"""
    if "prompt_config" not in config:
        raise ValueError("config.yaml 中没有配置全局 prompt_config")
    template_path = config["prompt_config"]
    if not os.path.isabs(template_path):
        base = os.path.dirname(os.path.abspath(config_path))
        template_path = os.path.join(base, template_path)
    return template_path


def load_ontology(ontology_path: str) -> Dict:
    """加载 build_ontology.py 生成的 ontology.json。"""
    if not os.path.exists(ontology_path):
        raise FileNotFoundError(f"ontology file not found: {ontology_path}")
    with open(ontology_path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_object_value(obj: str) -> str:
    """把 DBpedia 命名空间前缀和 underscore 转成可读文本。"""
    if not obj:
        return obj
    for prefix in ("dbr:", "dbo:", "dbc:", "schema:", "bibo:", "wd:", "gold:", "dct:", "owl:"):
        if obj.startswith(prefix):
            obj = obj[len(prefix):]
            break
    obj = obj.replace("_", " ")
    if "@" in obj:
        obj = obj.split("@")[0]
    return obj.strip()


def clean_predicate_name(pred: str) -> str:
    """去掉谓词前缀，并把驼峰拆分为空格分隔的小写词。"""
    if not pred:
        return pred
    for prefix in ("dbo:", "dbr:", "dbc:", "schema:", "bibo:", "wd:", "gold:", "dct:", "foaf:", "dc:", "rdf:", "rdfs:", "owl:"):
        if pred.startswith(prefix):
            pred = pred[len(prefix):]
            break
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", pred)
    return name.lower().strip()


def relation_label(pred: str, ontology: Dict) -> str:
    """获取谓词的可读标签：优先 ontology.json，其次硬编码 fallback，最后清洗前缀。"""
    prop_labels = ontology.get("property_labels", {})
    if pred in prop_labels:
        return prop_labels[pred]

    fallback = {
        "rdf:type": "type",
        "dct:subject": "category",
        "foaf:name": "name",
        "dc:publisher": "publisher",
    }
    if pred in fallback:
        return fallback[pred]

    return clean_predicate_name(pred)


def class_depth(cls: str, ontology: Dict, memo: Dict[str, int]) -> int:
    """计算本体类在 class_parents 中的最大深度（叶子最深）。"""
    if cls in memo:
        return memo[cls]
    parents = ontology.get("class_parents", {}).get(cls, [])
    if not parents:
        memo[cls] = 0
        return 0
    memo[cls] = 1 + max(class_depth(p, ontology, memo) for p in parents)
    return memo[cls]


def build_type_chain(type_uris: List[str], ontology: Dict) -> str:
    """把多个 type 类合并成一条从具象到抽象的 chain，如 book > written work > work。"""
    class_labels = ontology.get("class_labels", {})
    class_parents = ontology.get("class_parents", {})

    # 保留 ontology 中存在的 dbo 类，以及 owl 类（如 owl:Thing）
    kept = []
    for t in type_uris:
        if t in class_labels:
            kept.append(t)
        elif t.startswith("owl:"):
            kept.append(t)

    if not kept:
        return ""

    # 如果只存在 owl:Thing 这类顶层类，直接返回
    if all(t.startswith("owl:") for t in kept):
        return " > ".join(clean_object_value(t) for t in kept)

    # 去掉 owl 类（当存在更具体的 dbo 类时）
    kept = [t for t in kept if not t.startswith("owl:")]
    if not kept:
        return ""

    depth_memo: Dict[str, int] = {}
    kept.sort(key=lambda c: class_depth(c, ontology, depth_memo), reverse=True)

    chains = []
    used = set()
    for cls in kept:
        if cls in used:
            continue
        chain = []
        current = cls
        while current and current not in used:
            used.add(current)
            chain.append(current)
            parents = class_parents.get(current, [])
            # 选择仍在 kept 中且深度最大的父类延续 chain；否则选深度最大的 ontology 父类
            candidates = [p for p in parents if p in class_labels]
            if not candidates:
                break
            # 优先选 kept 中的父类，其次选任意父类
            kept_candidates = [p for p in candidates if p in kept]
            next_cls = max(kept_candidates if kept_candidates else candidates,
                           key=lambda p: class_depth(p, ontology, depth_memo))
            current = next_cls
        chains.append(" > ".join(class_labels.get(c, clean_object_value(c)) for c in chain))

    return "; ".join(chains)


def format_relations(
    entity_data: Dict,
    ontology: Dict,
    prompt_cfg: Dict,
    dataset_name: str,
    label: str,
    max_relations: int = 16,
) -> str:
    """把实体的 types、categories、object_properties、literal_properties 格式化为可读文本。

    relation 的展示优先级从 prompt_cfg["relation_priority"][dataset_name][label] 读取；
    若该数据集无专属配置则回退到 "default"。未配置的 label 默认居中，并按字母序稳定排列，
    从而兼容不同数据集和多跳 KG 中出现的新关系。
    """
    # 分组收集字段值：label -> list of values
    groups: Dict[str, List[str]] = {}

    def add_value(label: str, value: str):
        if not value:
            return
        groups.setdefault(label, []).append(value)

    # type：合并成 chain
    type_chain = build_type_chain(entity_data.get("types", []), ontology)
    if type_chain:
        groups["type"] = [type_chain]

    # category：合并成一行
    for c in entity_data.get("categories", []):
        add_value("category", clean_object_value(c))

    # object_properties
    for op in entity_data.get("object_properties", []):
        pred = op.get("predicate", "")
        obj = op.get("object", "")
        if not pred or not obj:
            continue
        label = relation_label(pred, ontology)
        add_value(label, clean_object_value(obj))

    # literal_properties：挑选较短的值
    for pred, val in entity_data.get("literal_properties", {}).items():
        if not pred or not val:
            continue
        if len(str(val)) > 80:
            continue
        label = relation_label(pred, ontology)
        add_value(label, clean_object_value(str(val)))

    # 去重并保持稳定顺序
    for label in groups:
        seen: Set[str] = set()
        deduped: List[str] = []
        for v in groups[label]:
            if v not in seen:
                seen.add(v)
                deduped.append(v)
        groups[label] = deduped

    # 从 prompt 配置读取 relation 展示优先级：按 数据集名 -> 子划分 label 查找，无则回退到 default
    priority_cfg = prompt_cfg.get("relation_priority", {})
    priority = {}
    if isinstance(priority_cfg, dict):
        dataset_cfg = priority_cfg.get(dataset_name, {})
        if isinstance(dataset_cfg, dict):
            priority = dataset_cfg.get(label, {})
        if not priority:
            priority = priority_cfg.get("default", {})
    default_priority = priority.get("*", 50)

    ordered_labels = sorted(groups.keys(), key=lambda k: (priority.get(k, default_priority), k))

    lines: List[str] = []
    for label in ordered_labels:
        values = groups[label]
        if not values:
            continue
        # 对多值字段用逗号分隔，但 type 已经是 chain 格式
        if label == "type":
            lines.append(f"{label}: {values[0]}")
        else:
            lines.append(f"{label}: {', '.join(values[:5])}")

    selected = lines[:max_relations]
    if not selected:
        return "(no relation information available)"
    return "\n".join(selected)


def normalize_seed_datasets(seed_datasets: Union[List[str], Iterable[str], None]) -> List[str]:
    """把 seed_datasets 归一化为字符串列表。config 中 seed_datasets 必须是有序列表。"""
    if seed_datasets is None:
        return []
    if isinstance(seed_datasets, str):
        raise ValueError(
            "config 中的 seed_datasets 必须是有序列表，不能是字符串。"
            "例如：[\"main\"]"
        )
    return list(seed_datasets)


def resolve_seed_datasets(config: Dict, dataset_name: str, sub_label: str,
                          seed_datasets: Union[List[str], Iterable[str], None] = None) -> List[str]:
    """解析当前子划分的上游 seed_datasets（同一数据集内的子划分名）。

    若调用方未显式传入 seed_datasets，则根据当前子划分的 label 与 config 中的
    seed_datasets 推断：取前 label 个上游子划分（label=1 取 [0]，label=2 取 [0:2]，以此类推）。
    """
    if seed_datasets is not None:
        return normalize_seed_datasets(seed_datasets)

    ds = config["datasets"].get(dataset_name, {}).get(sub_label)
    if ds is None:
        raise ValueError(f"config 中未找到数据集: {dataset_name}/{sub_label}")

    label = ds.get("label", 0)
    if label == 0:
        return []

    configured = ds.get("seed_datasets", [])
    configured = normalize_seed_datasets(configured)
    if not configured:
        raise ValueError(f"数据集 {dataset_name}/{sub_label} 的 label={label} > 0 但缺少 seed_datasets 配置")
    if label - 1 >= len(configured):
        raise ValueError(
            f"数据集 {dataset_name}/{sub_label} 的 label={label} 超出 seed_datasets 长度 {len(configured)}"
        )
    # label 表示当前子划分在依赖链中的深度：label=1 取 [0:1]，label=2 取 [0:2]，以此类推
    return configured[:label]


def merge_meta(dst: Dict[int, Dict], src: Dict[int, Dict]) -> None:
    """合并多个 seed dataset 的 kg_hop_meta：roles 去重，connected_items 按谓词去重保留顺序。"""
    for eid, m in src.items():
        if eid not in dst:
            dst[eid] = {"roles": [], "connected_items": {}}
        # roles 去重并保持有序
        roles = set(dst[eid].get("roles", []))
        roles.update(m.get("roles", []))
        dst[eid]["roles"] = sorted(roles)
        # connected_items 按谓词合并并去重保留顺序
        src_connected = m.get("connected_items", {})
        dst_connected = dst[eid].setdefault("connected_items", {})
        for pred, items in src_connected.items():
            seen = set(dst_connected.get(pred, []))
            merged = list(dst_connected.get(pred, []))
            for iid in items:
                if iid not in seen:
                    seen.add(iid)
                    merged.append(iid)
            dst_connected[pred] = merged
        # connected_items_total（02c 类别节点的真实相连数量）：跨来源取最大值
        for pred, n in m.get("connected_items_total", {}).items():
            totals = dst[eid].setdefault("connected_items_total", {})
            totals[pred] = max(totals.get(pred, 0), n)


def load_kg_hop_meta(paths: Dict) -> Dict[int, Dict]:
    """如果存在 kg_hop_meta.json，则加载。"""
    meta_path = paths.get("kg_hop_meta")
    if not meta_path or not os.path.exists(meta_path):
        return {}
    with open(meta_path, "r", encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}


def infer_types_from_relations(
    entity_id: int,
    meta: Dict[int, Dict],
    ontology: Dict,
    role_type_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """根据邻居实体在 KG 中的 roles 推断兼容类型。

    推断顺序：role_type_map（resources/role_type_map.json，人工补充/覆盖）优先，
    其次 ontology 的 property_range。与 02c 构建兜底类型边共用同一张表。
    """
    if entity_id not in meta:
        return []

    roles = meta[entity_id].get("roles", [])
    if not roles:
        return []

    property_range = ontology.get("property_range", {})
    class_labels = ontology.get("class_labels", {})
    role_type_map = role_type_map or {}

    inferred: Set[str] = set()
    for pred in roles:
        range_classes = [role_type_map[pred]] if pred in role_type_map else property_range.get(pred, [])
        for range_cls in range_classes:
            if not range_cls or range_cls == "xsd:string":
                continue
            # 优先使用 ontology 里的可读 label，否则清洗前缀
            label = class_labels.get(range_cls, clean_object_value(range_cls))
            if label:
                inferred.add(label)

    return sorted(inferred)


def format_inferred_types(inferred_types: List[str]) -> str:
    """把推断类型格式化为 prompt 文本；空则返回空字符串。"""
    if not inferred_types:
        return ""
    lines = ["Inferred types from relations:"] + [f"- {t}" for t in inferred_types]
    return "\n".join(lines)


def build_connected_descriptions(
    entity_id: int,
    entity_data: Dict,
    meta: Dict[int, Dict],
    seed_descriptions: Dict[int, Dict],
    ontology: Dict,
    max_items: int = 3,
    id_to_uri: Optional[Dict[int, str]] = None,
    max_summary_chars: int = 0,
) -> str:
    """为邻居实体构造相连物品的描述文本，保留完整的三元组信息（h r t）。

    输出格式示例：
        Connected items (showing 3 of 12):
        - The Hobbit author J. R. R. Tolkien: ...
        - The Hobbit publisher George Allen & Unwin: ...

    其中 h 为相连实体（seed item），r 为关系，t 为当前实体（entity_data）。
    保持 KG 中三元组的原始顺序；若同一实体通过多个谓词相连，则分别列出。
    """
    if entity_id not in meta:
        return "(no connected item information available)"

    connected = meta[entity_id].get("connected_items", {})
    if not connected:
        return "(no connected item information available)"

    main_name = entity_display_name(entity_data)

    # 按 KG 三元组的原始顺序收集 (predicate, item_id)
    triples: List[tuple] = []
    for pred, item_ids in connected.items():
        for iid in item_ids:
            triples.append((pred, int(iid)))

    stored_total = len(triples)
    # 02c 的类别节点 meta 带有截断前的真实相连数量；其余实体回退到存储数量
    totals = meta[entity_id].get("connected_items_total")
    total = sum(totals.values()) if totals else stored_total

    parts = []
    for pred, iid in triples[:max_items]:
        desc = seed_descriptions.get(iid)
        if desc is not None:
            label = desc.get("label", "") or "(unknown)"
            summary = desc.get("long_abstract", "").strip()
            if not summary:
                summary = desc.get("description", "").strip()
        else:
            # 不在上游 descriptions 中：通常是 02c 引入的 dbo/dbc 类别节点，
            # 通过当前子划分的 entity_list + ontology 解析 label（无摘要可附）
            label = connected_class_label(iid, id_to_uri or {}, ontology)
            summary = ""
        rel_label = relation_label(pred, ontology)
        triple_str = f"[{label}] --[{rel_label}]--> [{main_name}]"
        item_text = f"- (KG Triples) {triple_str}"
        if summary:
            if max_summary_chars > 0 and len(summary) > max_summary_chars:
                # 在词边界截断，避免 prompt 超过 max_model_len（dbo/dbc 展示成员多）
                cut = summary[:max_summary_chars].rsplit(" ", 1)[0]
                summary = cut.rstrip(" ,;.") + " ..."
            item_text += f"\n  {summary}"
        parts.append(item_text)

    if not parts:
        return "(connected items have no usable descriptions)"

    header = f"Connected items (showing {len(parts)} of {total}):"
    if total > stored_total:
        header = (f"Connected items (showing {len(parts)} of {total} in total; "
                  f"only {stored_total} are stored locally):")
    return header + "\n" + "\n".join(parts)


def entity_display_name(entity_data: Dict) -> str:
    """获取实体的显示名称：优先 label，其次 name，再尝试从 URI 最后一段提取（下划线替换为空格）。"""
    name = entity_data.get("label", "") or entity_data.get("name", "")
    if name:
        return name

    uri = entity_data.get("uri", "")
    if uri:
        # 取 URI 最后一段路径，替换下划线为空格
        stem = uri.rstrip("/").split("/")[-1]
        # DBpedia URI 中常见的下划线标题格式
        stem = stem.replace("_", " ")
        if stem:
            return stem

    return "(unknown entity)"


def resolve_template_status(entity_data: Dict, template_statuses: Set[str]) -> str:
    """决定实体使用哪个 prompt 模板。

    no_info 实体按 prefix 分流：dbo/dbc 类别节点使用专属模板，
    其余 no_info 前缀（wd / yago 等）使用通用 no_info 模板；
    status 不在模板表中的回退到 mapped。
    """
    status = entity_data.get("status", "mapped")
    if status == "no_info":
        prefix = entity_data.get("prefix", "")
        if prefix in ("dbo", "dbc"):
            return prefix
    if status not in template_statuses:
        return "mapped"
    return status


def connected_class_label(entity_id: int, id_to_uri: Dict[int, str], ontology: Dict) -> str:
    """为不在 seed_descriptions 中的相连实体（02c 引入的类别节点）解析显示名。

    不局限于数据集 descriptions：dbo 类优先使用 ontology 的 class_labels，
    其余（dbc 等）用 URI stem 人性化；均无摘要可附。
    """
    uri = id_to_uri.get(entity_id, "")
    if not uri:
        return "(unknown)"
    short = shorten_uri(uri)
    label = ontology.get("class_labels", {}).get(short)
    if label:
        return label
    return short.split(":", 1)[-1].replace("_", " ")


def build_prompt(
    entity_data: Dict,
    prompt_cfg: Dict,
    ontology: Dict,
    dataset_name: str,
    label: str,
    connected_desc: str = "",
    inferred_types_desc: str = "",
) -> Dict[str, str]:
    """构造单个实体的 prompt（system + user）。"""
    templates = prompt_cfg["templates"]
    status = resolve_template_status(entity_data, set(templates.keys()))
    template = templates[status]

    name = entity_display_name(entity_data)
    uri = entity_data.get("uri", "")
    abstract = entity_data.get("long_abstract", "").strip()
    if not abstract:
        abstract = entity_data.get("description", "").strip()

    relations = format_relations(
        entity_data,
        ontology,
        prompt_cfg,
        dataset_name,
        label,
        max_relations=prompt_cfg.get("max_relations", 16),
    )

    user = template["user_template"].format(
        name=name,
        uri=uri or "(no URI)",
        abstract=abstract or "(no abstract available)",
        relations=relations,
        inferred_types=inferred_types_desc,
        connected_item_descriptions=connected_desc,
    )

    return {"system": prompt_cfg["system"], "user": user}


def build_prompts_for_dataset(
    dataset_name: str,
    label: str,
    config_path: str,
    mode: str,
    limit: int = 10,
    seed_datasets: Union[List[str], Iterable[str], None] = None,
    suffix: str = "",
) -> Dict[int, Dict[str, str]]:
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)
    if suffix:
        paths["prompts_json"] = paths["prompts_json"].replace(".json", f"{suffix}.json")

    ensure_dir(os.path.dirname(paths["prompts_json"]))
    logger = setup_logging(paths["prompts_log"])
    logger.info("\n" * 3 + "=" * 50)
    logger.info("[03 BUILD PROMPTS] dataset=%s/%s mode=%s",
                dataset_name, label, mode)

    template_path = resolve_prompt_config_path(config, config_path)
    prompt_cfg = load_prompt_config(config_path, template_path)
    logger.info("Loaded prompt config: %s", template_path)

    descriptions_path = paths["descriptions_json"]
    with open(descriptions_path, "r", encoding="utf-8") as f:
        descriptions = {int(k): v for k, v in json.load(f).items()}
    logger.info("Loaded descriptions: %d", len(descriptions))

    # 加载 ontology.json
    ontology_path = prompt_cfg.get("ontology_path", "output/ontology.json")
    if not os.path.isabs(ontology_path):
        ontology_path = os.path.join(os.path.dirname(config_path), ontology_path)
    ontology = load_ontology(ontology_path)
    logger.info("Loaded ontology: %d classes, %d properties",
                len(ontology.get("class_labels", {})),
                len(ontology.get("property_labels", {})))

    # 加载谓词 -> 兼容 dbo 类型的兜底推断表（与 02c 共用；缺失时仅用 property_range）
    role_type_map: Dict[str, str] = {}
    rtm_path = config.get("role_type_map")
    if rtm_path:
        if not os.path.isabs(rtm_path):
            rtm_path = os.path.join(os.path.dirname(config_path), rtm_path)
        if os.path.exists(rtm_path):
            with open(rtm_path, "r", encoding="utf-8") as f:
                role_type_map = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
            logger.info("Loaded role_type_map: %d entries from %s", len(role_type_map), rtm_path)

    # 加载邻居实体的元数据和种子物品描述（可选，支持单个或多个 seed 子划分）
    meta: Dict[int, Dict] = {}
    seed_descriptions: Dict[int, Dict] = {}
    seed_dataset_list = resolve_seed_datasets(config, dataset_name, label, seed_datasets)
    if seed_dataset_list:
        for seed_label in seed_dataset_list:
            seed_paths = get_dataset_paths(config, dataset_name, seed_label)
            seed_meta = load_kg_hop_meta(seed_paths)
            with open(seed_paths["descriptions_json"], "r", encoding="utf-8") as f:
                seed_desc = {int(k): v for k, v in json.load(f).items()}
            merge_meta(meta, seed_meta)
            seed_descriptions.update(seed_desc)
            logger.info("Loaded seed split '%s/%s': descriptions=%d, meta=%d",
                        dataset_name, seed_label, len(seed_desc), len(seed_meta))
        logger.info("Merged seed descriptions: %d, meta entries: %d",
                    len(seed_descriptions), len(meta))

    # 合并当前子划分自己的 kg_hop_meta（如 full：02c 引入的类别节点成员信息）
    own_meta = load_kg_hop_meta(paths)
    if own_meta:
        merge_meta(meta, own_meta)
        logger.info("Merged own kg_hop_meta: %d entries", len(own_meta))

    # 当前子划分的 entity_list（id -> uri）：为不在 seed_descriptions 中的相连实体
    #（02c 引入的类别节点）解析 label 用
    id_to_uri: Dict[int, str] = {}
    entity_list_path = paths.get("entity_list")
    if entity_list_path and os.path.exists(entity_list_path):
        with open(entity_list_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    id_to_uri[int(parts[0])] = parts[1].strip()
        logger.info("Loaded entity_list: %d entries", len(id_to_uri))

    # 为每个实体预计算基于 KG 关系的推断类型（仅在存在 seed meta 时才有意义）
    inferred_types_map: Dict[int, List[str]] = {}
    if meta:
        inferred_types_map = {
            eid: infer_types_from_relations(eid, meta, ontology, role_type_map)
            for eid in descriptions
        }

    # 按 templates 中存在的 status 对实体 ID 分组（no_info 按 prefix 分流，未知 status 归到 mapped）
    template_statuses = list(prompt_cfg["templates"].keys())
    template_status_set = set(template_statuses)
    status_groups: Dict[str, List[int]] = {s: [] for s in template_statuses}
    for eid, info in descriptions.items():
        status_groups[resolve_template_status(info, template_status_set)].append(eid)
    for status in template_statuses:
        logger.info("Status '%s': %d entities", status, len(status_groups[status]))

    # 相连实体的最大展示数量：可按 status 覆盖（类别节点需要更多成员样本归纳主题）
    connected_cfg = prompt_cfg.get("max_connected_items", {})
    # 相连实体摘要的截断长度（字符数，0=不截断）：dbo/dbc 展示成员多，防止 prompt 超长
    summary_chars_cfg = prompt_cfg.get("max_connected_summary_chars", {})

    def build_one_prompt(eid: int) -> Dict[str, str]:
        status = resolve_template_status(descriptions[eid], template_status_set)
        max_items = connected_cfg.get(status, connected_cfg.get("default", 3))
        max_summary_chars = summary_chars_cfg.get(status, summary_chars_cfg.get("default", 0))
        connected_desc = build_connected_descriptions(
            eid, descriptions[eid], meta, seed_descriptions, ontology,
            max_items=max_items, id_to_uri=id_to_uri,
            max_summary_chars=max_summary_chars,
        ) if meta else "(no connected item information available)"
        inferred_types_desc = format_inferred_types(inferred_types_map.get(eid, []))
        return build_prompt(
            descriptions[eid],
            prompt_cfg,
            ontology,
            dataset_name,
            label,
            connected_desc,
            inferred_types_desc,
        )

    if mode == "full":
        target_eids = sorted(descriptions.keys())
        prompts: Dict[int, Dict[str, str]] = {}
        for i, eid in enumerate(target_eids):
            prompts[eid] = build_one_prompt(eid)
            if (i + 1) % 500 == 0 or (i + 1) == len(target_eids):
                logger.info("Built %d/%d prompts", i + 1, len(target_eids))
        output_path = paths["prompts_json"]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in prompts.items()}, f, ensure_ascii=False, indent=2)
        logger.info("Saved prompts aggregate to %s", output_path)
        return prompts

    # debug 模式：为每个 status 分别采样 limit 个并输出
    base_dir = os.path.dirname(paths["prompts_json"])
    base_name = os.path.basename(paths["prompts_json"])  # prompts.json
    stem = base_name.replace(".json", "")
    for status in template_statuses:
        group_eids = sorted(status_groups.get(status, []))[:limit]
        prompts = {}
        for eid in group_eids:
            prompts[eid] = build_one_prompt(eid)
        output_path = os.path.join(base_dir, f"{stem}_{status}.debug.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in prompts.items()}, f, ensure_ascii=False, indent=2)
        logger.info("Debug: saved %d '%s' prompts to %s", len(prompts), status, output_path)

    return None


def main():
    parser = argparse.ArgumentParser(description="Build LLM prompts from descriptions using a unified prompt config file.")
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--mode", type=str, choices=["debug", "full"], default="debug",
                        help="debug=只处理前 N 个实体，full=全量")
    parser.add_argument("--limit", type=int, default=10,
                        help="debug 模式下每个 status 采样的实体数量")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--suffix", type=str, default="",
                        help="输出 prompts 文件名后缀（如 _catfreq2 -> prompts_catfreq2.json）")
    args = parser.parse_args()

    build_prompts_for_dataset(
        args.dataset,
        args.label,
        args.config,
        args.mode,
        args.limit,
        suffix=args.suffix,
    )


if __name__ == "__main__":
    # python 03_build_prompts.py --dataset dbbook2014-mine --label main --mode debug
    # python 03_build_prompts.py --dataset dbbook2014-mine --label one-hop --mode debug
    # python 03_build_prompts.py --dataset dbbook2014-mine --label full --mode debug
    main()
