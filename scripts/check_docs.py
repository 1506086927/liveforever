#!/usr/bin/env python3
"""
病历文档一致性检查。

检查项：
 1. 全部 Markdown 文档中的相对链接是否指向存在的文件/锚点标题。
 2. 「2025-12-17」与「2026-09-04」两批铜梁化验的逐项比对，
    验证"2026-09-04 那批实为旧结果重打"这一结论。
 3. 关键临床数值在各文档间是否自相矛盾。

用法： python3 scripts/check_docs.py
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def discover_docs():
    """自动发现仓库根目录下所有 .md 文件，以及 docs/ 目录下（递归）的全部 .md。

    硬编码列表曾经漏掉新增文档，导致链接检查静默跳过它们
    （新增文件后仍报告旧的链接总数）。改为自动发现，
    并在有文件缺失时明确报错，而不是静默通过。
    """
    found = sorted(f for f in os.listdir(ROOT) if f.endswith(".md"))
    docs_dir = os.path.join(ROOT, "docs")
    if os.path.isdir(docs_dir):
        for dirpath, _dirs, files in os.walk(docs_dir):
            for f in files:
                if f.endswith(".md"):
                    found.append(os.path.relpath(os.path.join(dirpath, f), ROOT))
    return sorted(found)


DOCS = discover_docs()

# 这些文件是核心交付物，必须存在；缺失即为异常，不能静默通过。
REQUIRED_DOCS = [
    "诊疗方案-2026-09-11.md",
    "诊断与分期确认-2026-09.md",
    "补充资料-2019至2026完整病历.md",
    "病史整理.md",
    "紧急事项-2026-09-11.md",
    "费用与交涉手册-2026-09-12.md",
    "9月12日执行清单.md",
    "README.md",
]
_missing = [d for d in REQUIRED_DOCS if d not in DOCS]
if _missing:
    print("错误：以下核心文档缺失：%s" % ", ".join(_missing))
    sys.exit(2)

LAB_FILE = "补充资料-2019至2026完整病历.md"
LAB_MARKERS = {
    "2025-12-17": "#### LAB-2025-12-17",
    "2026-09-04": "#### LAB-2026-09-04",
}


# ---------------------------------------------------------------- helpers
def read(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


def strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def anchors(text: str) -> set[str]:
    """GitHub 风格锚点：小写、去标点、空格转 -"""
    out = set()
    for line in strip_code_fences(text).splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line.strip())
        if not m:
            continue
        raw = m.group(1).strip()
        slug = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", raw).strip().lower()
        out.add(slug.replace(" ", "-"))
        out.add(raw.lower().replace(" ", "-"))  # 宽松匹配
    return out


def headings_in_section(text: str, marker: str) -> str:
    """取出以 marker 开头到下一个 #### 之间的文本。"""
    idx = text.find(marker)
    if idx < 0:
        return ""
    rest = text[idx + len(marker):]
    nxt = rest.find("\n#### ")
    return rest if nxt < 0 else rest[:nxt]


def parse_lab_table(block: str) -> dict[str, str]:
    """解析 | 项目 | 结果 | 单位 | 表格 -> {项目: 结果}"""
    out: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name, value = cells[0], cells[1]
        if name in ("项目", "") or set(name) <= {"-", ":", " "}:
            continue
        out[name] = value
    return out


# 同一检验项目在不同医院报告中的写法差异（归一化后仍需人工确认）
SYNONYMS = {
    "胆碱脂酶": "胆碱酯酶",
    "γ-谷氨酰胺转肽酶": "γ-谷氨酰转肽酶",
    "人免疫缺陷病毒抗原/抗体": "人类免疫缺陷病毒抗原/抗体",
}
SYNONYMS = {re.sub(r"[\s\-_/()（）*]", "", k): re.sub(r"[\s\-_/()（）*]", "", v)
            for k, v in SYNONYMS.items()}


def norm(name: str) -> str:
    n = re.sub(r"[\s\-_/()（）*]", "", name)
    return SYNONYMS.get(n, n)


# ---------------------------------------------------------------- checks
def iter_md_links(text: str):
    """提取 [label](target)，target 允许包含成对的圆括号（CommonMark 行为）。"""
    for m in re.finditer(r"\[([^\]]*)\]\(", text):
        label = m.group(1)
        i = m.end()
        depth, out = 1, []
        while i < len(text) and depth:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            out.append(ch)
            i += 1
        if depth == 0:
            yield label, "".join(out)


