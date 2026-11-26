#!/usr/bin/env python3
"""解析河北政府采购网公告页的两种页面格式。

实测 2026-11 该站有两种详情页：

A. 旧版（2025 及更早）：正文在 `#con` 容器里（HTML），标包明细是一段
   `#detail#...` 的分隔符编码表。

B. 新版（2026 起）：正文不再直接渲染，改为在页面里内联一段
   `const announcementData = { ... }` 的 JS 对象（含 baseInfo /
   bidWinningAnnouncement 等字段），标包明细放在 htmlContent 字段里，
   同样是 `#detail#` 编码。

`#detail#` 编码格式：
    #detail#<表头1>#_#<表头2>...#_@_@<行1单元格>#_#...#_@_@<行2>...
  - 行分隔符：#_@_@
  - 单元格分隔符：#_#
  - 空单元格写作 "null"

本模块把两种格式归一成"字段名: 值" + 可读表格的文本，交给 LLM 抽取。
"""

from __future__ import annotations

import re

ROW_SEP = "#_@_@"
CELL_SEP = "#_#"

# 旧版 HTML 里行分隔符写作 "#@_@"，页面 JS 加载时会把它替换成 "#_@_@"。
# 解析前先归一化，两种页面就能共用一套切分逻辑。
LEGACY_ROW_SEP = "#@_@"

FIELD_RE = re.compile(r"(\w+)\s*:\s*`([^`]{1,4000})`")
DOUBLE_QUOTED_RE = re.compile(r"(\w+)\s*:\s*\"([^\"]{1,4000})\"")

FIELD_LABELS = {
    "docTitle": "公告标题", "DOCTITLE": "公告标题", "docreltime": "发布日期",
    "ANNCTIME": "发布日期", "anncTime": "发布日期", "anncCode": "公告编号",
    "annccode": "公告编号", "projectName": "项目名称", "PROJECTNAME": "项目名称",
    "projectname": "项目名称", "ANNCPROJECTNAME": "项目名称",
    "PURCHASEWAY": "采购方式", "PURCHASERAMOUNT": "中标金额",
    "PURCHASERAMOUNT2020": "中标金额", "PURCHASERPRICE": "中标金额",
    "CONTRACTAMOUNT": "合同金额", "TENDERAMOUNT": "招标金额", "gpbudgetamt": "采购预算",
    "limitedprice": "最高限价", "SHORTLISTPRICE": "中标价", "FEEAMOUNT": "代理服务费",
    "PURCHASERNAME2020": "采购人", "PURCHASERNAME": "采购人", "PurchaserName": "采购人",
    "PurchaserName2020": "采购人", "PurchaserAddr": "采购人地址",
    "AGENCYFULLNAME": "代理机构", "ADMINDIVNAME": "行政区划", "adminDivName": "行政区划",
    "PROCURMENTCODE": "采购项目编号", "PROJECTCODE": "项目编号",
    "WINSUPPLIERNAME": "中标供应商", "WINSUPPLIERADDR": "中标供应商地址",
    "EVALUATIONMETHOD": "评标方法", "Note": "备注", "NOTE": "备注",
    "PURCHASENUM": "标段数", "BIDOPENTIME": "开标时间", "BIDENDTIME": "投标截止时间",
    "type": "公告类型",
}


def parse_detail_table(payload: str) -> list[str]:
    """把 #detail# 编码表解析成可读的多行文本。

    payload 应当是纯粹的编码表内容（不含页面 JS）。若混入了 JS，
    只会解析出无意义的行 —— 调用方负责给对内容。
    """
    if "#detail#" not in payload:
        return []
    body = payload.split("#detail#", 1)[1]
    body = body.split("`")[0]
    body = body.split("#filename#")[0]
    body = body.replace(LEGACY_ROW_SEP, ROW_SEP)

    rows = [r for r in body.split(ROW_SEP) if r.strip()]
    lines: list[str] = []
    for row in rows:
        cells = [c.strip() for c in row.split(CELL_SEP)]
        cells = ["" if c == "null" else c for c in cells]
        if not any(cells):
            continue
        lines.append(" | ".join(cells))
    return lines


