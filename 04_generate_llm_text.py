#!/usr/bin/env python3
"""
04_generate_llm_text.py

使用 vLLM 为 03 生成的 prompt 批量生成文本，并解析出 SUMMARY / ATTRIBUTIVE。

输入：
    full 模式：output/{dataset}/03_prompts/prompts.json
    debug 模式：output/{dataset}/03_prompts/prompts_{status}.debug.json

输出：
    full 模式：output/{dataset}/04_llm_output/llm_outputs.json
    debug 模式：output/{dataset}/04_llm_output/llm_outputs_{status}.debug.json

云端运行示例：
    python 04_generate_llm_text.py --dataset dbbook2014-mine-main --mode full
"""
import os
import json
import re
import argparse
from typing import Dict, List, Tuple

# vLLM 仅在云端 GPU 环境可用；本地不做运行时检查，py_compile 仍可过语法
from vllm import LLM, SamplingParams

from utils import load_config, get_dataset_paths, ensure_dir, setup_logging


def load_prompts(paths: Dict, mode: str, logger):
    """加载 prompts。

    full 模式：加载 prompts.json，返回 {eid: prompt}。
    debug 模式：加载 03 生成的 prompts_{status}.debug.json，返回 {status: {eid: prompt}}。
    """
    base_path = paths["prompts_json"]
    if mode != "debug":
        with open(base_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Loaded full prompts: %d", len(data))
        return data

    # debug 模式：扫描所有 prompts_{status}.debug.json
    base_dir = os.path.dirname(base_path)
    base_name = os.path.basename(base_path)
    stem = base_name.replace(".json", "")
    debug_prompts = {}
    if os.path.isdir(base_dir):
        for fname in sorted(os.listdir(base_dir)):
            if fname.startswith(f"{stem}_") and fname.endswith(".debug.json"):
                status = fname[len(stem) + 1:-len(".debug.json")]
                fpath = os.path.join(base_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                debug_prompts[status] = data
                logger.info("Loaded debug prompts [%s]: %d entries from %s",
                            status, len(data), fpath)
                if len(data) == 0:
                    logger.warning("Debug prompt file is empty: %s", fpath)
    return debug_prompts


def format_chat_prompt(system: str, user: str, tokenizer) -> str:
    """使用模型的 chat template 把 system + user 拼成单条生成 prompt。"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )


def parse_generated_text(text: str) -> Tuple[str, str, str]:
    """解析输出中的 SUMMARY 和 ATTRIBUTIVE；解析失败则返回原文。"""
    raw = text.strip()

    # 使用宽松正则匹配 <<<TAG>>>，允许 TAG 前后有空格
    summary_pat = re.compile(
        r"<<<\s*SUMMARY\s*>>>\s*\n(.*?)(?=\n\s*<<<\s*\w+\s*>>>|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    attr_pat = re.compile(
        r"<<<\s*ATTRIBUTIVE\s*>>>\s*\n(.*?)(?=\n\s*<<<\s*\w+\s*>>>|\Z)",
        re.DOTALL | re.IGNORECASE,
    )

    summary_match = summary_pat.search(raw)
    attr_match = attr_pat.search(raw)

    summary = summary_match.group(1).strip() if summary_match else raw
    attributive = attr_match.group(1).strip() if attr_match else ""

    return raw, summary, attributive


def build_vllm_kwargs(llm_cfg: Dict) -> Dict:
    """从 config 构造 vLLM.LLM 的初始化参数。"""
    kwargs = {
        "model": llm_cfg["model_name"],
        "tensor_parallel_size": llm_cfg.get("tensor_parallel_size", 1),
        "gpu_memory_utilization": llm_cfg.get("gpu_memory_utilization", 0.85),
        "dtype": llm_cfg.get("dtype", "auto"),
    }

    if "max_model_len" in llm_cfg and llm_cfg["max_model_len"] is not None:
        kwargs["max_model_len"] = llm_cfg["max_model_len"]
    if "trust_remote_code" in llm_cfg:
        kwargs["trust_remote_code"] = llm_cfg["trust_remote_code"]
    if "quantization" in llm_cfg and llm_cfg["quantization"] is not None:
        kwargs["quantization"] = llm_cfg["quantization"]

    return kwargs


def generate_texts(
    dataset_name: str,
    label: str,
    config_path: str,
    mode: str,
    batch_size: int,
    resume: bool,
    suffix: str = "",
):
    config = load_config(config_path)
    paths = get_dataset_paths(config, dataset_name, label)
    if suffix:
        # 输入（03 的 prompts）与输出（llm_outputs）同步带后缀
        paths["prompts_json"] = paths["prompts_json"].replace(".json", f"{suffix}.json")
        paths["llm_outputs_json"] = paths["llm_outputs_json"].replace(".json", f"{suffix}.json")
    llm_cfg = config["defaults"]["llm"]

    ensure_dir(os.path.dirname(paths["llm_outputs_json"]))
    logger = setup_logging(paths["llm_log"])
    logger.info("\n" * 3 + "=" * 50)
    logger.info("[04 GENERATE LLM TEXT] dataset=%s/%s mode=%s", dataset_name, label, mode)

    prompts_raw = load_prompts(paths, mode, logger)

    if mode == "debug":
        # prompts_raw: {status: {eid: prompt}}
        if not prompts_raw:
            logger.info("No debug prompts found. Exiting.")
            return
        # 合并所有 status 的 prompts，同时记录每个 eid 属于哪个 status
        merged_prompts: Dict[str, Dict[str, str]] = {}
        eid_to_status: Dict[str, str] = {}
        for status, ps in prompts_raw.items():
            for eid, p in ps.items():
                eid_str = str(eid)
                merged_prompts[eid_str] = p
                eid_to_status[eid_str] = status
        logger.info("Loaded %d debug status groups, total %d prompts",
                    len(prompts_raw), len(merged_prompts))
        target_prompts = merged_prompts
    else:
        # prompts_raw: {eid: prompt}
        target_prompts = {str(k): v for k, v in prompts_raw.items()}
        logger.info("Loaded %d prompts", len(target_prompts))

    # resume：已存在的输出直接跳过
    # debug 模式从各 status 的 debug 输出文件中恢复；full 模式从 llm_outputs.json 恢复
    existing = {}
    if resume:
        if mode == "debug":
            base_dir = os.path.dirname(paths["llm_outputs_json"])
            base_name = os.path.basename(paths["llm_outputs_json"])
            stem = base_name.replace(".json", "")
            if os.path.isdir(base_dir):
                for fname in os.listdir(base_dir):
                    if fname.startswith(f"{stem}_") and fname.endswith(".debug.json"):
                        fpath = os.path.join(base_dir, fname)
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        existing.update(data)
                        logger.info("Resume: loaded %d existing entries from %s",
                                    len(data), fpath)
        elif os.path.exists(paths["llm_outputs_json"]):
            with open(paths["llm_outputs_json"], "r", encoding="utf-8") as f:
                existing = json.load(f)
            logger.info("Resume: found %d existing outputs", len(existing))

    # 丢弃空输出（vLLM 因超长中止请求时会产生 raw/summary 全空的条目），
    # 让它们在 resume 时自动重新生成，无需手工删键
    if existing:
        n_empty = sum(1 for v in existing.values()
                      if not v.get("summary", "").strip() and not v.get("raw", "").strip())
        if n_empty:
            existing = {k: v for k, v in existing.items()
                        if v.get("summary", "").strip() or v.get("raw", "").strip()}
            logger.warning("Resume: %d empty outputs will be regenerated", n_empty)

    # 过滤已处理的 entity_id
    todo_ids = [eid for eid in target_prompts.keys() if str(eid) not in existing]
    logger.info("Entities to generate: %d", len(todo_ids))

    if not todo_ids:
        logger.info("Nothing to generate. Exiting.")
        return

    # 初始化 vLLM
    logger.info("Initializing vLLM with model: %s", llm_cfg["model_name"])
    llm = LLM(**build_vllm_kwargs(llm_cfg))
    tokenizer = llm.get_tokenizer()
    logger.info("vLLM initialized")

    sampling_params = SamplingParams(
        temperature=llm_cfg.get("temperature", 0.0),
        top_p=llm_cfg.get("top_p", 0.001),
        max_tokens=llm_cfg.get("max_tokens", 512),
    )

    outputs = dict(existing)
    failed_ids: List[str] = []
    batch_size = batch_size if batch_size is not None else llm_cfg.get("batch_size", 64)

    for start in range(0, len(todo_ids), batch_size):
        batch_ids = todo_ids[start:start + batch_size]
        batch_prompts = []
        for eid in batch_ids:
            p = target_prompts[eid]
            chat_text = format_chat_prompt(p["system"], p["user"], tokenizer)
            batch_prompts.append(chat_text)

        logger.info("Generating batch %d/%d (%d prompts)",
                    start // batch_size + 1,
                    (len(todo_ids) + batch_size - 1) // batch_size,
                    len(batch_prompts))

        try:
            vllm_outputs = llm.generate(batch_prompts, sampling_params)
        except Exception as e:
            logger.error("Batch generation failed: %s", e)
            failed_ids.extend(batch_ids)
            continue

        # 防御：vLLM 跳过超长请求时返回数量会少于 prompt 数，
        # zip 配对会静默错位——宁可整批标记失败（可由 --resume 恢复）也不写错位结果
        if len(vllm_outputs) != len(batch_ids):
            logger.error(
                "Batch output count mismatch: %d outputs for %d prompts; "
                "marking whole batch as failed to avoid misalignment",
                len(vllm_outputs), len(batch_ids))
            failed_ids.extend(batch_ids)
            continue

        for eid, out in zip(batch_ids, vllm_outputs):
            generated = out.outputs[0].text
            raw, summary, attributive = parse_generated_text(generated)
            outputs[eid] = {
                "raw": raw,
                "summary": summary,
                "attributive": attributive,
            }

        # 每个 batch 后保存一次中间进度（仅 full 模式写入主文件；debug 模式最后按 status 拆分）
        if mode != "debug":
            with open(paths["llm_outputs_json"], "w", encoding="utf-8") as f:
                json.dump(outputs, f, ensure_ascii=False, indent=2)
            logger.info("Saved progress: %d/%d", len(outputs), len(target_prompts))

    # 保存最终输出
    if mode == "debug":
        # 按 status 拆分保存
        base_dir = os.path.dirname(paths["llm_outputs_json"])
        base_name = os.path.basename(paths["llm_outputs_json"])
        stem = base_name.replace(".json", "")
        status_outputs = {status: {} for status in prompts_raw.keys()}
        for eid, out in outputs.items():
            status = eid_to_status.get(eid)
            if status is None:
                continue
            status_outputs[status][eid] = out
        for status, out in status_outputs.items():
            output_path = os.path.join(base_dir, f"{stem}_{status}.debug.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            logger.info("Saved %s debug outputs to %s (%d entries)", status, output_path, len(out))
    else:
        with open(paths["llm_outputs_json"], "w", encoding="utf-8") as f:
            json.dump(outputs, f, ensure_ascii=False, indent=2)
        logger.info("Saved outputs to %s", paths["llm_outputs_json"])

    if failed_ids:
        stem = os.path.basename(paths["llm_outputs_json"]).replace("llm_outputs", "failed_ids")
        failed_path = os.path.join(os.path.dirname(paths["llm_outputs_json"]), stem)
        with open(failed_path, "w", encoding="utf-8") as f:
            json.dump(failed_ids, f, ensure_ascii=False, indent=2)
        logger.warning("Failed entities: %d, saved to %s", len(failed_ids), failed_path)

    logger.info("Done. Total outputs: %d", len(outputs))


def main():
    parser = argparse.ArgumentParser(description="Generate entity descriptions with vLLM.")
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--label", type=str, required=True,
                        help="数据集内的子划分（如 main / one-hop / full）")
    parser.add_argument("--config", type=str, default="config.yaml")
    parser.add_argument("--mode", type=str, choices=["debug", "full"], default="debug")
    parser.add_argument("--batch_size", type=int, default=None,
                        help="覆盖 config 中的 batch_size")
    parser.add_argument("--resume", action="store_true",
                        help="从已有 llm_outputs.json 继续生成")
    parser.add_argument("--suffix", type=str, default="",
                        help="输入 prompts 与输出 llm_outputs 的文件名后缀（如 _catfreq2）")
    args = parser.parse_args()

    generate_texts(
        args.dataset,
        args.label,
        args.config,
        args.mode,
        args.batch_size,
        args.resume,
        args.suffix,
    )


if __name__ == "__main__":
    # python 04_generate_llm_text.py --dataset dbbook2014-mine --label main --mode debug
    # python 04_generate_llm_text.py --dataset dbbook2014-mine --label main --mode full
    # python 04_generate_llm_text.py --dataset dbbook2014-mine --label full --mode full
    """
    注意：vllm 0.6.6 指定的 torch 2.5.1 和 numpy 1.26.4 之间存在 C++ 层面的不兼容问题，
    执行此脚本需要找到vllm库的这四个文件：
    /root/miniconda3/lib/python3.12/site-packages/vllm/utils.py
    /root/miniconda3/lib/python3.12/site-packages/vllm/attention/backends/utils.py
    /root/miniconda3/lib/python3.12/site-packages/vllm/attention/backends/flash_attn.py
    /root/miniconda3/lib/python3.12/site-packages/vllm/v1/worker/gpu_model_runner.py
    
    在它们导入torch的语句下方增加这个补丁函数 ↓
    def _safe_from_numpy(ndarray):
        if isinstance(ndarray, torch.Tensor):
            return ndarray
        try:
            return torch.from_numpy(ndarray)
        except (TypeError, RuntimeError):
            pass
        
        dtype_str = str(ndarray.dtype)
        dtype_map = {
            'int32': torch.int32,
            'int64': torch.int64,
            'float32': torch.float32,
            'float64': torch.float64,
            'bool': torch.bool,
            'uint8': torch.uint8,
            'int8': torch.int8,
            'int16': torch.int16,
            'float16': torch.float16,
        }
        torch_dtype = dtype_map.get(dtype_str)
        
        if torch_dtype:
            # 用 astype 确保类型正确
            return torch.tensor(ndarray.astype(ndarray.dtype).tolist(), dtype=torch_dtype)
        return torch.tensor(ndarray.tolist())
    """
    main()
