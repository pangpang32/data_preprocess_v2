# 数据预处理流水线

本项目为基于知识图谱的推荐系统生成实体语义嵌入。流程从 `DBpedia` 本地转储中抽取实体描述，经人工消歧义、`LLM` 生成语义摘要，再由 `SimCSE` 编码为向量，最终供下游推荐模型使用。本流水线的设计参考了  `DCGL` 、`ColaKG`、`CIKGRec` 等工作的思路。

## 核心设计

- **去重与原始 ID 空间兼容**：种子实体先去重处理，再通过 `expand_map` 扩展回推荐系统使用的原始 ID 空间，去重便于 `01a/01b` 阶段进行人工审核与修复。
- **多跳 KG 与子划分机制**：`config.yaml` 中 `datasets.{name}.{label}` 两级配置（如 `dbbook2014-mine` 的 `main` / `one-hop` / `full`），`seed_datasets` 按依赖深度有序引用上游子划分。脚本统一以 `--dataset {name} --label {label}` 调用。
- **类别信息 KG（02c）**：在目标跳数 KG 之上统一追加 dbo 类型边（叶子过滤 + `owl:equivalentClass` 归一化 + roles 兜底推断）、dbo 类层级边与 dbc 类别边；类别节点 ID 连续分配在普通实体之后（dbc 在前、dbo 按抽象度在后），`status=no_info`，走专属 prompt 模板或随机初始化。
- **Prompt 统一配置**：`resources/mvp_prompts.json` 提供跨数据集共享的 system/user 模板（含 `no_info` / `dbo` / `dbc` 类别节点模板）与按 数据集→子划分 分键的 `relation_priority`。
- **多版本消融支持**：`min_cat_freq` 控制 dbc 类别节点的纳入阈值；`output/concat_catfreq_prompts.py` 把多个阈值版本的 prompts 去重拼接为一份供云端一次跑完，再 `--split` 拆回。
- **一次运行双版本嵌入**：`05_vectorize.py` 同时输出 `L2` 归一化与未归一化的 `entity_embeddings.npy`。

## 目录结构

```
data_preprocess/
├── config.yaml                 # 全局配置
├── README.md                   # 本文件
├── utils.py                    # 公共工具函数（含 dbc 类别黑名单等内联常量）
│
├── 01a_resolve_uris.py         # 初始化实体描述并进入交互式消歧义
├── 01b_crawl_dbpedia.py        # 从 DBpedia 转储抓取字段、打状态标签
├── 02a_split_kg_entities.py    # 从种子实体描述中拆出一跳 KG
├── 02b_backfill_entity_meta.py # 把邻居实体真实 status/label 回填到 meta
├── 02c_build_full_kg.py        # 追加 dbo/dbc 类别节点与类型/类层级/类别边，合成 full 数据集
├── 03_build_prompts.py         # 构造 LLM prompt
├── 04_generate_llm_text.py     # vLLM 批量生成文本并解析 SUMMARY/ATTRIBUTIVE
├── 05_vectorize.py             # SimCSE 编码为向量
│
├── output/probe_predicates.py  # 谓词分布探查（供 KG 关系筛选与 relation_priority 参考）
├── output/probe_objects.py     # types/categories 宾语分布探查（供类型/类别边构建策略参考）
├── output/concat_catfreq_prompts.py  # 多 min_cat_freq 版本 prompts 的去重拼接与拆分（含 --split_embeddings）
├── output/summarize_dcgl_logs.py     # DCGL 实验日志汇总（recall@50，txt + xlsx）
│
├── resources/
│   ├── build_ontology.py       # 从 dbpedia_2016-10.owl 生成 ontology.json
│   ├── mvp_prompts.json        # prompt 模板与 relation_priority
│   ├── ontology.json           # 轻量化 ontology（含 class_equivalents / class_comments）
│   └── role_type_map.json      # 连接谓词 -> 兼容 dbo 类型（03 与 02c 共用的兜底推断表）
│
├── docs/
│   └── ontology_pipeline.md    # ontology 诊断与 ontology_embeddings 方案（下一步计划）
│
├── tmp_dcgl_data/              # DCGL 对比实验数据包与批处理脚本（见"下游实验对接"）
│
├── dumps/
│   ├── dbpedia_download.py     # DBpedia 转储下载脚本
│   ├── probe_dbpedia.py        # 单个实体 / URI 的转储探查工具
│   └── dbpedia_files/          # DBpedia 转储文件与索引
│       ├── build_index.py      # 为 TTL 文件构建 subject 索引
│       ├── index/              # 索引文件
│       └── bz2_and_zip/        # 原始压缩包
│
└── output/
    ├── probe/{dataset}/{label}/        # 探查报告
    └── {dataset}/{label}/
        ├── 01_crawl/
        │   ├── descriptions_a.json     # 01a 初始化结果（含消歧义信息）
        │   ├── descriptions_b.json     # 01b 抓取结果
        │   ├── descriptions.json       # 最终描述（已扩展回原始 ID 空间）
        │   └── problem_entities_b.dat  # 01b 发现的问题实体列表
        ├── 02_kg_build/
        ├── 03_prompts/
        │   ├── prompts.json
        │   ├── prompts_catfreq{N}.json         # 各 min_cat_freq 版本（full）
        │   ├── prompts_catfreq_split.json      # 拼接/拆分记录（full）
        │   └── prompts_{status}.debug.json
        ├── 04_llm_output/
        │   ├── llm_outputs.json
        │   ├── llm_outputs_catfreq{N}.json     # --split 拆回的各版本（full）
        │   └── llm_outputs_{status}.debug.json
        └── 05_embeddings/
            ├── entity_embeddings.npy
            └── entity_embeddings_no_l2.npy
```

