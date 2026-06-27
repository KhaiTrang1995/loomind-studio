# Loomind Experience Engine — AI Agent Integration Guide

> **Mục đích**: File này giúp các AI agent (GitHub Copilot, Cursor, Claude, Gemini, Windsurf, Cline...)
> hiểu cách vận hành và tự động gọi API kinh nghiệm trước khi viết code.

---

## Tổng Quan Hệ Thống

Loomind Experience Engine là hệ thống **bộ nhớ kinh nghiệm tập thể** cho AI coding agent.
Nó hoạt động như một lớp chặn (intercept layer) giữa agent và code:

```
Agent muốn sửa code
    → Gọi /api/intercept
        → Layer 1: Bỏ qua nếu là hành động chỉ đọc (0ms)
        → Layer 2: Tìm kinh nghiệm tương tự bằng vector search (<50ms)
        → Layer 3: Lọc nhiễu bằng LLM local (<500ms)
    → Trả về danh sách suggestions
        → Agent áp dụng suggestions vào code
```

**Base URL**: `http://localhost:8082`
**API Docs (Swagger)**: `http://localhost:8082/docs`

---

## Quy Tắc Vận Hành Cho AI Agent

### ✅ KHI NÀO phải gọi Engine

Gọi `POST /api/intercept` **TRƯỚC KHI** viết code nếu action thuộc loại:

| Loại Action | Ví dụ | Tại sao |
|-------------|-------|---------|
| **Tạo file mới** | Tạo module, service, controller | Tránh lặp lỗi thiết kế đã biết |
| **Sửa code database** | Connection, migration, query | Tránh N+1, SQL injection, connection leak |
| **Xử lý authentication/security** | Password, token, secret, key | Tránh lỗ hổng bảo mật đã biết |
| **Tối ưu performance** | Cache, index, query optimize | Áp dụng pattern đã chứng minh hiệu quả |
| **Thay đổi config/infra** | Docker, CI/CD, deploy | Tránh misconfiguration |
| **Refactor code** | Tách module, đổi kiến trúc | Áp dụng bài học từ lần refactor trước |

### ❌ KHÔNG gọi Engine khi

- **Chỉ đọc/xem file**: `cat`, `ls`, `git log`, `view_file`, `list_dir`
- **Sửa comment/format**: Thay đổi không ảnh hưởng logic
- **Đã có suggestion gần đây**: Cho cùng action trong cùng session
- **Engine không chạy**: Không block workflow — ghi nhận và tiếp tục

---

## API Reference

### 1. 🔍 Intercept — Truy Vấn Kinh Nghiệm (Endpoint Chính)

```
POST /api/intercept
Content-Type: application/json
```

**Request Body:**

```json
{
  "action": "create database connection pool",
  "action_type": "write",
  "file_path": "src/db.ts",
  "file_content": "import { Pool } from 'pg'...",
  "language": "typescript",
  "agent": "copilot",
  "context": "User đang build REST API với PostgreSQL"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | `string` | ✅ | Mô tả hành động agent sắp thực hiện |
| `action_type` | `"read" \| "write" \| "execute" \| "unknown"` | ❌ | Phân loại hành động (mặc định: `"unknown"`) |
| `file_path` | `string` | ❌ | Đường dẫn file đang thao tác |
| `file_content` | `string` | ❌ | Nội dung file (snippet) để engine hiểu context |
| `language` | `string` | ❌ | Ngôn ngữ lập trình (`python`, `typescript`, `go`...) |
| `agent` | `string` | ❌ | Tên agent gọi API (`copilot`, `cursor`, `claude`) |
| `context` | `string` | ❌ | Context bổ sung (task description, user intent) |

**Response:**

```json
{
  "skipped": false,
  "suggestions": [
    {
      "experience_id": "a1b2c3d4-...",
      "title": "Use Connection Pool Singleton",
      "message": "Luôn dùng singleton pattern cho database connection pool. Tạo pool 1 lần khi app start, tái sử dụng cho mọi request. KHÔNG tạo connection mới cho mỗi request — sẽ gây connection leak và crash server khi traffic cao.",
      "severity": "warning",
      "relevance_score": 0.72,
      "source": "semantic_search"
    }
  ],
  "latency_ms": 42.5,
  "layers_executed": ["L1", "L2", "L3"]
}
```

| Response Field | Type | Description |
|----------------|------|-------------|
| `skipped` | `boolean` | `true` nếu Layer 1 bỏ qua (action chỉ đọc) |
| `suggestions` | `Suggestion[]` | Danh sách kinh nghiệm liên quan |
| `latency_ms` | `number` | Thời gian xử lý (ms) |
| `layers_executed` | `string[]` | Các layer đã chạy: `["L1"]`, `["L1","L2"]`, `["L1","L2","L3"]` |

#### Cách xử lý suggestions:

| Severity | Hành động của Agent |
|----------|---------------------|
| `critical` | **BẮT BUỘC** tuân thủ. Cảnh báo user rõ ràng. Sẽ gây lỗi nếu bỏ qua. |
| `warning` | **NÊN** tuân thủ. Giải thích lý do cho user. Chỉ bỏ qua khi có lý do chính đáng. |
| `info` | **Tham khảo**. Áp dụng nếu phù hợp, bỏ qua nếu không liên quan. |

#### Ví dụ gọi bằng cURL:

```bash
curl -s -X POST http://localhost:8082/api/intercept \
  -H "Content-Type: application/json" \
  -d '{
    "action": "create user authentication with JWT",
    "action_type": "write",
    "file_path": "src/auth/jwt.py",
    "language": "python",
    "agent": "claude"
  }' | jq
