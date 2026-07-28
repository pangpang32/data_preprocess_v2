#!/usr/bin/env python3
"""DBpedia 英文核心文件下载脚本 - 简洁版"""

import os
import urllib.request

# ==================== 用户配置区 ====================

# 目标下载目录（留空，会自动创建）
DOWNLOAD_DIR = "./dbpedia_files"

# 当前采用的主链接索引（0=2016旧版, 1=2022新版）
ACTIVE_URL_INDEX = 0

# 主链接列表
BASE_URLS = [
    # 0: 2016-10 旧版 - 路径稳定，文档完善，推荐
    "http://downloads.dbpedia.org/2016-10/core-i18n/en/",
    # 1: 2022-09 新版 - Databus系统，路径可能变化（我没有试过）
    "https://downloads.dbpedia.org/repo/dbpedia/",
]

# 需要下载的文件列表（文件名 + 注释说明）
FILES = [
    # 长摘要：实体的详细描述文本，通常500-3000字符
    # ("long_abstracts_en.ttl.bz2", "长摘要（Long Abstracts）- 实体详细描述"),
    # # 短摘要：实体的精简描述，约500字符以内
    # ("short_abstracts_en.ttl.bz2", "短摘要（Short Abstracts）- 实体精简描述"),
    # # 标签：实体的多语言名称（英文版只含英文标签）
    # ("labels_en.ttl.bz2", "标签（Labels）- 实体英文名称"),
    # # 实体类型：实体所属的本体类（如 Book, Person, City）
    # ("instance_types_en.ttl.bz2", "实体类型（Instance Types）- 具体类型"),
    # # 传递闭包类型：包含父类继承关系（如 Novel -> WrittenWork -> Work）
    # ("instance_types_transitive_en.ttl.bz2", "传递类型（Transitive Types）- 含继承链"),
    # # 对象属性：实体间的关系（如 author, publisher, country）
    # ("mappingbased_objects_en.ttl.bz2", "对象属性（Object Properties）- 实体间关系"),
    # # 数据属性：实体的字面量特征（如 publicationDate, isbn, pages）
    # ("mappingbased_literals_en.ttl.bz2", "数据属性（Datatype Properties）- 字面量特征"),
    # ("article_categories_en.ttl.bz2", ""),
    # ("dbpedia_2016-10.owl", ""),
    # ("redirects_en.ttl.bz2", ""),
    # ("disambiguations_en.ttl.bz2", ""),
]

# ==================== 下载函数 ====================

def download_file(url, save_path):
    """下载单个文件并显示进度"""
    print(f"\n下载: {os.path.basename(save_path)}")
    print(f"URL: {url}")

    try:
        urllib.request.urlretrieve(url, save_path)
        size = os.path.getsize(save_path) / (1024 * 1024)
        print(f"完成: {size:.1f} MB")
        return True
    except Exception as e:
        print(f"失败: {e}")
        return False

# ==================== 主程序 ====================

if __name__ == "__main__":
    # 创建下载目录
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print(f"下载目录: {os.path.abspath(DOWNLOAD_DIR)}")
    print(f"使用版本: {'2016-10 旧版' if ACTIVE_URL_INDEX == 0 else '2022-09 新版'}")
    print(f"主链接: {BASE_URLS[ACTIVE_URL_INDEX]}")

    # 循环下载每个文件
    for filename, description in FILES:
        url = BASE_URLS[ACTIVE_URL_INDEX] + filename
        save_path = os.path.join(DOWNLOAD_DIR, filename)

        # 如果文件已存在则跳过
        if os.path.exists(save_path):
            size = os.path.getsize(save_path) / (1024 * 1024)
            print(f"\n跳过（已存在）: {filename} ({size:.1f} MB)")
            continue

        print(f"\n{'='*50}")
        print(f"文件: {filename}")
        print(f"说明: {description}")
        print(f"{'='*50}")

        download_file(url, save_path)

    print("\n" + "="*50)
    print("下载完成！")
    print(f"文件保存在: {os.path.abspath(DOWNLOAD_DIR)}")
    print("="*50)