KG 的实际文件（`{}_hop_triples.dat`、`{}_hop_entities.dat`、`{}_hop_entity_meta.json`、`full_*.dat`、`ontology_map.dat`）存储路径于 `config.yaml` 中配置。

## 环境准备

1. Python 3.12

2. 安装依赖（详见 `gpu_requirements_data.txt`）：
   ```bash
   pip install -r gpu_requirements_data.txt
   ```

   `注：除 04、05，其它脚本仅需 rdflib，其中 04 必须使用完整依赖，05 可以在本地没有 vllm 的 CPU 环境运行。 `

3. 下载模型：

   - LLM：`Qwen/Qwen2.5-14B-Instruct`（或其他兼容 chat template 的模型）
   - 向量模型：`princeton-nlp/sup-simcse-roberta-large`

4. 准备 DBpedia 转储：
   ```bash
   python dumps/dbpedia_download.py
   ```

5. 为 TTL 文件构建索引：
   ```bash
   python dumps/dbpedia_files/build_index.py
   ```

## 配置说明（config.yaml）

关键字段：

- `prompt_config`: 全局 prompt 模板路径。
- `role_type_map`: 谓词 → 兼容 dbo 类型的兜底推断表（03 推断类型与 02c 兜底类型边共用）。
- `output_base`: 输出根目录，默认 `output`。
- `dbpedia.dump_dir` / `dbpedia.idx_dir`: DBpedia 转储与索引路径。
- `datasets.{name}.{label}`: 两级结构，主键为数据集名，二级键为子划分（如 `main` / `one-hop` / `full`）。
  - `label`: 子划分在 KG 依赖链中的深度。`0` 表示种子子划分，无上游；`1` 表示一跳邻居；`2` 表示合并子划分（02c 产物）。
  - `seed_datasets`: 必须是有序列表，元素为**同一数据集内**的上游子划分名。`label=N` 时取前 N 个作为全部上游。
  - `expand_map`: 原始 ID → 去重后 ID 的映射，用于将结果扩展回推荐侧原始 ID 空间。
  - `kg_hop_triples` / `kg_hop_entities` / `kg_hop_meta`: 各跳/合并 KG 产物路径。

示例（dbbook2014-mine）：

```yaml
datasets:
  dbbook2014-mine:
    main:
      label: 0
      base_dir: "../MINE/data/dbbook2014"
      entity_list: "item_list.dat"
      relation_list: "kg/one_hop_relations.dat"
      expand_map: "original_i2i_map.dat"
      kg_hop_triples: "kg/one_hop_triples.dat"
      kg_hop_entities: "kg/one_hop_entities.dat"
      kg_hop_meta: "kg/one_hop_entity_meta.json"
      n_entities: 2624
      n_original_entities: 2680

    one-hop:
      label: 1
      base_dir: "../MINE/data/dbbook2014/kg"
      seed_datasets: ["main"]
      entity_list: "one_hop_entities.dat"
      n_entities: 4660

    full:
      label: 2
      base_dir: "../MINE/data/dbbook2014/kg"
      seed_datasets: ["main", "one-hop"]
      entity_list: "full_entities.dat"        # 02c 输出：全部实体（含 dbo/dbc 类别节点）
      relation_list: "full_relations.dat"     # 02c 输出
      kg_hop_triples: "full_triples.dat"      # 02c 输出
      kg_hop_entities: "full_entities.dat"
      kg_hop_meta: "full_entity_meta.json"    # 02c 输出
      n_entities: 9612                        # 随 min_cat_freq 版本变化，以 02c 日志为准
```

