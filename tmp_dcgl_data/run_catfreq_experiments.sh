#!/bin/bash
# DCGL catfreq 消融实验：8 份数据 × 3 次运行（共 24 次）
# 数据包：dbbook2014_catfreq{N}_{l2|no_l2}（N = min_cat_freq 2/3/4/5）
# 用法（在 DCGL 项目目录下）：
#   bash run_catfreq_experiments.sh 2>&1 | tee run_catfreq_experiments.log
# 单次失败不会中断后续运行；日志文件名与 --desc 形如 mine_kg_catfreq2_l2_1

for N in 2 3 4 5; do
  for norm in l2 no_l2; do
    ds="dbbook2014_catfreq${N}_${norm}"
    for i in 1 2 3; do
      echo "===== $(date '+%F %T') ${ds} run ${i}/3 ====="
      python run_dcgl.py \
        --cl_weight 0.05 \
        --alpha 0.03 \
        --beta 70 \
        --mu 0.1 \
        --dataset "${ds}" \
        --log \
        --log_fn "mine_kg_catfreq${N}_${norm}_${i}" \
        --desc "mine_kg_catfreq${N}_${norm}_${i}"
    done
  done
done

echo "===== $(date '+%F %T') ALL 24 RUNS DONE ====="
