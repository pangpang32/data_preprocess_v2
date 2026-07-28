# Ontology 现状诊断与 ontology_embeddings 构建方案

> 目标：把 dbo 类节点的描述与嵌入**数据集无关化**，产出全局资产 `ontology_embeddings.npy`，
> 支撑跨 KG 共享语义空间（类节点作为跨数据集"锚点"）。本文档包含三部分：
> 现状诊断、处理流程、`ontology_overrides.json` 建议稿。

## 一、ontology.json 现状诊断

数据来源：`dumps/dbpedia_files/dbpedia_2016-10.owl`（DBpedia 2016-10 本体），
经 `resources/build_ontology.py` 解析。当前包含 7 个键：
`class_parents` / `class_labels` / `class_comments` / `class_equivalents` /
`property_domain` / `property_range` / `property_labels`。

### 1.1 基本盘（健康部分）

| 指标 | 数值 |
| --- | --- |
| 类总数 | 760（键全部合法 dbo 短 URI） |
| 属性总数 | 2865 |
| rdfs:label 覆盖 | 760/760（100%） |
| rdfs:comment 覆盖 | 267/760（35%） |
| subClassOf 环 | 无 |
| 层级深度 | 0–7 层（根类 50 个） |
| 直接子类数最大值 | 50（dbo:Person）；>20 的仅 4 个类 |
| property_domain 空值 | 444（未声明，非错误） |
| property_range 空值 | 277（未声明，非错误） |

- 属性 range 中的非 dbo 值均为正常 datatype（`xsd:` 1560 条、`http://dbpedia.org/datatype/*` 149 条）。
- 子类列表长度可控（最大 50），全量子类进 prompt 长度可接受（必要时 >20 截断并注明总数）。

### 1.2 噪声与缺口（按严重度排序）

**① equivalentClass 的 dul/d0 对齐噪声（最需处理）**

`class_equivalents` 共 393 条，按来源前缀：`wd:` 323、`schema:` 45、`dul:` 16、`d0:` 3、
`bibo:` 3、`foaf:` 2、skos full-uri 1。其中 wd/schema/bibo/foaf 质量高；
dul/d0 的 19 条是 DBpedia 上层本体对齐的已知烂摊子，约一半明显错误，例如：

- `d0:Location → dbo:Monastery`（地点→修道院）
- `dul:Description → dbo:Tax`（描述→税）
- `dul:SpaceRegion → dbo:Polyhedron`（空间区域→多面体）
- `dul:FunctionalSubstance → dbo:Food`（功能物质→食物）
- `dul:InformationObject → dbo:Database`（信息对象→数据库）

**② comment 覆盖倒挂**

267/760 的类有英文 comment，但分布倒挂：具体类（Abbey、Actor）有，
核心高层类（Book、Person、Work、Genre、Language、Country）反而没有。
dbbook2014 数据集实际用到的 84 个类中只有 23 个有 comment（27%）。
高层类恰好是跨数据集锚点，值得人工补写一句话定义。

**③ 层级断链**

50 个根类中混有本应挂靠的 fringe 类（本体声明缺失，非解析错误）：

- `dbo:PenaltyShootOut`（应挂 dbo:SportCompetitionResult 下）
- `dbo:GrossDomesticProduct` / `dbo:GrossDomesticProductPerCapita` / `dbo:HumanDevelopmentIndex`（应挂 dbo:Statistic 下）
- `dbo:ChartsPlacements`（应挂 dbo:Statistic 下）
- `dbo:Polyhedron`、`dbo:RouteStop` 等（无合适 dbo 父类，保持根类）

**④ 层级中的外部引用（轻微）**

仅 6 个值：`schema:Festival/MusicGroup/Organization/Product`、`dul:NaturalPerson/SocialPerson`。
清洗时直接丢弃（与类型归一化消除平行本体的目标一致）。

**⑤ 遗留脏 URI（已在 02c 防御）**

`dbo:Wikidata:Q11424` 这类脏类型断言来自 `instance_types_transitive_en.ttl` dump
（不是 ontology 的问题），02c 的 `is_valid_dbo_class`（恰好一个冒号）已拦截。

**⑥ 多值等价类消歧**

12 个多值 key 已按"人工消歧表 → 同名匹配 → 字母序"规则处理并打日志，
其中 `dul:Concept → dbo:TopicalConcept`、`dul:TimeInterval → dbo:Year` 来自人工消歧表；
`schema:Product → dbo:Aircraft`（字母序兜底）不理想但该类型不在本数据集中，暂接受。

## 二、处理流程（独立流水线，全局资产）

```
resources/
├── build_ontology.py            # Step 2：解析 owl + 应用 overrides → ontology.json (v2)
├── ontology_overrides.json      # Step 1：人工审核层（本文件第三节为建议稿）
├── build_ontology_prompts.py    # Step 3：760 个类的数据集无关 prompt（待写）
└── embeddings/
    ├── ontology_embeddings.npy          # Step 4 产物（L2）
    ├── ontology_embeddings_no_l2.npy    # Step 4 产物
    └── ontology_entities.dat            # 行号 ↔ dbo 类 URI
```

- **Step 1. 人工审核层**：`resources/ontology_overrides.json`，一次投入长期复用
  （等价表审核 ~19 条、断链挂靠 ~5 条、核心类定义 ~15 条）。
