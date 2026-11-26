---
name: esg-tender-monitor
description: Use when the user asks to collect ESG/可持续发展/双碳 tender and award announcements, analyze bidding hotspots and award amount distribution over the past 2 years, or monitor and push new ESG-related tender opportunities daily. 用于招投标信息汇总分析与每日新增推送。
version: "1.0.0"
license: MIT
---

# ESG 招投标信息汇总与监控

两件事：
1. **汇总分析** —— 过去 2 年 ESG / 可持续发展 / 双碳相关中标情况，输出热点招标情况与中标金额分布。
2. **每日监控** —— 每天抓取新增的 ESG 相关招标信息并推送。

## 何时使用

- 用户要求汇总 ESG / 双碳 / 可持续��度相关招投标信息
- 用户问"今年 ESG 招标热点是什么""中标金额一般多少"
- 用户要求每天推送新的 ESG 招标公告
- 用户问某个客户有没有在投标 / 中标 ESG 类项目

## 环境约束（重要，先读）

本机实测（2026-11）：

1. **`WebFetch` 工具对这些站点不可用**（域名安全校验失败）。抓正文一律用
   `scripts/fetch_page.py`（本地 requests）。
2. **国家级站点封本机 IP**：`www.ccgp.gov.cn` 403、`search.ccgp.gov.cn` "访问过于频繁"、
   `ggzy.gov.cn` 检索需验证码、`new.ebidding.cecep.cn` 403。**不要重试，直接换源。**
3. **可直连的省级源**：`ccgp-hebei.gov.cn`（列表+详情+翻页，最完整）、
   `xuancheng.gov.cn`、`nynct.jiangsu.gov.cn`、`ggzy.guizhou.gov.cn`、
   `ggzyjy.ahsz.gov.cn`、`ggzy.xinjiang.gov.cn`、`shaanxi.jianyu360.cn`、
   `bidding.csg.cn`。见 `references/sources.md`。
4. **河北列表分页只到 `index_9.html`**（约 10 页 × 50 条 ≈ 500 条），月份归档目录 403。
   → **2 年历史无法靠翻页拿全**，必须用 WebSearch 发现历史公告，走 seed 通道补齐。
5. 河北详情页有**两种格式**，已由 `scripts/parse_hebei.py` 统一解析：
   - 2025 及更早：正文 + `<span id="字段">` + `#detail#` 分隔符编码表
   - 2026 起：内联 `const announcementData = {...}` JS 对象（正文不直接渲染）
   - 编码表行分隔符 `#_@_@`，单元格 `#_#`，空值写 "null"

## 任务一：2 年汇总分析

### 第 1 步：采集

```bash
cd .claude/skills/esg-tender-monitor
python scripts/collect.py --mode list --pages 10 --since 2024-11-26 \
    --output data/bids.json --raw-output data/bids_raw.jsonl
```

list 通道从省级镜像翻页，产出近期公告。

### 第 2 步：补齐历史（WebSearch）

2 年跨度必须靠 WebSearch 补。检索式：

```
ESG OR 双碳 OR 可持续发展 中标公告 2024 2025 金额
碳足迹核算 中标公告 2025
绿色工厂评价 服务采购 中标 2025
碳排放核查 成交结果公告 2025
节能降碳改造 EPC 中标 2024
```

把搜到的 URL 写进 `data/urls.jsonl`（每行一条 JSON）：

```json
{"url": "https://...", "title": "项目名称", "source": "来源站名", "section": "award"}
```

然后：

```bash
python scripts/collect.py --mode seed --input data/urls.jsonl \
    --output data/bids.json --raw-output data/bids_raw.jsonl
```

### 第 3 步：分析

```bash
python scripts/analyze.py --input data/bids.json --since 2024-11-26
```

输出 `analysis/summary.md`（热点 + 金额分布）与 `analysis/summary.json`。

### 第 4 步：解读并向用户汇报

`summary.md` 是**统计结果**。你还要在此基础上给出判断，例如：

