# Crypto Open Interest Dashboard

参考 Coinglass 风格的多交易所期货持仓量（Open Interest）看板，支持从各币种上线之日起追溯历史，并保持后台自动更新。

## 功能

- 展示主流币种的期货持仓量历史
- 支持周期：`5m`、`15m`、`1h`、`4h`、`1d`、`1w`、`1M`
- 多数据源：`binance`（币安）、`bybit`、`coinglass`
- 自动后台同步更新
- 最新持仓量排名 + 24h 变化榜
- 双轴交互式图表（持仓量 + 持仓价值）

## 数据源说明

| 数据源 | 费用 | 历史数据 | 持仓价值 | 高频周期限制 |
|--------|------|----------|----------|--------------|
| Bybit | 免费 | 可回溯至 2020 年 | 通过价格 × 持仓量估算 | 支持 5m/15m/1h/4h |
| Binance | 免费 | 仅最近约 30 天 | 官方提供 | 支持 5m/15m/1h/4h |
| Coinglass | 付费（需 API Key） | 完整历史（Hobbyist 及以上） | 官方提供 | Hobbyist 仅支持 ≥4h；<4h 需升级至 Standard 及以上 |

> 默认启用 `bybit,binance`，默认显示 `bybit`。如需使用 Coinglass，请在 `.env` 中填写 `COINGLASS_API_KEY`。
>
> **注意**：Coinglass V4 Hobbyist 套餐对 `/api/futures/open-interest/history` 的 `interval` 参数限制为 `4h/6h/8h/12h/1d/1w`，`1h/15m/5m` 会返回 `403 The requested interval is not available for your current API plan.`。因此短周期 OI 通过 Bybit / Binance 补齐。

## 技术栈

- 后端：FastAPI + SQLAlchemy + PostgreSQL/SQLite
- 数据源：Bybit V5 API、Binance FAPI、Coinglass V4 API
- 定时任务：APScheduler
- 前端：原生 HTML/JS + ECharts + DataTables

## 快速开始

### 1. 安装依赖

```bash
cd F:\PyProject\coinglass_
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

关键配置项：

```env
# 数据源（逗号分隔）
DATA_SOURCES=bybit,binance
DEFAULT_DATA_SOURCE=bybit

# 数据库（生产环境建议 PostgreSQL）
DATABASE_URL=sqlite:///./coinglass.db

# Coinglass API Key（可选）
COINGLASS_API_KEY=your_key_here
```

### 3. 启动服务

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

访问：`http://127.0.0.1:8000/`

### 4. Docker Compose（可选）

```bash
docker-compose up --build -d
```

## 部署上线

以下方案任选其一。

### 方案 A：阿里云 ECS 部署（国内用户推荐）

详细步骤见 [`deploy/ALIBABA_CLOUD.md`](deploy/ALIBABA_CLOUD.md)。

适合已有域名、希望稳定长期运行的国内用户。费用约 50-100 元/月，需完成域名 ICP 备案。

### 方案 B：Docker Compose + Caddy（通用 VPS）

前置准备：一台公网服务器（如 Ubuntu 22.04/24.04）、一个域名解析到服务器、开放 80/443 端口。

#### 1. 推送代码到 Git 仓库

```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/mmdzzh/coinglass_look.git
git push -u origin main
```

#### 2. 服务器上执行一键部署脚本

```bash
# 登录服务器后
export REPO_URL=https://github.com/mmdzzh/coinglass_look.git
export DOMAIN=oi.example.com
export ACME_EMAIL=your-email@example.com

curl -fsSL https://raw.githubusercontent.com/mmdzzh/coinglass_look/main/deploy/deploy.sh | sudo bash
```

或手动操作：

```bash
git clone https://github.com/mmdzzh/coinglass_look.git /opt/coinglass_
cd /opt/coinglass_
cp .env.example .env
# 编辑 .env：设置 DOMAIN、ACME_EMAIL、COINGLASS_API_KEY 等

docker compose -f docker-compose.prod.yml up -d --build
```

Caddy 会自动为 `DOMAIN` 申请 Let's Encrypt 证书。稍等片刻后访问 `https://你的域名` 即可。

### 方案 C：Render 免费部署（适合演示）

Render 提供免费 Web Service + PostgreSQL（数据库免费 90 天），无需自己准备服务器和域名。

1. 访问 [Render Dashboard](https://dashboard.render.com/)。
2. 点击 **New + → Blueprint**，粘贴仓库地址 `https://github.com/mmdzzh/coinglass_look`，选择 `render.yaml`。
3. Render 会自动创建 Web Service 和 PostgreSQL。
4. 部署完成后会分配 `https://xxx.onrender.com` 域名。

**限制**：免费 Web Service 15 分钟无访问会休眠；免费 PostgreSQL 90 天后删除。

### 方案 D：Systemd + Nginx/Caddy

不想用 Docker 可参考 `deploy/coinglass.service` 与 `deploy/Caddyfile` 手动配置。

### 本地快速验证

```bash
cp .env.example .env
# 按需编辑 .env
docker compose up -d
```

访问 `http://localhost:8000/`。

## 首次数据同步

启动后，后台会自动增量同步。如需手动同步全部历史数据：

```bash
# Docker 部署

docker compose -f docker-compose.prod.yml exec web python sync_once.py

# 本地/Python 环境
python sync_once.py
```

或点击页面上的「立即同步」按钮。

### 高频数据补全

```bash
# 补全 Bybit 4h/1h/15m/5m
docker compose -f docker-compose.prod.yml exec web python sync_intervals.py bybit --intervals 4h 1h 15m 5m

# 补全 Binance 高频（仅最近约 30 天）
docker compose -f docker-compose.prod.yml exec web python sync_intervals.py binance --intervals 4h 1h 15m 5m
```

## 数据同步策略

由于短周期历史数据量巨大，项目采用分层回溯策略，可在 `.env` 中调整：

| 周期 | 默认回溯 | 更新频率 |
|------|----------|----------|
| 5m   | 30 天    | 15 分钟  |
| 15m  | 30 天    | 15 分钟  |
| 1h   | 30 天    | 1 小时   |
| 4h   | 365 天   | 1 小时   |
| 1d   | 上线至今 | 6 小时   |
| 1w   | 上线至今 | 6 小时   |
| 1M   | 上线至今 | 6 小时   |

> 可通过 `.env` 中的 `BACKFILL_DAYS_5M`、`BACKFILL_DAYS_15M`、`BACKFILL_DAYS_1H`、`BACKFILL_DAYS_4H` 覆盖上述默认值。

## API 接口

- `GET /api/sources` - 列出已启用的数据源
- `GET /api/pairs?source=bybit` - 列出交易对
- `GET /api/oi/{symbol}?source=bybit&interval=1d` - 持仓量历史
- `GET /api/oi/latest?source=bybit` - 最新持仓量排名（含 24h 变化）
- `POST /admin/sync?source=bybit` - 触发手动同步

## 注意事项

- 当前 `.env` 默认使用 SQLite，便于本地快速验证。生产环境建议改为 PostgreSQL。
- 程序会自动检测 Windows 系统代理设置，也支持通过 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量配置代理。
- 若网络无法访问交易所 API，请配置代理/VPN。

## 目录结构

```
coinglass_/
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── README.md
├── main.py
├── config.py
├── database.py
├── models.py
├── schemas.py
├── api.py
├── sync_service.py
├── binance_client.py
├── sync_once.py
├── data_sources/
│   ├── __init__.py
│   ├── base_source.py
│   ├── binance_source.py
│   ├── bybit_source.py
│   └── coinglass_source.py
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```
