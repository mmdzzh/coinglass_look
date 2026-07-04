# 直接 Python 部署指南（Ubuntu 24.04）

本文档介绍如何在不使用 Docker 的情况下，直接在 Ubuntu 24.04 上部署 Crypto OI Dashboard。

适用场景：
- 服务器资源有限，不想运行 Docker 额外开销
- 更习惯传统的 Python + systemd + Nginx 部署方式
- 需要自定义 PostgreSQL 安装

## 前置准备

1. 一台 Ubuntu 24.04 服务器（推荐阿里云 ECS 香港/新加坡，可直接访问境外 API）
2. 一个域名解析到服务器公网 IP
3. 服务器安全组放行 22、80、443 端口
4. 大陆 ECS 需要准备代理（HTTP/SOCKS5）

## 1. 连接服务器

```bash
ssh root@<ECS公网IP>
```

## 2. 安装系统依赖

```bash
apt-get update && apt-get upgrade -y
apt-get install -y python3.12 python3.12-venv python3-pip python3-dev postgresql postgresql-contrib nginx git curl
```

## 3. 配置 PostgreSQL

```bash
# 启动 PostgreSQL
systemctl enable --now postgresql

# 创建数据库用户和数据库
sudo -u postgres psql <<EOF
CREATE USER coinglass WITH PASSWORD 'YOUR_DB_PASSWORD';
CREATE DATABASE coinglass OWNER coinglass;
GRANT ALL PRIVILEGES ON DATABASE coinglass TO coinglass;
EOF
```

> 将 `YOUR_DB_PASSWORD` 替换为强密码。

## 4. 拉取代码

```bash
git clone https://github.com/mmdzzh/coinglass_look.git /opt/coinglass_
cd /opt/coinglass_
```

## 5. 创建 Python 虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. 配置环境变量

```bash
cp .env.example .env
nano .env
```

关键配置：

```env
# 数据库
DATABASE_URL=postgresql+psycopg2://coinglass:YOUR_DB_PASSWORD@localhost:5432/coinglass

# 数据源
DATA_SOURCES=bybit,binance
DEFAULT_DATA_SOURCE=bybit

# 同步周期
BACKFILL_DAYS_5M=30
BACKFILL_DAYS_15M=30
BACKFILL_DAYS_1H=30
BACKFILL_DAYS_4H=365
BACKFILL_DAYS_1D=0

# 仅大陆 ECS 需要代理
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
```

按 `Ctrl+O` 保存，`Ctrl+X` 退出。

## 7. 初始化数据库表

```bash
source .venv/bin/activate
python -c "from database import init_db; init_db()"
```

## 8. 配置 systemd 服务

编辑服务文件：

```bash
nano /etc/systemd/system/coinglass.service
```

写入：

```ini
[Unit]
Description=Crypto OI Dashboard
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/coinglass_
Environment=PATH=/opt/coinglass_/.venv/bin
EnvironmentFile=/opt/coinglass_/.env
ExecStart=/opt/coinglass_/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
systemctl daemon-reload
systemctl enable --now coinglass
systemctl status coinglass
```

查看日志：

```bash
journalctl -u coinglass -f
```

## 9. 配置 Nginx + HTTPS

安装 Certbot：

```bash
apt-get install -y certbot python3-certbot-nginx
```

编辑 Nginx 配置：

```bash
nano /etc/nginx/sites-available/coinglass
```

写入：

```nginx
server {
    listen 80;
    server_name oi.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name oi.example.com;

    ssl_certificate /etc/letsencrypt/live/oi.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/oi.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用站点：

```bash
ln -s /etc/nginx/sites-available/coinglass /etc/nginx/sites-enabled/
nginx -t
```

申请 HTTPS 证书：

```bash
certbot --nginx -d oi.example.com
```

启动 Nginx：

```bash
systemctl enable --now nginx
```

## 10. 首次数据同步

```bash
cd /opt/coinglass_
source .venv/bin/activate

# 日线全量同步
python sync_once.py

# 高频数据（建议在 tmux/screen 中执行）
python sync_intervals.py bybit --intervals 4h 1h 15m 5m
python sync_intervals.py binance --intervals 4h 1h 15m 5m
```

使用 tmux 防止 SSH 断开：

```bash
apt-get install -y tmux
tmux new -s sync
python sync_intervals.py bybit --intervals 4h 1h 15m 5m
# Ctrl+B 然后 D 退出
# tmux attach -t sync 重新进入
```

## 11. 配置定时同步

```bash
crontab -e
```

添加：

```cron
# 每小时同步日线
0 * * * * cd /opt/coinglass_ && /opt/coinglass_/.venv/bin/python sync_intervals.py bybit --intervals 1d >> /var/log/coinglass_cron.log 2>&1

# 每 15 分钟同步高频
*/15 * * * * cd /opt/coinglass_ && /opt/coinglass_/.venv/bin/python sync_intervals.py bybit --intervals 5m 15m 1h 4h >> /var/log/coinglass_cron.log 2>&1
```

创建日志文件：

```bash
touch /var/log/coinglass_cron.log
```

## 12. 大陆 ECS 代理配置

如果服务器在中国大陆，需要配置代理才能访问 Bybit/Binance API。

### 12.1 启动本地代理（以 Clash 为例）

```bash
cd /opt
mkdir clash && cd clash
# 上传你的 config.yaml 到 /opt/clash/
wget https://release.dreamacro.workers.dev/latest/clash-linux-amd64.gz
gunzip clash-linux-amd64.gz
chmod +x clash-linux-amd64
nohup ./clash-linux-amd64 -f config.yaml > clash.log 2>&1 &
```

### 12.2 验证代理

```bash
source /opt/coinglass_/.venv/bin/activate
python -c "
import requests, os
proxies = {'http': os.getenv('HTTP_PROXY',''), 'https': os.getenv('HTTPS_PROXY','')}
r = requests.get('https://api.bybit.com/v5/market/time', proxies=proxies, timeout=10)
print('Bybit:', r.status_code, r.text)
"
```

## 13. 常用维护命令

```bash
# 重启服务
systemctl restart coinglass

# 查看日志
journalctl -u coinglass -f

# 查看定时任务日志
tail -f /var/log/coinglass_cron.log

# 升级代码
cd /opt/coinglass_
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart coinglass

# 备份数据库
pg_dump -U coinglass -h localhost coinglass > /backup/coinglass_$(date +%F).sql
```

## 14. 费用估算

| 项目 | 费用 |
|------|------|
| ECS 2核4GB（香港） | 约 60-120 元/月 |
| 域名 | 约 60-100 元/年 |
| HTTPS（Let's Encrypt） | 免费 |

---

参考项目根目录 `README.md` 和 `AGENTS.md`。