## 完整运行流程

以下以 `dbbook2014-mine` 为例。

### Step 0. 构建 ontology

```bash
python resources/build_ontology.py
```

输出：`resources/ontology.json`。

### Step 1. 01a：初始化实体描述与交互式消歧义

```bash
python 01a_resolve_uris.py --dataset dbbook2014-mine --label main
```

`01a` 会读取实体列表，初始化 `descriptions_a.json`，并进入交互式消歧义过程。此阶段通常**只需执行一次**，因为人工消歧义成本高、难以自动化。

### Step 1.5. 问题实体修复（循环迭代）

`01b` 会读取 `descriptions_a.json`，运行后输出 `problem_entities_b.dat`。修复问题实体是最麻烦的阶段，通常需要反复执行：

1. 对照 `descriptions_a.json`、`descriptions_b.json` 和 `problem_entities_b.dat` 定位问题实体。

2. 使用 `dumps/probe_dbpedia.py` 探查该实体在 DBpedia 转储中的真实情况：
   ```bash
   python dumps/probe_dbpedia.py --entity "Animalia_(book)"
   python dumps/probe_dbpedia.py --uri "http://dbpedia.org/resource/Animalia_(book)"
   ```

3. 对于 `failed` 或 `label_only` 实体，检查 `descriptions_b.json` 中是否有 `redirect_uri` 字段；如有，可探查重定向目标是否与数据集吻合。

4. 实在没有数据的可以人工从其它渠道寻找信息填入`descriptions_a.json`。

5. 修正 `descriptions_a.json` 后，重新运行 `01b`。

### Step 2. 01b：抓取字段并生成最终描述

```bash
python 01b_crawl_dbpedia.py --dataset dbbook2014-mine --label main --mode full
```

`01b` 读取 `descriptions_a.json`，从本地 DBpedia 转储中抓取 `label`、`abstract`、`types`、`categories`、`object_properties`、`literal_properties` 等字段，为每个实体打状态标签，输出：
- `descriptions_b.json`
- `descriptions.json`（若配置了 `expand_map`，会自动扩展回原始 ID 空间）
- `problem_entities_b.dat`
- `crawl.log`

### Step 3. 探查分布并构建 relation_list

在拆分 KG 之前，需要先决定保留哪些谓词作为 KG 边，并设计 `resources/mvp_prompts.json` 中的 `relation_priority`。

```bash
# 谓词分布（object_properties / literal_properties）
python output/probe_predicates.py --dataset dbbook2014-mine --label main
# types / categories 宾语分布（供后续类型/类别边策略参考）
python output/probe_objects.py --dataset dbbook2014-mine --label main
```

输出：
- `output/probe/dbbook2014-mine/main/probe_predicates_report.md` / `probe_predicates_stats.json`
- `output/probe/dbbook2014-mine/main/probe_objects_report.md` / `probe_objects_stats.json`

根据报告中的谓词频次与语义重要性，编写 `{base_dir}/kg/one_hop_relations.dat`（谓词 URI → 关系 ID 的映射）。`02a_split_kg_entities.py` 会读取该文件筛选 KG 边。

如果后续需要调整 KG 构造（例如从 `one_hop_relations.dat` 中剔除某个关系），也应从这里重新开始，修改后重新执行 Step 4 及以后。

### Step 4. 02a：从种子实体描述中拆分一跳 KG

```bash
python 02a_split_kg_entities.py --dataset dbbook2014-mine --label main
```

输入是 `01b` 输出的 `descriptions.json`。脚本根据配置中的 `relation_list` 筛选谓词，生成种子实体的一跳 KG：
- `{base_dir}/kg/one_hop_triples.dat`
- `{base_dir}/kg/one_hop_entities.dat`
- `{base_dir}/kg/one_hop_entity_meta.json`

### Step 4.5. 01a / 01b：为一跳 KG 实体生成描述

`02a` 生成的一跳实体列表需要在 `config.yaml` 的 `dbbook2014-mine.one-hop` 中配置，并且其 `n_entities` 要更新为 `02a` 日志输出的实体总数。然后为一跳实体解析 URI、抓取描述：

```bash
python 01a_resolve_uris.py --dataset dbbook2014-mine --label one-hop
python 01b_crawl_dbpedia.py --dataset dbbook2014-mine --label one-hop
```

> 示例：剔除 `dbo:nonFictionSubject` 后，`02a` 日志输出 `total=4417`，比剔除前（4660）减少 243，`mapped` 占比从 81.8% 微升至 82.2%。这时需要根据日志输出的新数量修改`config`中的`n_entities`数值，然后再运行此步骤。

### Step 5. 02b：回填邻居实体 meta

