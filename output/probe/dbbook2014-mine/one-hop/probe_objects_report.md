# 宾语（types / categories）分布分析报告

数据集：`dbbook2014-mine-one-hop`

## 1. 总体统计

- 实体总数：4660
- 含 categories 的实体数：3849（平均 9.98 个/实体）
- 含 types 的实体数：3393（平均 8.99 个/实体）
- 不同 dbc 类别数：14213，引用总次数：38407
- 不同类型数（全前缀）：151，引用总次数：30499
- 没有任何 dbo: 类型的实体数：392
- 类型仅有 owl:Thing 的实体数：392

## 2. categories（dbc）频次阈值表

> 行含义：仅保留至少被 k 个实体共享的类别时，剩下的类别节点数与类别边总数。
> 用于权衡"类别节点的共享度"与"引入的边数/噪声"。

| 最小共享实体数 k | 保留类别数 | 保留类别边数 |
|---|---|---|
| 1 | 14213 | 38407 |
| 2 | 4899 | 29093 |
| 3 | 2827 | 24949 |
| 5 | 1490 | 20469 |
| 10 | 595 | 14775 |
| 20 | 201 | 9574 |
| 50 | 43 | 5110 |
| 100 | 15 | 3301 |

## 3. categories（dbc）Top 50

| 类别 | 共享实体数 |
|---|---|
| dbc:Living_people | 725 |
| dbc:20th-century_American_novelists | 408 |
| dbc:21st-century_American_novelists | 333 |
| dbc:American_male_novelists | 286 |
| dbc:20th-century_women_writers | 240 |
| dbc:American_women_novelists | 204 |
| dbc:21st-century_women_writers | 200 |
| dbc:American_fantasy_novels | 149 |
| dbc:American_science_fiction_writers | 115 |
| dbc:American_children's_writers | 113 |
| dbc:20th-century_English_novelists | 113 |
| dbc:HarperCollins_books | 105 |
| dbc:American_fantasy_writers | 104 |
| dbc:Women_science_fiction_and_fantasy_writers | 103 |
| dbc:20th-century_American_short_story_writers | 103 |
| dbc:American_male_short_story_writers | 96 |
| dbc:American_science_fiction_novels | 91 |
| dbc:Postmodern_writers | 87 |
| dbc:21st-century_American_short_story_writers | 83 |
| dbc:Sequel_novels | 79 |
| dbc:Novels_first_published_in_serial_form | 76 |
| dbc:Fantasy_novels | 75 |
| dbc:20th-century_American_writers | 74 |
| dbc:Guggenheim_Fellows | 74 |
| dbc:Fellows_of_the_Royal_Society_of_Literature | 70 |
| dbc:2000s_fantasy_novels | 68 |
| dbc:Tor_Books_books | 68 |
| dbc:American_novels_adapted_into_films | 62 |
| dbc:Women_children's_writers | 59 |
| dbc:American_young_adult_novels | 59 |
| dbc:American_essayists | 56 |
| dbc:Book_publishing_companies_based_in_New_York | 55 |
| dbc:1990s_science_fiction_novels | 55 |
| dbc:Children's_fantasy_novels | 55 |
| dbc:American_women_short_story_writers | 54 |
| dbc:Writers_from_New_York_City | 54 |
| dbc:Hugo_Award-winning_writers | 53 |
| dbc:Book_publishing_companies_of_the_United_Kingdom | 53 |
| dbc:Fantasy_novel_series | 52 |
| dbc:Alfred_A._Knopf_books | 51 |
| dbc:British_fantasy_novels | 50 |
| dbc:20th-century_short_story_writers | 50 |
| dbc:American_memoirists | 50 |
| dbc:English_male_novelists | 49 |
| dbc:National_Book_Award_winners | 48 |
| dbc:Jewish_American_writers | 47 |
| dbc:LGBT_novelists | 47 |
| dbc:Del_Rey_books | 47 |
| dbc:British_novels_adapted_into_films | 46 |
| dbc:LGBT_writers_from_the_United_States | 46 |

## 4. types 按命名空间前缀统计

| 前缀 | 类型实例次数 | 去重类型数 |
|---|---|
| dbo | 9031 | 78 |
| wd | 8089 | 49 |
| schema | 4570 | 13 |
| owl | 3393 | 1 |
| dul | 2732 | 7 |
| bibo | 1517 | 1 |
| foaf | 1164 | 1 |
| d0 | 3 | 1 |

## 5. types 频次阈值表（全前缀 vs 仅 dbo）

| 最小共享实体数 k | 保留类型数（全前缀） | 保留边数（全前缀） | 保留类型数（仅 dbo） | 保留边数（仅 dbo） |
|---|---|---|---|---|
| 1 | 151 | 30499 | 78 | 9031 |
| 2 | 86 | 30434 | 42 | 8995 |
| 3 | 73 | 30408 | 34 | 8979 |
| 5 | 64 | 30378 | 29 | 8962 |
| 10 | 47 | 30283 | 20 | 8912 |
| 20 | 45 | 30261 | 18 | 8890 |
| 50 | 30 | 29765 | 12 | 8692 |
| 100 | 26 | 29562 | 9 | 8540 |

## 6. types Top 50（全前缀）

| 类型 | 共享实体数 |
|---|---|
| owl:Thing | 3393 |
| dbo:Work | 1546 |
| wd:Q386724 | 1546 |
| schema:CreativeWork | 1546 |
| dbo:WrittenWork | 1535 |
| dbo:Book | 1517 |
| bibo:Book | 1517 |
| schema:Book | 1517 |
| wd:Q571 | 1517 |
| dbo:Agent | 1362 |
| dul:Agent | 1362 |
| wd:Q24229398 | 1362 |
| wd:Q215627 | 1164 |
| schema:Person | 1164 |
| dul:NaturalPerson | 1164 |
| dbo:Person | 1164 |
| foaf:Person | 1164 |
| wd:Q5 | 1164 |
| dbo:Writer | 848 |
| wd:Q36180 | 848 |
| wd:Q43229 | 198 |
| dul:SocialPerson | 198 |
| schema:Organization | 198 |
| dbo:Organisation | 198 |
| dbo:Company | 194 |
| dbo:Publisher | 176 |
| dbo:Place | 51 |
| dbo:Location | 51 |
| schema:Place | 51 |
| dbo:PopulatedPlace | 50 |
| dbo:Country | 46 |
| schema:Country | 46 |
| wd:Q6256 | 46 |
| wd:Q901 | 37 |
| dbo:Scientist | 37 |
| wd:Q4964182 | 34 |
| dbo:Philosopher | 34 |
| dbo:FictionalCharacter | 31 |
| wd:Q95074 | 31 |
| wd:Q34770 | 27 |
| schema:Language | 27 |
| wd:Q315 | 27 |
| dbo:Language | 27 |
| dbo:Artist | 23 |
| wd:Q483501 | 23 |
| dbo:OfficeHolder | 12 |
| dbo:ComicsCreator | 10 |
| wd:Q1092563 | 7 |
| dbo:PeriodicalLiterature | 7 |
| schema:MusicGroup | 7 |