- **Step 2. build_ontology.py 应用 overrides**：等价表先过 overrides 再入库；
  层级去外部引用 + 应用 parent_patches；comment 合并 comment_patches。
- **Step 3. 生成 prompt**：每个 dbo 类 = label + 父类链 + 全量直接子类（>20 截断注明总数）
  + comment（含 patches）。模板为 `mvp_prompts.json` 新增 `ontology_class` 键，
  **不含 connected_item_descriptions**，保证跨数据集一致。
- **Step 4. 跑 04/05**：760 条 prompt，GPU 几分钟。产物存 `resources/embeddings/`。
- **Step 5. 每 KG 版本一份映射**：02c 输出 `ontology_map.dat`
  （`kg_entity_id \t dbo:ClassName`，格式对齐 `original_i2i_map.dat`），
  按 `catfreq{N}` 各一份；下游与 `ontology_entities.dat` join 得到行号映射。
  dbo 节点已排于 ID 空间末尾连续区间，`use_global_ontology_embeddings=true` 时
  在 data loader 按行替换即可。

**设计边界**：dbc 类别节点不参与（频次过滤的数据集产物，语义数据集相关）；
`ontology_embeddings.npy` 与 owl 版本（2016-10）绑定，换数据集无需重跑。

## 三、ontology_overrides.json 建议稿

### 3.1 equivalence_overrides（dul/d0 共 19 条逐条审核）

| 映射 | 建议 | 理由 |
| --- | --- | --- |
| d0:Activity → dbo:Activity | accept | 同名等价 |
| d0:CognitiveEntity → dbo:Ideology | **reject** | 认知实体≠意识形态 |
| d0:Location → dbo:Monastery | **reject** | 明显错误 |
| dul:Agent → dbo:Agent | accept | 同名等价 |
| dul:ChemicalObject → dbo:ChemicalSubstance | accept | 语义吻合 |
| dul:Collection → dbo:List | accept | 语义接近 |
| dul:Concept → dbo:TopicalConcept | accept | 人工消歧已选，语义吻合 |
| dul:Description → dbo:Tax | **reject** | 明显错误 |
| dul:DesignedArtifact → dbo:MeanOfTransportation | **reject** | 人造物范围远大于交通工具 |
| dul:Entity → dbo:Unknown | **reject** | dbo:Unknown 是垃圾兜底类 |
| dul:Event → dbo:Event | accept | 同名等价（已消歧掉 PenaltyShootOut） |
| dul:FunctionalSubstance → dbo:Food | **reject** | 明显错误 |
| dul:InformationObject → dbo:Database | **reject** | 信息对象≠数据库 |
| dul:NaturalPerson → dbo:Person | accept | 语义吻合 |
| dul:PlanExecution → dbo:Project | **reject** | 计划执行≠项目 |
| dul:Situation → dbo:LegalCase | **reject** | 明显错误 |
| dul:SocialPerson → dbo:Organisation | accept | DUL 中 SocialPerson 即组织 |
| dul:SpaceRegion → dbo:Polyhedron | **reject** | 明显错误 |
| dul:TimeInterval → dbo:Year | accept | 时间区间最接近 dbo:Year（可争议，倾向保留） |

实现方式：overrides 中 `reject` 的键从 class_equivalents 删除；
wd/schema/bibo/foaf/skos 的 374 条全部保留（质量高）。

### 3.2 parent_patches（断链挂靠，5 条）

```json
{
  "dbo:PenaltyShootOut": ["dbo:SportCompetitionResult"],
  "dbo:GrossDomesticProduct": ["dbo:Statistic"],
  "dbo:GrossDomesticProductPerCapita": ["dbo:Statistic"],
  "dbo:HumanDevelopmentIndex": ["dbo:Statistic"],
  "dbo:ChartsPlacements": ["dbo:Statistic"]
}
```

### 3.3 comment_patches（核心高层类一句话定义，15 条草稿）

```json
{
  "dbo:Work": "A distinct intellectual or artistic creation, such as a book, film, song, or other creative product.",
  "dbo:Book": "A written or printed work consisting of pages bound together, covering a particular subject or story.",
  "dbo:Person": "A human being, real or fictional, typically described by occupation, nationality, and life events.",
  "dbo:Agent": "An entity that can act or produce effects, such as a person or an organisation.",
  "dbo:Organisation": "A structured group of people with a shared purpose, such as a company, institution, or association.",
  "dbo:Place": "A physical location or geographic area, such as a city, country, building, or natural feature.",
  "dbo:Genre": "A category of artistic composition characterized by similarities in form, style, or subject matter.",
  "dbo:Language": "A system of communication used by a particular community or country.",
  "dbo:Country": "A nation with its own government, occupying a particular territory.",
  "dbo:Activity": "Something that a person or group does or has done, such as a sport, game, or occupation.",
  "dbo:Sport": "A physical activity governed by rules and often played competitively.",
  "dbo:Event": "Something that happens at a specific time and place, such as a competition, disaster, or historical occurrence.",
  "dbo:Writer": "A person who writes books, articles, or other texts, especially as an occupation.",
  "dbo:TopicalConcept": "An abstract concept used to classify entities by subject or theme.",
  "dbo:Media": "Means of mass communication, such as television, radio, newspapers, and the internet."
}
```