```bash
python 02b_backfill_entity_meta.py --dataset dbbook2014-mine --label one-hop
```

上游种子子划分根据 `label` 与 `seed_datasets` 自动推断，无需显式传入。

### Step 5.5. 02c：构建合并 KG（追加 dbo/dbc 类别节点与边）

在目标跳数 KG 完成后，统一为**全部实体**追加类别信息：

```bash
python 02c_build_full_kg.py --dataset dbbook2014-mine --label full --min_cat_freq 5
```

- 类型边（`rdf:type`）：实体 types 经 `owl:equivalentClass` 归一化后只保留最具体的 dbo 类；无类型的按连接谓词兜底推断（`role_type_map.json` + ontology `property_range`）
- 类层级边（`rdfs:subClassOf`）：沿 ontology 父类链逐级连接
- 类别边（`dct:subject`）：dbc 类别按频次阈值（`--min_cat_freq`）+ `utils.CATEGORY_BLACKLIST` 过滤
- 类别节点 ID 连续分配在普通实体之后（dbc 在前、dbo 按抽象度在后），合成 `full` 的 `descriptions.json`（`status=no_info`，03 自动分流到 `dbo`/`dbc` 模板）
- 同时输出 `ontology_map.dat`（dbo 类节点 ID → 类 URI），供全局 ontology_embeddings 行映射（见 `docs/ontology_pipeline.md`）

产物：`full_entities.dat` / `full_triples.dat` / `full_relations.dat` / `full_entity_meta.json` / `ontology_map.dat`。跑完按日志更新 config 中 `full.n_entities`。

**多版本消融（min_cat_freq 2/3/4/5）**：对每个阈值分别跑 02c（备份 `kg/catfreq{N}/` 快照）与 03 full（用 `--suffix` 区分输出），然后用拼接脚本合成一份供云端一次跑完：

```bash
python 03_build_prompts.py --dataset dbbook2014-mine --label full --mode full --suffix _catfreq{N}
# 4 个版本都跑完后：
python output/concat_catfreq_prompts.py --dataset dbbook2014-mine --label full
```

拼接是去重的（main+one-hop+dbo 的 prompt 各版本相同，只保留一份），键格式与拆分规则见 `prompts_catfreq_split.json`。`--suffix` 在 03/04/05 中规则一致：传入后**读取的上游产物也带相同后缀**（如 04 `--suffix _catfreq2` 读 `prompts_catfreq2.json`、写 `llm_outputs_catfreq2.json`）。

### Step 6-8. 03 / 04 / 05

```bash
# 构造 prompt
python 03_build_prompts.py --dataset dbbook2014-mine --label main --mode full
python 03_build_prompts.py --dataset dbbook2014-mine --label one-hop --mode full

# LLM 生成（云端 GPU）
python 04_generate_llm_text.py --dataset dbbook2014-mine --label main --mode full
python 04_generate_llm_text.py --dataset dbbook2014-mine --label one-hop --mode full
python 04_generate_llm_text.py --dataset dbbook2014-mine --label full --mode full   # 拼接版 prompts

# 拆回各版本（在 05 之前；05 只接受纯数字键）
python output/concat_catfreq_prompts.py --dataset dbbook2014-mine --label full --split

# 向量化（本地）
python 05_vectorize.py --dataset dbbook2014-mine --label main --mode full
python 05_vectorize.py --dataset dbbook2014-mine --label one-hop --mode full
# full 逐版本（--suffix 同时作用于输入 llm_outputs 与输出 npy）：
python 05_vectorize.py --dataset dbbook2014-mine --label full --mode full --suffix _catfreq2
```

**full 的单跑流程（推荐，避免逐版本编码）**：直接在拼接版 `llm_outputs.json` 上跑一次 05（自动识别非数字键、按拼接顺序分配行号，并输出 `entity_embeddings_row_map.dat`），然后用 `--split_embeddings` 一次性拆回各版本 npy（行与各版本实体 ID 对齐，等效于逐版本跑 05）：

```bash
python 05_vectorize.py --dataset dbbook2014-mine --label full --mode full   # 拼接版，单次编码
python output/concat_catfreq_prompts.py --dataset dbbook2014-mine --label full --split_embeddings
```

> **04 的 resume 机制**：`--resume` 跳过已有输出，并自动重新生成 raw/summary 全空的条目（vLLM 因 prompt 超过 `max_model_len` 中止请求时会产生这种空输出）；`generate` 返回数量与 prompt 数不一致时整批标记失败（防止错位），失败实体记录在 `failed_ids.json`。遇到超长 prompt 时可调高 `defaults.llm.max_model_len` 后 resume 补跑，无需重跑全量。

