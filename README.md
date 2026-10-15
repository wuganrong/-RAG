# YF Vision RAG

YF Vision RAG 是基于 Django + Celery 的企业级 RAG 演示项目，覆盖文本 RAG、多模态页图 RAG、租户、模型管理、知识库、文档管理、会话、反馈、评测、用量成本、内容安全、审计与健康监控等能力。

## 目录入口

- 项目结构说明：`__000__doc/__000__project_docs/项目结构说明.md`
- 需求清单：`__000__doc/__001__requirements/vlm-rag需求清单.md`
- 环境启动文档：`__000__doc/__003__operations/环境启动文档.md`
- 业务测试文档：`__000__doc/__002__testing/业务测试文档.md`
- VLM-RAG 测试文档：`__000__doc/__002__testing/vlm-rag测试文档.md`

## 快速启动

本地演示可使用 SQLite；如果需要复用 MySQL / Redis / MinIO / Elasticsearch，请按环境启动文档配置 `.env.local`。

```powershell
set DJANGO_ENV=local
python manage.py migrate
python manage.py runserver 9380
```

需要异步任务时启动 Celery：

```powershell
celery -A __000__django worker --pool=eventlet --loglevel=info
celery -A __000__django worker --pool=solo -Q vision --loglevel=info
```

## 访问地址

- 前端页面：`http://127.0.0.1:9380/`
- Swagger：`http://127.0.0.1:9380/api/docs/`
- 默认账号：`admin` / `admin123`

## 验证命令

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_checks.ps1
```