```

#### Ví dụ gọi bằng PowerShell:

```powershell
$body = @{
    action = "create user authentication with JWT"
    action_type = "write"
    file_path = "src/auth/jwt.py"
    language = "python"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8082/api/intercept" `
    -Method POST -ContentType "application/json" -Body $body |
    ConvertTo-Json -Depth 5
```

---

### 2. 📝 Experience CRUD — Quản Lý Kinh Nghiệm

#### Tạo experience mới

Khi user chia sẻ một kinh nghiệm quý giá, agent NÊN lưu vào engine:

```
POST /api/experiences
Content-Type: application/json
```

```json
{
  "title": "Always use parameterized queries",
  "description": "Không bao giờ dùng string concatenation để build SQL query. Luôn dùng parameterized queries hoặc ORM để tránh SQL injection. Đã gặp lỗi bảo mật nghiêm trọng khi dùng f-string trong SQLAlchemy raw query.",
  "category": "security",
  "tags": ["sql-injection", "database", "security", "sqlalchemy"],
  "file_patterns": ["*.py", "db.*", "models.*", "repository.*"],
  "language": "python",
  "severity": "critical"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | `string` | ✅ | Tiêu đề ngắn gọn, dễ hiểu |
| `description` | `string` | ✅ | Mô tả chi tiết: vấn đề, giải pháp, lý do |
| `category` | `string` | ❌ | `"pattern"` \| `"bug"` \| `"security"` \| `"performance"` (mặc định: `"pattern"`) |
| `tags` | `string[]` | ❌ | Các tag liên quan để tìm kiếm |
| `file_patterns` | `string[]` | ❌ | File patterns liên quan (e.g., `["*.ts", "db.*"]`) |
| `language` | `string` | ❌ | Ngôn ngữ lập trình |
| `severity` | `string` | ❌ | `"info"` \| `"warning"` \| `"critical"` (mặc định: `"info"`) |

#### Liệt kê experiences

```
GET /api/experiences?limit=20&offset=0
```

Response:
```json
{
  "items": [ /* Experience[] */ ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

#### Lấy 1 experience

```
GET /api/experiences/{id}
```

#### Cập nhật experience

```
PUT /api/experiences/{id}
Content-Type: application/json
```

```json
{
  "title": "Updated title",
  "severity": "critical",
  "tags": ["new-tag"]
}
```

> Chỉ gửi các field cần cập nhật (partial update).

#### Xóa experience

```
DELETE /api/experiences/{id}
```

#### Tìm kiếm experience

```
POST /api/experiences/search
Content-Type: application/json
```

```json
{
  "query": "database connection pool singleton"
}
```

> Trả về `Experience[]` sorted by relevance.

---

### 3. 👍 Feedback — Đánh Giá Kinh Nghiệm

Sau khi user xác nhận suggestion hữu ích (hoặc không), agent NÊN gửi feedback:

```
POST /api/experiences/{id}/feedback
Content-Type: application/json
```

```json
{
  "score": 1.0,
  "comment": "Suggestion này đã giúp tránh connection leak"
}
```

| Score | Ý nghĩa |
|-------|---------|
| `1.0` | Rất hữu ích — áp dụng trực tiếp |
| `0.5` | Hữu ích một phần |
| `0.0` | Không liên quan |
| `-0.5` | Gây nhầm lẫn |
| `-1.0` | Sai hoàn toàn — cần sửa experience |

---

### 4. 💾 Backup & Restore

#### Export toàn bộ

```
GET /api/experiences/backup/export
```

Response: `ExportBundle` chứa toàn bộ experiences.

#### Import từ backup

```
POST /api/experiences/backup/import
Content-Type: application/json
```

```json
{
  "experiences": [ /* danh sách experience objects */ ],
  "overwrite": false
}
```

---

### 5. 🏥 Health Check & Stats

#### Health check (kiểm tra engine sống hay chết)

```
GET /health
```

```json
{
  "status": "ok",
  "engine": "running",
  "qdrant": true,
  "embedder_loaded": true,
  "llm_available": false,
  "uptime_seconds": 3421.5,
  "version": "0.1.0"
}
```

#### Readiness probe

```
GET /ready
```

```json
{ "ready": true }
```

#### Engine statistics

```
GET /api/stats
```

```json
{
  "total_experiences": 42,
  "total_queries": 156,
  "avg_latency_ms": 38.5,
  "cache_hit_rate": 0.0,
  "queries_today": 23
}
```

---

## Workflow Tích Hợp Cho Agent

### Flow Chuẩn

```mermaid
flowchart TD
    A["User yêu cầu viết code"] --> B{"Action type?"}
    B -->|"Chỉ đọc"| C["Bỏ qua — viết code bình thường"]
    B -->|"Write/Execute"| D["Gọi POST /api/intercept"]
    D --> E{"Engine phản hồi?"}
    E -->|"Không kết nối được"| F["Thông báo user, tiếp tục viết code"]
    E -->|"skipped: true"| C
    E -->|"Có suggestions"| G{"Severity?"}
    G -->|"critical"| H["BẮT BUỘC áp dụng\nCảnh báo user rõ ràng"]
    G -->|"warning"| I["NÊN áp dụng\nGiải thích cho user"]
    G -->|"info"| J["Tham khảo\nÁp dụng nếu phù hợp"]
    H --> K["Viết code theo suggestion"]
    I --> K
    J --> K
    K --> L{"User hài lòng?"}
    L -->|"Có"| M["Gửi feedback score: 1.0"]
    L -->|"Không"| N["Gửi feedback score: -1.0"]
```

### Pseudocode Cho Agent

```python
async def before_writing_code(action: str, file_path: str, language: str):
    """Gọi trước khi viết/sửa code."""

    # Skip read-only actions
    readonly = ["ls", "cat", "git log", "git status", "grep", "find",
                "head", "tail", "tree", "pwd", "read_file", "view_file"]
    if any(cmd in action.lower() for cmd in readonly):
        return None  # Không cần gọi engine

    # Gọi engine
    try:
        response = await http_post("http://localhost:8082/api/intercept", {
            "action": action,
            "action_type": "write",
            "file_path": file_path,
            "language": language,
            "agent": "your_agent_name"
        }, timeout=5000)
    except ConnectionError:
        # Engine không chạy — tiếp tục bình thường
        return None

    if response["skipped"]:
        return None

    # Áp dụng suggestions
    for s in response["suggestions"]:
        if s["severity"] == "critical":
            # BẮT BUỘC: Nhúng instruction vào prompt
            inject_into_prompt(f"⚠️ CRITICAL: {s['title']}\n{s['message']}")
        elif s["severity"] == "warning":
            # NÊN: Thêm vào context
            inject_into_context(f"💡 {s['title']}: {s['message']}")
        else:
            # INFO: Ghi chú
            add_note(f"ℹ️ {s['title']}")

    return response["suggestions"]
```

### Khi User Chia Sẻ Kinh Nghiệm Mới

```python
async def save_user_experience(lesson: str):
    """Khi user nói 'nhớ lấy bài học này' hoặc chia sẻ kinh nghiệm."""

    # Phân tích lesson từ user
    experience = {
        "title": extract_title(lesson),       # Tiêu đề ngắn
        "description": lesson,                 # Full content
        "category": classify_category(lesson), # bug/pattern/security/performance
        "severity": classify_severity(lesson), # info/warning/critical
        "tags": extract_tags(lesson),          # Các keyword
        "language": detect_language(lesson),   # python/typescript/...
    }

    await http_post("http://localhost:8082/api/experiences", experience)
```

---

## Xử Lý Lỗi

| Tình huống | Hành động |
|------------|-----------|
| Engine không kết nối (`ECONNREFUSED`) | Thông báo user: "Experience Engine chưa chạy" + hướng dẫn khởi động |
| Timeout (>5s) | Bỏ qua, tiếp tục viết code. Không block workflow. |
| HTTP 404 | Experience không tồn tại — bỏ qua |
| HTTP 500 | Log lỗi, tiếp tục bình thường |
| `skipped: true` | Action chỉ đọc — bỏ qua hoàn toàn |
| Không có suggestions | Không có kinh nghiệm liên quan — viết code bình thường |

### Khởi động Engine

Khi engine không chạy, hướng dẫn user:

**Windows:**
```powershell
cd core\loomind-engine
.venv\Scripts\activate
python -m uvicorn src.main:app --host 0.0.0.0 --port 8082
```

**macOS/Linux:**
```bash
cd core/loomind-engine
source .venv/bin/activate
python -m uvicorn src.main:app --host 0.0.0.0 --port 8082
```

**Docker:**
```bash
cd apps/docker-deployment
docker compose up -d
```

---

## Ví Dụ Tích Hợp Thực Tế

### Ví dụ 1: User yêu cầu tạo authentication module

```
User: "Tạo JWT authentication cho FastAPI app"

Agent (nghĩ):
  → action = "create JWT authentication module"
  → file_path = "src/auth.py"
  → language = "python"
  → Gọi POST /api/intercept

Engine trả về:
  suggestions:
    - title: "Always hash passwords with bcrypt"
      severity: "critical"
      message: "KHÔNG BAO GIỜ lưu password dạng plaintext..."
    - title: "Set JWT expiry to 15-30 minutes"
      severity: "warning"
      message: "Access token nên expire trong 15-30 phút..."

Agent áp dụng:
  → Dùng bcrypt cho password hashing (critical → bắt buộc)
  → Set JWT_EXPIRE_MINUTES = 30 (warning → nên làm)
  → Inform user về các quyết định này
```

### Ví dụ 2: User yêu cầu tối ưu database query

```
User: "Tối ưu query lấy danh sách orders"

Agent:
  → Gọi intercept: action = "optimize database query for orders listing"

Engine trả về:
  suggestions:
    - title: "Use pagination for large datasets"
      severity: "warning"
      message: "Luôn dùng LIMIT/OFFSET hoặc cursor-based pagination..."
    - title: "Add indexes for WHERE and ORDER BY columns"
      severity: "info"
      message: "Tạo composite index cho các cột trong WHERE clause..."

Agent áp dụng:
  → Thêm pagination vào query
  → Recommend thêm index trong migration file
```

### Ví dụ 3: User chia sẻ kinh nghiệm mới

```
User: "Nhớ nhé: khi dùng Redis cache, luôn set TTL. Lần trước quên set
       TTL làm memory leak crash server production."

Agent:
  → Nhận diện đây là kinh nghiệm quan trọng
  → Gọi POST /api/experiences:
    {
      "title": "Always set TTL for Redis cache keys",
      "description": "Khi dùng Redis cache, luôn set TTL (Time-To-Live) cho mọi key.
                       Không set TTL sẽ gây memory leak — keys tích tụ vĩnh viễn
                       cho đến khi Redis OOM và crash. Đã gặp sự cố production
                       do thiếu TTL trên cache keys.",
      "category": "bug",
      "severity": "critical",
      "tags": ["redis", "cache", "ttl", "memory-leak", "production"],
      "language": "python"
    }

Agent confirm: "Đã lưu kinh nghiệm về Redis TTL vào Experience Engine ✅"
```

---

## Lưu Ý Kỹ Thuật

| Item | Giá trị |
|------|---------|
| **Engine URL** | `http://localhost:8082` (hoặc `http://127.0.0.1:8082`) |
| **Lần chạy đầu** | Engine cần ~12-20s để load AI model lần đầu |
| **Lần chạy sau** | ~3-5s (model đã cached) |
| **Timeout recommend** | 5000ms cho intercept, 3000ms cho health check |
| **Vector DB** | Qdrant (embedded mode hoặc Docker server) |
| **Embedding model** | `all-MiniLM-L6-v2` (Sentence-Transformers) |
| **LLM (Layer 3)** | Ollama hoặc llama.cpp (optional, default port 11434) |
| **Data location** | `core/loomind-engine/data/qdrant/` (local mode) |
| **Qdrant API** | Dùng `query_points()` (v1.17+), KHÔNG dùng `search()` |
| **Desktop app** | Tự reconnect engine mỗi 10 giây |
| **Swagger UI** | `http://localhost:8082/docs` |
| **ReDoc** | `http://localhost:8082/redoc` |
