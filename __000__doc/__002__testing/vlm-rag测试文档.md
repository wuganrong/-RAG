# VLM-RAG 测试文档

## 1. 测试目标

验证当前项目是否具备完整的 VLM-RAG 产品闭环：

- 环境可初始化
- 数据库可迁移并导入种子数据
- 前端页面可访问
- 租户、权限、模型、知识库、文档、会话、反馈、任务、检索调试、评测、用量、审计等模块可用
- 文本 RAG、视觉 RAG、混合 RAG 能完成基础实验流程

项目目录：

```powershell
D:\AI02-就业\B-大模型项目\2-rag项目\vlm-rag项目\localGPT-Vision-main
```

访问地址：

```text
http://127.0.0.1:9380/
```

## 2. 测试前准备

### 2.1 必要服务

按完整 RAG 流程测试，建议准备：

- Python 环境
- MySQL 或 SQLite
- Redis
- Celery Worker（本机窗口启动，不要用 docker `yf-rag-celery`）
- MinIO
- Elasticsearch
- DashScope API Key 或其他兼容模型 API Key

只测试页面、租户、模型配置、评测问题维护等管理功能，可以先用 SQLite。

实测环境（2026-09-17）：MySQL `yf_vision_rag` @ 127.0.0.1；Django `127.0.0.1:9380`；Celery `e2e@local` + `vision@local` 均 pong；`REQUIRE_AUTH=1` 另开 `127.0.0.1:9381`。Tongyi Key 脱敏为 `sk-e****fd1f`。

### 2.2 初始化 SQLite

```powershell
cd "D:\AI02-就业\B-大模型项目\2-rag项目\vlm-rag项目\localGPT-Vision-main"
powershell -ExecutionPolicy Bypass -File scripts\init_sqlite.ps1
```

### 2.3 初始化 MySQL

```powershell
cd "D:\AI02-就业\B-大模型项目\2-rag项目\vlm-rag项目\localGPT-Vision-main"
powershell -ExecutionPolicy Bypass -File scripts\init_mysql.ps1 -HostName 127.0.0.1 -Port 3306 -User root -Database yf_vision_rag
```

### 2.4 启动 Django

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_dev.ps1
```

### 2.5 启动 Celery

新开一个 PowerShell：

```powershell
cd "D:\AI02-就业\B-大模型项目\2-rag项目\vlm-rag项目\localGPT-Vision-main"
powershell -ExecutionPolicy Bypass -File scripts\start_celery.ps1
```

实测（2026-09-17）：本机 `e2e@local`（default 队列）和 `vision@local`（vision 队列）inspect ping 均返回 pong。docker `yf-rag-celery` 按设计不使用。

## 3. 种子数据检查

初始化完成后，前端应能看到：

- 默认租户：`default`
- 默认用户：
  - `admin`
  - `editor`
  - `viewer`
- 默认模型厂商：
  - `Tongyi`
  - `OpenAI`
  - `Ollama`
- 默认模型：
  - `qwen-plus`
  - `qwen-turbo`
  - `qwen-vl-plus`
  - `qwen-vl-max`
  - `text-embedding-v4`
  - `qwen3-rerank`
- 默认助理：`chat`
- 默认检索方法：`vector / keyword / hybrid`

验收标准：

- 页面顶部租户下拉框能看到 `默认租户 (default)`
- 模型管理页面能看到默认模型
- 厂商配置中能看到 `Tongyi`

实测（2026-09-17）：通过。租户含 `默认租户` / `测试租户-013241`；用户 `admin` `editor` `viewer` `test_editor`；厂商 Tongyi / OpenAI / Ollama；模型含 qwen-plus、qwen-turbo、qwen-vl-plus、qwen-vl-max、text-embedding-v4、`qwen3-rerank`（原 `gte-rerank-v2` 已下线）；助手 `chat`、`demo_assistant`；检索策略 hybrid。

## 4. 页面功能测试

### 4.1 首页概览

步骤：

1. 打开 `http://127.0.0.1:9380/`
2. 点击“首页概览”
3. 查看统计卡片

验收标准：

- 页面无报错
- 显示知识库、文档、切片、页图数量
- 主链路状态显示正常

实测（2026-09-17）：通过。首次页图卡片曾显示 0（KB.page_num 过期 + status=1 过滤），已改为按文档 `Sum(page_num)` 实时汇总。回归：9 个知识库、页图合计 4。后续页面完善：首页增加组件健康条、知识库卡片（可点进文档管理）、快捷操作。

