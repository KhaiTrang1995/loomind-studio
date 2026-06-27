# Phase 8: Harness Engineering & Agentic Kit

Trang thai: Lap ke hoach (Planning)
Muc tieu: Xay dung evaluation harness cho pipeline va phat trien MCP server cung nhu Python SDK de AI agent de dang tich hop.

---

## 1. Harness Engineering (He Thong Danh Gia Chat Luong)

Muc tieu cua Harness Engineering la giup lap trinh vien va AI agent tu dong danh gia chat luong goi y (suggestions), do chinh xac cua Layer 2 (semantic search) va Layer 3 (LLM anti-noise filter), cung nhu theo doi do tre (latency) cua he thong.

### 1.1. Dataset Danh Gia (Evaluation Dataset)
Tao file dataset mau tai core/loomind-engine/src/harness/data/eval_dataset.json voi cau truc:
[
  {
    "action": "create a new database connection pool",
    "file_path": "src/db.ts",
    "language": "typescript",
    "expected_experience_titles": ["Use Singleton Pattern for Database Connections"],
    "expected_skip": false
  },
  {
    "action": "cat README.md",
    "file_path": "README.md",
    "language": "markdown",
    "expected_experience_titles": [],
    "expected_skip": true
  }
]

### 1.2. Cong cu danh gia (Evaluator Core)
Tep code core/loomind-engine/src/harness/evaluator.py:
- Nap file dataset tu harness/data.
- Gui tung request den pipeline cua engine (ExperienceService).
- Tinh toan cac chi so:
  - Skip Rate Accuracy: Ty le skip dung yeu cau.
  - Precision: Ty le suggestion dung tren tong so suggestion tra ve.
  - Recall: Ty le suggestion dung duoc tra ve tren tong so suggestion mong doi.
  - F1-Score: Gia tri trung binh dieu hoa cua Precision va Recall.
  - Latency: Average, P50, P95, P99 latency cho tung layer va e2e.
- Xuat bao cao danh gia ra file Markdown tai docs/eval-report.md.

### 1.3. CLI va Skill integration
- Bo sung lenh eval vao CLI va file manage_experiences.py.
- Tao skill moi tai .agents/skills/eval-harness/SKILL.md de huong dan cach chay va doc ket qua danh gia.

---

## 2. Agentic Kit (Bo Cong Cu Tich Hop Agent)

Muc tieu la ket noi he thong Experience Engine voi bat ky AI agent nao de he thong tu dong hoc hoi va lam viec.

### 2.1. Model Context Protocol (MCP) Server
Tich hop MCP server truc tiep vao Python engine:
- Dung thu vien mcp chinh thuc cua Python.
- Code chinh o tep: core/loomind-engine/src/presentation/mcp_server.py.
- MCP Tools bao gom:
  - intercept_action: Check filter L1-L2-L3 de dua ra suggestion cho context hien tai cua agent.
  - add_experience: Them trai nghiem moi vao co so du lieu.
  - search_experiences: Tim kiem semantic search cac trai nghiem.
  - get_health: Lay trang thai suc khoe dong bo.
  - get_stats: Xem thong ke cua engine.

### 2.2. Python SDK Client
- Tao tep core/loomind-engine/src/client.py de lam Python Client SDK.
- Cung cap adapter cho LangChain (CallbackHandler) va CrewAI (Tool wrapper) de cac framework Python agent khac co the goi de dang.

---

## 3. Danh Sach File Can Them Hoac Sua Doi

### Them moi:
- core/loomind-engine/src/harness/data/eval_dataset.json - Dataset danh gia he thong.
- core/loomind-engine/src/harness/evaluator.py - Script danh gia tu dong.
- core/loomind-engine/src/presentation/mcp_server.py - MCP Server cho Python.
- core/loomind-engine/src/client.py - Python Client SDK.
- .agents/skills/eval-harness/SKILL.md - Skill chay harness (khong chua icon).

### Cap nhat:
- core/loomind-engine/requirements.txt va pyproject.toml - Them dependency mcp va pytest-mock (neu can).
- core/loomind-engine/src/main.py - Ho tro khoi dong MCP song song voi FastAPI hoac qua entrypoint rieng.
- docs/plans/README.md - Them Phase 8 vao muc luc.
- README.md - Them phan gioi thieu Harness va MCP Server/Agentic Kit (khong co icon).
- docs/change-log.md - Luu lai lich su thay doi.

---

## 4. Ke Hoach Thuc Hien Chi Tiet

### Buoc 1: Chuan bi va dependency
- Cai dat mcp library cho Python engine.
- Xac nhan moi truong Python hoat dong dung va chay cac test co san.

### Buoc 2: Trien khai Harness Engineering
- Tao eval_dataset.json voi it nhat 10-15 truong hop kiem thu tieu bieu.
- Code script evaluator.py dung python de chay test e2e voi mocked database hoac real database.
- Tich hop vao CLI va tao skill.

### Buoc 3: Trien khai Agentic Kit (MCP & SDK)
- Viet mcp_server.py dang ky cac mcp tool dung API noi bo cua ExperienceService.
- Cho phep khoi chay mcp server thong qua lenh python -m src.presentation.mcp_server.
- Viet Python client SDK o src/client.py.

### Buoc 4: Polish va Testing
- Viet test cases cho mcp_server va evaluator trong core/loomind-engine/tests/.
- Kiem tra de chac chan moi thu build thanh cong.
- Hoan thien tai lieu README.md va docs/change-log.md.
