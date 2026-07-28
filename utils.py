"""公共工具函数。"""
import os
import logging
import yaml
import pickle
import urllib.parse
from typing import List, Union, Iterable, Dict, Any, Tuple, Optional
from rdflib import Graph


# ------------------------------------------------------------------
# URI 前缀映射与 shorten / expand 工具
# ------------------------------------------------------------------

NAMESPACE_MAP = {
    "http://dbpedia.org/resource/": "dbr:",
    "http://dbpedia.org/ontology/": "dbo:",
    "http://dbpedia.org/property/": "dbp:",
    "http://dbpedia.org/class/yago/": "yago:",
    "http://dbpedia.org/resource/Category:": "dbc:",
    "http://dbpedia.org/class/": "dbpc:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
    "http://xmlns.com/foaf/0.1/": "foaf:",
    "http://purl.org/dc/elements/1.1/": "dc:",
    "http://purl.org/dc/terms/": "dcterms:",
    "http://purl.org/ontology/bibo/": "bibo:",
    "http://schema.org/": "schema:",
    "http://umbel.org/umbel/rc/": "umbel:",
    "http://vocab.org/frbr/core#": "frbr:",
    "http://www.wikidata.org/entity/": "wd:",
    "http://www.w3.org/2002/07/owl#": "owl:",
    "http://www.ontologydesignpatterns.org/ont/d0.owl#": "d0:",
    "http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#": "dul:",
    "http://www.w3.org/2003/01/geo/wgs84_pos#": "geo:",
}

KNOWN_PREFIXES = set(NAMESPACE_MAP.keys())

# 反向映射：缩短前缀 -> 完整前缀
EXPAND_MAP = {v: k for k, v in NAMESPACE_MAP.items()}

# 预排序的命名空间列表：长前缀优先，避免 dbr 吞掉 dbc
_SORTED_NAMESPACE_ITEMS = sorted(NAMESPACE_MAP.items(), key=lambda x: -len(x[0]))

# 这些前缀代表 DBpedia 中通常不会有 label/abstract 等描述的实体
# （本体类、分类、YAGO 类、书目本体等）
NO_INFO_PREFIXES = {
    "dbc",      # Wikipedia category
    "yago",     # YAGO class
    "dbo",      # DBpedia ontology class
    "dbpc",     # DBpedia class
    "owl",      # OWL class
    "schema",   # Schema.org term
    "wd",       # Wikidata entity
    "umbel",    # UMBEL class
    "frbr",     # FRBR term
    "d0",       # Ontology Design Patterns
    "dul",      # DOLCE+DnS Ultralite
    "geo",      # WGS84 geo
    "bibo",     # Bibliographic ontology
}


# ------------------------------------------------------------------
# KG 构建外部表（02c 使用）：dbc 类别黑名单
# ------------------------------------------------------------------

# dbc 类别黑名单：维基百科维护/行政类类别，对推荐无语义区分度。
# "*" 后缀表示前缀匹配；与频次阈值配合使用（02c），跨数据集通用。
CATEGORY_BLACKLIST = [
    "dbc:Living_people",
    "dbc:*_births",
    "dbc:*_deaths",
    "dbc:Year_of_birth_missing*",
    "dbc:Year_of_death_missing*",
    "dbc:Place_of_birth_missing*",
]


def shorten_uri(uri: str) -> str:
    """缩短 URI 为带前缀的形式。"""
    for full, short in _SORTED_NAMESPACE_ITEMS:
        if uri.startswith(full):
            return short + uri[len(full):]
    return uri


def expand_uri(short_uri: str) -> str:
    """把缩短后的 URI 还原为完整 URI。无法识别则原样返回。"""
    if ":" in short_uri:
        prefix, name = short_uri.split(":", 1)
        prefix_key = prefix + ":"
        if prefix_key in EXPAND_MAP:
            return EXPAND_MAP[prefix_key] + name
    return short_uri


def is_known_uri(uri: str) -> bool:
    """判断 URI 是否属于已知命名空间。"""
    return any(uri.startswith(p) for p in KNOWN_PREFIXES)


# ------------------------------------------------------------------
# 索引与 TTL 行解析工具（01 / 01a / 01b 通用）
# ------------------------------------------------------------------

def load_index(index_path: str) -> Dict[str, List[int]]:
    """加载 Pickle 格式的 subject 索引，key 做 URL decode 归一化。"""
    with open(index_path, "rb") as f:
        raw = pickle.load(f)
    return {urllib.parse.unquote(k): v for k, v in raw.items()}


def read_line_at_offset(filepath: str, offset: int) -> str:
    """按字节偏移读取文件中一行。"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        return f.readline().strip()


def parse_ttl_line(line: str) -> Optional[Tuple[Any, Any, Any]]:
    """用 rdflib 解析单行 TTL，返回 (s, p, o) 或 None。"""
    g = Graph()
    try:
        g.parse(data=line, format="turtle")
    except Exception:
        return None
    for s, p, o in g:
        return s, p, o
    return None


# ------------------------------------------------------------------
# 基础工具
# ------------------------------------------------------------------

def load_config(config_path: str = "config.yaml") -> Dict:
    """加载 YAML 配置。"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(log_path: str, level: int = logging.INFO) -> logging.Logger:
    """初始化日志，写入文件并输出到控制台。"""
    ensure_dir(os.path.dirname(log_path))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger()


