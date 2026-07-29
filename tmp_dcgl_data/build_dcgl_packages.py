"""
build_dcgl_packages.py

为 DCGL 对比实验构建 8 份数据包（4 个 min_catfreq 版本 × L2/no-L2）：

    dbbook2014_catfreq{N}_{l2|no_l2}/
    ├── entity_embeddings.npy   # 对应版本的嵌入（重命名）
    ├── kg_final.txt            # h r t 空格分隔、三元组打乱（来自 kg/catfreq{N}/full_triples.dat）
    ├── train.txt / test.txt    # 从示例文件夹复制
    └── item/user_interaction_counts_sorted.json

每份数据压缩为同名 .zip 便于上传。

执行位置：项目根目录（data_preprocess/）
用法：python tmp_dcgl_data/build_dcgl_packages.py              # 全量嵌入版（8 份 + zip）
      python tmp_dcgl_data/build_dcgl_packages.py --item_only  # 物品嵌入对照版（item_ 前缀，不压缩）
      python tmp_dcgl_data/build_dcgl_packages.py --legacy     # 4660 版（KG 重新打乱）+ 原始 KG 基线（共 6 份，不压缩）
"""
import os
import json
import random
import shutil
import argparse

FREQS = [2, 3, 4, 5]
TAGS = {"l2": "", "no_l2": "_no_l2"}

ROOT = "tmp_dcgl_data"
EXAMPLE_DIR = os.path.join(ROOT, "dbbook2014")
EMB_DIR = "output/dbbook2014-mine/full/05_embeddings"
ITEM_EMB_DIR = "output/dbbook2014-mine/main/05_embeddings"
KG_DIR = "../MINE/data/dbbook2014/kg"

SHARED_FILES = [
    "train.txt",
    "test.txt",
    "item_interaction_counts_sorted.json",
    "user_interaction_counts_sorted.json",
]
SEED = 42


def build_kg_final(triples_path: str, out_path: str):
    """full_triples.dat (h\\tt\\tr) -> kg_final.txt (h r t，空格分隔，固定种子打乱)。"""
    lines = []
    with open(triples_path, "r", encoding="utf-8") as f:
        for line in f:
            h, t, r = line.split()
            lines.append(f"{h} {r} {t}\n")
    random.Random(SEED).shuffle(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return len(lines)


def build_one(name: str, src_emb: str, triples_path: str = None,
              kg_final_src: str = None):
    """构建一份数据文件夹：共享文件 + entity_embeddings.npy + kg_final.txt。

    kg_final.txt 来源二选一：triples_path（h\\tt\\tr，转换并打乱）或
    kg_final_src（现成的 kg_final.txt，原样复制，用于对标 DCGL 原设计的基线）。
    """
    folder = os.path.join(ROOT, name)
    os.makedirs(folder, exist_ok=True)
    for fname in SHARED_FILES:
        shutil.copy2(os.path.join(EXAMPLE_DIR, fname), os.path.join(folder, fname))
    shutil.copy2(src_emb, os.path.join(folder, "entity_embeddings.npy"))
    if kg_final_src:
        shutil.copy2(kg_final_src, os.path.join(folder, "kg_final.txt"))
        with open(kg_final_src, "r", encoding="utf-8") as f:
            n_triples = sum(1 for _ in f)
    else:
        n_triples = build_kg_final(triples_path, os.path.join(folder, "kg_final.txt"))
    print(f"[OK] {name}: {n_triples} triples")
    return name, n_triples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--item_only", action="store_true",
                        help="物品嵌入对照版：嵌入只用 main 的 2680 物品嵌入，"
                             "其余实体由 DCGL 随机初始化；文件夹加 item_ 前缀，不压缩")
    parser.add_argument("--legacy", action="store_true",
                        help="4660 版（KG 重新打乱）+ 原始 KG 基线 item_dbbook2014（共 6 份，不压缩）")
    args = parser.parse_args()

    if args.legacy:
        summary = []
        for tag, emb_tag in TAGS.items():
            # 4660 全量嵌入版（kg/entity_embeddings.npy = 7340 行；KG 重新打乱）
            summary.append(build_one(
                f"dbbook2014_4660_{tag}",
                os.path.join(KG_DIR, f"entity_embeddings{emb_tag}.npy"),
                triples_path=os.path.join(KG_DIR, "one_hop_triples.dat")))
            # 4660 物品嵌入版
            summary.append(build_one(
                f"item_dbbook2014_4660_{tag}",
                os.path.join(ITEM_EMB_DIR, f"entity_embeddings{emb_tag}.npy"),
                triples_path=os.path.join(KG_DIR, "one_hop_triples.dat")))
            # 原始 KG 基线（完全对标 DCGL 原设计：原 KG 不动，仅替换物品嵌入）
            summary.append(build_one(
                f"item_dbbook2014_{tag}",
                os.path.join(ITEM_EMB_DIR, f"entity_embeddings{emb_tag}.npy"),
                kg_final_src=os.path.join(EXAMPLE_DIR, "kg_final.txt")))
        print(f"\n共 {len(summary)} 份数据文件夹（未压缩）")
        return

    summary = []
    for n in FREQS:
        for tag, emb_tag in TAGS.items():
            if args.item_only:
                name = f"item_dbbook2014_catfreq{n}_{tag}"
                src_emb = os.path.join(ITEM_EMB_DIR, f"entity_embeddings{emb_tag}.npy")
            else:
                name = f"dbbook2014_catfreq{n}_{tag}"
                src_emb = os.path.join(EMB_DIR, f"entity_embeddings_catfreq{n}{emb_tag}.npy")
            folder = os.path.join(ROOT, name)
            os.makedirs(folder, exist_ok=True)

            # 共享文件
            for fname in SHARED_FILES:
                shutil.copy2(os.path.join(EXAMPLE_DIR, fname), os.path.join(folder, fname))

            # 嵌入（重命名复制）
            shutil.copy2(src_emb, os.path.join(folder, "entity_embeddings.npy"))

            # KG
            n_triples = build_kg_final(
                os.path.join(KG_DIR, f"catfreq{n}", "full_triples.dat"),
                os.path.join(folder, "kg_final.txt"),
            )

            # 压缩（item_only 对照版不压缩）
            zip_path = None
            if not args.item_only:
                zip_path = shutil.make_archive(folder, "zip", root_dir=ROOT, base_dir=name)
            summary.append((name, n_triples, zip_path))
            print(f"[OK] {name}: {n_triples} triples" + (f" -> {zip_path}" if zip_path else ""))

    print(f"\n共 {len(summary)} 份数据包：")
    for name, n_triples, zip_path in summary:
        line = f"  {name}: {n_triples} triples"
        if zip_path:
            line += f", zip {os.path.getsize(zip_path) / 1e6:.1f}MB"
        print(line)


if __name__ == "__main__":
    main()