### 4.2 租户管理

步骤：

1. 点击“租户管理”
2. 新增租户：
   - 名称：`测试租户`
   - 描述：`用于页面测试`
   - 状态：启用
3. 保存
4. 顶部租户下拉切换到新租户

验收标准：

- 租户保存成功
- 顶部租户下拉出现新租户
- 切换租户后，知识库/模型/会话列表按当前租户刷新

实测（2026-09-17）：通过。CRUD 创建/更新/读取/删除均成功。浏览器切换 `测试租户-013241`、`隔离租户B-072917` 后列表按租户刷新。

### 4.3 用户权限

步骤：

1. 点击“用户权限”
2. 新增用户角色：
   - 租户：当前租户
   - 用户ID：`test_editor`
   - 用户名称：`测试编辑员`
   - 角色：`editor`
   - 状态：启用
3. 保存

验收标准：

- 用户角色保存成功
- 列表展示 `test_editor`
- 审计日志中应有 `user_role/save`

实测（2026-09-17）：通过。列表含 admin / editor / viewer / test_editor。用户角色 CRUD 通过。审计有 `user_role/save`。

### 4.4 模型管理

步骤：

1. 点击“模型管理”
2. 在“厂商配置”中编辑 `Tongyi`
3. 填入真实 API Key
4. 保存厂商
5. 在模型列表中点击 Chat 模型“测试”

验收标准：

- 厂商保存成功
- API Key 不明文展示，只展示脱敏结果
- Chat / Embedding / Rerank 模型测试能返回真实调用结果
- VLM 模型测试返回明确提示：尚未封装独立 VLM 测试适配器

实测（2026-09-17）：通过。Key 展示 `sk-e****fd1f`。Chat / Embedding / `qwen3-rerank` 真实调用成功（DashScope `/compatible-api/v1/reranks`，含 404 回退）。VLM 返回“尚未封装独立 VLM 测试适配器”。模型 CRUD、启停通过。

### 4.5 知识库管理

步骤：

1. 点击“知识库”
2. 新建知识库：
   - 名称：`测试知识库`
   - 模式：建议先选 `混合`
   - Embedding：选择可用 embedding 模型
   - VLM：选择 `qwen-vl-plus`
3. 保存

验收标准：

- 知识库创建成功
- 列表展示新知识库
- 模式显示为“混合”
- 审计日志中应有 `knowledgebase/create`

实测（2026-09-17）：通过。文本库 `68f0f48624314925bd01ab458de8c8b7`、混合库 `0cbeb584b2fd444dbcf4256375c08cff`、视觉库均创建成功。CRUD 通过。审计有 `knowledgebase/create`。

### 4.6 文档管理

步骤：

1. 点击“文档管理”
2. 选择刚创建的知识库
3. 上传 PDF、图片或 Word 文档
4. 点击“解析”
5. 打开“详情”

验收标准：

- 文档上传成功
- 文档列表出现记录
- 详情中展示：
  - 状态
  - 解析状态
  - 文本切片数量
  - 视觉页图数量
  - 版本记录
  - 处理日志
- 审计日志中应有 `document/upload`

实测（2026-09-17）：通过。混合库上传 md/png/pdf/docx 并解析完成。详情含状态、切片、页图、版本、处理日志。切片弹窗可见正文。`GET /v1/document/get/{id}` 返回二进制。首次 `GET /v1/document/image/{doc_id}` 因 UUID 无连字符返回 404，已修复：按文档 ID 读 MinIO 原图。回归 `e2e_valve_plate.png` → HTTP 200，`image/png`，61375 bytes。不存在的 ID 返回 404。后续页面完善：PNG 缩略图、独立页图预览、文件名/状态/类型筛选、7 列精简表与更多菜单、进度条、text/vision 索引徽标、点击文件名打开详情、原文件下载。列表接口会把「完成但进度<1」的历史脏数据对齐为 100%。

### 4.7 任务中心

步骤：

1. 点击“任务中心”
2. 选择知识库
3. 查看任务进度
4. 对任务点击“重试”
5. 对任务点击“取消”

验收标准：

- 能看到任务 ID、文档、进度、日志
- 重试可触发解析任务
- 取消可提交取消请求
- 审计日志中应有 `document/run`

