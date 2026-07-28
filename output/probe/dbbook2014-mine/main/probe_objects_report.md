# 宾语（types / categories）分布分析报告

数据集：`dbbook2014-mine-main`

## 1. 总体统计

- 实体总数：2680
- 含 categories 的实体数：2658（平均 6.29 个/实体）
- 含 types 的实体数：2680（平均 8.87 个/实体）
- 不同 dbc 类别数：4955，引用总次数：16716
- 不同类型数（全前缀）：27，引用总次数：23770
- 没有任何 dbo: 类型的实体数：1
- 类型仅有 owl:Thing 的实体数：1

## 2. categories（dbc）频次阈值表

> 行含义：仅保留至少被 k 个实体共享的类别时，剩下的类别节点数与类别边总数。
> 用于权衡"类别节点的共享度"与"引入的边数/噪声"。

| 最小共享实体数 k | 保留类别数 | 保留类别边数 |
|---|---|---|
| 1 | 4955 | 16716 |
| 2 | 2181 | 13942 |
| 3 | 1345 | 12270 |
| 5 | 757 | 10273 |
| 10 | 322 | 7457 |
| 20 | 116 | 4764 |
| 50 | 23 | 2066 |
| 100 | 7 | 1006 |

## 3. categories（dbc）Top 50

| 类别 | 共享实体数 |
|---|---|
| dbc:American_novels_adapted_into_films | 203 |
| dbc:American_fantasy_novels | 172 |
| dbc:American_science_fiction_novels | 150 |
| dbc:Debut_novels | 148 |
| dbc:Novels_first_published_in_serial_form | 123 |
| dbc:HarperCollins_books | 107 |
| dbc:British_novels_adapted_into_films | 103 |
| dbc:American_young_adult_novels | 95 |
| dbc:Alfred_A._Knopf_books | 91 |
| dbc:Doubleday_(publisher)_books | 84 |
| dbc:Fantasy_novels | 77 |
| dbc:1990s_science_fiction_novels | 68 |
| dbc:2000s_fantasy_novels | 65 |
| dbc:Novels_set_in_New_York_City | 65 |
| dbc:Tor_Books_books | 62 |
| dbc:2005_American_novels | 62 |
| dbc:American_children's_novels | 60 |
| dbc:Dystopian_novels | 58 |
| dbc:Metafictional_novels | 57 |
| dbc:Viking_Press_books | 57 |
| dbc:2003_American_novels | 55 |
| dbc:Children's_fantasy_novels | 54 |
| dbc:Novels_set_in_London | 50 |
| dbc:Sequel_novels | 48 |
| dbc:Del_Rey_books | 47 |
| dbc:1990s_fantasy_novels | 46 |
| dbc:British_children's_novels | 45 |
| dbc:2001_American_novels | 43 |
| dbc:1999_American_novels | 42 |
| dbc:2002_American_novels | 42 |
| dbc:Jonathan_Cape_books | 41 |
| dbc:British_fantasy_novels | 41 |
| dbc:English-language_books | 41 |
| dbc:2006_American_novels | 40 |
| dbc:2000s_science_fiction_novels | 40 |
| dbc:Random_House_books | 39 |
| dbc:Postmodern_novels | 39 |
| dbc:English_novels | 39 |
| dbc:Hugo_Award_for_Best_Novel-winning_works | 39 |
| dbc:1960s_science_fiction_novels | 39 |
| dbc:2004_American_novels | 39 |
| dbc:Ace_Books_books | 37 |
| dbc:Novels_about_orphans | 36 |
| dbc:Historical_novels | 36 |
| dbc:1980s_science_fiction_novels | 36 |
| dbc:19th-century_British_novels | 35 |
| dbc:Fiction_with_unreliable_narrators | 35 |
| dbc:British_science_fiction_novels | 35 |
| dbc:American_historical_novels | 34 |
| dbc:1996_American_novels | 34 |

## 4. types 按命名空间前缀统计

| 前缀 | 类型实例次数 | 去重类型数 |
|---|---|
| dbo | 7999 | 12 |
| wd | 5321 | 10 |
| schema | 5225 | 3 |
| owl | 2658 | 1 |
| bibo | 2567 | 1 |

## 5. types 频次阈值表（全前缀 vs 仅 dbo）

| 最小共享实体数 k | 保留类型数（全前缀） | 保留边数（全前缀） | 保留类型数（仅 dbo） | 保留边数（仅 dbo） |
|---|---|---|---|---|
| 1 | 27 | 23770 | 12 | 7999 |
| 2 | 21 | 23764 | 9 | 7996 |
| 3 | 21 | 23764 | 9 | 7996 |
| 5 | 19 | 23758 | 8 | 7993 |
| 10 | 15 | 23730 | 6 | 7979 |
| 20 | 13 | 23710 | 5 | 7969 |
| 50 | 9 | 23574 | 3 | 7901 |
| 100 | 9 | 23574 | 3 | 7901 |

## 6. types Top 50（全前缀）

| 类型 | 共享实体数 |
|---|---|
| owl:Thing | 2658 |
| schema:CreativeWork | 2657 |
| dbo:Work | 2657 |
| wd:Q386724 | 2657 |
| dbo:WrittenWork | 2656 |
| dbo:Book | 2588 |
| wd:Q571 | 2567 |
| schema:Book | 2567 |
| bibo:Book | 2567 |
| wd:Q245068 | 38 |
| dbo:Comic | 38 |
| wd:Q25379 | 30 |
| dbo:Play | 30 |
| dbo:Manga | 10 |
| wd:Q8274 | 10 |
| dbo:PeriodicalLiterature | 9 |
| wd:Q1092563 | 9 |
| dbo:Magazine | 5 |
| wd:Q41298 | 5 |
| wd:Q11032 | 3 |
| dbo:Newspaper | 3 |
| dbo:AcademicJournal | 1 |
| wd:Q737498 | 1 |
| dbo:Song | 1 |
| schema:MusicRecording | 1 |
| wd:Q2188189 | 1 |
| dbo:MusicalWork | 1 |
