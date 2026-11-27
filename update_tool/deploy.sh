#!/bin/bash
# 华泰看板云端部署脚本（Ubuntu 24.04）
set -e

APP=/opt/app
PY=$APP/.venv/bin/python

echo "=== 1. 解压项目 ==="
sudo chown -R ubuntu:ubuntu $APP
cd $APP
tar xzf /tmp/app.tgz
mkdir -p logs

echo "=== 2. 统一 akshare 版本（与本地一致 1.20.61）==="
$APP/.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple "akshare==1.20.61" || echo "版本安装警告（继续）"
$PY -c "import akshare;print('akshare',akshare.__version__)"

echo "=== 3. 配置 Nginx ==="
sudo tee /etc/nginx/sites-available/htboard > /dev/null <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    root /opt/app;
    index index.html;
    charset utf-8;

    gzip on;
    gzip_comp_level 6;
    gzip_min_length 1000;
    gzip_types text/plain text/css application/javascript application/json text/html;

    location / {
        try_files $uri $uri/ =404;
    }
    location ~* \.(js|css|html)$ {
        add_header Cache-Control "public, max-age=300";
    }
}
NGINX
sudo ln -sf /etc/nginx/sites-available/htboard /etc/nginx/sites-enabled/htboard
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx && sudo systemctl enable nginx

echo "=== 4. 配置定时任务 ==="
( crontab -l 2>/dev/null | grep -v "run_update.py\|run_stock_all.py" ; \
  echo "*/30 * * * * cd /opt/app/update_tool && /opt/app/.venv/bin/python run_update.py >> /opt/app/logs/cron_update.log 2>&1" ; \
  echo "30 17 * * * cd /opt/app/update_tool && /opt/app/.venv/bin/python run_stock_all.py >> /opt/app/logs/cron_stock.log 2>&1" ) | crontab -
crontab -l | tail -3

echo "=== 5. 开放 80 端口（本地防火墙）==="
sudo ufw allow 80/tcp 2>/dev/null || echo "ufw 未启用，跳过"

echo "=== 6. 验证静态站点 ==="
curl -s -o /dev/null -w "首页 HTTP %{http_code}\n" http://127.0.0.1/
curl -s -o /dev/null -w "数据文件 HTTP %{http_code}\n" http://127.0.0.1/HT_Trading_System_data/all_screen.js
echo "gzip 测试:"; curl -s -H "Accept-Encoding: gzip" -o /dev/null -w "压缩后字节 %{size_download}\n" http://127.0.0.1/HT_Trading_System_data/all_bars/801010.js

echo "=== 部署完成 ==="