## 消歧义与重定向处理说明 -- 以 DBbook2014 为例

### 1. 数据来源与背景

本项目对 DBbook2014 知识图谱中的实体进行 DBpedia URI 消歧义与重定向修正。DBbook2014 是图书推荐数据集，其原始版本包含 8170 个实体。`i2kg_map.tsv` 来自 2019 年 KTUP 的工作，对原始数据集执行了过滤，保留了 2680 个本工作处理的实体，并提供了实体 ID、物品名称到 DBpedia URI 的映射。由于 DBpedia 中存在大量同名异义实体、错误重定向和系统性数据问题，需要对映射结果进行人工审核与修正。

### 2. 核心处理策略

#### 2.1 领域约束优先

DBbook2014 是图书数据集，优先选择符合"图书"领域的候选：

- 小说（novel）> 戏剧（play）> 漫画（comics）> 短篇故事（short_story）
- 排除电影、电视剧、专辑、歌曲、游戏等非图书类候选
- 例外：数据集中确实包含少量漫画（如 Buffy 相关的 *Fray*）、视觉小说（*Happiness!*）等

#### 2.2 作者与系列一致性

检查数据集中是否已有该作者或系列的其他作品：

- 若某作者的其他书已在 KG 中，优先选择该作者
- 系列作品倾向于在数据集中保持连续性
- 例如：Modesty Blaise 系列、The Black Company 系列、A Dance to the Music of Time 系列等

#### 2.3 拼写与命名匹配

注意原始标签、重定向前 URI 与候选的拼写差异：

- 原始标签的拼写（单复数、冠词、连字符、空格）是重要线索
- 例如：`Airborn`（无 e）≠ `Airborne`（有 e），`Night_Work`（分开）≠ `Nightwork`（合写）
- 重定向前 URI 与候选拼写不一致时，警惕错误重定向

### 3. 消歧义阶段的典型问题

#### 3.1 DBpedia 消歧义数据不完整

`dbo:wikiPageDisambiguates` 未包含正确的图书实体，但 `dbo:wikiPageWikiLink` 中存在。

**案例**：

- `Airborn` → 正确实体 `dbr:Airborn_(novel)`（Kenneth Oppel）不在 `wikiPageDisambiguates` 中
- `Night_Work` → 正确实体 `dbr:Night_Work_(King_novel)` 只在 `wikiPageWikiLink` 中
- `Doing_It` → 正确实体 `dbr:Doing_It_(novel)` 只在 `wikiPageWikiLink` 中
- `Port_of_Call` → 正确实体 `dbr:Ports_of_Call_(Vance_novel)` 和 `dbr:Ports_of_Call_(Maalouf_novel)` 只在 `wikiPageWikiLink` 中

**处理**：跳过当前候选列表，通过浏览器手动查询确认正确 URI。

#### 3.2 消歧义页本身作为候选

`wikiPageDisambiguates` 的第一个候选通常是消歧义页自身。

**案例**：`Flood_tide_(disambiguation)` 的候选 0 是 `dbr:Flood_tide`（消歧义页本身）

**处理**：候选 0 为消歧义页自身时不应选择，选择具体实体。

#### 3.3 缺少"图书"含义的候选

消歧义页中完全没有图书类候选。

**案例**：

- `Villager` → 只有报纸、地名、乐队等
- `47` → 只有数字、年份、品牌（原数据集中的噪声）
- `Trek` → 只有历史事件、自行车、徒步装备（缺少 Star Trek）
- `Tale` → 只有地名（缺少"故事/童话"含义）
- `Account` → 只有金融账户（缺少"叙述/记述"含义）

**处理**：标记为"DBpedia 消歧义数据覆盖不足"，根据 `wikiPageWikiLink`、上下文或外部知识推断正确含义，或标记为无效实体。

#### 3.4 映射错误

`i2kg_map.tsv` 中的名称与 URI 不匹配。

**案例**：物品名称 "Journals" 被错误映射到 `dbr:Bizjournals`（商业新闻出版社），正确实体应为 `dbr:Journals_(Cobain)`（Kurt Cobain 的日记集）

**处理**：核对名称与 URI 的一致性，修正错误映射。

### 4. 重定向阶段的典型问题

#### 4.1 错误重定向的主要模式

