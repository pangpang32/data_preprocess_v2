#!/usr/bin/env python3
"""
build_ontology.py

解析 DBpedia ontology (dbpedia_2016-10.owl)，生成轻量化的 ontology.json：
  - class_parents: 每个类的父类链（subClassOf）
  - class_labels: 每个类的 rdfs:label
  - property_domain: 属性的 domain
  - property_range: 属性的 range
  - property_labels: 属性的 rdfs:label

输出 ontology.json 供 01/02 等脚本使用。
"""
import os
import json
import argparse
import urllib.parse
from collections import defaultdict
from typing import Dict, List, Set
from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import shorten_uri


DBO = Namespace("http://dbpedia.org/ontology/")
RDF_NS = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDFS_NS = Namespace("http://www.w3.org/2000/01/rdf-schema#")


def collect_parents(graph: Graph, cls) -> List[str]:
    """通过 rdfs:subClassOf 递归收集所有父类。"""
    parents = []
    visited = set()
    stack = [cls]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        for parent in graph.objects(current, RDFS_NS.subClassOf):
            parent_str = str(parent)
            # 跳过 owl:Thing 等顶层类
            if parent_str == "http://www.w3.org/2002/07/owl#Thing":
                continue
            parents.append(parent_str)
            stack.append(parent)
    return parents


def get_label(graph: Graph, uri) -> str:
    """获取英文 rdfs:label，没有则返回缩短后的 URI。"""
    for label in graph.objects(uri, RDFS_NS.label):
        lang = getattr(label, "language", "")
        if lang and lang.lower() != "en":
            continue
        return str(label)
    return shorten_uri(str(uri))


def get_comment(graph: Graph, uri) -> str:
    """获取英文 rdfs:comment，没有则返回空字符串。"""
    for comment in graph.objects(uri, RDFS_NS.comment):
        lang = getattr(comment, "language", "")
        if lang and lang.lower() != "en":
            continue
        return str(comment)
    return ""


def build_ontology(owl_path: str, output_path: str):
    print(f"Loading ontology: {owl_path}")
    g = Graph()
    g.parse(owl_path, format="xml")
    print(f"  triples: {len(g)}")

    ontology = {
        "class_parents": {},
        "class_labels": {},
        "property_domain": {},
        "property_range": {},
        "property_labels": {},
        "class_equivalents": {},
        "class_comments": {},
    }

    # 1. 收集所有 owl:Class 和 rdfs:Class
    classes = set()
    for s in g.subjects(RDF.type, OWL.Class):
        classes.add(str(s))
    for s in g.subjects(RDF.type, RDFS_NS.Class):
        classes.add(str(s))

    for cls in sorted(classes):
        cls_short = shorten_uri(cls)
        parents = collect_parents(g, URIRef(cls))
        ontology["class_parents"][cls_short] = [shorten_uri(p) for p in parents]
        ontology["class_labels"][cls_short] = get_label(g, URIRef(cls))
        comment = get_comment(g, URIRef(cls))
        if comment:
            ontology["class_comments"][cls_short] = comment

    # 2. 收集所有 owl:ObjectProperty / owl:DatatypeProperty / rdf:Property
    properties = set()
    for s in g.subjects(RDF.type, OWL.ObjectProperty):
        properties.add(str(s))
    for s in g.subjects(RDF.type, OWL.DatatypeProperty):
        properties.add(str(s))
    for s in g.subjects(RDF.type, RDF_NS.Property):
        properties.add(str(s))

    for prop in sorted(properties):
        prop_short = shorten_uri(prop)
        domains = [str(d) for d in g.objects(URIRef(prop), RDFS_NS.domain)]
        ranges = [str(r) for r in g.objects(URIRef(prop), RDFS_NS.range)]
        ontology["property_domain"][prop_short] = [shorten_uri(d) for d in domains]
        ontology["property_range"][prop_short] = [shorten_uri(r) for r in ranges]
        ontology["property_labels"][prop_short] = get_label(g, URIRef(prop))

    # 3. 收集 owl:equivalentClass：非 dbo 类 -> dbo 类（02c 类型归一化用，替代手写映射表）
    # 多值时优先人工消歧表，其次同名类，最后按字母序取第一个；多值情况全部打印
    EQUIV_DISAMBIG = {
        "dul:Concept": "dbo:TopicalConcept",
        "dul:TimeInterval": "dbo:Year",
    }
    equiv_raw = defaultdict(list)
    for s in set(g.subjects(OWL.equivalentClass, None)):
        s_short = shorten_uri(str(s))
        for o in g.objects(s, OWL.equivalentClass):
            o_short = shorten_uri(str(o))
            if s_short.startswith("dbo:") and not o_short.startswith("dbo:"):
                equiv_raw[o_short].append(s_short)
            elif o_short.startswith("dbo:") and not s_short.startswith("dbo:"):
                equiv_raw[s_short].append(o_short)
    for ext, dbo_list in equiv_raw.items():
        dbo_list = sorted(set(dbo_list))
        if len(dbo_list) == 1:
            ontology["class_equivalents"][ext] = dbo_list[0]
            continue
        chosen = EQUIV_DISAMBIG.get(ext)
        if chosen is None:
            stem = ext.split(":", 1)[-1].lower()
            matches = [c for c in dbo_list if c.split(":", 1)[-1].lower() == stem]
            chosen = matches[0] if matches else dbo_list[0]
        ontology["class_equivalents"][ext] = chosen
        print(f"  equivalentClass multi-valued: {ext} -> {chosen} (candidates: {dbo_list})")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ontology, f, ensure_ascii=False, indent=2)
    print(f"Saved ontology to {output_path}")
    print(f"  classes: {len(ontology['class_parents'])}")
    print(f"  properties: {len(ontology['property_domain'])}")
    print(f"  equivalents: {len(ontology['class_equivalents'])}")
    print(f"  comments: {len(ontology['class_comments'])}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owl", type=str, default="dumps/dbpedia_files/dbpedia_2016-10.owl",
                        help="Path to dbpedia_2016-10.owl")
    parser.add_argument("--out", type=str, default="resources/ontology.json",
                        help="Output ontology.json path")
    args = parser.parse_args()
    build_ontology(args.owl, args.out)


if __name__ == "__main__":
    main()