实测（2026-09-17）：通过。任务列表可见。首次取消/恢复会把 `progress` 清零并把 `run=1` 标成“完成 0%”，已修复：仅 `run=2` 或 `delete=true` 清零进度；取消保留进度；`run=1` 将进度置为 1.0。回归：取消前 progress=1.0，取消后仍 1.0 且 run=3；恢复 run=1 progress=1.0；重试 `run=2 delete=true` 后解析完成 chunk_num=1。续测：任务状态筛选（完成/进行中/失败）、自动刷新、切换知识库即查询。文本阶段留下的「等待视觉建索」任务在文档完成后对齐为 100%。

### 4.8 问答对话

步骤：

1. 点击“问答对话”
2. 用户ID 使用 `admin`
3. 选择知识库
4. 选择 Chat 模型
5. 输入问题，例如：

```text
请总结这个文档的主要内容
```

6. 发送

验收标准：

- 能返回回答
- 回答下方展示文本依据或页图依据
- 页图可点击预览
- 用量统计中新增一条问答调用记录

实测（2026-09-17）：通过。文本 / 视觉 / 混合知识库均可回答并带引用。混合问答有文本依据和页图依据。用量新增调用记录。续测：问答空态提示、发送中禁用按钮、导出会话为 Markdown 文件、反馈 Toast、会话按标题/正文筛选、Markdown 粗体与换行渲染。E-204 问答约 11s 返回停机/换滤芯 HF-330A 步骤，并带文本依据与页图依据。

### 4.9 反馈评价

步骤：

1. 在问答回答下点击“有用”
2. 再问一个问题，点击“无用”，填写原因
3. 点击“反馈评价”

验收标准：

- 反馈列表展示有用/无用评价
- 无用反馈展示原因
- 审计日志中应有 `conversation/feedback`

实测（2026-09-17）：通过。有用/无用均可写入，无用含原因，审计有反馈记录。

### 4.10 检索调试

步骤：

1. 点击“检索调试”
2. 选择知识库
3. 输入问题：

```text
文档中有哪些关键结论？
```

4. 点击“调试检索”

验收标准：

- 展示文本召回结果
- 如果知识库有视觉索引，展示页图召回结果
- 展示上下文预览
- 混合知识库应能同时观察文本和视觉召回

实测（2026-09-17）：通过。混合库同时有文本 chunk 与页图召回，上下文预览可见。ES knn 语法已按 ES7 调整。

### 4.11 评测数据集

步骤：

1. 点击“评测数据集”
2. 选择知识库
3. 新增问题：
   - 问题：`文档主要讲了什么？`
   - 期望答案：填写文档中确定会出现的关键词
4. 保存
5. 点击“一键运行”

验收标准：

- 问题保存成功
- 评测结果展示：
  - 文本召回数
  - 视觉召回数
  - 期望命中
  - 得分
  - 状态

实测（2026-09-17）：通过。首次 expected_hit 因整句匹配过严为 0%，已改为 token 多数命中。回归后期望命中与得分有值，状态成功。评测问题 CRUD 通过。

### 4.12 用量统计

步骤：

1. 点击“用量统计”
2. 查看统计卡片
3. 按用户ID过滤，例如 `admin`

验收标准：

- 展示调用次数
- 展示失败次数
- 展示 Token 估算
- 展示平均耗时
- 问答后列表新增调用记录

实测（2026-09-17）：通过。调用次数、失败次数、Token 估算、平均耗时、调用列表均有值。Token 仍为估算，见第 9 节限制。

### 4.13 审计安全

步骤：

1. 点击“审计安全”
2. 查看操作日志
3. 按操作过滤：
   - `create`
   - `upload`
   - `run`
   - `save`

验收标准：

- 能看到模型、知识库、文档、租户、用户角色等操作日志
- 日志包含：
  - 时间
  - 用户
  - 操作
  - 资源类型
  - 资源ID
  - 状态
  - 详情

实测（2026-09-17）：通过。create / upload / run / save / delete 及 llm / knowledgebase / document / conversation / evaluation 资源过滤均有记录。续测：下拉切换即查询，`action=login` 仅返回 login/auth 记录。

## 5. 接口测试

以下示例使用 PowerShell `Invoke-RestMethod`。

实测（2026-09-17）：5.1–5.7 均通过 `doc_item_suite` / `remaining_gap_suite` 对应接口覆盖。租户列表、模型列表、KB 创建/列表、检索调试、审计、用量 summary 返回 `code=0`。

### 5.1 查询租户

```powershell
Invoke-RestMethod -Method GET `
  -Uri "http://127.0.0.1:9380/v1/tenant/list"
