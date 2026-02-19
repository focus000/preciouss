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
preciouss init                    # 初始化账本目录和默认文件
preciouss import <file>...        # 导入账单文件（自动识别平台）
preciouss import --source alipay  # 指定平台导入
preciouss match                   # 运行跨平台交易匹配
preciouss categorize              # 运行智能分类
preciouss status                  # 查看导入状态和统计
preciouss fava                    # 启动 Fava Web UI
```

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
CSV/PDF/API
    │
    ▼
Importer (解析为中间 Transaction 格式)
    │
    ▼
Matcher (三阶段匹配，合并跨平台交易)
    │
    ▼
Categorizer (规则 → ML → 人工标记)
    │
    ▼
Ledger Writer (写入 .bean 文件)
    │
    ▼
Fava (可视化 + 编辑)
```

## 开发

```bash
# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check src/

# 类型检查
uv run mypy src/preciouss/
```

## License

MIT