def ensure_dir(paths: Union[str, Iterable[str], Dict[Any, str]]) -> None:
    """确保目录存在。支持单个路径字符串、路径列表/元组、或路径字典。"""
    if isinstance(paths, str):
        if paths:
            os.makedirs(paths, exist_ok=True)
    elif isinstance(paths, dict):
        for path in paths.values():
            if isinstance(path, str) and path:
                os.makedirs(path, exist_ok=True)
    else:
        # 列表、元组、集合等可迭代对象
        for path in paths:
            if isinstance(path, str) and path:
                os.makedirs(path, exist_ok=True)


# ------------------------------------------------------------------
# MINE 格式读取（去重后的 entity_id -> uri）
# ------------------------------------------------------------------

def read_mine_entity_mapping(e2kge_path: str) -> List[Dict[str, Any]]:
    """
    读取 MINE 去重后的 entity 映射。

    输入：
        e2kge_path:  entity_id \t entity_uri

    返回：
        [{
            "entity_id": int,     # 去重后的 entity 编号
            "uri": str,           # entity URI
            "has_uri": bool,
        }, ...]
    """
    entities = []
    with open(e2kge_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            eid = int(parts[0])
            uri = urllib.parse.unquote(parts[1].strip())
            is_uri = uri.startswith("http://") or uri.startswith("https://")
            has_uri = bool(uri) and uri.lower() != "none" and is_uri and eid != -1
            entities.append({
                "entity_id": eid,
                "uri": uri,
                "has_uri": has_uri,
            })
    return entities


# ------------------------------------------------------------------
# 路径管理
# ------------------------------------------------------------------

def get_dataset_paths(config: Dict, dataset_name: str, label: str) -> Dict[str, Any]:
    """根据配置生成某个数据集（dataset_name）下某个子划分（label，如 main/one-hop/full）需要的所有路径。"""
    ds = config["datasets"][dataset_name][label]
    base = ds["base_dir"]
    out_base = os.path.join(config["output_base"], dataset_name, label)
    dbpedia = config["dbpedia"]

    crawl_dir = os.path.join(out_base, "01_crawl")
    kg_build_dir = os.path.join(out_base, "02_kg_build")
    prompts_dir = os.path.join(out_base, "03_prompts")
    llm_outputs_dir = os.path.join(out_base, "04_llm_output")
    embeddings_dir = os.path.join(out_base, "05_embeddings")

    paths = {
        "entity_list": os.path.join(base, ds["entity_list"]),
        "out_base": out_base,

        "crawl_dir": crawl_dir,
        "crawl_log": os.path.join(crawl_dir, "crawl.log"),
        "problem_entities_b": os.path.join(crawl_dir, "problem_entities_b.dat"),
        "descriptions_a": os.path.join(crawl_dir, "descriptions_a.json"),
        "descriptions_b": os.path.join(crawl_dir, "descriptions_b.json"),
        "descriptions_json": os.path.join(crawl_dir, "descriptions.json"),

        "kg_build_dir": kg_build_dir,
        "kg_build_log": os.path.join(kg_build_dir, "extract_kg_one_hop.log"),

        "prompts_dir": prompts_dir,
        "prompts_json": os.path.join(prompts_dir, "prompts.json"),
        "prompts_log": os.path.join(prompts_dir, "build_prompts.log"),
        
        "llm_outputs_dir": llm_outputs_dir,
        "llm_outputs_json": os.path.join(llm_outputs_dir, "llm_outputs.json"),
        "llm_log": os.path.join(llm_outputs_dir, "generate_llm.log"),

        "embeddings_dir": embeddings_dir,
        "embeddings_npy": os.path.join(embeddings_dir, "entity_embeddings.npy"),
        "embeddings_no_l2_npy": os.path.join(embeddings_dir, "entity_embeddings_no_l2.npy"),
        "embeddings_log": os.path.join(embeddings_dir, "vectorize.log"),
        
        "dbpedia_dump_dir": dbpedia["dump_dir"],
        "dbpedia_idx_dir": dbpedia["idx_dir"],
    }

    if "relation_list" in ds:
        paths["relation_list"] = os.path.join(base, ds["relation_list"])
        paths["kg_r_map"] = os.path.join(base, ds["relation_list"])
    if "kg_hop_triples" in ds:
        paths["kg_hop_triples"] = os.path.join(base, ds["kg_hop_triples"])
    if "kg_hop_entities" in ds:
        paths["kg_hop_entities"] = os.path.join(base, ds["kg_hop_entities"])
    if "kg_hop_meta" in ds:
        paths["kg_hop_meta"] = os.path.join(base, ds["kg_hop_meta"])
    if "n_entities" in ds:
        paths["n_entities"] = ds["n_entities"]
    if "n_original_entities" in ds:
        paths["n_original_entities"] = ds["n_original_entities"]
    if "expand_map" in ds:
        paths["expand_map"] = os.path.join(base, ds["expand_map"])

    # item_list 可选（MINE 格式）
    if "item_list" in ds:
        paths["item_list"] = os.path.join(base, ds["item_list"])

    # KG 边抽取相关配置（可选）
    if "kg_files" in ds:
        kg_files = ds["kg_files"]
        if isinstance(kg_files, str):
            kg_files = [kg_files]
        paths["kg_files"] = [os.path.join(base, p) for p in kg_files]
    if "kg_format" in ds:
        paths["kg_format"] = ds["kg_format"]

    return paths
