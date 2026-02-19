# Preciouss - 开发上下文

## 项目概览

跨平台个人记账系统，基于 Beancount v3 + Fava，采用 CLI 形态。

## 工具链约定（mise + uv）

项目使用 mise 管理开发工具，uv 管理 Python 依赖。所有工具和依赖都必须限定在项目作用域内，禁止安装到全局。

### mise — 开发工具管理

```bash
mise use <tool>[@version]       # 添加工具到项目（写入 .mise.toml）
mise use --pin <tool>           # 锁定精确版本
mise install                    # 安装 .mise.toml 中定义的所有工具
mise ls                         # 查看当前激活的工具
```

**规则：**
- 用 `mise use` 添加工具，**不要用** `mise use -g`（会写入全局配置）
- `mise use` 默认写入当前目录的 `.mise.toml`，这是项目作用域
- 需要一个 CLI 工具时，**优先** `mise use` 安装，mise 没有的才考虑 `uvx`

### uv — Python 依赖管理

```bash
uv add <package>                # 添加依赖到 pyproject.toml [project.dependencies]
uv add --dev <package>          # 添加开发依赖到 [dependency-groups] dev
uv sync                        # 同步安装所有依赖到 .venv
uv run <command>                # 在项目虚拟环境中运行命令
uvx <tool> [args...]            # 临时运行一个 CLI 工具（不安装到项目）
uv pip install <package>        # 最后手段：pip 兼容安装到 .venv（不更新 pyproject.toml）
```

**规则：**
- Python 库依赖用 `uv add`，**不要** 手动编辑 pyproject.toml
- 运行项目命令一律用 `uv run`（如 `uv run pytest`、`uv run preciouss`）
- 需要临时跑一个 Python CLI 工具，用 `uvx`（不污染项目依赖）
- `uv pip install` 仅作为 `uv add` 无法添加时的 fallback，且只安装到 `.venv`
- **禁止** `uv tool install`（会安装到 `~/.local/bin`，属于全局作用域）

### 安装新工具的决策流程

```
需要一个工具？
  ├─ 是开发工具/CLI（非 Python 库）？
  │   ├─ mise use <tool>          ← 优先
  │   └─ uvx <tool>               ← mise 没有时
  └─ 是 Python 库依赖？
      ├─ uv add <package>         ← 优先
      └─ uv pip install <package> ← uv add 失败时（不更新锁文件）
```

## 开发命令

```bash
uv run pytest tests/ -v         # 运行测试
uv run ruff check src/          # Lint
uv run ruff format src/         # 格式化
uv run mypy src/preciouss/      # 类型检查
uv run preciouss --help         # CLI 帮助
uv run preciouss init           # 初始化账本
uv run preciouss import <file>              # 导入账单
uv run preciouss import --year 2024:2025 <file>  # 只导入 2024 年
uv run preciouss status         # 查看状态
uv run preciouss fava           # 启动 Fava
```

## 架构

### 核心模块

- `config/schema.py` - Pydantic 配置模型 + TOML 加载
- `importers/base.py` - Importer 基类（PrecioussImporter, CsvImporter）和中间 Transaction 模型
- `importers/alipay.py` - 支付宝 CSV 导入
- `importers/cmb.py` - 招商银行信用卡/储蓄卡 CSV 导入
- `importers/wechat.py` - 微信支付 CSV/XLSX 导入
- `importers/wechathk.py` - 微信支付香港 JSON 导入（跨币种 HKD→CNY 自动转换）
- `importers/aldi.py` - ALDI 奥乐齐 JSON 导入（多 posting，商品明细写入 posting metadata）
- `importers/costco.py` - Costco 开市客 JSON 导入（多 posting，商品明细 + 跨币种支付）
- `importers/jd.py` - 京东 CSV 导入（支持退款净额计算）
- `importers/resolve.py` - 支付方式字符串 → Beancount 账户名解析
- `matching/engine.py` - 三阶段匹配引擎（Reference ID → Intermediary → Fuzzy）
- `categorize/rules.py` - 规则分类（关键词 + 正则）
- `categorize/taxonomy.py` - 分类体系定义
- `ledger/writer.py` - Beancount .bean 文件写入（含跨币种 @ 价格注解）
- `ledger/accounts.py` - 账户体系和默认账户
- `cli.py` - Click CLI 入口

### 关键设计决策

1. **中间 Transaction 模型**: 所有 importer 先解析为统一的 `Transaction` dataclass，再由 ledger writer 转为 beancount 格式。这样匹配引擎和分类引擎可以在统一模型上工作。

2. **三阶段匹配**: Phase 1 用交易号精确匹配，Phase 2 识别"平台刷卡"模式（如支付宝→信用卡），Phase 3 用金额+日期+商户名模糊匹配。

3. **beangulp 兼容但不强依赖**: 我们的 importer 基类是独立的 `PrecioussImporter`，但可以包装为 beangulp `Importer`。

## 新增 Importer 开发指南

1. 在 `src/preciouss/importers/` 下创建新文件
2. 继承 `CsvImporter`（CSV 格式）或 `PrecioussImporter`（其他格式）
3. 实现 `identify()`, `extract()`/`_parse_row()`, `account_name()` 方法
4. 在 `cli.py` 的 `_get_importers()` 中注册
5. 在 `tests/fixtures/` 下添加样本文件
6. 编写测试

## 代码风格

- Ruff: line-length=100, target-version=py312
- Lint rules: E, F, I, N, W, UP
- 使用类型注解

## 测试约定

- fixtures 目录: `tests/fixtures/` 存放样本 CSV/JSON/XLSX
- 每个 importer 至少一个测试用例
- 测试文件命名: `test_<module>.py`
