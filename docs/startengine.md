# Loomind Studio — Hướng dẫn chạy

> Từ phase 12+, toàn bộ stack chạy qua Docker Compose.
> Chỉ cần khởi động **CLI Bridge** trên host (vì nó spawn `claude.exe` / `grok.exe`).

---

## Khởi động nhanh

### Bước 1 — Docker (engine + qdrant + agent-loop + frontend)

```bash
cd apps/docker-deployment
docker compose up -d
```

Lần đầu sẽ mất **2–5 phút** để build frontend (Node.js + Vite). Các lần sau dùng Docker layer cache, khởi động trong vài giây.

### Bước 2 — CLI Bridge (chạy trên host, 1 terminal)

```bash
cd apps/cli-bridge

# Lần đầu: tạo venv
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# Khởi động
.venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8083
```

> **Tại sao phải chạy riêng?**
> CLI Bridge spawn các binary như `claude.exe`, `grok.exe` trên máy host —
> Windows `.exe` không chạy được trong Linux container.

### Tắt tất cả

```bash
cd apps/docker-deployment
docker compose down
# Ctrl+C terminal CLI Bridge
```

---

## URL sau khi khởi động

| Dịch vụ | URL | Chạy ở |
|---|---|---|
| **Dashboard** | http://localhost:3000 | Docker (nginx) |
| Fleet | http://localhost:3000/fleet | |
| Goals | http://localhost:3000/goals | |
| Graph | http://localhost:3000/graph | |
| Terminal | http://localhost:3000/terminal | |
| Experiences | http://localhost:3000/experiences | |
| **Engine API** | http://localhost:8082 | Docker |
| Engine Docs | http://localhost:8082/docs | |
| **Qdrant** | http://localhost:6333 | Docker |
| **CLI Bridge** | http://localhost:8083 | Host |
| Bridge Health | http://localhost:8083/health | |

---

## Cấu hình

### `.env` (tùy chọn)

Copy file mẫu và chỉnh:

```bash
cp apps/docker-deployment/.env.example apps/docker-deployment/.env
```

Các biến hay dùng:

```env
# Thay port nếu 8082 bị dùng bởi app khác
ENGINE_PORT=8082
FRONTEND_PORT=3000

# LLM — mặc định Ollama trên host
LLM_PROVIDER=ollama
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2:3b

# Bật xác thực API (tùy chọn)
AUTH_SECRET_KEY=your-secret-key

# Thông báo Telegram (mặc định tắt)
NOTIFICATION_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### CLI Bridge — cấu hình CLI

Chỉnh `apps/cli-bridge/config.json` hoặc dùng trang Settings (http://localhost:3000/settings):

```json
{
  "enabled_clis": ["claude", "grok", "agy"],
  "cli_timeout": 120,
  "poll_interval": 15,
  "engine_url": "http://localhost:8082",
  "cli_paths": {
    "claude": "C:\\Users\\YourName\\.local\\bin\\claude.exe",
    "grok":   "",
    "agy":    ""
  }
}
```

---

## Rebuild khi có thay đổi code

```bash
cd apps/docker-deployment

# Rebuild tất cả services
docker compose up -d --build

# Rebuild chỉ 1 service cụ thể
docker compose up -d --build engine
docker compose up -d --build frontend
docker compose up -d --build agent-loop
```

> **Khi nào cần rebuild:**
> - Sửa code Python trong `core/loomind-engine/` → rebuild `engine`
> - Sửa code React/TypeScript trong `apps/loomind-desktop/` → rebuild `frontend`
> - Sửa `apps/cli-bridge/agent_loop.py` → rebuild `agent-loop`
> - Sửa `apps/cli-bridge/main.py` → restart CLI Bridge (không cần Docker rebuild)

---

## Xem logs

```bash
cd apps/docker-deployment

# Tất cả services
docker compose logs -f

