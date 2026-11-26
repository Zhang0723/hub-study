# 信息源清单

实测时间：2026-11-26。环境：本机（36.24.98.14）、Chrome UA。

## 一、可直连（脚本可抓）

| 来源 | 列表页 | 用于 |
|------|--------|------|
| 生态环境部-应对气候变化与碳市场 | `https://www.mee.gov.cn/ywgz/ydqhbh/` | CCER 方法学、碳市场政策、年度报告 |
| 生态环境部-法律法规与标准 | `https://www.mee.gov.cn/ywgz/fgbz/` | 行政法规修订、环保标准 |
| 生态环境部-部内要闻 | `https://www.mee.gov.cn/ywdt/hjywnews/` | 监管导向、行业会议 |
| 国家发改委-新闻发布 | `https://www.ndrc.gov.cn/xwdt/xwfb/` | 能源价格、产业政策 |

这些站点的列表页把发布日期编进文件名（`t20261021_1183474.shtml`），
解析时优先从 URL 取日期，比文本日期可靠。

## 二、不可直连（只能 WebSearch）

| 来源 | 原因 |
|------|------|
| `www.ccgp.gov.cn` / `search.ccgp.gov.cn` | 403 / "访问过于频繁"，封 IP |
| `www.ggzy.gov.cn` 检索 | 需验证码 |
| `new.ebidding.cecep.cn` | 403 |
| `www.mee.gov.cn/xxgk2018/xxgk/xxgk03/` | 空响应 / 403 |
| 生态环境部政策解读 `.../xxgk03/` | 需换路径或 WebSearch |
| 证监会 `csrc.gov.cn` 列表 | 静态页是 JS 渲染，抓到的是陈旧缓存 |
| MSCI / 标普 / Sustainalytics / 中诚信 评级公告 | 需登录或付费 |
| 交易所公告（上交所/港交所） | 需 WebSearch 或换镜像 |
| 客户与对标企业官网、财报 | 逐个站点验证，优先 WebSearch |

## 三、省级镜像（招投标场景用，见 h2 skill）

| 来源 | 状态 |
|------|------|
| `ccgp-hebei.gov.cn` | ✅ 列表页 + 详情页 + 分页（到 `index_9.html`） |
| `www.ccgp-tianjin.gov.cn` | ⚠️ 首页可达，列表结构待确认 |
| `xuancheng.gov.cn` / `nynct.jiangsu.gov.cn` | ✅ 详情页 |
| `ggzy.guizhou.gov.cn` / `ggzyjy.ahsz.gov.cn` / `ggzy.xinjiang.gov.cn` | ✅ 详情页 |
| `shaanxi.jianyu360.cn` / `bidding.csg.cn` | ✅ 详情页 |
| `www.ccgp-guangdong.gov.cn` / `ccgp-sichuan.gov.cn` | ❌ 首页可达但列表被封 |

## 四、WebSearch 检索式模板

### 政策与标准
```
生态环境部 2026年10月 碳市场 OR 方法学 通知
国务院 2026年10月 行政法规 修订 绿色低碳
上市公司可持续发展报告指引 2026 交易所
ISSB IFRS S2 2026 进展 中国
```

### 评级
```
MSCI 中国 煤炭 能源 ESG 评级 2026年10月
标普全球 CSA 中国 能源 2026
中诚信 ESG 评级 煤炭 2026
```

### 客户与对标
```
<客户别名> 2026年10月 ESG报告 OR 可持续发展报告
<客户别名> 碳排放 2026 公告
<对标企业名> ESG报告 2026 减碳 目标
```

### 招投标（h2 skill）
```
ESG OR 双碳 OR 可持续 中标公告 2026年10月 金额
碳足迹核算 中标 2026
绿色工厂评价 中标金额 2026
```