```

### 5.2 查询模型

```powershell
Invoke-RestMethod -Method GET `
  -Uri "http://127.0.0.1:9380/v1/llm/list?tenant_id=default&model_type=&flat=1"
```

### 5.3 创建知识库

```powershell
$body = @{
  tenant_id = "default"
  name = "接口测试知识库"
  description = "接口创建"
  embd_id = "text-embedding-v4"
  parser_id = "naive"
  chunker_id = "naive"
  rag_mode = "hybrid"
  vlm_id = "qwen-vl-plus"
  page_top_n = 3
  permission = "me"
  chunker_config = @{ chunk_token_num = 512 }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:9380/v1/kb/create" `
  -Headers @{ "X-Tenant-Id"="default"; "X-User-Id"="admin" } `
  -ContentType "application/json" `
  -Body $body
```

### 5.4 查询知识库

```powershell
$body = @{ tenant_id="default"; page=1; page_size=100 } | ConvertTo-Json

Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:9380/v1/kb/list" `
  -ContentType "application/json" `
  -Body $body
```

### 5.5 检索调试

```powershell
$body = @{
  tenant_id = "default"
  kb_ids = @("替换为知识库ID")
  question = "文档主要讲了什么？"
  top_n = 6
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:9380/v1/retrieval/debug" `
  -ContentType "application/json" `
  -Body $body
```

### 5.6 查询审计日志

```powershell
Invoke-RestMethod -Method GET `
  -Uri "http://127.0.0.1:9380/v1/ops/audit/list?tenant_id=default&page=1&page_size=20"
```

### 5.7 查询用量统计

```powershell
Invoke-RestMethod -Method GET `
  -Uri "http://127.0.0.1:9380/v1/ops/usage/summary?tenant_id=default"
```

## 6. 权限测试

当前角色规则：

- `admin`：模型、租户、用户角色、知识库、文档全部管理
- `editor`：知识库和文档管理
- `viewer`：只读查看和问答

### 6.1 viewer 创建知识库应失败

```powershell
$body = @{
  tenant_id = "default"
  name = "viewer不应创建"
  embd_id = "text-embedding-v4"
  parser_id = "naive"
  chunker_id = "naive"
  rag_mode = "text"
} | ConvertTo-Json

Invoke-RestMethod -Method POST `
  -Uri "http://127.0.0.1:9380/v1/kb/create" `
  -Headers @{ "X-Tenant-Id"="default"; "X-User-Id"="viewer" } `
  -ContentType "application/json" `
  -Body $body
```

验收标准：

- 返回权限不足
- HTTP/业务 code 表示失败

实测（2026-09-17）：通过。viewer 创建知识库被拒绝。9381 强认证下 viewer 读可过、写被拒。

### 6.2 editor 创建知识库应成功

把上面 Header 改为：

```powershell
@{ "X-Tenant-Id"="default"; "X-User-Id"="editor" }
```

验收标准：

- 创建成功

实测（2026-09-17）：通过。editor 可创建知识库。

### 6.3 editor 修改模型应失败

模型管理写操作需要 `admin`。

验收标准：

- `editor` 调用模型新增、更新、删除、启停时返回权限不足

实测（2026-09-17）：通过。editor 改模型被拒绝；admin 改模型成功。

## 7. 异常场景测试

### 7.1 未配置 API Key

步骤：

1. 不配置 `Tongyi` API Key
2. 点击 Chat 模型测试

验收标准：

- 返回模型调用失败
- 不导致服务崩溃

实测（2026-09-17）：通过。缺 Key 时模型测试失败且 Django 不崩溃。当前环境已配置脱敏 Key，正向路径 Chat/Embedding/Rerank 成功。

### 7.2 未启动 Celery

步骤：

1. 只启动 Django
2. 上传文档
3. 点击解析

验收标准：

- 解析任务可能无法执行或停留在等待状态
- 页面不应崩溃
- 任务中心可看到状态

实测（2026-09-17）：通过。停 Worker 后上传/提交解析不崩溃，任务仍可见。随后本机重启 `e2e@local` + `vision@local`，ping 恢复 pong。

### 7.3 未启动 Elasticsearch

步骤：

1. 不启动 ES
2. 文档解析后进行检索调试

验收标准：

- 检索调试返回失败或空结果
- 错误信息可见
- 服务不崩溃

实测（2026-09-17）：通过。停 ES 后检索调试失败或空、错误可见、服务不崩。健康检查 ES=FAILED 并生成告警，可点“解决”。ES 恢复后健康 OK，检索恢复。

