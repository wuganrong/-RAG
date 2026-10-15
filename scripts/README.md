# 脚本说明

## SQLite 本地初始化

```powershell
powershell -ExecutionPolicy Bypass -File scripts\init_sqlite.ps1
```

只重新导入种子数据：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\init_sqlite.ps1 -SeedOnly
```

## MySQL 初始化

```powershell
powershell -ExecutionPolicy Bypass -File scripts\init_mysql.ps1 -HostName 127.0.0.1 -Port 3306 -User root -Database yf_vision_rag
```

## 启动 Django

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_dev.ps1
```

访问：

```text
http://127.0.0.1:9380/
```

## 启动 Celery

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_celery.ps1
```