- 哪个类别最热、金额中枢在哪
- 金额分档是否集中，说明这个市场是"小额咨询为主"还是"工程改造为主"
- 头部供应商是谁，其业务重心是什么
- 对我方客户（能源/资源类）意味着什么机会

## 任务二：每日监控推送

### 手动跑一次

```bash
python scripts/monitor.py --days 2 --pages 2
```

产出：
- `output/daily-<日期>.md` —— 推送用日报（按中标/招标/其他分组）
- `output/daily-<日期>.json` —— 结构化数据
- `data/bids.json` —— 累计库
- `data/seen.json` —— 已推送 URL（增量去重依据）

### 每天自动跑

用 `scripts/setup_cron.sh` 注册 launchd 定时任务（macOS 推荐，比 cron 更可靠）：

```bash
bash scripts/setup_cron.sh          # 注册每日 09:07 任务
bash scripts/setup_cron.sh --remove  # 卸载
```

或用 CronCreate 工具在会话内调度（适合临时观察）：

```
cron: "7 9 * * *"
```

### 推送渠道

按优先级：

1. **在会话里推送** —— 运行 `monitor.py` 后，把 `output/daily-<日期>.md` 的内容直接
   呈现给用户；需要通知其他人时用 `SendMessage`。
2. **Webhook** —— `--webhook https://...`，POST 飞书/钉钉风格的 markdown 消息。
3. **邮件 / 企业微信机器人** —— 见 `references/sources.md` 的推送配置段。

### 增量逻辑

`data/seen.json` 记录已处理过的 URL。重复运行不会重复推送。判定为"非 ESG 相关"的
公告也会记入 seen，避免每天重复抓取。

## 关键配置

`config/sources.yaml`：

| 段 | 作用 |
|----|------|
| `sources` | 列表页地址、翻页规则、请求间隔（政务站点对频率敏感，`delay` 别小于 2 秒） |
| `keywords.must` | 具体词，命中任一即相关（ESG、双碳、碳足迹、绿色工厂…） |
| `keywords.any` | 泛词，需同时命中 `any_min_hits` 个才算（避免"碳素钢管"这类噪声） |
| `keywords.exclude` | 排除词，命中即丢弃 |
| `categories` | 分类枚举，供 LLM 选择 |
| `amount_buckets` | 金额分档，用于分布分析 |

新增数据源：往 `sources` 里加一条 `list_url` 即可，翻页规则是 `list_url + /index_{n}.html`。
不同站点结构不同时，在 `collect.py` 的 `extract_list_items` 里加分支。

## 常见错误

| 错误 | 正确做法 |
|------|---------|
| 用 WebFetch 抓公告 | 用 `scripts/fetch_page.py` |
| 反复重试 ccgp.gov.cn | 换省级镜像；该站封 IP，重试无用 |
| 只翻页就想要 2 年数据 | 翻页最多覆盖约 500 条；必须用 WebSearch + seed 通道补 |
| 把更正公告当中标公告 | `notice_type` 会区分"更正公告"，汇报时说明清楚 |
| 金额字段全是 null | 节能收益分成/费率类项目本就没有固定金额，不是 bug；看覆盖率 |
| 关键词一命中"碳"就收 | 用 must + any 双层规则，见 config/sources.yaml |
| 忘记 `seen.json` 导致重复推送 | monitor.py 自动维护，不要手删 |

## 快速参考

| 操作 | 命令 |
|------|------|
| 采集（列表翻页） | `python scripts/collect.py --mode list --pages 10 --since 2024-11-26` |
| 采集（指定 URL） | `python scripts/collect.py --mode seed --input data/urls.jsonl` |
| 汇总分析 | `python scripts/analyze.py --input data/bids.json --since 2024-11-26` |
| 每日监控 | `python scripts/monitor.py --days 2 --pages 2` |
| 注册每日任务 | `bash scripts/setup_cron.sh` |
| 抓单页正文 | `python scripts/fetch_page.py <URL>` |
| 解析河北详情页 | `python scripts/parse_hebei.py <html文件>` |
