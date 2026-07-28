"""
concat_catfreq_prompts.py

把多个 min_cat_freq 版本的 prompts_catfreq{N}.json 去重拼接为一份 prompts.json，
并写出拆分记录 prompts_catfreq_split.json；04 在云端跑完后，用 --split 把
llm_outputs.json 拆回各版本的 llm_outputs_catfreq{N}.json（键还原为原始 entity_id）。

去重原理：4 个版本中 main + one-hop 实体（ID 0-7339）与 dbo 类节点的 prompt 完全
相同（dbo 节点的实体 ID 随版本变化，但内容一致），只保留一份：
    共享实体（0-7339）：键 = 原始 entity_id 字符串
    dbo 类节点：        键 = 短 URI（如 "dbo:Book"），拆分记录中存有各版本的 ID 映射
    dbc 类别节点：      键 = catfreq{N}_{entity_id}（各版本独有）

执行位置：项目根目录（data_preprocess/）
用法：
    拼接：python output/concat_catfreq_prompts.py --dataset dbbook2014-mine --label full
    拆分 llm_outputs：python output/concat_catfreq_prompts.py --dataset dbbook2014-mine --label full --split
    拆分 embeddings：python output/concat_catfreq_prompts.py --dataset dbbook2014-mine --label full --split_embeddings
      （在拼接版 llm_outputs 上跑一次 05 后使用；依赖 05 输出的 entity_embeddings_row_map.dat，
       输出行与该版本实体 ID 对齐，等效于逐版本跑 05）
"""
import os
import json
import argparse
from typing import Dict

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_config, get_dataset_paths, shorten_uri

FREQS = [2, 3, 4, 5]
DBO_URI_PREFIX = "http://dbpedia.org/ontology/"


def load_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_entity_list(path: str) -> Dict[int, str]:
    id_to_uri = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                id_to_uri[int(parts[0])] = parts[1].strip()
    return id_to_uri


def concat(prompts_dir: str, kg_base: str):
    # 各版本的 prompts 与 KG 快照（full_entities.dat）
    prompts_by_freq = {}
    entities_by_freq = {}
    for n in FREQS:
        prompts_by_freq[n] = load_json(os.path.join(prompts_dir, f"prompts_catfreq{n}.json"))
        entities_by_freq[n] = load_entity_list(
            os.path.join(kg_base, f"catfreq{n}", "full_entities.dat"))

    ref = FREQS[0]
    ref_entities = entities_by_freq[ref]
    # 共享实体 = 非 dbo/dbc 节点（ID 连续，0 到第一个类别节点之前）
    first_class_id = min(
        eid for eid, uri in ref_entities.items()
        if uri.startswith(DBO_URI_PREFIX) or "/resource/Category:" in uri
    )

    merged = {}
    # 1. 共享实体：键 = 原始 entity_id
    for eid in range(first_class_id):
        key = str(eid)
        prompt = prompts_by_freq[ref][key]
        for n in FREQS[1:]:
            if prompts_by_freq[n].get(key) != prompt:
                print(f"WARNING: 共享实体 {key} 的 prompt 在 catfreq{n} 中不一致，仍采用 catfreq{ref} 版本")
        merged[key] = prompt
    n_shared = len(merged)

    # 2. dbo 类节点：键 = 短 URI；记录各版本的 ID 映射
    dbo_map_by_freq: Dict[int, Dict[str, int]] = {}
    for n in FREQS:
        dbo_map = {}
        for eid, uri in entities_by_freq[n].items():
            if uri.startswith(DBO_URI_PREFIX):
                short = shorten_uri(uri)
                dbo_map[short] = eid
                prompt = prompts_by_freq[n][str(eid)]
                if short in merged and merged[short] != prompt:
                    print(f"WARNING: dbo 节点 {short} 的 prompt 在 catfreq{n} 中不一致，仍采用首次出现版本")
                merged.setdefault(short, prompt)
        dbo_map_by_freq[n] = dbo_map
    n_dbo = len(merged) - n_shared

    # 3. dbc 类别节点：键 = catfreq{N}_{entity_id}（各版本独有）
    n_dbc = 0
    for n in FREQS:
        for eid, uri in entities_by_freq[n].items():
            if "/resource/Category:" in uri:
                merged[f"catfreq{n}_{eid}"] = prompts_by_freq[n][str(eid)]
                n_dbc += 1

    out_path = os.path.join(prompts_dir, "prompts.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    record = {
        "key_format": {
            "shared": "{entity_id}（0 到第一个类别节点之前，各版本 prompt 完全相同）",
            "dbo": "dbo:{ClassName}（各版本内容相同；dbo_id_map 记录各版本的实体 ID）",
            "dbc": "catfreq{N}_{entity_id}（各版本独有）",
        },
        "split_instructions": (
            "04 跑完后执行 --split：shared 键直接复制到各版本；dbo 键按 dbo_id_map "
            "还原为各版本实体 ID；catfreq{N}_ 前缀键还原为原始 entity_id。"
            "之后对每个版本单独跑 05；KG 与 n_entities 必须选对应版本（KG 快照在 kg/catfreq{N}/）。"
        ),
        "versions": {},
    }
    for n in FREQS:
        record["versions"][f"catfreq{n}"] = {
            "min_cat_freq": n,
            "n_entities": len(entities_by_freq[n]),
            "n_dbc_nodes": sum(1 for uri in entities_by_freq[n].values() if "/resource/Category:" in uri),
            "kg_snapshot": os.path.join(kg_base, f"catfreq{n}"),
            "dbo_id_map": dbo_map_by_freq[n],
        }
    record_path = os.path.join(prompts_dir, "prompts_catfreq_split.json")
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print(f"shared: {n_shared}, dbo: {n_dbo}, dbc: {n_dbc}, total: {len(merged)}")
    print(f"Merged -> {out_path}")
    print(f"Split record -> {record_path}")


