---
name: esg-monthly-report
description: Use when the user asks for an ESG monthly report, ESG 月报, 可持续发展月报, or wants ESG policy/ratings/standards developments, industry ESG news, or a client company's ESG progress and peer benchmarking summarized for a given month. 以中国神华为默认示例客户。
version: "1.0.0"
license: MIT
---

# ESG 月报生成

汇总过去一个月的时政与产业信息，为客户生成 ESG 月报。

## 何时使用

- 用户要求生成 ESG 月报 / 可持续发展月报 / ESG 简报
- 用户问"这个月 ESG 有什么新动态""双碳政策有什么变化""XX 公司 ESG 评级如何"
- 需要对标企业某月采取的 ESG 关键行动

## 报告必须覆盖的四个板块

| 板块 | section 标识 | 内容 |
|------|--------------|------|
| 一、ESG 政策、评级、标准动态 | `policy` / `rating` / `standard` | 法规修订、监管政策、评级机构变动、披露标准更新 |
| 二、所属行业新闻动态与最佳实践 | `industry` | 客户所在行业的 ESG 进展、行业最佳实践 |
| 三、客户公司动态与 ESG 建议 | `company` | 客户自身动态、对 ESG 的影响、行动建议 |
| 四、对标企业 ESG 关键行动 | `peer` | 可对标企业本期采取的 ESG 关键举措 |

## 环境约束（重要，先读）

本机实测（2026-11）：

1. **`WebFetch` 工具对这些站点基本不可用** —— 政务与企业站点普遍返回
   "Unable to verify if domain ... is safe to fetch"。**抓取正文一律用
   `scripts/fetch_page.py`（本地 requests）**，不要用 WebFetch。
2. **`WebSearch` 可用且信息量大**，但脚本调不到它 —— 必须由 Claude 在会话里执行搜索，
   再把 URL 追加进 `data/urls.jsonl`。这是"客户动态"和"对标企业"两个板块的主要来源。
3. 国家级站点（`ccgp.gov.cn`、`search.ccgp.gov.cn`）封本机 IP，**不要浪费时间重试**。
4. 省级站点（河北、贵州、陕西、江苏、安徽等）大多可直连。

## 执行流程

### 第 1 步：确认参数

```bash
cd .claude/skills/esg-monthly-report
cat config/clients.yaml          # 看客户档案；新增客户在此加节点
```

- 客户标识（默认 `shenhua`）
- 报告周期（默认上一个自然月，`--period YYYY-MM`）
- 客户可按需改用别名或新增 profile

### 第 2 步：政策与行业板块 —— 脚本发现

```bash
python scripts/discover.py --client shenhua --period 2026-10 --output data/urls.jsonl
```

从实测可直连的列表页抽取候选（生态环境部应对气候变化/法规标准/部内要闻、发改委新闻发布），
按 URL 里的 `tYYYYMMDD` 过滤到报告期内。

### 第 3 步：客户与对标板块 —— WebSearch 补充

对 `company` 和 `peer` 两个板块，用 **WebSearch** 检索，把结果里的 URL 追加进
`data/urls.jsonl`（每行一条 JSON）：

```json
{"url": "https://...", "title": "标题", "source": "来源名", "section": "company", "date_hint": "2026-10-15"}
```

建议检索式（替换别名与对标企业名）：

```
<客户别名> 2026年10月 ESG报告 OR 可持续发展报告 OR 业绩说明会
<客户别名> 2026年10月 碳排放 OR 绿色矿山 OR 安全生产 公告
<对标企业名> 2026 ESG 报告 碳排放 目标 进展
<评级机构> 中国 能源 煤炭 ESG 评级 2026年10月
```

### 第 4 步：抓取 + 结构化抽取

```bash
python scripts/collect.py --input data/urls.jsonl --output data/events.json
```

逐条抓正文，用 LLM 抽成结构化事件（日期、标题、摘要、关键事实、E/S/G 板块、
重要性、对客户影响、涉及主体）。非 ESG 相关的会自动剔除。

### 第 5 步：生成报告

```bash
python scripts/build_report.py --client shenhua --events data/events.json --period 2026-10
```

输出到 `output/esg-monthly-report-<client>-<period>.md`。

### 第 6 步：人工复核（不可跳过）

生成后**必须**检查并向用户说明：

- `data/events.json` 里 `failed` 非空 → 哪些源没抓到，是否需要换 URL 补
- 报告里 `industry` / `company` / `peer` 板块若为空 → 明确告诉用户该板块无数据，
  不要用模型编造内容填坑
- 影响判断与建议是模型输出，**落地前需人工复核**

## 数据源清单

| 板块 | 来源 | 可直连 | 备注 |
|------|------|--------|------|
| policy | 生态环境部-应对气候变化与碳市场 | ✅ | CCER 方法学、碳市场公告 |
| policy | 生态环境部-法律法规与标准 | ✅ | 行政法规修订、标准发布 |
| policy | 生态环境部-部内要闻 | ✅ | |
| industry | 国家发改委-新闻发布 | ✅ | |
| policy | 生态环境部政策解读栏目 | ❌ | 403，改用 WebSearch |
| rating | MSCI / 标普 / 中诚信 | — | 只能 WebSearch |
| company / peer | 交易所公告、公司官网、财报 | — | 只能 WebSearch |

详见 `references/sources.md`。

## 常见错误

| 错误 | 正确做法 |
|------|---------|
| 用 WebFetch 抓政务站点 | 用 `scripts/fetch_page.py`，WebFetch 在本机不可用 |
| 反复重试 `ccgp.gov.cn` | 换省级镜像或 WebSearch，该站封 IP |
| 脚本里调用 WebSearch | 做不到；由 Claude 搜索后写进 `urls.jsonl` |
| 只跑 discover 就出报告 | 那只有 policy/industry，必须补 company/peer |
| 板块为空就用常识补写 | 明确报告无数据，让用户决定是否补搜 |
| 报告里不标来源链接 | 每条事件都必须带 URL |

## 快速参考

| 操作 | 命令 |
|------|------|
| 发现政策/行业候选 | `python scripts/discover.py --client shenhua --period 2026-10` |
| 抓取并抽取 | `python scripts/collect.py --input data/urls.jsonl --output data/events.json` |
| 生成报告 | `python scripts/build_report.py --client shenhua --events data/events.json` |
| 抓单页正文 | `python scripts/fetch_page.py <URL>` |
| 改客户档案 | 编辑 `config/clients.yaml` |
