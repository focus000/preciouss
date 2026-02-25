# Preciouss

跨平台个人记账系统，基于 Beancount v3 生态，管理中国大陆和香港的多个银行、支付平台和券商账户。

## 解决的问题

- 账单分散在十几个平台，无法统一查看
- 跨平台交易（如支付宝刷信用卡）产生重复记录需要匹配
- 手动分类耗时，需要智能分类辅助

## 支持的平台

| 平台 | 类型 | 状态 |
|------|------|------|
| 支付宝 | CSV 导入 | ✅ |
| 招商银行 (信用卡/储蓄卡) | CSV 导入 | ✅ |
| 微信支付 | CSV/XLSX 导入 | ✅ |
| 微信支付香港 (WeChat Pay HK) | JSON 导入 | ✅ |
| 京东 | CSV 导入 | ✅ |
| ALDI 奥乐齐 | JSON 导入 | ✅ |
| Costco 开市客 | JSON 导入 | ✅ |
| 工商银行 | CSV/PDF 导入 | 🔜 |
| 建设银行 | CSV/PDF 导入 | 🔜 |
| 中国银行 | CSV 导入 | 🔜 |
| 汇丰香港 | CSV 导入 | 🔜 |
| 中银香港 | CSV/PDF 导入 | 🔜 |
| AlipayHK | CSV 导入 | 🔜 |
| 云闪付 | CSV 导入 | 🔜 |
| Interactive Brokers | Flex Query API | 🔜 |
| PayPal | REST API | 🔜 |

## 安装

### 前置要求

- [mise](https://mise.jdx.dev/) - 版本管理工具

### 安装步骤

```bash
# 克隆项目
git clone <repo-url> preciouss
cd preciouss

# 安装 Python 和 uv (通过 mise)
mise install

# 安装依赖
uv sync

# 验证安装
uv run preciouss --version
```

## 快速开始

```bash
# 1. 初始化账本目录
uv run preciouss init

# 2. 导入账单文件（自动识别平台）
uv run preciouss import ~/Downloads/alipay_202401.csv ~/Downloads/cmb_202401.csv

# 3. 查看导入状态
uv run preciouss status

# 4. 启动 Fava Web UI 查看和编辑
uv run preciouss fava
```

## CLI 命令

```
preciouss init                          # 初始化账本目录和默认文件
preciouss import <file>...              # 导入账单文件（自动识别平台）
preciouss import --source alipay        # 指定平台导入
preciouss import --year 2024:2025       # 只导入 2024 年的交易
preciouss import --year 2020:2026       # 只导入 2020–2025 年的交易
preciouss match                         # 运行跨平台交易匹配
preciouss categorize                    # 运行智能分类
preciouss status                        # 查看导入状态和统计
preciouss fava                          # 启动 Fava Web UI
```

### `--year` 日期范围过滤

当账单文件跨多年，但只需导入特定年份时使用：

```bash
# 只导入 2024 年（2024-01-01 到 2024-12-31）
preciouss import --year 2024:2025 alipay_all.csv

# 导入 2020–2025 年（2026-01-01 之前的所有交易）
preciouss import --year 2020:2026 alipay_all.csv
```

语义：`--year START:END` 保留满足 `START-01-01 ≤ 交易日期 < END-01-01` 的交易，即包含 START 年、不包含 END 年。

## 分类规则

内置规则覆盖常见商户、品牌和交易类型，自动映射到 Beancount 账户。部分规则感知收支方向：

| 交易描述 | 支出 (expense) | 收入 (income) |
|----------|---------------|--------------|
| 转账 | `Expenses:Transfer` | `Income:Transfer` |
| 群收款 | `Expenses:Transfer` | `Income:Transfer` |
| 工资/薪资 | — | `Income:Salary` |
| 退款/退货 | — | `Income:Refund` |

可在 `config.toml` 中通过 `[categorize.keyword_rules]` 添加自定义关键词规则（优先级高于内置规则）。

## 配置

复制示例配置文件并修改：

```bash
cp config.example.toml config.toml
```

配置文件支持：
- 账户定义（银行、支付平台、券商）
- 匹配引擎参数（日期容差、相似度阈值）
- 自定义分类规则（关键词 → 分类映射）

详见 `config.example.toml` 中的注释。

## 数据流

```
CSV/JSON/XLSX
    │
    ▼
Importer (解析为中间 Transaction 格式)
    │  每笔交易独立导入；跨平台重复不合并，而是通过清算账户桥接
    ▼
Clearing Engine (DFS 清算链匹配)
    │  从"终端支出"向上追溯清算账户链，分配共享 ^clr-NNNNNN 链接标签
    │  终端支出 = source_account 是清算账户 + counter_account 是消费账户
    ▼
Categorizer (规则分类)
    │  关键词/正则 → Beancount 账户；感知收支方向
    ▼
Ledger Writer (写入 .bean 文件)
    │  普通交易 / 多 posting（ALDI/Costco/JD） / 跨币种桥接（WeChatHK）
    ▼
Fava (可视化 + 编辑)
```

### 清算账户设计

跨平台交易不做运行时合并，而是通过 `Assets:Clearing:*` 账户自然对冲：

```
微信支付  →  Assets:Clearing:JD:WX        ←  京东收款
ALDI 收据 ←  Assets:Clearing:ALDI         ←  微信/支付宝付款
WechatHK  →  Assets:Clearing:Costco (HKD) ←  Costco 收据 (CNY, @ rate)
```

`preciouss import` 时自动运行 DFS 清算链匹配，将相关交易用 `^clr-NNNNNN` 链接标签关联，便于在 Fava 中查看完整链路。

## 开发

```bash
# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check src/

# 类型检查
uv run mypy src/preciouss/
```

## GitHub Actions: Review -> 自动修复 PR

已提供工作流文件：`.github/workflows/codex-pr-review-autofix.yml`。

行为约束：
- 先 Review，再 Auto-fix（两阶段）
- 仅处理 `P0/P1`
- 不做重构
- 必须补测试
- 必须执行并通过 `uv run pytest tests/ -v`

启用前请在仓库设置中添加 Secret：
- `OPENAI_API_KEY`

触发条件：
- `pull_request`（opened / synchronize / reopened / ready_for_review）
- 仅对同仓库 PR（非 fork）执行
- PR 是 `draft` 时不执行

## License

MIT
