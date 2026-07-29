#!/bin/bash
# DCGL 4660 版（KG 重新打乱）+ 原始 KG 基线实验：6 份数据 × 3 次运行（共 18 次）
# 数据：
#   dbbook2014_4660_{l2|no_l2}        4660 一跳 KG（已打乱）+ 7340 全量嵌入
#   item_dbbook2014_4660_{l2|no_l2}   4660 一跳 KG（已打乱）+ 2680 物品嵌入
#   item_dbbook2014_{l2|no_l2}        DCGL 原始 KG（未动）+ 2680 物品嵌入（原设计基线）
# 用法（在 DCGL 项目目录下）：
#   bash run_legacy_experiments.sh 2>&1 | tee run_legacy_experiments.log
# 单次失败不会中断后续运行；日志文件名与 --desc 形如 mine_kg_4660_l2_1

DATASETS=(
  dbbook2014_4660_l2
  dbbook2014_4660_no_l2
  item_dbbook2014_4660_l2
  item_dbbook2014_4660_no_l2
  item_dbbook2014_l2
  item_dbbook2014_no_l2
)

for ds in "${DATASETS[@]}"; do
  # dbbook2014_4660_l2 -> 4660_l2; item_dbbook2014_4660_l2 -> item_4660_l2; item_dbbook2014_l2 -> item_l2
  suffix=$(echo "$ds" | sed 's/dbbook2014_//')
  for i in 1 2 3; do
    echo "===== $(date '+%F %T') ${ds} run ${i}/3 ====="
    python run_dcgl.py \
      --cl_weight 0.05 \
      --alpha 0.03 \
      --beta 70 \
      --mu 0.1 \
      --dataset "${ds}" \
      --log \
      --log_fn "mine_kg_${suffix}_${i}" \
      --desc "mine_kg_${suffix}_${i}"
  done
done

echo "===== $(date '+%F %T') ALL 18 RUNS DONE ====="