### 7.4 不同租户隔离

步骤：

1. 在 `default` 租户创建知识库 A
2. 新建租户 B
3. 切换到租户 B
4. 查看知识库列表

验收标准：

- 租户 B 不应看到租户 A 的知识库

实测（2026-09-17）：通过。切换隔离租户后看不到 default 混合库。`check_tenant_isolation` 通过。

## 8. 完整实验流程验收

推荐最终验收流程：

1. 初始化数据库和种子数据
2. 启动 Django
3. 启动 Celery
4. 配置真实模型 API Key
5. 测试 Chat / Embedding / Rerank 模型
6. 创建混合知识库
7. 上传 PDF 或图片文档
8. 触发解析
9. 在任务中心观察完成状态
10. 打开文档详情，查看切片、页图、版本
11. 在问答对话中提问
12. 查看回答、文本引用、页图引用
13. 提交有用/无用反馈
14. 打开检索调试台，验证召回内容
15. 新增评测问题，一键运行评测
16. 查看用量统计
17. 查看审计日志

最终验收标准：

- 页面无明显 JS 报错
- 后端无 500 崩溃
- 知识库、文档、问答、引用、反馈、评测、审计、用量形成闭环
- 混合 RAG 能体现文本召回和视觉页图召回

实测（2026-09-17）：通过。文本 / 视觉 / 混合三条主链路闭环。映射用例 101/101；CRUD 36/36；剩余缺口 85/85（其中图片 UUID 当时假通过，已修后 14/14 回归全过）。pytest 8 passed。控制台 `http://127.0.0.1:9380/`。

## 9. 当前已知限制

- VLM 独立图片连通测试尚未封装为单独适配器，但 VLM 已用于多模态 RAG 链路。
- 用量中的 Token 当前主要是粗略估算，不是所有模型的真实 usage。
- 文档版本目前记录 `v1` 和版本列表，尚未完成同名文档自动升版与回滚。
- ES / MinIO / 异步任务已经有租户字段基础，但仍建议生产前继续做全链路隔离复核。
- 当前前端是单文件管理控制台，适合实验和演示；正式产品可继续拆分为工程化前端项目。
- docker `yf-rag-celery` 按设计不使用，解析走本机 Celery。

## 10. 实测汇总（2026-09-17）

| 条目 | 结果 | 说明 |
|---|---|---|
| 3 种子数据 | 通过 | Rerank 现为 `qwen3-rerank` |
| 4.1 首页 | 通过 | 页图实时 Sum，合计 4 |
| 4.2 租户 | 通过 | CRUD + 切换隔离 |
| 4.3 用户权限 | 通过 | 含 test_editor 与审计 |
| 4.4 模型 | 通过 | Key 脱敏；Chat/Emb/Rerank 真调用 |
| 4.5 知识库 | 通过 | 文本/视觉/混合 |
| 4.6 文档 | 通过 | 图片 UUID 404 已修复 |
| 4.7 任务中心 | 通过 | 取消不再清零进度 |
| 4.8 问答 | 通过 | 回答 + 引用 + 用量 |
| 4.9 反馈 | 通过 | 有用/无用 |
| 4.10 检索调试 | 通过 | 混合文本+页图 |
| 4.11 评测 | 通过 | token 多数命中 |
| 4.12 用量 | 通过 | Token 为估算 |
| 4.13 审计 | 通过 | 操作/资源过滤 |
| 5 接口 | 通过 | 5.1–5.7 |
| 6 权限 | 通过 | viewer 拒写，editor 可建库 |
| 7.1 无 Key | 通过 | 失败不崩溃 |
| 7.2 无 Celery | 通过 | 后已恢复本机 Worker |
| 7.3 无 ES | 通过 | 告警可解决 |
| 7.4 租户隔离 | 通过 | 无串库 |
| 8 闭环 | 通过 | 混合 RAG 文本+页图 |

Bug 回归 `data/init/bug_retest_report.json`：**14/14 PASS**。Celery `e2e@local` + `vision@local` pong。

页面完善（同日续测）：首页健康条 + 知识库卡片、文档 7 列精简表（更多菜单含切片/下载/启停）、类型筛选、进度条、索引徽标、任务自动刷新与状态筛选、快捷入口、侧栏菜单筛选、登录/解析 Toast、页图独立预览、问答空态/会话筛选/Markdown 渲染与导出。文本解析完成会写入 `index_modes=text`。列表接口会修复「完成但进度<1」的历史脏数据。
