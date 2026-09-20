#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成《术前卡片包 · 打印版》.docx

用法： python3 scripts/make_cardpack_docx.py
输出： 卡片包-打印版-2026-09-20.docx（仓库根目录）

排版约定：
  · A4，页边距 1.4–1.6cm，正文宋体 10pt（西文 Calibri），行距单倍
  · 每张卡从新页开始，可单独抽出带走
  · 以「＋」开头的行 = 2026-09-20 新增内容（深蓝色），删掉即为 v3 原样
  · 卡 N（术后记录表）用横向页面；卡 M（红旗卡）用大字，便于贴床头
"""
from __future__ import annotations

import os

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "卡片包-打印版-2026-09-20.docx")

BODY = "宋体"
HEAD = "微软雅黑"
NEW = RGBColor(0x1F, 0x4E, 0x79)      # 新增内容：深蓝（黑白打印呈深灰）
NOTE = RGBColor(0x59, 0x59, 0x59)     # 注/因/源：灰
RED = RGBColor(0xC0, 0x00, 0x00)      # 红线


# --------------------------------------------------------------- low level
# pPr/tcPr 子元素顺序在 OOXML 中是强制的，shd / pBdr 必须插在 spacing、ind、jc 之前
_PPR_SUCCESSORS = ("w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
                   "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
                   "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
                   "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                   "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
                   "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr")
_TCPR_SUCCESSORS = ("w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd",
                    "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign",
                    "w:hideMark")


def _insert_ordered(parent, el, successors):
    """把 el 插到 parent 中第一个「应排在其后」的元素之前；找不到就追加。"""
    for tag in successors:
        found = parent.find(qn(tag))
        if found is not None:
            found.addprevious(el)
            return
    parent.append(el)


def set_run(run, size=10, bold=False, color=None, font=BODY, italic=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = font
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:eastAsia"), font)
    rf.set(qn("w:ascii"), font)
    rf.set(qn("w:hAnsi"), font)
    return run


def para(doc, text="", size=10, bold=False, color=None, font=BODY,
         before=0, after=2, left=0.0, first_line=0.0, spacing=1.0,
         align=None, shade=None, border_bottom=False, keep_with_next=False):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = spacing
    pf.left_indent = Cm(left)
    pf.first_line_indent = Cm(first_line)
    pf.keep_with_next = keep_with_next
    if align is not None:
        p.alignment = align
    if text:
        set_run(p.add_run(text), size=size, bold=bold, color=color, font=font)
    if shade:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), shade)
        _insert_ordered(p._p.get_or_add_pPr(), shd, _PPR_SUCCESSORS)
    if border_bottom:
        pbdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "12")
        bottom.set(qn("w:space"), "2")
        bottom.set(qn("w:color"), "808080")
        pbdr.append(bottom)
        _insert_ordered(p._p.get_or_add_pPr(), pbdr,
                        ("w:shd",) + _PPR_SUCCESSORS)
    return p


def page_break(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run()
    run.add_break(WD_BREAK.PAGE)
    return p


def card_head(doc, title, tag=None):
    p = para(doc, before=0, after=4, shade="D9D9D9",
             border_bottom=True, keep_with_next=True)
    set_run(p.add_run(title), size=13, bold=True, font=HEAD)
    if tag:
        set_run(p.add_run("　" + tag), size=10, bold=True, font=HEAD, color=NEW)
    return p


def h(doc, text, size=10.5):
    return para(doc, text, size=size, bold=True, before=4, after=1,
                keep_with_next=True)


def q(doc, text, size=10):
    return para(doc, text, size=size, left=0.45, after=1)


def n(doc, text, size=8):
    return para(doc, text, size=size, color=NOTE, left=0.45, after=1)


def plus(doc, text, size=10):
    return para(doc, text, size=size, color=NEW, left=0.45, after=1)


def li(doc, text, size=10, left=0.45):
    return para(doc, "· " + text, size=size, left=left, after=1)


def bullet_box(doc, text, size=10, shade="F2F2F2"):
    return para(doc, text, size=size, left=0.2, after=1, shade=shade)


def footer_with_page(section, text):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(text + "　·　第 "), size=8, color=NOTE)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "16")
    rpr.append(sz)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = "1"
    run.append(t)
    fld.append(run)
    p._p.append(fld)
    set_run(p.add_run(" 页"), size=8, color=NOTE)


def new_section(doc, landscape=False):
    s = doc.add_section(WD_SECTION.NEW_PAGE)
    if landscape:
        s.orientation = WD_ORIENT.LANDSCAPE
        s.page_width, s.page_height = Cm(29.7), Cm(21.0)
    else:
        s.orientation = WD_ORIENT.PORTRAIT
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
    s.top_margin = s.bottom_margin = Cm(1.3)
    s.left_margin = s.right_margin = Cm(1.5)
    s.footer.is_linked_to_previous = True
    return s


def make_table(doc, headers, rows, widths=None, size=8.5, header_fill="D9D9D9"):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    hdr = t.rows[0].cells
    for i, txt in enumerate(headers):
        cell = hdr[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(p.add_run(txt), size=size, bold=True, font=HEAD)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), header_fill)
        _insert_ordered(cell._tc.get_or_add_tcPr(), shd, _TCPR_SUCCESSORS[3:])
    for row in rows:
        cells = t.add_row().cells
        for i, txt in enumerate(row):
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            set_run(p.add_run(str(txt)), size=size)
    if widths:
        for r in t.rows:
            for i, w in enumerate(widths):
                r.cells[i].width = Cm(w)
    return t


# --------------------------------------------------------------- document
def build() -> None:
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.size = Pt(10)
    normal.font.name = BODY
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.0

    s0 = doc.sections[0]
    s0.page_width, s0.page_height = Cm(21.0), Cm(29.7)
    s0.top_margin = s0.bottom_margin = Cm(1.3)
    s0.left_margin = s0.right_margin = Cm(1.5)
    footer_with_page(s0, "术前卡片包 v3＋补充 · 曹雪梅 · 2026-09-20")

    # ============================================================ 封面 / 总则
    para(doc, "术前卡片包 · 打印版", size=20, bold=True, font=HEAD,
         after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "v3 ＋ 2026-09-20 补充（手术日：2026-09-22 周二）", size=11,
         font=HEAD, color=NEW, after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "患者 曹雪梅（女，1966-12-07）　重庆大学附属肿瘤医院",
         size=10, color=NOTE, after=6, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "每张卡从新页开始，可单独抽出随身带。以「＋」开头的行是 2026-09-20 新增内容；"
              "只想用 v3 原样时，把「＋」行删掉即可。",
         size=9, color=NOTE, after=6)

    h(doc, "🔴 王牌开场（万能，一句压场）")
    q(doc, "「9-18 的病理报告原文就建议做分子检测协诊——我们只是在执行。」")

    h(doc, "🔴 三不要")
    li(doc, "不提公众号/探论名　·　不说“要定制方案”　·　不当场争")

    h(doc, "🔴 记录法")
    li(doc, "时间、数字、名字、下一步找谁 —— 记在卡片背面。当天的记录，就是下一次对话的底气。")

    h(doc, "🔴 卡序（原版）")
    q(doc, "周日（A 若签字、B 若访视）→ 周一（C＋J 递上、D 门口、H 电话）→ 周二手术（E 当天起、F 周三起）"
           "→ 周二后（K 电话）→ 送样日（G）→ 报告日（L）")
    plus(doc, "＋ 时间要留活口：麻醉访视多在术前一晚或术日晨（不是周日）；卡 H 放午间，别和卡 C 的早查房撞；"
              "铜梁病案室（卡 K）周一先打电话，人/邮寄排在术后。")

    h(doc, "🔴 三个必须记住的日期（本版新增）", size=11)
    bullet_box(doc, "①  9/24（周四）—— 白片/样本必须送出。晚了撞中秋（9/25–27）与国庆（10/1–7），"
                    "报告会滑到 10 月中下旬。", size=10.5)
    bullet_box(doc, "②  10/20–11/3 —— 术后 4–6 周全身治疗窗口（按 9/22 手术算）。"
                    "国庆后门诊最挤，现在就把日期预留出来。", size=10.5)
    bullet_box(doc, "③  假期：9/25–27、10/1–7 —— 收样、切片、出报告分别怎么算工作日？先问清（卡 H、卡 I）。",
               size=10.5)

    h(doc, "🔴 标记说明")
    li(doc, "⭐⭐ 必须办到　｜　⭐ 尽量问到　｜　【注】术语　｜　【因】为什么问　｜　【源】依据　｜　＋ 本次新增")

    page_break(doc)   # 保证第 1 页＝封面/总则、第 2 页＝目录，后面每卡独立起页，页码可对上
    h(doc, "🔴 目录与打印份数（本版新增）")
    make_table(
        doc,
        ["页", "卡片", "用在哪 / 打印几份"],
        [
            ["1", "封面 / 总则（王牌开场、三不要、卡序、三个日期）", "自留 1 份"],
            ["2", "目录与打印份数　← 本页", "自留 1 份"],
            ["3", "A · 主刀/签字医生", "术前谈话，1 份（背面记回答）"],
            ["4", "B · 麻醉访视", "1 份"],
            ["5", "C · 管床医生（第一接口）", "周一早查房，1 份"],
            ["6", "D · 主治/教授（门口）", "1 份"],
            ["7", "E · 责任护士（术后当天起）", "1 份"],
            ["8", "F · 病理窗口（周三起）", "1 份"],
            ["9", "G · 检测中心窗口（送样日）", "1 份"],
            ["10", "H · 附一客服（周一）", "1 份"],
            ["11", "I · 金域/第三方", "1 份"],
            ["12", "J · MDT 带话纸", "打印 3 份（主治、MDT、自留）"],
            ["13", "K · 铜梁病案室", "1 份"],
            ["14", "L · 报告日＋化疗前启动（新）", "1 份"],
            ["15", "M · 术后红旗卡（新）", "打印 2 份（床头、随身各 1）"],
            ["16", "N · 术后每日记录表（新）", "打印 7 份（一天一张）"],
            ["17", "O · 出院日（新）", "1 份"],
            ["18", "P · 术前一天清单（新）", "1 份"],
            ["19", "附录 1 · 口径待核实 8 条", "自留（不交医生）"],
            ["20", "附录 2 · 钥匙句速查", "自留 1 份"],
        ],
        widths=[1.4, 6.0, 10.4], size=9,
    )

    para(doc, "⚠️ 本文件为病历资料整理与沟通用话术，不构成医疗建议；所有治疗决策由主诊医生/MDT 做出。",
         size=8.5, color=NOTE, before=6)

    # ============================================================ 卡 A
    new_section(doc)
    card_head(doc, "卡 A · 主刀 / 签字医生 · 术前谈话", "⭐⭐")
    h(doc, "开场")
    q(doc, "「医生，签字前想确认几个问题，两分钟。」")

    h(doc, "① 范围 ⭐⭐")
    q(doc, "「这次计划切哪些病灶？哪些位置因为风险高打算保留？」")
    plus(doc, "＋①b ⭐⭐ 「这次手术的目标是什么？如果做减瘤，目标是肉眼无残留（CC-0）吗？」")
    n(doc, "　【因】目标不定，术后“还剩多少”没人答得上来；也决定要不要叫腹膜肿瘤/HIPEC 团队上台。")
    plus(doc, "＋①c ⭐⭐ 「需要切肠管（直肠/乙状结肠）、大网膜、阑尾吗？可能要临时造口吗？」")
    n(doc, "　【注】骶前 5.5×6.1cm 与直肠上段、乙状结肠分界不清（PET/CT 原文）。")
    n(doc, "　【因】可能要造口，就得提前备好造口护理与陪护方案；同意书范围也要覆盖。")
    plus(doc, "＋①d ⭐ 「切下来的东西会送腹腔冲洗液细胞学吗？」")
    n(doc, "　【因】冲洗液阳性＝腹腔种植的证据；12 月的手术记录未提及是否送检。")
    plus(doc, "＋①e ⭐⭐ 「如果开腹发现切不净，会取活检并把残留位置与大小（CC 评分）写进手术记录吗？」")
    n(doc, "　【因】残留的准确记录，是后续放疗/化疗/临床试验入组的依据。")
    n(doc, "【注】减瘤＝尽量切可见病灶；切净叫 R0　【因】留下的病灶就是术后化疗/安罗替尼的战场　【源】ESGO 2024：完全减瘤改善生存")

    h(doc, "② 术中预案 ⭐")
    q(doc, "「如果开腹后发现比影像多、或粘连严重，是继续减瘤还是探查后关腹？什么情况改计划？」")
    plus(doc, "＋②b ⭐⭐ 「今天签的同意书能不能覆盖‘必要时扩大手术’？我们接受、也希望一次做够，只求提前知道可能的范围。」")
    n(doc, "　【因】避免二次麻醉、二次开腹。")
    n(doc, "【注】探查关腹＝看清就关、不强切　【因】先有心理预案，避免术后落差；也决定术后多快接全身治疗　【源】ESGO：不可完全切除时先全身治疗是正规选项")

    h(doc, "③ 输尿管支架 ⭐")
    q(doc, "「这次放不放输尿管支架？」")
    plus(doc, "＋③b ⭐ 「PET/CT 提示右肾盂-上段输尿管扩张积液、盆腔右侧病灶与右输尿管盆段分界不清——"
              "术前要不要泌尿科会诊、复查泌尿系影像？」")
    n(doc, "　【因】术中保护输尿管，和术后腰痛的两种处理方式完全不同。")
    n(doc, "【因】放了支架术后腰胀属正常；没放却腰痛要警惕梗阻　【源】盆腔手术常规")

    h(doc, "④ 标本三请求 ⭐⭐（全卡最重）")
    q(doc, "「三个请求：① 每个病灶分别留蜡块；② 新鲜组织冻存备份；③ 病理加做 HER2、CD3、CD8、MAGE-A4"
           "——加做单我们现在就签字。」")
    plus(doc, "＋④b ⭐⭐ 「新鲜组织冻存：术前一天我们想和病理科对一遍流程——取材后 30 分钟内进 −80℃，"
              "谁执行、谁签收、登记在哪？」")
    n(doc, "　【因】冻存窗口很短，手术当天才提基本会落空；三个先决条件：病理科同意、冰箱可及、人到位。")
    n(doc, "【注】蜡块＝一切检测的源头；冻存＝留给未来新技术　【因】标本不可再生；分病灶留块才能看清哪个病灶“进化”了"
           "（ER+→ER− 就是教训）　【源】WHO 第 6 版：HG-ESS 诊断需分子确认")

    h(doc, "⑤ 12 月记录 ⭐⭐（本版更新）")
    q(doc, "「12 月手术记录我们已备好，复印件给您。请团队调阅铜梁中医院的 12 月石蜡病理报告，和本次手术标本对照"
           "——原发灶与转移灶免疫表型有差异（ER+→ER−），对照对分型很有价值。」")
    plus(doc, "＋⑤ 更快的口径（建议照这句说）：「12 月的石蜡报告复印件（255317，含 IHC 12 张）和重肿会诊报告"
              "（H26-09047，2026-09-11）我们都带来了，请您一并看；需要盖章正式件或切片复核，我们再去铜梁取。」")
    n(doc, "　【因】会诊报告已在你们院内系统里，“我带来了”比“请你们调阅”快得多。")
    n(doc, "【注】12 月术中冰冻已报恶性（25289B），石蜡报告 255317（2025-12-29）含 IHC 12 张　"
           "【因】原发 vs 转移 vs 分子三方互证＝分型核心证据　【源】WHO 第 6 版；12 月手术记录（已转录）")

    h(doc, "⑥ 衔接 ⭐⭐")
    q(doc, "「术后病理几天出？出来后会安排化疗或 MDT 吗？时间线大概怎样？」")
    plus(doc, "＋⑥b ⭐ 「出报告当天能不能挂上您的号、或直接排 MDT？预约单我们现在就办好。」")
    plus(doc, "＋⑦ ⭐ 「她 2019 年已切右下肺叶，又有高血压和低前白蛋白（134）——术后要不要进观察室/ICU？"
              "第一晚需要人陪吗？」")
    n(doc, "【因】术后 4–6 周是全身治疗窗口（＝10/20–11/3）；中秋国庆夹击，不排期就拖到 10 月中　"
           "【源】ESGO；法国肉瘤组回顾数据（详见卡 J 的 caveat）")

    # ============================================================ 卡 B
    new_section(doc)
    card_head(doc, "卡 B · 麻醉访视医生", "⭐⭐")
    h(doc, "① 降压药 ⭐⭐")
    q(doc, "「她每天吃氨氯地平，手术当天早上还吃吗？」")
    plus(doc, "＋①b 「术前禁食禁饮到几点？她早上吃药，用多少水送服？」")
    n(doc, "【注】氨氯地平≠抗凝药　【因】通常照吃（清晨一小口水），但须麻醉医生亲口定　【源】术前药物管理常规")
    h(doc, "② 停药确认 ⭐")
    q(doc, "「还有要提前停的药吗？她没在用抗凝药吧？」")
    plus(doc, "＋②b ⭐ 请家属先核实：是否同时在吃活血中药、阿司匹林/氯吡格雷、鱼油、维生素 E（这些才真正影响手术）。")
    h(doc, "③ 镇痛 ⭐⭐")
    q(doc, "「术后镇痛什么方案？有镇痛泵（PCA）吗？她对痛敏感。」")
    plus(doc, "＋③b ⭐⭐ 「镇痛泵里是什么药？会不会加重便秘/腹胀？——她有肠梗阻风险，术后要尽早排气。」")
    n(doc, "　【因】阿片类抑制肠蠕动，便秘/腹胀反而会掩盖肠梗阻信号。")
    plus(doc, "＋③c ⭐ 「能不能加做腹横肌平面阻滞（TAP）或切口局麻，少用一点阿片？」")
    n(doc, "【注】PCA＝自控泵，有锁定间隔不会过量　【因】镇痛好＝敢咳敢动＝肺炎血栓都少　【源】ERAS 常规")
    h(doc, "④ 止吐 ⭐")
    q(doc, "「她容易恶心，术后止吐怎么安排？」")
    plus(doc, "＋④b ⭐ 「呕吐风险算高危（女性、不吸烟、术后用阿片）——会做三联预防吗（如昂丹司琼＋地塞米松＋NK1）？」")
    n(doc, "【因】吐＝吃不下＝46kg 掉不起")
    h(doc, "⑤ 过敏 ⭐")
    q(doc, "「过敏史对一遍——她有没有药物过敏？」（家属先知道答案）")
    h(doc, "⑥ 复苏室")
    q(doc, "「术后待多久？家属什么时候能见？」")
    plus(doc, "＋⑥b 「她右下肺叶已切除，术后要不要雾化/呼吸训练？第一晚需要人陪吗？」")
    h(doc, "⑦ 抗凝（本卡最大缺口）⭐⭐", size=11)
    q(doc, "「她 D-二聚体 2.22、FDP 6.9、纤维蛋白原 4.9，属高凝状态。术后抗凝（低分子肝素＋间歇充气加压）"
           "什么时候开始、什么时候停？」", size=10)
    n(doc, "【注】低分子肝素与硬膜外/腰麻的配合要求，由麻醉与外科共同定。")
    n(doc, "【因】妇科肿瘤大手术＋高凝＝血栓高危；术后血栓比出血更容易被漏掉。【源】ERAS／VTE 预防常规。")
    plus(doc, "＋⑧ 「她 46kg、前白蛋白 134（低）——用药剂量按体重调整吗？」")
    plus(doc, "＋⑨ 「术后疼痛怎么打分（0–10）？我们按这个记录，什么时候该叫你们？」")

    # ============================================================ 卡 C
    new_section(doc)
    card_head(doc, "卡 C · 管床医生 · 周一早查房（第一接口）", "⭐⭐ 整卡")
    h(doc, "开场")
    q(doc, "「医生，几件事请您帮忙，两分钟，您看单子。」")
    h(doc, "① 白片医嘱 ⭐⭐")
    q(doc, "「9-18 穿刺蜡块 26-25469，麻烦开白片外送医嘱：白片 8–10 张 ＋ HE 1 张，做基因检测。」")
    n(doc, "【注】医嘱＝正式单据，没有它不切片、缴不了费　【因】全链条起点　【源】9-18 报告原文“建议分子检测协诊”")
    h(doc, "② 带话纸 ⭐⭐")
    q(doc, "（递卡 J）「这张麻烦转主治、提进 MDT。」")
    h(doc, "③ 问第三方 ⭐")
    q(doc, "「咱们院外送分子检测是哪家？」")
    n(doc, "【因】有通道顺走最快；没有就启动金域备胎　【源】手册 B2 决策树")
    h(doc, "④ 加 LDH ⭐")
    q(doc, "「抽血加开一个 LDH。」")
    n(doc, "【注】组织坏死时升高　【因】坏死三自查之一　【源】坏死征兆自查（9-20）")
    h(doc, "⑤ 不等手术标本 ⭐⭐")
    q(doc, "「9-18 的块先送，不用等手术标本——手术的留着做 IHC 和各病灶留块。」")
    n(doc, "【因】9-18＝最新现役病灶，融合/靶点/MSI 全线通用；两边不耽误　【源】样本代表性原则")
    h(doc, "⑥ 取材备注 ⭐")
    q(doc, "「手术取材单请注明：请取活性组织、避开坏死区，各病灶分别留块。」")
    n(doc, "【因】坏死区 DNA 降解、检测易失败　【源】NGS 取材规范")
    plus(doc, "＋⑥b ⭐⭐ 「请在病理申请单上写明：分病灶留蜡块、新鲜组织冻存、加做 HER2/CD3/CD8/MAGE-A4，"
              "并请病理科接收时确认。」")
    n(doc, "　【因】不写进申请单，台上和病理科不会自动做——这是全包最容易“说了却没发生”的一条。")
    plus(doc, "＋⑦ ⭐⭐ 「白片张数按送检机构的 SOP：穿刺块常要 15–20 张，或者直接把蜡块送检。"
              "请先把机构 SOP 给我们，我们按 SOP 开单。」")
    n(doc, "　【因】26-25469 是穿刺组织，比 12 月的子宫标本小得多，张数不够只会换来一张“组织不足”。")
    plus(doc, "＋⑧ ⭐⭐ 「抽血加三样：① HBV DNA 定量（她 anti-HBc 4.538，既往感染，化疗/免疫前必查）；"
              "② HLA-A 高分辨分型（TCR-T 硬门槛，只要血）；③ 血常规含单核细胞绝对值＋淋巴细胞亚群。」")
    n(doc, "　【因】HBV 再激活可致命且常被忽略；HLA-A*02 与 LMR（淋巴/单核比）是后续筛试验要用的指标。")
    plus(doc, "＋⑨ ⭐ 「请病理在报告里注明肿瘤细胞含量（TC%）和坏死比例。」")
    n(doc, "　【因】NGS 有最低肿瘤含量要求，低于阈值需要富集/显微切割。")
    plus(doc, "＋⑩ ⭐⭐ 「9-18 的块 9/24（周四）前必须送出——中秋 9/25–27 机构停检。」")
    h(doc, "推脱三档")
    li(doc, "一档「院里做还是外送？」→ 二档「那就开白片外送医嘱＋切 8–10 张」→ 三档「我们自己联系金域，只需您开医嘱。」")
    h(doc, "钥匙句 ⭐⭐")
    q(doc, "「我们想尽早做、不想等。医院流程慢的话我们自己联系机构，报告拿回来给您参考——只需要您开个白片外送医嘱。"
           "死线是 9/24。」")

    # ============================================================ 卡 D
    new_section(doc)
    card_head(doc, "卡 D · 主治 / 教授 · 查房后门口（钓鱼法）", "⭐")
    h(doc, "时机")
    q(doc, "不拦查房；队伍出来后门口：「教授耽误您两分钟。」")
    h(doc, "① ⭐⭐")
    q(doc, "「手术所见和最终病理什么时间定？术后治疗什么时候启动？」")
    h(doc, "② ⭐")
    q(doc, "「如果病理维持‘似低级别’，全身一线您倾向什么方向？」——听完只记录，不接话不反驳。")
    h(doc, "③")
    q(doc, "（递卡 J）「这三条想请您带进 MDT。」")
    h(doc, "④")
    q(doc, "「我们准备把 9-18 的块自费送基因检测，报告出来给您参考。」")
    plus(doc, "＋⑤ ⭐ 「手术记录和病理出来后，能不能请您在病程记录或门诊病历里写一句‘建议分子检测/建议 MDT’？」")
    n(doc, "　【因】有医生签字的一句话，才是开单、报销、入组试验的凭据——9-18 报告原文那句就是这么起作用的。")
    plus(doc, "＋⑥ 「我们不带方案、只带问题。今天请您定三件事：术后治疗谁启动、什么时候启动、走哪扇门"
              "（门诊/MDT/住院）。」")
    h(doc, "钥匙句")
    q(doc, "「我们自己花钱送检、结果给您参考，不耽误您定的方案。」")
    n(doc, "【因】主治只见缝插针地见——门口两分钟胜过病房等一天　【源】MDT 三扇门")

    # ============================================================ 卡 E
    new_section(doc)
    card_head(doc, "卡 E · 责任护士 · 术后当天起", "⭐⭐")
    h(doc, "① 镇痛泵 ⭐⭐")
    q(doc, "「泵里什么药？她自己能按吗？多久能按一次？」")
    h(doc, "② 体温线 ⭐⭐")
    q(doc, "「多久测一次？到多少度必须叫人？」（红线 38.5℃）")
    h(doc, "③ 引流管 ⭐")
    q(doc, "「几根？量和颜色记在哪？我们家属帮着记。」")
    h(doc, "④ 活动表 ⭐⭐")
    q(doc, "「什么时候翻身、半坐、下床？」——问清时间点，陪护执行")
    h(doc, "⑤ 饮水")
    q(doc, "「排气前能喝水吗？一次多少？」")
    h(doc, "⑥ 让护士亲口说 ⭐⭐")
    q(doc, "「我们家属看到什么情况必须马上叫你们？」")
    plus(doc, "＋⑦ ⭐ 「抗凝针和气压治疗什么时候做？谁来提醒？」")
    plus(doc, "＋⑧ ⭐ 「弹力袜 / 踝泵怎么做？一天几次？」")
    plus(doc, "＋⑨ ⭐ 「如果她疼得不敢动，能不能先用镇痛再让她坐起来？」")
    plus(doc, "＋⑩ 「翻身拍背、口腔护理几点做？我们家属可以帮着做哪部分？」")
    plus(doc, "＋⑪ ⭐⭐ 移交记录：「这张记录表（卡 N）我们每天填，交班时给您看一眼。」")
    h(doc, "钥匙句")
    q(doc, "「您教我们怎么观察，我们帮您盯着，有事立刻叫。」")
    n(doc, "【因】术后并发症最早都是家属先看见　【源】术后红旗卡（卡 M）＋ `紧急事项-2026-09-11.md`")

    # ============================================================ 卡 F
    new_section(doc)
    card_head(doc, "卡 F · 病理窗口 · 周三起", "⭐⭐")
    li(doc, "白片 8–10 张 ＋ HE 1 张，蜡块号 26-25469——当场核对玻片边缘编号　⭐⭐", size=10)
    li(doc, "手术标本：各病灶分别留块 ＋ 院内永久备份　⭐⭐", size=10)
    li(doc, "加做 IHC：HER2、CD3、CD8、MAGE-A4（申请单已备）", size=10)
    li(doc, "取材单备注“取活性组织、避开坏死区”", size=10)
    li(doc, "报告出后复印两份（家属＋主治）", size=10)
    plus(doc, "＋6. ⭐⭐ 手术标本再确认一遍：各病灶分别留块、院内永久备份；蜡块永不离院、且不得用完。")
    plus(doc, "＋7. ⭐⭐ 一次申请全开：MMR 四项（MLH1/PMS2/MSH2/MSH6）、cyclin D1、BCOR、IFITM1、ER/PR 定量、"
              "Ki-67 复核——和 HER2/CD3/CD8/MAGE-A4 写在同一张申请单上。")
    n(doc, "　【因】一次排队省一周；cyclin D1 是 YWHAE 型最敏感的标志物。【源】`诊疗方案-2026-09-11.md` P0 清单。")
    plus(doc, "＋8. 报告出后：复印两份 ＋ 逐页拍照留档（含玻片边缘编号）。")
    plus(doc, "＋9. ⭐⭐ 如果病理科说“组织不够”：请先打电话给我们，不要自动降级或砍项目——宁可直接送蜡块。")
    h(doc, "红线")
    q(doc, "蜡块永不离院；白片可以走。", size=10.5)
    n(doc, "【源】递件卡 ＋ 全量手册")

    # ============================================================ 卡 G
    new_section(doc)
    card_head(doc, "卡 G · 检测中心窗口 · 送样日随身", "⭐⭐")
    h(doc, "报样本（照读）")
    q(doc, "「外院 FFPE 白片送检，实体瘤 DNA＋RNA 双 panel NGS。曹雪梅，女，59 岁，子宫内膜间质肉瘤转移灶穿刺组织，"
           "病理号 26-25469，2026-09-18 取材，白片 8–10 张未染色 ＋ HE 1 张。」")
    h(doc, "五项必含核对")
    li(doc, "① RNA 融合 JAZF1/PHF1/YWHAE/BCOR 家族")
    li(doc, "② RNA 融合 NTRK/ALK/ROS1/RET")
    li(doc, "③ CDK4/MDM2 扩增")
    li(doc, "④ CDKN2A/B 缺失")
    li(doc, "⑤ MSI ＋ TMB")
    h(doc, "两条口头红线 ⭐⭐")
    q(doc, "① 「融合必须基于 RNA，不能只有 DNA。」（三重出处：FISH 不见伙伴／WHO 要 RNA 确认／MSK：31% 的 DNA NTRK 融合是乘客）")
    q(doc, "② 「组织不够先打电话给我们，不要自行降级项目或只做 DNA；宁可直接送蜡块。实在做不了，"
           "请书面写明哪一项做不了、为什么，我们据此补样。」")
    h(doc, "送样当天必拿四样（本版新增）")
    li(doc, "样本接收凭证（白片张数、编号、日期、经手人签名）")
    li(doc, "白片/玻片逐张拍照（含边缘编号）")
    li(doc, "书面 SOP ＋ 报价单 ＋ 承诺周期")
    li(doc, "联系人姓名＋手机/微信；报告电子版先发、纸质件自取或邮寄")
    h(doc, "两个书面约定（看一眼再签）")
    li(doc, "剩余白片、剩余 DNA/RNA 与数据的去留（是否退还、是否可用于科研——科研需另外同意）")
    li(doc, "报告性质写明“临床诊断用途”，CAP 或 ISO15189 认证实验室出具")

    # ============================================================ 卡 H
    new_section(doc)
    card_head(doc, "卡 H · 附一客服 · 周一（放午间）", "⭐")
    for i, t in enumerate([
        "外院病理会诊＋白片外送流程？哪个窗口？",
        "咱们外送第三方是哪家？有电话吗？",
        "家属自己送金域行不行？要医院出什么手续？",
        "白片切取在哪办、多少钱、几个工作日？",
        "中秋（25–27）国庆（1–7）收样吗？窗口几点？　⭐⭐",
        "双 panel（DNA＋RNA）费用和周期？",
        "报告怎么取——纸质＋电子？能给主治一份吗？",
    ], 1):
        li(doc, f"{i}. {t}")
    plus(doc, "＋8. ⭐⭐ 「请直接给我病理科/分子病理室的直线电话，客服转不到。」")
    plus(doc, "＋9. ⭐⭐ 「RNA 融合（RNA-based NGS）贵院院内能做吗，还是必须外送？」")
    plus(doc, "＋10. ⭐⭐ 「中秋 9/25–27、国庆 10/1–7：收样、切片、出报告分别怎么算工作日？"
              "报告会不会顺延到 10 月中？」")
    plus(doc, "＋11. 「报告能不能出电子版 PDF＋纸质件？能不能直接给主治一份？」")
    plus(doc, "＋12. 「白片外送要什么手续（申请单/会诊单/缴费/生物安全）？家属自己送行不行？」")

    # ============================================================ 卡 I
    new_section(doc)
    card_head(doc, "卡 I · 金域 / 第三方 · 拿到电话后", "⭐")
    h(doc, "① 覆盖")
    q(doc, "「实体瘤 panel 是 DNA＋RNA 双线吧？覆盖 JAZF1/PHF1/YWHAE/BCOR 家族、NTRK/ALK/ROS1/RET、CDK4/MDM2 扩增、"
           "CDKN2A/B、MSI/TMB 吗？融合走 RNA 线吧？（顺口：含 ESR1、KDM2B 吗？）」")
    n(doc, "【注】ESR1＝WHO 第 6 版点名“ER 表达降低的 LG-ESS 应检测”，阳性有氟维司群类可用；"
           "KDM2B＝第 6 版新纳入的 HG-ESS 罕见驱动（EPC1::KDM2B）　【源】WHO 第 6 版（2026-08-24 上线）")
    h(doc, "② 资质")
    q(doc, "「CAP 或 ISO15189？出纸质报告吗？」")
    h(doc, "③ 价格、周期、节假日收样安排")
    plus(doc, "＋④ ⭐ 「ESR1 是按重排/融合报，还是按表达/扩增报？请在报告里写清。」")
    n(doc, "　【因】写法不同，后面能不能用内分泌/氟维司群完全不同。")
    plus(doc, "＋⑤ ⭐⭐ 「样本肿瘤细胞含量低于阈值时，你们做显微切割富集吗，还是直接报‘组织不足’？」")
    plus(doc, "＋⑥ 「假期（9/25–27、10/1–7）停不停？请写进承诺周期。」")
    plus(doc, "＋⑦ 「报告双签吗？签发人是谁？有没有 CAP/CNAS 编号可核？」")

    # ============================================================ 卡 J（带话纸，可单独打印）
    new_section(doc)
    card_head(doc, "卡 J · MDT 带话纸（打印后递交，家属自留说明见下）", "⭐⭐")
    para(doc, "请管床医生转交主治医师并提请 MDT 讨论——患者曹雪梅家属",
         size=11.5, bold=True, after=4, align=WD_ALIGN_PARAGRAPH.CENTER)
    for i, t in enumerate([
        "1. 患者 2025-12-20 外院术后仅 9 个月即腹腔多发（短复发间隔为不良预后因素），伴 ER 表达丢失、Ki-67 升高。"
        "若本次手术有残留，请按转移性疾病尽早启动一线全身治疗；若切净，鉴于上述高危特征，请按 ESGO/EURACAN 2024 "
        "讨论以蒽环为基础的辅助化疗（指南措辞“应予考虑”；回顾性证据：法国肉瘤组 39 例多因素分析示辅助化疗与总生存改善相关，"
        "中位 41.0 vs 10.3 个月，P=0.034；NCDB 1383 例方向一致；上述为回顾性、非随机、样本量小，前瞻证据尚缺）。"
        "若最终分型为低级别或 ER 保留，也请一并讨论内分泌治疗路径（芳香化酶抑制剂/孕激素，进展后氟维司群）"
        "——我们不预判方向，只想让两条路都被 MDT 看到。",
        "2. 2025-12-20 于铜梁区中医院行腹腔镜全子宫＋双附件切除术（住院号 457107；冰冻号 25289B；术后石蜡病理号 255317，"
        "2025-12-29，含 IHC 12 张；术者杨亚，记录中亦作杨娅）。经阴道完整取出、瘤体包膜完整；术中冰冻已报恶性，"
        "术后未行辅助治疗。建议调阅该院 12 月石蜡病理与本次标本对照。",
        "3. 全身方案请考虑含安罗替尼的组合（NRDL 肉瘤适应症）。若肿瘤与肠管分界不清、存在肠瘘/出血风险，"
        "请先评估安全性再定。",
        "4. PD-1/免疫治疗时机请等 MMR/MSI/TMB/MDM2 结果再定（MDM2 扩增者 PD-1 单药有超进展风险）。"
        "若 MMR/MSI 提示 dMMR/MSI-H，免疫治疗是可讨论的路径（泛癌种适应症），请单独评估。",
        "5. 基因检测报告（预计 10 月初）回来后，申请再次上 MDT。",
        "6. 请把“术后 4–6 周内启动全身治疗”写进病程记录与出院小结；并在分子报告回来前先定启动原则、预留床位，"
        "不要把启动系在报告上。",
        "7. 家属自费加做 HER2/CD3/CD8/MAGE-A4 免疫组化及 NGS，报告回来当天提交一份给主治，所有结果均供 MDT 参考。",
    ], 1):
        para(doc, t, size=10, left=0.3, after=3)
    para(doc, "家属签名：＿＿＿＿＿＿　　联系电话：＿＿＿＿＿＿＿＿　　床号：＿＿＿＿", size=10, before=6)
    para(doc, "──────────────── 以下家属自留，不要打印给医生 ────────────────",
         size=8.5, color=NOTE, before=8)
    h(doc, "卡 J 本次新增了什么（家属自看）", size=10)
    li(doc, "第 1 条：加“内分泌治疗路径”这一句 ⭐⭐（只喊化疗容易被误解为替医生定方案）", size=9)
    li(doc, "第 1 条：数据后主动加 caveat（回顾性、非随机、样本量小）", size=9)
    li(doc, "第 2 条：编号写全（住院号/冰冻号/病理号/术者），病案室与病理科一分钟就能调出来", size=9)
    li(doc, "第 3 条：主动说出肠瘘/出血风险", size=9)
    li(doc, "第 4 条：补 dMMR/MSI-H 的泛癌种路径", size=9)
    li(doc, "第 6、7 条：把“4–6 周窗口”写进病历，并约定报告回来再上 MDT", size=9)
    n(doc, "【因】先给请求、再给数据、最后主动说局限——最不容易被当成“外行指挥”。若被质疑，钥匙句："
           "「我可能理解得不准确，以 MDT 的判断为准；我们的请求只是‘请讨论’。」")

    # ============================================================ 卡 K
    new_section(doc)
    card_head(doc, "卡 K · 铜梁区中医院病案室 · 电话优先，术后办", "⭐⭐")
    h(doc, "话术（照读）")
    q(doc, "「你好，患者曹雪梅，2025 年 12 月在贵院妇科住院，12 月 20 日杨亚医生做了腹腔镜全子宫＋双附件手术"
           "（术后诊断子宫恶性肿瘤，冰冻号 25289B，住院号 457107）。我们要办病历复印，三样：① 石蜡病理报告"
           "（含免疫组化，病理号 255317）；② 出院记录/出院小结；③ 全部病理检查报告单。患者委托家属办理，"
           "身份证都齐。请问病案室上班时间、手续怎么办？能不能邮寄？」")
    li(doc, "若有更早的诊刮/宫腔镜记录，一并复印", size=9.5)
    li(doc, "被问用途就答：「治疗需要——上级医院 MDT 要对照原发灶病理。」（不提追责二字）", size=9.5)
    li(doc, "时机：周一可先打电话问流程，人去/邮寄排在周二手术之后——重肿主线不动摇", size=9.5)
    h(doc, "本版新增：材料与小票都要带全", size=10.5)
    plus(doc, "＋ 材料：患者身份证原件＋复印件 2 份、代理人身份证、委托书（必须术前签！）、关系证明（户口本/结婚证）、"
              "住院号 457107、病理号 255317、冰冻号 25289B。")
    plus(doc, "＋ 明确要四样（前 3 样是治疗刚需，第 4 样是证据链）：① 石蜡病理报告（含 12 张 IHC，255317）；"
              "② 出院记录/出院小结；③ 全部病理检查报告单；④ 手术记录＋麻醉记录＋护理记录单（盖章件）。")
    plus(doc, "＋ 平和地追问四件事 ⭐")
    n(doc, "　① 术中是否送腹腔冲洗液细胞学（手术记录未提及）；② 标本取出时是否完整、有无破裂；"
           "③ 蜡块/切片的借出与归还记录（12 月蜡块我们借过，还剩多少）；"
           "④ 出院诊断编码 M80000/3（“恶性肿瘤，未特指”）能否按 255317 补正为内膜间质肉瘤形态学编码。")
    n(doc, "　【因】编码不补正，后面医保结算、门特备案、临床试验入组审核都可能被卡。")
    plus(doc, "＋ 「复印件请盖病案室章/骑缝章，并给一张页数清单。」")
    plus(doc, "＋ 「能不能邮寄？到付可以，要几天？」")
    n(doc, "【因】三份文件＝证据链＋治疗刚需，一条路两个用途　【源】《医疗纠纷预防和处理条例》第十六条：患者有权复印病历")

    # ============================================================ 卡 L（全文）
    new_section(doc)
    card_head(doc, "卡 L · 报告日 ＋ 化疗前启动（本版新补全文）", "⭐⭐")
    h(doc, "时机")
    q(doc, "拿到分子报告当天——当天就挂号/申请 MDT，不要“看完报告再想”。")
    h(doc, "① 报告当场逐条核对（照读）⭐⭐")
    q(doc, "「我们对六个点：① 融合：JAZF1::SUZ12 / YWHAE::NUTM2 / BCOR 家族 / PHF1 家族 / NTRK / ESR1 / KDM2B "
           "逐条有无；② 这条融合结论是不是 RNA 线出的（只有 DNA 不算）；③ CDK4/MDM2 扩增、CDKN2A/B 缺失；"
           "④ MSI/TMB 与 MMR IHC；⑤ HER2/CD3/CD8/MAGE-A4、ER/PR 定量、cyclin D1、Ki-67。」")
    h(doc, "② 三句话定方向 ⭐⭐")
    q(doc, "「① 若是低级别/ER 保留 → 想讨论内分泌治疗（AI/孕激素；进展后氟维司群）＋骨密度基线；"
           "② 若有 YWHAE/BCOR 或高级别转化 → 想讨论蒽环类为基础的化疗，或安罗替尼＋化疗（ALTN-III-04）；"
           "③ 若有 NTRK 融合 → 请按 NTRK 抑制剂走。」")
    h(doc, "③ 化疗前基线一次开全 ⭐⭐")
    q(doc, "血常规含分类 ｜ 肝肾功 ｜ 电解质（K 历史 3.36↓）｜ 凝血＋D-二聚体/FDP ｜ HBV DNA 定量"
           "（阳性或高危即恩替卡韦/替诺福韦预防）｜ 心脏彩超 LVEF＋心电图（蒽环类必需）｜ 胸部 CT 基线"
           "（肺癌术后随访＋免疫治疗前基线）｜ 肺功能含 DLCO ｜ 营养科会诊＋口服营养补充 ｜ 钙＋维 D（若用 AI）"
           "｜ PICC 或输液港评估 ｜ 口腔检查与止吐预案。")
    h(doc, "④ 排期（本卡最硬的一句）⭐⭐")
    q(doc, "「按 9/22 手术算，术后 4–6 周窗口＝10/20–11/3。国庆后门诊最挤，请现在就把第一次化疗或住院日期预留出来。」")
    h(doc, "⑤ 文书 ⭐")
    q(doc, "分子报告 PDF＋纸质各一份交主治，请其在病历中记录；同时按卡 J 第 5 条申请再次 MDT。")
    h(doc, "⑥ 细胞治疗 / 试验窗口（有时限）⭐")
    q(doc, "若 MAGE-A4 ≥2+ 且 ≥30% 细胞，且 HLA-A*02 阳性 → 立刻联系 TCR-T 中心（JWTCR001 等）。"
           "化疗前留新鲜组织冻存、抽血留胚系对照最划算；化疗后淋巴细胞低、取材难，门槛会变高。"
           "（12 月蜡块 255317 按厂家要求有效至 2028-12，可作备选。）")
    h(doc, "⑦ 两个局部问题单列 ⭐")
    q(doc, "骶前 5.5×6.1cm（与直肠/乙状结肠分界不清）→ 放疗科（SBRT）评估；"
           "右肾盂-上段输尿管扩张 → 泌尿科随访/必要时支架。")

    # ============================================================ 卡 M（红旗卡，大字）
    new_section(doc)
    card_head(doc, "卡 M · 术后红旗卡（贴床头 ＋ 随身各一份）", "⭐ 大字版")
    para(doc, "出现下列任一条，立刻行动——不要等查房。", size=12, bold=True, after=4)
    h(doc, "A. 立刻打 120 / 马上叫护士", size=13)
    for t in [
        "喘不上气、胸痛、嘴唇发紫、说话不成句",
        "血压很低/头晕要倒、意识改变、叫不醒、抽搐",
        "阴道大出血（1 小时湿透一条大垫）、面色苍白、心率很快",
        "无尿超过 6–8 小时，或腰痛剧烈＋尿少",
    ]:
        para(doc, "□　" + t, size=12, left=0.3, after=4)
    h(doc, "B. 当天就叫医生处理", size=13)
    for t in [
        "体温 ≥38.5℃ 或寒战发抖",
        "腹痛突然加重、肚子硬、按不得",
        "引流液突然增多 / 变红 / 变浑浊 / 有粪样物或气泡（肠瘘信号，本例要特别盯）",
        "切口红肿、渗液、裂开",
        "一条腿肿、痛、发热（深静脉血栓）",
        "术后超过 3 天没排气、腹胀、呕吐（肠梗阻）",
        "心慌、出冷汗、饿得慌（低血糖/低钾）",
    ]:
        para(doc, "□　" + t, size=12, left=0.3, after=4)
    h(doc, "C. 说话模板（护士最怕听到“她不舒服”）", size=12)
    q(doc, "「我们看到【具体现象：引流 2 小时 200ml 变红】，现在是【时间】，请来看一下。」", size=12)
    n(doc, "【因】术后并发症最早都是家属先看见。【源】`紧急事项-2026-09-11.md` 危险信号 ＋ 术后常规。")

    # ============================================================ 卡 N（横向记录表）
    new_section(doc, landscape=True)
    card_head(doc, "卡 N · 术后每日记录表（打印 7 份，一天一张）", "⭐ 横向页")
    para(doc, "日期：＿＿＿＿年＿＿月＿＿日　　床号：＿＿＿＿　　值班护士：＿＿＿＿", size=10, after=4)
    make_table(
        doc,
        ["时间", "体温℃", "血压 / 心率", "呼吸", "引流量·颜色", "尿量", "腹痛 0–10",
         "排气 / 排便", "进食饮水", "下床(次)", "用药（止痛/抗凝/通便）", "备注"],
        [[t, "", "", "", "", "", "", "", "", "", "", ""]
         for t in ["06:00", "10:00", "14:00", "18:00", "22:00", "02:00"]],
        widths=[1.5, 1.5, 2.4, 1.4, 2.6, 1.5, 1.6, 2.0, 2.2, 1.5, 3.3, 2.5],
        size=9,
    )
    para(doc, "今日汇总：最高体温＿＿＿　引流合计＿＿＿ml　尿量合计＿＿＿ml　是否排气：□有 □无　"
              "腹痛最高＿＿＿分　是否下床：□是 □否", size=10, before=6)
    para(doc, "规则：每 4 小时记一次；异常随时加记。交班时递给护士看一眼——这张纸是你后面跟医生对话的底气。",
         size=9.5, color=NOTE, before=4)

    # ============================================================ 卡 O
    new_section(doc)
    card_head(doc, "卡 O · 出院日 ＋ 化疗前基线（术后 5–7 天）", "⭐ 新版")
    for i, t in enumerate([
        "出院前必问：拆线/换药时间、引流管与缝线、出院带药（止痛/抗凝/通便）、复诊时间与挂号方式、"
        "出院小结什么时候能复印、术后病理报告复印件、出院诊断编码是否正确。",
        "复印全套住院病历（出院后约 3–7 个工作日；带身份证＋委托书）。",
        "门特/特病备案——还没办就现在办；同时核对住院费用清单、留好自费发票（检测＋靶向药报销都要）。",
        "把下一次就诊定死在窗口里：术后 4–6 周＝10/20–11/3。",
        "回家继续：卡 M 判断 ＋ 卡 N 记录，出现红线直接回院。",
    ], 1):
        li(doc, f"{i}. {t}", size=10)

    # ============================================================ 卡 P
    new_section(doc)
    card_head(doc, "卡 P · 术前一天（周一）总清单", "⭐ 新版")
    items = [
        "病理科：确认“分病灶留块＋新鲜冻存（30 分钟内 −80℃）＋加做 HER2/CD3/CD8/MAGE-A4＋冲洗液细胞学”，留下执行人姓名电话",
        "病理科：9-18 块（26-25469）白片按机构 SOP 开单，确认周四能取",
        "手术室/麻醉：台次时间、禁食禁饮、降压药怎么吃",
        "输血科/病房：备血、血型核对",
        "泌尿科：右输尿管 / 支架安排",
        "护士站抽血：HBV DNA、HLA-A、血常规含单核＋淋巴亚群",
        "文书（最容易被拖掉的一件事）：① 委托书（病历复印、取报告、代办检测）② 自费检测同意 ③ 麻醉/手术/输血同意 "
        "④ 扩大手术范围授权 ⑤ 患者签名——都由患者清醒时一次签完",
        "送检方：机构 SOP ＋ 书面报价 ＋ 交接凭证模板",
        "电话三连：铜梁病案室（卡 K）／附一客服（卡 H）／金域等第三方（卡 I）",
        "家里：卡片打印、记录本＋笔、充电宝、吸管杯、润唇膏、护理垫、陪护轮班表、病历袋（身份证/医保卡/全部复印件）",
    ]
    for t in items:
        para(doc, "□　" + t, size=10, left=0.3, after=3)

    # ============================================================ 附录 1
    new_section(doc)
    card_head(doc, "附录 1 · 口径待核实清单（8 条，不改会被问住）", "家属自留")
    rows = [
        ["1", "卡 A⑤ 与自家档案冲突：你们已持有 255317 全文（含 IHC 12 张），且重肿会诊 H26-09047（9/11）"
              "已引用原单位 IHC。改成“我们带来了复印件，缺的是盖章正式件”，卡 K 收敛为补齐盖章件与缺项。"],
        ["2", "“附一客服 1860”指哪一家？重肿＝重庆大学附属肿瘤医院；“附一”通常指重医附一院。主体与号码先核实"
              "（1860 不像重庆固话号段）。只为拿 RNA 融合，重肿分子病理室直线电话更直接。"],
        ["3", "卡 B 的氨氯地平：仓库病历只写“高血压”，没有药名/剂量。核实药名、每天几点吃，以及是否同服"
              "活血中药、阿司匹林/氯吡格雷、鱼油、维生素 E。"],
        ["4", "卡序时间留活口：麻醉访视多在术前一晚/术日晨，术前谈话也可能改到周一；卡 H 放午间，别与卡 C 撞。"],
        ["5", "卡 A⑤ 的“ER+→ER−”要带证据页：本次 9-18 穿刺 IHC 复印件＋12 月报告复印件，并先写好原发结果"
              "（ER 热点约 70%+、PR−、Ki-67 约 5%、CD10 部分+、SMA 散在灶性+、p53−，据 H26-09047 引用）。"],
        ["6", "卡 J 引用顺序：先请求 → 再数据 → 最后主动说局限（回顾性、39 例、非随机）。被质疑就说"
              "“以 MDT 判断为准，我们的请求只是请讨论”。"],
        ["7", "白片张数口径统一为“按送检机构 SOP”：v3 写 8–10 张、仓库手册写 10–15 张（穿刺 15–20 张）。周一先把 SOP 要到手。"],
        ["8", "冻存不是“请求”而是“流程”：谁取、几分钟内进冰箱、登记在哪、谁签收——周一先与病理科对好（卡 A④b、卡 P）。"],
    ]
    make_table(doc, ["#", "要核实的内容与建议口径"], rows, widths=[0.9, 16.9], size=9)

    # ============================================================ 附录 2
    new_section(doc)
    card_head(doc, "附录 2 · 钥匙句速查（背下来，随时能用）", "家属自留")
    entries = [
        ("王牌开场", "「9-18 的病理报告原文就建议做分子检测协诊——我们只是在执行。」"),
        ("要开单", "「医院流程慢的话我们自己联系机构，报告拿回来给您参考——只需要您开个白片外送医嘱。死线是 9/24。」"),
        ("被劝阻（主治）", "「我们自己花钱送检、结果给您参考，不耽误您定的方案。」"),
        ("被质疑数据", "「我可能理解得不准确，以 MDT 的判断为准；我们的请求只是‘请讨论’。」"),
        ("请护士教", "「您教我们怎么观察，我们帮您盯着，有事立刻叫。」"),
        ("报红旗", "「我们看到【具体现象】，现在是【时间】，请来看一下。」"),
        ("要标本", "「三个请求：每个病灶分别留蜡块、新鲜组织冻存、加做 HER2/CD3/CD8/MAGE-A4——加做单现在就签。」"),
        ("要编号", "「住院号 457107、冰冻号 25289B、病理号 255317、蜡块号 26-25469。」"),
    ]
    for k, v in entries:
        para(doc, k, size=10.5, bold=True, font=HEAD, before=4, after=0)
        q(doc, v, size=10)
    para(doc, "⚠️ 免责声明：本卡片包为病历资料整理与沟通用话术，不构成医疗建议；所有治疗决策由主诊医生/MDT 做出。",
         size=8.5, color=NOTE, before=10)

    doc.save(OUT)
    print("已生成：", OUT)


if __name__ == "__main__":
    build()
