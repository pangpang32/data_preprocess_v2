#!/usr/bin/env python3
"""
05_vectorize.py

使用 sentence-transformers（SimCSE）把 04 生成的 summary 文本批量编码成向量。

输入：
    output/{dataset}/04_llm_output/llm_outputs.json

输出：
    output/{dataset}/05_embeddings/entity_embeddings.npy        # L2 归一化嵌入 [n_entities, dim]
    output/{dataset}/05_embeddings/entity_embeddings_no_l2.npy  # 未归一化嵌入 [n_entities, dim]
"""
import os
import json
import torch
import argparse
from typing import Dict, List, Tuple
import numpy as np
from sentence_transformers import SentenceTransformer
from utils import load_config, get_dataset_paths, ensure_dir, setup_logging


def build_texts(outputs: Dict[str, Dict], use_field: str = "summary") -> Tuple[List[Tuple[int, str]], List[str]]:
    """从每个实体输出中提取用于向量化的文本。

    返回 (items, ordered_keys)：items 为 (row_id, text)。
    键全部为纯数字时按 entity_id 排序（旧行为）；存在非数字键（catfreq 拼接版）
    时按 JSON 插入顺序分配行号，调用方应把 ordered_keys 写成行号映射文件。
    """
    all_int = all(k.isdigit() for k in outputs)
    items = []
    ordered_keys = []
    for row, (eid_str, v) in enumerate(outputs.items()):
        text = v.get(use_field, "").strip()
        if not text:
            # fallback 到 raw
            text = v.get("raw", "").strip()
        if not text:
            text = "(no text available)"
        items.append((int(eid_str) if all_int else row, text))
        ordered_keys.append(eid_str)
    if all_int:
        # 按 entity_id 排序，保证输出顺序稳定
        items.sort(key=lambda x: x[0])
        ordered_keys = [str(eid) for eid, _ in items]
    return items, ordered_keys


def vectorize_dataset(
    dataset_name: str,
    label: str,
    config_path: str,
    mode: str,
    limit: int,
    use_field: str,
    llm_outputs: str = None,
    suffix: str = "",
):
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)
    vec_cfg = config["defaults"]["vectorizer"]

    ensure_dir(paths["embeddings_dir"])
    logger = setup_logging(paths["embeddings_log"])
    logger.info("\n" * 3 + "=" * 50)
    logger.info("[05 VECTORIZE] dataset=%s/%s mode=%s model=%s suffix=%s",
                dataset_name, label, mode, vec_cfg["model_name"], suffix)

    if llm_outputs:
        outputs_path = llm_outputs
    else:
        # 默认读取带相同后缀的上游（04）输出
        outputs_path = paths["llm_outputs_json"].replace(".json", f"{suffix}.json")
    with open(outputs_path, "r", encoding="utf-8") as f:
        outputs = json.load(f)
    logger.info("Loaded %d LLM outputs from %s", len(outputs), outputs_path)

    items, ordered_keys = build_texts(outputs, use_field=use_field)
    if mode == "debug":
        items = items[:limit]
        logger.info("Debug mode: processing first %d entities", len(items))

    entity_ids = [eid for eid, _ in items]
    texts = [text for _, text in items]

    logger.info("Loading embedding model: %s", vec_cfg["model_name"])
    
    device = vec_cfg.get("device", "auto")
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Auto-selected device: %s", device)

    model = SentenceTransformer(vec_cfg["model_name"], device=device)

    # 限制最大输入长度
    max_length = vec_cfg.get("max_length")
    if max_length:
        model.max_seq_length = max_length

    logger.info("Encoding %d texts (max_length=%s)", len(texts), max_length)
    # 先以未归一化方式编码，再手动生成 L2 归一化版本，一次运行得到两种嵌入
    embeddings_no_l2 = model.encode(
        texts,
        batch_size=vec_cfg.get("batch_size", 64),
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=False,
    )
    logger.info("Embeddings shape: %s", embeddings_no_l2.shape)

    # L2 归一化版本
    norms = np.linalg.norm(embeddings_no_l2, axis=1, keepdims=True)
    # 防止除零
    norms = np.where(norms == 0, 1.0, norms)
    embeddings_l2 = embeddings_no_l2 / norms

    embeddings_npy = paths["embeddings_npy"].replace(".npy", f"{suffix}.npy")
    embeddings_no_l2_npy = paths["embeddings_no_l2_npy"].replace(".npy", f"{suffix}.npy")
    np.save(embeddings_npy, embeddings_l2)
    logger.info("Saved L2-normalized embeddings -> %s", embeddings_npy)

    np.save(embeddings_no_l2_npy, embeddings_no_l2)
    logger.info("Saved non-L2 embeddings -> %s", embeddings_no_l2_npy)

    # 拼接版（含 catfreq 前缀 / dbo 类键）时输出行号映射（key -> npy 行号），
    # 供 output/concat_catfreq_prompts.py --split_embeddings 拆回各版本
    if mode != "debug" and any(not k.isdigit() for k in ordered_keys):
        row_map_path = os.path.join(paths["embeddings_dir"], f"entity_embeddings{suffix}_row_map.dat")
        with open(row_map_path, "w", encoding="utf-8") as f:
            f.write("# key\trow_id\n")
            for row, key in enumerate(ordered_keys):
                f.write(f"{key}\t{row}\n")
        logger.info("Saved row map -> %s", row_map_path)


def main():
    parser = argparse.ArgumentParser(description="Encode entity summaries into embeddings with SimCSE.")
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--mode", type=str, choices=["debug", "full"], default="debug")
    parser.add_argument("--limit", type=int, default=10,
                        help="debug 模式处理的实体数量")
    parser.add_argument("--use_field", type=str, default="summary",
                        help="使用 llm_outputs.json 中的哪个字段，默认 summary")
    parser.add_argument("--llm_outputs", type=str, default=None,
                        help="覆盖默认的 llm_outputs.json 路径（如拆分后的 llm_outputs_catfreq2.json）")
    parser.add_argument("--suffix", type=str, default="",
                        help="输出 npy 文件名后缀（如 _catfreq2），用于多版本区分")
    args = parser.parse_args()

    vectorize_dataset(
        args.dataset,
        args.label,
        args.config,
        args.mode,
        args.limit,
        args.use_field,
        args.llm_outputs,
        args.suffix,
    )


if __name__ == "__main__":
    # python 05_vectorize.py --dataset dbbook2014-mine --label main --mode debug --limit 10
    # python 05_vectorize.py --dataset dbbook2014-mine --label one-hop --mode full
    # python 05_vectorize.py --dataset dbbook2014-mine --label full --mode full
    main()