| 模式                 | 典型案例                                              | 占比估计 |
| -------------------- | ----------------------------------------------------- | -------- |
| 书籍 → 作者          | Dead and Loving It → MaryJanice_Davidson              | ~40%     |
| 书籍 → 系列/故事弧   | Night Whispers → Warriors:_Omen_of_the_Stars          | ~20%     |
| 书籍 → 前作/续作     | Secret of the Sixth Magic → Master_of_the_Five_Magics | ~10%     |
| 书籍 → 抽象概念      | Slights → Insult                                      | ~5%      |
| 书籍 → 虚构世界/设定 | Arrow's Flight → Velgarth                             | ~5%      |
| 书籍 → 历史人物/绰号 | The Winter King → Frederick_V                         | ~5%      |
| 书籍 → 地点/国家     | Herland → Netherlands                                 | ~5%      |

#### 4.2 检测方法的局限性

| 检测方法                | 能捕获的模式         | 无法捕获的模式          |
| ----------------------- | -------------------- | ----------------------- |
| domain / range 类型检查 | 书籍→人物、书籍→国家 | 书籍→系列、书籍→前作    |
| 类型白名单过滤          | 书籍→非书籍实体      | 书籍→书籍（同名不同书） |
| 特征属性检查            | 缺少书籍属性的实体   | 属性完整但语义错误      |
| 拼写相似度检查          | 单复数混淆           | 完全不同的标题          |
| 人工核对                | 所有模式             | 成本高、不可扩展        |

核心难点：当重定向目标也是书籍时（如续作→前作），类型检查完全失效，必须依赖外部知识或人工判断。

#### 4.3 DBpedia 数据本身的系统性问题

1. `dbo:series` 质量差：大量指向作者而非系列实体（如 `dbr:The_Black_Gryphon dbo:series dbr:Mercedes_Lackey`）
2. 系列实体缺失：常见系列如 `Heralds_of_Valdemar`、`Alaskan_Royals` 在 dump 中不存在
3. `dbo:previousWork` / `dbo:subsequentWork` 覆盖不均：部分书籍有，部分缺失
4. 重定向与实体共存：同一 URI 有时作为实体存在，有时作为重定向，状态不一致
5. 消歧义页处理：Wikipedia 消歧义页在 DBpedia 中可能被错误映射为单一实体

### 5. 特殊类型说明

| 类型         | 说明             | 数据集中是否出现             |
| ------------ | ---------------- | ---------------------------- |
| novel        | 长篇小说         | 主流                         |
| play         | 戏剧/剧本        | 少量                         |
| comics       | 漫画             | 少量（如 Buffy 相关）        |
| visual_novel | 视觉小说（游戏） | 极少量                       |
| short_story  | 短篇故事         | 少量                         |
| novella      | 中篇小说         | 少量                         |
| journal      | 学术期刊         | 通常排除，但学术专著可能保留 |
| magazine     | 杂志             | 通常排除                     |
| film         | 电影             | 排除                         |
| album        | 音乐专辑         | 排除                         |

### 6. 工具与数据限制

- 使用 DBpedia 2016-10 本地转储，在线 API 不稳定
- `wikiPageWikiLink` 转储文件达数百 GB，无法下载
- 脚本仅查询 `dbo:wikiPageDisambiguates`，遗漏部分正确实体
- 对于遗漏情况，通过浏览器手动查询 DBpedia 页面确认

### 7. 人工审核流程

1. 脚本读取需要消歧义/重定向审核的实体列表
2. 对每个实体，查询 `dbo:wikiPageDisambiguates` 获取候选，或查询重定向信息
3. 显示原始标签、重定向前 URI、当前 URI、候选列表
4. 人工根据以下信息判断：
   - 数据集领域（图书）
   - 作者与系列一致性
   - 拼写与命名匹配
   - YAGO/DBO 类型信息（如有）
5. 对于 `wikiPageDisambiguates` 未覆盖或重定向可疑的情况，通过浏览器手动查询确认
6. 输出审核结果到映射文件

### 8. 典型案例参考

DBpedia 的重定向关系有时完全不考虑上下文，且本地 dump、在线浏览器、消歧义页三者可能互相矛盾，导致自动方法无法恢复正确 URI。

**案例 1**：`The Winter King` → `Frederick V`

- `The Winter King` 是历史上 Frederick V 的绰号，而非某本书的作者。
- 在 Wikipedia 中，`The Winter King` 是一个重定向页，指向 Frederick V 的人物页面（因为绰号更常见）。
- DBpedia 提取框架把这个重定向关系直接映射为 `dbr:The_Winter_King → dbr:Frederick_V,_Elector_Palatine`，完全没有考虑上下文。
- 同时 Bernard Cornwell 的小说也叫《The Winter King》，但它在 Wikipedia/DBpedia 中可能是 `The_Winter_King_(novel)` 或消歧义页。
- 结果：消歧义和重定向都无法找到正确 URI，甚至在线浏览器也找不到明确信息，最后只能通过外部知识猜测正确 URI。