def check_links() -> tuple[int, list[str]]:
    problems: list[str] = []
    total = 0
    for doc in DOCS:
        if not os.path.exists(os.path.join(ROOT, doc)):
            problems.append(f"[缺失文件] {doc} 不存在")
            continue
        text = strip_code_fences(read(doc))
        base = os.path.dirname(os.path.join(ROOT, doc))
        for label, target in iter_md_links(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            total += 1
            path_part, _, frag = target.partition("#")
            path_part = urllib.parse.unquote(path_part)
            if path_part:
                full = os.path.normpath(os.path.join(base, path_part))
                if not os.path.exists(full):
                    problems.append(f"[断链] {doc} -> {target} （{label}）")
                    continue
            if frag:
                tgt_doc = os.path.normpath(os.path.join(base, path_part)) if path_part \
                    else os.path.join(ROOT, doc)
                if tgt_doc.endswith(".md") and os.path.exists(tgt_doc):
                    rel = os.path.relpath(tgt_doc, ROOT)
                    if frag not in anchors(read(rel)):
                        problems.append(f"[断锚点] {doc} -> {target}")
    return total, problems


def check_duplicate_labs() -> tuple[dict, list[str]]:
    text = read(LAB_FILE)
    blocks = {k: headings_in_section(text, v) for k, v in LAB_MARKERS.items()}
    missing = [k for k, v in blocks.items() if not v]
    if missing:
        return {}, [f"[缺少 LAB 表] {missing}"]

    a = parse_lab_table(blocks["2025-12-17"])
    b = parse_lab_table(blocks["2026-09-04"])
    if not a or not b:
        return {}, ["[LAB 表解析失败] 未解析出任何项目"]

    a_norm = {norm(k): (k, v) for k, v in a.items()}
    b_norm = {norm(k): (k, v) for k, v in b.items()}

    identical, differing, near = [], [], []
    for key, (name_b, val_b) in b_norm.items():
        if key in a_norm:
            name_a, val_a = a_norm[key]
            if val_a.strip() == val_b.strip():
                identical.append((name_a, val_a, name_b))
            else:
                differing.append((name_a, val_a, name_b, val_b))
            continue
        # 近似名称匹配（处理 "γ-谷氨酰转肽酶/γ-谷氨酰胺转肽酶" 这类差异）
        cand = difflib.get_close_matches(key, list(a_norm), n=1, cutoff=0.8)
        if cand:
            name_a, val_a = a_norm[cand[0]]
            near.append((name_a, val_a, name_b, val_b, val_a.strip() == val_b.strip()))
        else:
            differing.append((None, None, name_b, val_b))

    stats = {
        "n_2025": len(a),
        "n_2026": len(b),
        "identical": len(identical),
        "near_name_same_value": sum(1 for x in near if x[4]),
        "near_name_diff_value": sum(1 for x in near if not x[4]),
        "differing": len(differing),
        "detail_identical": identical,
        "detail_near": near,
        "detail_differing": differing,
    }
    return stats, []


def check_key_values() -> list[str]:
    """关键数值应在各文档中一致出现。"""
    plan = read("诊疗方案-2026-09-11.md")
    diag = read("诊断与分期确认-2026-09.md")
    arch = read(LAB_FILE)
    problems = []
    expectations = {
        "CA-125 当前值 140.1": ["140.1"],
        "CA-125 术前值 26.9": ["26.9"],
        "骶前病灶 SUVmax 5.6": ["5.6"],
        "左腹横肌结节 1.2cm": ["1.2cm"],
        "MRI 层定位 Se901": ["Se901"],
        "D-二聚体当前 2.22": ["2.22"],
        "anti-HBc 4.538": ["4.538"],
        "原病理号 255317": ["255317"],
        "会诊病理号 H26-09047": ["H26-09047"],
        "EGFR 19 外显子缺失": ["p.E746_A750del"],
    }
    for label, needles in expectations.items():
        for needle in needles:
            if needle not in arch:
                problems.append(f"[归档缺失] {label}（'{needle}' 未出现在补充资料中）")
            if needle not in plan and needle not in diag:
                problems.append(f"[方案未引用] {label}（'{needle}' 未出现在方案/诊断文件中）")

    # 旧值 0.17（2025-12-17 的 D-二聚体）只允许出现在"纠错/说明旧值"的语境中，
    # 不得被当作当前值引用。
    CORRECTION_WORDS = ("旧", "重打", "互认", "调阅", "不是新", "不是当前", "真实当前",
                        "错误", "纠正", "纠错", "误")
    for doc_name, text in (("诊疗方案", plan), ("诊断与分期", diag),
                           ("README", read("README.md"))):
        for sec_title, sec_body in iter_sections(text):
            if "0.17" not in sec_body:
                continue
            ok = any(w in sec_title for w in CORRECTION_WORDS) or \
                any(w in sec_body for w in CORRECTION_WORDS)
            if not ok:
                problems.append(
                    f"[数值误用] {doc_name} 小节「{sec_title}」出现旧值 0.17，"
                    f"但该小节未说明它是旧值")
    return problems


def iter_sections(text: str):
    """按标题切分，产出 (标题, 小节正文含标题行)。"""
    lines = text.splitlines()
    title, buf = "(文首)", []
    for line in lines:
        if re.match(r"^#{1,6}\s+", line):
            yield title, "\n".join(buf)
            title = line.lstrip("#").strip()
            buf = [line]
        else:
            buf.append(line)
    yield title, "\n".join(buf)


# ---------------------------------------------------------------- main
def main() -> int:
    failed = False
    print("=" * 72)
    print("病历文档一致性检查")
    print("=" * 72)

    total, link_problems = check_links()
    root_docs = [d for d in DOCS if os.sep not in d and "/" not in d]
    sub_docs = [d for d in DOCS if d not in root_docs]
    print(f"\n[1] 相对链接/锚点：共 {total} 个（扫描 {len(DOCS)} 个文档："
          f"根目录 {len(root_docs)} 个：{', '.join(root_docs)}；docs/ 下 {len(sub_docs)} 个）")
    if link_problems:
        failed = True
        for p in link_problems:
            print("    ✗", p)
    else:
        print(f"    ✓ 全部 {total} 个链接与锚点均可解析")

    stats, lab_problems = check_duplicate_labs()
    print("\n[2] 铜梁化验重复性比对（2025-12-17 vs 2026-09-04）")
    if lab_problems:
        failed = True
        for p in lab_problems:
            print("    ✗", p)
    else:
        print(f"    2025-12-17 项目数：{stats['n_2025']}")
        print(f"    2026-09-04 项目数：{stats['n_2026']}")
        print(f"    同名同值：{stats['identical']}")
        print(f"    近似同名且同值：{stats['near_name_same_value']}")
        print(f"    近似同名但不同值：{stats['near_name_diff_value']}")
        print(f"    无法匹配/不同值：{stats['differing']}")
        matched = (stats["identical"] + stats["near_name_same_value"]
                   + stats["near_name_diff_value"])
        same = stats["identical"] + stats["near_name_same_value"]
        pct = 100.0 * same / matched if matched else 0.0
        print(f"    → 可比对 {matched} 项中 {same} 项数值完全一致（{pct:.1f}%）")
        if stats["detail_near"]:
            print("    近似同名项目：")
            for name_a, val_a, name_b, val_b, ok in stats["detail_near"]:
                print(f"      {'✓' if ok else '✗'} 「{name_a}={val_a}」 ~ 「{name_b}={val_b}」")
        if stats["detail_differing"]:
            print("    不同值项目：")
            for row in stats["detail_differing"]:
                print("      ✗", row)
        if pct >= 99.0 and stats["differing"] == 0:
            print("    ✓ 结论成立：2026-09-04 那批化验为 2025-12-17 结果的重打/互认调阅")
        else:
            failed = True
            print(f"    ✗ 一致率 {pct:.1f}%、不匹配 {stats['differing']} 项，"
                  "'重复报告'结论需要重新评估")

    print("\n[3] 文档中声明的比对项数 vs 实际计算项数")
    declared_problems = []
    if stats:
        actual = (stats["identical"] + stats["near_name_same_value"]
                  + stats["near_name_diff_value"])
        for doc in DOCS:
            if not os.path.exists(os.path.join(ROOT, doc)):
                continue
            for n in re.findall(r"(\d+)\s*项(?:逐项)?比对", read(doc)):
                if int(n) != actual:
                    declared_problems.append(
                        f"[计数不符] {doc} 声明 {n} 项比对，实际可比对 {actual} 项")
    if declared_problems:
        failed = True
        for p_ in declared_problems:
            print("    ✗", p_)
    else:
        print(f"    ✓ 文档声明的比对项数与脚本计算一致（{actual if stats else 'N/A'} 项）")

    print("\n[4] 关键临床数值交叉引用")
    val_problems = check_key_values()
    if val_problems:
        failed = True
        for p in val_problems:
            print("    ✗", p)
    else:
        print("    ✓ 10 组关键数值在归档与方案/诊断文件间一致")

    print("\n" + "=" * 72)
    print("结果：" + ("✗ 存在问题" if failed else "✓ 全部通过"))
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
