loomind-studio/
├── package.json                  # Turborepo config (build scripts cho toàn bộ project)
├── turbo.json                    # Cấu hình cache build của Turborepo
│
├── core/                         # TRÁI TIM HỆ THỐNG (Python)
│   └── loomind-engine/       # FastAPI + Qdrant Local
│       ├── pyproject.toml        # Quản lý dependency bằng Poetry
│       ├── src/
│       │   ├── domain/           # Nghiệp vụ: experience, routing, feedback
│       │   ├── infrastructure/   # Giao tiếp Qdrant, Ollama, File System
│       │   ├── presentation/     # FastAPI Routes (POST /api/intercept)
│       │   └── main.py           # Entrypoint khởi động Server
│       └── scripts/
│           └── build_exe.py      # Script dùng PyInstaller đóng gói ra file .exe/.bin
│
├── apps/                         # CÁC ỨNG DỤNG THỰC THI CHÍNH
│   ├── loomind-desktop/      # Giao diện quản lý (Tauri + React/Vue)
│   │   ├── src-tauri/            # Rust backend (Chỉ dùng để spawn loomind-engine)
│   │   ├── src/                  # React UI (Dashboard, Logs, Settings)
│   │   └── package.json
│   │
│   ├── loomind-cli/          # NPM Package CLI (để user gõ lệnh `loomind` trên terminal)
│   │   ├── src/
│   │   │   └── commands/         # start, stop, status
│   │   └── package.json
│   │
│   └── docker-deployment/        # Dành cho VPS/Enterprise
│       ├── Dockerfile            # Đóng gói Python Engine
│       └── docker-compose.yml    # Chạy Engine + Qdrant Server (nếu không dùng local mode)
│
├── packages/                     # THƯ VIỆN DÙNG CHUNG (TypeScript)
│   ├── loomind-types/        # Chứa schema, tự động gen từ Python FastAPI
│   │   ├── src/
│   │   │   ├── schema.d.ts       # Code auto-generated từ openapi.json
│   │   │   └── index.ts
│   │   └── package.json
│   │
│   └── loomind-client/       # SDK nội bộ (Axios instance, Interceptors)
│       ├── src/
│       │   ├── api.ts            # Class gọi API có type-safe
│       │   └── filters/          # Layer 1: Read-only skip (0ms)
│       └── package.json
│
└── extensions/                   # THIN CLIENTS (Plugins gắn vào IDE)
    ├── vscode/                   # VS Code Extension
    │   ├── src/
    │   │   ├── extension.ts      # Vòng đời extension
    │   │   └── hooks/            # Móc vào Copilot/Cursor
    │   └── package.json
    │
    └── jetbrains/                # Tương lai: Plugin cho WebStorm/IntelliJ