**案例 2**：`Airborn` 的多轮重定向

- 浏览器找到 `Airborn_(novel)`，但本地 dump 又把它重定向回 `Airborne`。
- 继续去浏览器查找该作者的书，发现 `Skybreaker`。
- 探查本地 `Skybreaker`，它的前一本显示 `Airborn_(Kenneth_Oppel_novel)`。
- 继续探查本地发现没有信息，再查重定向文件，发现 `Airborn_(Kenneth_Oppel_novel)` 被重定向到了 `Airborn_(Oppel_novel)`。
- 继续探查 `Airborn_(Oppel_novel)` 才终于正确。

**处理**：这类情况无法通过规则自动处理，只能依赖人工结合外部知识（作者、系列、Goodreads/Wikidata）逐步排查。这也是本项目采用人工审核关键实体的原因。

### 9. 处理策略的权衡

| 策略                   | 优点               | 缺点               | 适用场景           |
| ---------------------- | ------------------ | ------------------ | ------------------ |
| 完全放弃重定向         | 零错误、语义纯净   | 部分实体数据缺失   | 语义纯度要求极高   |
| 类型检查过滤           | 自动化、可扩展     | 漏检书籍→书籍错误  | 大规模初步过滤     |
| 特征属性检查           | 能捕获部分隐蔽错误 | 需要维护规则集     | 中等规模精细化     |
| 人工审核               | 准确率最高         | 成本极高、不可扩展 | 关键实体小规模审核 |
| 混合策略（本项目采用） | 平衡精度与效率     | 需要多轮迭代       | 实际生产环境       |

### 10. 本项目的处理方式

- **方向**：仅使用主语方向抽取，避免宾语方向引入噪声
- **重定向**：人工审核关键实体，拒绝明显错误的重定向
- **消歧义**：人工标注消歧义结果，修正错误映射
- **补全**：对缺失的系列、前后作品、类别、摘要等信息进行人工标注

## Debug 模式

### status 含义

`01b_crawl_dbpedia.py` 根据实体在本地 DBpedia 转储中的信息完整度为每个实体打上 status 标签，`03_build_prompts.py` 会为不同 status 选择对应的 prompt 模板。各 status 含义如下：

| status | 含义 | 信息来源 |
| ------ | ---- | -------- |
| `mapped` | 有 label、abstract，以及结构化信息（types / categories / relations） | 摘要 + 结构化关系 |
| `abstract_only` | 有 label 和 abstract，但缺少结构化 types / categories / relations | 摘要为主，可辅以相连实体描述 |
| `struct_only` | 有 label 和结构化信息，但无 abstract | 结构化关系 + 相连实体描述 |
| `label_only` | 只有 label 文件命中，无 abstract 和结构化信息 | 相连实体描述推断 |
| `failed` | 有 URI 但本地 dump 中无信息 | 完全依赖相连实体描述 |
| `no_info` | URI 属于已知无信息前缀（通用兜底模板） | 名称 + 相连实体描述推断 |
| `dbo` | DBpedia 本体类节点（02c 引入；由 `no_info` + prefix=dbo 分流） | 类层级 + 子类 + 成员实体样本 |
| `dbc` | Wikipedia 类别节点（02c 引入；由 `no_info` + prefix=dbc 分流） | 成员实体样本归纳主题 |
| `no_uri` | 没有解析到 URI | 仅基于 label 生成占位描述 |

> `no_info` 实体会按 `prefix` 字段自动分流：`dbo`/`dbc` 使用类别节点专属模板，其余前缀使用通用 `no_info` 模板。

### 03 按 status 采样

`03_build_prompts.py` 的 debug 模式会为 `resources/mvp_prompts.json` 中定义的每个 status（`mapped`、`abstract_only`、`label_only`、`struct_only`、`failed`、`no_uri`、`no_info`、`dbo`、`dbc`）分别采样最多 `--limit` 个实体，输出：

```
output/{dataset}/{label}/03_prompts/prompts_{status}.debug.json
```

不存在的 status 输出空文件 `{}`。

示例：

```bash
python 03_build_prompts.py --dataset dbbook2014-mine --label one-hop --mode debug --limit 5
```

### 04 按 status 分别生成

`04_generate_llm_text.py` 的 debug 模式会读取 03 生成的所有 `prompts_{status}.debug.json`，初始化一次 vLLM 后统一生成，再按 status 保存为：

```
output/{dataset}/{label}/04_llm_output/llm_outputs_{status}.debug.json
```

示例：

```bash
python 04_generate_llm_text.py --dataset dbbook2014-mine --label one-hop --mode debug
```

## 分布探查