# Từng service
docker compose logs -f engine
docker compose logs -f frontend
docker compose logs -f agent-loop

# Chỉ lấy 50 dòng cuối
docker compose logs --tail=50 engine
```

---

## Kiểm tra trạng thái

```bash
# Tất cả containers đang chạy?
docker compose ps

# Engine health
curl http://localhost:8082/health

# Engine readiness
curl http://localhost:8082/ready

# CLI Bridge + trạng thái CLIs
curl http://localhost:8083/health
```

---

## Submit goal (test autonomous loop)

```bash
curl -X POST http://localhost:8082/api/goals \
  -H "Content-Type: application/json" \
  -d '{"goal": "Viết hàm Python đọc CSV và tính tổng cột amount", "submitted_by": "user"}'
```

Hoặc dùng trang **Goals** trên Dashboard.

---

## Linux — thêm `extra_hosts`

Trên Linux, `host.docker.internal` không tự resolve. Bỏ comment dòng này trong `docker-compose.yml` cho cả service `engine` và `agent-loop`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

---

## Troubleshooting

| Triệu chứng | Nguyên nhân | Giải pháp |
|---|---|---|
| Frontend trắng, không load | Engine chưa ready | Chờ 30–90s sau `docker compose up`, F5 lại |
| `agent-loop` exit ngay sau start | Engine chưa healthy | Agent-loop depends on engine healthy — tự restart khi engine sẵn sàng |
| CLI Bridge không tìm thấy `claude` | Đường dẫn binary sai | Set `cli_paths.claude` trong `config.json` hoặc trang Settings |
| Ollama timeout | Ollama chưa chạy trên host | Chạy Ollama: `ollama serve` |
| Port 8082 bị dùng | App khác đang dùng | Đổi `ENGINE_PORT=8083` trong `.env`, cập nhật config.json tương ứng |
| `npm ci` fail lúc build frontend | `package-lock.json` lỗi thời | Xóa `node_modules/` và `package-lock.json`, chạy `npm install`, rồi rebuild |
| Qdrant `search()` error | Qdrant version cũ | Dùng `query_points()` — đã được xử lý trong engine |
| `host.docker.internal` không resolve (Linux) | Thiếu extra_hosts | Bỏ comment `extra_hosts` trong docker-compose.yml |

---

## Scripts tiện ích

```bash
# Windows — khởi động + mở browser
scripts\windown\start.bat

# Mac/Linux
bash scripts/windown/start.sh

# Seed dữ liệu mẫu vào engine
cd core/loomind-engine
.venv\Scripts\python seed_data.py
```

---

## Kiến trúc services

```
┌─────────────────────────── Docker Compose ──────────────────────────────┐
│                                                                          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │   frontend       │    │   engine         │    │   qdrant         │  │
│  │   nginx:alpine   │───▶│   FastAPI :8082  │───▶│   :6333          │  │
│  │   :3000          │    │   Python         │    │   Vector DB      │  │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘  │
│                                   ▲                                      │
│  ┌──────────────────┐             │                                      │
│  │   agent-loop     │─────────────┘                                      │
│  │   Python         │   polls tasks / reports outcomes                   │
│  │   (no port)      │──────────────────────────────────────▶ host:8083  │
│  └──────────────────┘                                                    │
└──────────────────────────────────────────────────────────────────────────┘

HOST MACHINE:
  ┌──────────────────────────────────────────────────────────────────────┐
  │  CLI Bridge :8083  (main.py)                                         │
  │  Spawns: claude.exe / grok.exe / agy.exe                            │
  │  Nhận lệnh từ agent-loop, trả kết quả về engine                     │
  └──────────────────────────────────────────────────────────────────────┘

BROWSER (user):
  Truy cập localhost:3000 → nhận static files từ nginx
  Gọi API trực tiếp đến localhost:8082 (port exposed từ Docker)
  Gọi Bridge config tại localhost:8083 (host)
```