def extract_con_payload(html: str) -> str:
    """取出旧版页面 <span id="con"> 里纯编码表的内容。

    页面里的 JS 也会出现 "#detail#" 字样（split 调用），所以必须限定在
    con 容器内找，否则会把脚本当成表数据。
    """
    m = re.search(r'id="con"[^>]*>(.*?)</span>', html, re.S | re.I)
    if m:
        return m.group(1)
    return ""


def parse_new_format(html: str) -> str:
    """新版：解析内联的 announcementData JS 对象。"""
    idx = html.find("const announcementData")
    if idx < 0:
        return ""
    seg = html[idx: idx + 200000]

    pairs: list[tuple[str, str]] = []
    for m in FIELD_RE.finditer(seg):
        pairs.append((m.group(1), m.group(2)))
    for m in DOUBLE_QUOTED_RE.finditer(seg):
        pairs.append((m.group(1), m.group(2)))

    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for key, val in pairs:
        val = val.strip()
        if not val or val == "null" or (key, val) in seen:
            continue
        seen.add((key, val))
        label = FIELD_LABELS.get(key, key)
        if label == "备注" and len(val) > 400:
            val = val[:400] + "…"
        lines.append(f"{label}: {val}")

    table = parse_detail_table(seg)
    if table:
        lines.append("")
        lines.append("【标包明细表】")
        lines.extend(table)
    return "\n".join(lines)


def parse_old_format(html: str) -> str:
    """旧版：正文标签字段（<span id="XXX">值</span>）+ #detail# 标包明细表。"""
    lines: list[str] = []

    # 旧版把每个字段放在 <span id="FIELD">值</span> 里
    for m in re.finditer(
        r'<span\s+id="([A-Za-z_][\w]*)"[^>]*>(.*?)</span>', html, re.S | re.I
    ):
        key = m.group(1)
        if key in ("con", "fujian", "fujian_2020", "OLD_VERSION", "NEW_VERSION"):
            continue  # 这些容器装的是标包明细/附件，单独解析
        val = re.sub(r"<[^>]+>", " ", m.group(2))
        val = re.sub(r"\s+", " ", val.replace("&nbsp;", " ")).strip()
        if not val or val == "null":
            continue
        label = FIELD_LABELS.get(key, key)
        lines.append(f"{label}({key}): {val}")

    # 标签之间的散落文本（采购内容等）；剔除 CSS 与原始编码表
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    extra = [re.sub(r"[ \t\xa0]+", " ", x).strip() for x in text.split("\n")]
    extra = [x for x in extra
             if x and x != "null" and len(x) > 4
             and "#detail#" not in x and "#_#" not in x and "#@_@" not in x
             and not x.startswith((
                 "中标公告详细", "body {", "margin", "padding", "border", "background",
                 "color:", "font", "a.", "div", "span", "}", "/*", "*", "line-height",
                 "text-align", "width", "height", "table", "td", "th", "tr", "img",
                 "@media", ".", "#", "position", "display", "cursor", "list", "float",
                 "clear", "text", "vertical", "z-index", "overflow", "content", "!",
             )) and not x.endswith("{") and "{" not in x and "}" not in x]
    if extra:
        lines.append("")
        lines.append("【正文】")
        lines.extend(extra[:60])

    table = parse_detail_table(extract_con_payload(html))
    if table:
        lines.append("")
        lines.append("【标包明细表】")
        lines.extend(table)
    return "\n".join(lines)


def parse_announcement(html: str) -> str:
    """自动识别两种格式，返回可用于 LLM 抽取的文本。"""
    new = parse_new_format(html)
    old = parse_old_format(html)
    return new if len(new) >= len(old) else old


if __name__ == "__main__":
    import sys

    with open(sys.argv[1], encoding="utf-8") as fh:
        print(parse_announcement(fh.read()))
