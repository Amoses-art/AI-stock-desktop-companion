# 🐂 股大师 Gudashi — AI Stock Desktop Companion

> 桌面级股票持仓监控与智能分析桌宠，基于 **Tauri v2 + Vue3 + Python**。
> A desktop-grade AI-driven stock portfolio companion app built with Tauri, Vue and Python.

---

## ✨ 功能特性

- **多市场持仓管理** — A 股个股 / 场内 ETF·LOF / 场外基金 / 港股 / 美股
- **智能阈值预警** — 价格上穿下穿触发气泡提醒 + 系统通知
- **AI 对话分析** — 本地 Ollama LLM 驱动的 NLU 意图识别与 Skill 执行
- **三个独立窗口** — 桌宠窗口 / 气泡弹窗 / 功能面板，各司其职
- **实时行情** — 腾讯批量 API 主源 + 东方财富 / AKShare / 新浪多路备援
- **分析引擎** — 支撑压力位、趋势预测、个股复盘、盘面综述等 6 大内置 Skill
- **AI 可选关闭** — 安装时一键决定是否启用 AI 对话能力

## 🧩 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 · TypeScript · Vite · Pinia · Tauri v2 |
| Rust 桥接 | tokio · serde_json · Tauri Plugin (shell / notification / positioner) |
| 后端 | Python 3.12 · aiohttp · aiosqlite · SQLite |
| AI | 本地 Ollama (qwen2.5:1.5b / 7b) · NLU 规则引擎 |
| 数据源 | 腾讯公开行情 API · 东方财富 · AKShare · 新浪 |

## 📁 目录结构

```
AI-stock-desktop-companion/
├── frontend/                 # Tauri + Vue 前端（桌宠 / 面板 / 气泡三窗口）
│   ├── src-tauri/            # Rust 桥接层 (TCP 进程管理 + RPC 命令)
│   │   └── src/
│   │       ├── bridge.rs       # Python↔Rust TCP 桥
│   │       ├── process.rs      # 后端进程管理
│   │       └── commands/       # RPC handler (portfolio / quote / alert / skill / config)
│   ├── src/                  # Vue3 源码
│   │   ├── views/            # PetView · BubbleView · PanelView · ChatView · SettingsView
│   │   ├── stores/           # Pinia: app / pet / portfolio / settings
│   │   ├── core/             # rpc / contracts / events / state-machine
│   │   └── composables/      # usePetDisplay · usePetDrag · useTicker
│   ├── public/               # 静态资源 (skins / icons)
│   ├── package.json
│   └── vite.config.ts
│
├── backend/                  # Python 后端 (NLU + 行情 + Skill + 持久层)
│   ├── main.py                 # RPC Server 入口
│   ├── gudashi-backend.spec    # PyInstaller 打包 spec
│   ├── requirements.txt
│   ├── config/               # global_config + llm_config.json
│   ├── core/                 # nlu / alert_engine / ollama_client / stock_dict / trading_hours_guard / ...
│   ├── data/                 # quote_service · multi_market_router · health_checker
│   │   └── adapters/         # 腾讯 / 东财 / AKShare / 新浪 8 种数据源适配器
│   ├── handlers/             # RPC 命令处理器 (chat / portfolio / alert / quote / stats / orchestrator)
│   ├── rpc/                  # server + registry + tasks
│   ├── skills/               # 9 种 Skill + analysis_engine (6 大分析引擎)
│   ├── local/db.py           # SQLite 持久层 (aiosqlite + WAL)
│   └── tests/                # 回归测试
│
└── .gitignore
```

## 🚀 快速开始

### 前置依赖

- **Node.js** ≥ 18
- **Python** ≥ 3.10
- **Rust** ≥ 1.75 + Tauri v2 CLI
- **SQLite** (Python 内置)
- **[可选] Ollama** + `qwen2.5:1.5b`（启用 AI 对话时）

### 1. 克隆仓库

```bash
git clone https://github.com/Amoses-art/AI-stock-desktop-companion.git
cd AI-stock-desktop-companion
```

### 2. 后端启动（开发模式）

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # macOS / Linux

pip install -r requirements.txt
python main.py                    # RPC Server 监听 18765 端口
```

### 3. 前端启动（开发模式）

```bash
cd frontend
npm install
npm run tauri dev                 # 同时启动 Vue + 编译 Rust + spawn Python 后端
```

### 4. 构建安装包

```bash
cd backend
pyinstaller gudashi-backend.spec --clean   # 打包 Python 后端

cd ../frontend
npm run tauri build                         # 构建 NSIS 安装包
```

## 🔌 RPC 接口速览

| 命令 | 说明 |
|------|------|
| `portfolio.list / add / remove / update` | 持仓管理 |
| `quote.get / refresh` | 行情查询 / 批量刷新 |
| `alert_add / alert_remove` | 阈值预警规则 |
| `skill.execute / skill.cancel` | Skill 执行 / 取消 |
| `chat_history.list / chat_history.clear` | AI 对话历史 |
| `config.get / config.set` | 全局配置 |

## 📊 数据源优先级

```
腾讯批量 API (~0.3s)  →  东方财富 / AKShare  →  新浪单股查询
 (主源 / A股优先)           (并行备源)           (兜底，含 10 分钟熔断)
```

## 📝 版本历史

- **v0.7.0** (2026-10-15) — 完整恢复港美股 / 场内基金 / 场外基金支持；行情并行拉取；修复 3 个港美股根因 Bug
- **v0.6.0** (2026-10-09) — 行情刷新修复；NLU 规则引擎优化；数据状态提示改进
- **v0.5.2** — 首次可运行版本

---

© Gudashi Team · Licensed under MIT