```bash
python output/probe_predicates.py --dataset dbbook2014-mine --label one-hop
python output/probe_objects.py --dataset dbbook2014-mine --label one-hop
```

对 `label > 0` 的子划分，`probe_predicates.py` 的报告会自动按上一级连接谓词（role）分组统计；`probe_objects.py` 输出 types/categories 的宾语频次与阈值表。输出：

```
output/probe/{dataset}/{label}/probe_predicates_report.md (+ _stats.json)
output/probe/{dataset}/{label}/probe_objects_report.md  (+ _stats.json)
```

探查结果同时用于：
- **KG 关系筛选**：决定保留哪些谓词作为 KG 边
- **prompts 关系优先级**：为 `resources/mvp_prompts.json` 中的 `relation_priority` 提供数据依据
- **类型/类别边策略**：dbc 频次阈值（`--min_cat_freq`）与黑名单的选择

## 输出产物

- `entity_embeddings.npy`：L2 归一化嵌入，形状 `[n_entities, dim]`
- `entity_embeddings_no_l2.npy`：未归一化嵌入

这两个文件可直接被下游推荐模型加载使用。若下游模型使用自己构建的 KG，需同时替换其 KG 文件，并保证实体 ID 空间一致（一跳邻居实体 ID 从 `n_original_entities` 开始）。

full 数据集的额外产物：

- `full_entities.dat` / `full_triples.dat` / `full_relations.dat` / `full_entity_meta.json`：合并 KG（含 dbo/dbc 类别节点与边）
- `ontology_map.dat`：dbo 类节点 ID → 类 URI，供全局 ontology_embeddings 行映射（方案见 `docs/ontology_pipeline.md`）
- `kg/catfreq{N}/`：各 `min_cat_freq` 版本的 KG 快照（消融用）

## 下游实验对接（DCGL）

`tmp_dcgl_data/` 存放 DCGL 对比实验的数据包与批处理脚本：

- `build_dcgl_packages.py`：构建 DCGL 格式数据文件夹（`entity_embeddings.npy` + `kg_final.txt`（h r t 空格分隔、固定种子打乱）+ 共享的 train/test/interaction counts）。三种模式：
  - 默认：catfreq 全量嵌入 8 份（`dbbook2014_catfreq{N}_{l2|no_l2}`，含 zip）
  - `--item_only`：catfreq 物品嵌入对照 8 份（`item_` 前缀，仅 2680 物品嵌入，其余实体由 DCGL 随机初始化）
  - `--legacy`：4660 版 4 份（KG 重新打乱）+ 原始 KG 基线 2 份（`item_dbbook2014_{l2|no_l2}`）
- `run_catfreq_experiments.sh` / `run_item_catfreq_experiments.sh` / `run_legacy_experiments.sh`：每份数据 3 次运行的批处理脚本（在 DCGL 项目目录下执行）。
- 日志汇总：`output/summarize_dcgl_logs.py` 解析日志目录（取每条日志的 DESC 与最后一行 early stopping/recall@50），输出 `汇总.txt`（分组明细 + 降序总榜）与 `汇总.xlsx`（汇总/明细/透视三 sheet）。需要 openpyxl（项目内 `venv/` 已安装，用 `./venv/Scripts/python` 运行）。

## 下一步计划

- **全局 ontology_embeddings**（dbo 类节点嵌入的数据集无关化，支撑跨 KG 共享语义空间）：ontology 现状诊断、五步流程与 `ontology_overrides.json` 建议稿见 `docs/ontology_pipeline.md`。**待模型 MVP 阶段完成后实施**；落地路径为 overrides 审核 → `build_ontology.py` v2 → 760 类独立 prompt → 04/05 → `resources/embeddings/`，下游用 02c 已输出的 `ontology_map.dat` 按行替换类节点嵌入。

## 注意事项

1. **脚本执行位置**：
   - 主流程脚本（`01a` ~ `05`、以及 `resources/build_ontology.py`）应在项目根目录 `data_preprocess/` 下执行。
   - `output/` 下的探查与拼接脚本也在项目根目录下执行（内部通过 `sys.path` 定位到 `utils.py`）。
   - `dumps/probe_dbpedia.py` 应在 `dumps/` 目录下执行（它使用相对于脚本自身的路径定位转储文件）。
   - `dumps/dbpedia_files/build_index.py` 应在 `dumps/dbpedia_files/` 目录下执行。
2. **vLLM 补丁**：云端使用 vLLM 时需要给 vLLM 源码打补丁，详见 `04_generate_llm_text.py` 文件末尾注释。
3. **relation_priority**：`resources/mvp_prompts.json` 中按 数据集→子划分 分键配置；未配置的 label 默认优先级 50 并按字母序排列。