def split(prompts_dir: str, llm_dir: str):
    record = load_json(os.path.join(prompts_dir, "prompts_catfreq_split.json"))
    outputs = load_json(os.path.join(llm_dir, "llm_outputs.json"))

    shared_keys = [k for k in outputs if k.isdigit()]
    for version, info in record["versions"].items():
        n = version.replace("catfreq", "")
        prefix = f"catfreq{n}_"
        part = {k: outputs[k] for k in shared_keys}
        for short, eid in info["dbo_id_map"].items():
            if short in outputs:
                part[str(eid)] = outputs[short]
        for k, v in outputs.items():
            if k.startswith(prefix):
                part[k[len(prefix):]] = v
        out_path = os.path.join(llm_dir, f"llm_outputs_{version}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(part, f, ensure_ascii=False, indent=2)
        expected = info["n_entities"]
        status = "OK" if len(part) == expected else f"MISMATCH (expected {expected})"
        print(f"{version}: {len(part)} outputs -> {out_path} [{status}]")

    n_used = len(shared_keys) + sum(
        len(v["dbo_id_map"]) + v["n_dbc_nodes"] for v in record["versions"].values())
    if n_used < len(outputs):
        print(f"WARNING: {len(outputs) - n_used} 个输出键未被任何版本使用")


def split_embeddings(prompts_dir: str, embeddings_dir: str):
    """把拼接版 entity_embeddings.npy 按拆分记录拆回各版本（输出行 = 该版本实体 ID）。

    依赖 05 在拼接模式下输出的 entity_embeddings_row_map.dat（key -> npy 行号）。
    共享键直接按数字 ID 放置；dbo 键按 dbo_id_map 放置；catfreq{N}_ 前缀键去前缀放置。
    """
    import numpy as np
    record = load_json(os.path.join(prompts_dir, "prompts_catfreq_split.json"))

    key_to_row = {}
    row_map_path = os.path.join(embeddings_dir, "entity_embeddings_row_map.dat")
    with open(row_map_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, row = line.split("\t")
            key_to_row[key] = int(row)

    for npy_name, out_tag in [("entity_embeddings.npy", ""), ("entity_embeddings_no_l2.npy", "_no_l2")]:
        npy_path = os.path.join(embeddings_dir, npy_name)
        if not os.path.exists(npy_path):
            continue
        emb = np.load(npy_path)
        print(f"Loaded {npy_path}: shape={emb.shape}")
        for version, info in record["versions"].items():
            n = version.replace("catfreq", "")
            prefix = f"catfreq{n}_"
            rows = np.zeros((info["n_entities"], emb.shape[1]), dtype=emb.dtype)
            covered = 0
            for key, row in key_to_row.items():
                if key.isdigit():
                    rows[int(key)] = emb[row]
                    covered += 1
                elif key in info["dbo_id_map"]:
                    rows[info["dbo_id_map"][key]] = emb[row]
                    covered += 1
                elif key.startswith(prefix):
                    rows[int(key[len(prefix):])] = emb[row]
                    covered += 1
            out_path = os.path.join(embeddings_dir, f"entity_embeddings_{version}{out_tag}.npy")
            np.save(out_path, rows)
            expected = info["n_entities"]
            status = "OK" if covered == expected else f"MISMATCH (expected {expected})"
            print(f"  {version}: {covered} rows [{status}] -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True)
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--split", action="store_true",
                        help="拆分模式：把 llm_outputs.json 按拆分记录拆回各版本")
    parser.add_argument("--split_embeddings", action="store_true",
                        help="拆分模式：把拼接版 entity_embeddings.npy 按拆分记录拆回各版本")
    args = parser.parse_args()

    config = load_config(args.config)
    paths = get_dataset_paths(config, args.dataset, args.label)

    if args.split:
        split(paths["prompts_dir"], paths["llm_outputs_dir"])
    elif args.split_embeddings:
        split_embeddings(paths["prompts_dir"], paths["embeddings_dir"])
    else:
        kg_base = os.path.dirname(paths["kg_hop_entities"])
        concat(paths["prompts_dir"], kg_base)


if __name__ == "__main__":
    main()
