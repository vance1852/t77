#!/bin/sh
set -e

echo "[entrypoint] 等待数据库就绪..."
python - <<'PY'
import os
import time

import pymysql

cfg = dict(
    host=os.getenv("DB_HOST", "db"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "show"),
    password=os.getenv("DB_PASSWORD", "show123"),
    database=os.getenv("DB_NAME", "show_ticketing"),
)
for i in range(60):
    try:
        conn = pymysql.connect(**cfg)
        conn.close()
        print("数据库已就绪")
        break
    except Exception as exc:  # noqa: BLE001
        print(f"等待数据库... ({i + 1}) {exc}")
        time.sleep(2)
else:
    raise SystemExit("数据库在超时时间内未就绪")
PY

echo "[entrypoint] 生成并应用数据库迁移..."
python manage.py makemigrations tickets --noinput
python manage.py migrate --noinput

echo "[entrypoint] 初始化种子数据..."
python manage.py seed

echo "[entrypoint] 启动服务..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:7652 --workers 2
