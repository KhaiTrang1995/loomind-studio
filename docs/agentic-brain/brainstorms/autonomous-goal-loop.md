---
type: brainstorm
feature: agentic-brain
idea_slug: autonomous-goal-loop
status: draft
mode: deep
lang: vi
owner: "@TechSphrexTA"
created: 2026-06-14
updated: 2026-06-14
complexity_flags:
  - has_async_flow
  - has_state_machine
  - has_multi_role
links: []
tags:
  - brainstorm
  - agentic-brain
changelog:
  - 2026-06-14 | /brainstorm | autonomous-goal-loop, deep mode, 5 OQs flagged
---

# Autonomous Goal Loop — Agentic Brain

## 1. Idea Seed

Tích hợp BA-Au-Brain (brainstorm-skill-package) vào Loomind Studio để hệ thống có khả năng tự phân tích goal, tự decompose thành tasks, tự thực hiện và tự học từ kết quả — tiệm cận autonomous agent loop không cần hỏi lại người dùng. Nâng cấp từ AI Junior (agent phải hỏi từng bước) lên AI Senior (agent tự chủ, người dùng chỉ approve hoặc can thiệp khi cần).

## 2. Context

Loomind Studio hiện có Harness Brain (Phase 9) với Agent Registry, Goal Decomposition cơ bản (4 task cứng: research → code → test → evaluate), SSE Event Bus, và PostTool learning loop. Tuy nhiên:
- Goal decomposition chưa thông minh — pipeline cứng không phân tích ngữ cảnh
- Không có User Stories, Acceptance Criteria, hay Story Points
- Task state lưu in-memory — mất khi restart hoặc tràn RAM
- Không có cơ chế HITL timeout — agent bị block mãi
- Không có cơ chế thông báo tiến độ từ xa

BA-Au-Brain bổ sung "bộ não BA" — phân tích goal bằng LLM, sinh User Stories + AC + Fibonacci story points, phân loại task AUTO/HITL/SECURITY trước khi đưa vào Harness.

## 3. User Types

| Vai trò | Mô tả | Quyền |
|---|---|---|
| **SA (Solution Architect)** | Người dùng chính — submit goal, nhận báo cáo, approve HITL | Submit goal, override priority, approve/reject HITL |
| **BA Agent** | AI phân tích goal → sinh User Stories, AC, story points | Tự động, không cần approve |
| **Coding Agent** | AI thực hiện task code | AUTO cho code thường; HITL cho xóa/security |
| **Testing Agent** | AI chạy test, verify AC | AUTO hoàn toàn |
| **Evaluation Agent** | AI chấm outcome, PostTool → Experience | AUTO hoàn toàn |
| **Observer (tương lai)** | Nhận thông báo Telegram/webhook | Read-only |

## 4. Capabilities Breakdown

### P0 — v1 (Ship ngay)
- BA Agent phân tích goal → User Stories + AC + Fibonacci story points
- Priority queue task distribution (không tranh chấp, pick theo story point priority)
- HITL mode với timeout 180s → auto-execute (trừ security và delete)
- Security task: HITL bắt buộc, không bao giờ auto-escalate
- Bất biến tuyệt đối: không tự xóa dữ liệu
- Persist Goal/Task state vào SQLite trong Docker (tránh RAM overflow)
- Resume từ checkpoint khi interrupted (không restart)
- Feature flag architecture cho notification (tắt mặc định)
- MCP tools cho agent tự bật notification + submit goal + get stories

### P1 — v2 (Sau khi v1 ổn định)
- Telegram Bot notification (push one-way)
- Multi-webhook endpoint management
- Toggle notification qua UI + MCP

### P2 — Tương lai
- Slack, Discord, custom webhook channels
- Telegram two-way (remote commands)
- ASCII UI wireframe generation
- Architecture diagram auto-generation

## 5. Core Flows (Happy Path)

### Flow 1 — BA Agent Phân Tích Goal

```
[SA / Agent CLI]
       │
       ▼ POST /api/ba/analyze {goal: "..."}
┌──────────────────────┐
│   BA Agent Service   │
│  Gọi LLM phân tích  │
│  → User Stories      │
│  → AC per story      │
│  → Fibonacci pts     │
│  → Classify AUTO/    │
│    HITL/SECURITY     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Task Planner        │
│  Sắp xếp priority    │
│  queue theo story    │
│  points (cao → thấp) │
└──────────┬───────────┘
           │
           ▼ Persist to SQLite
┌──────────────────────┐
│  GoalRecord saved    │
│  + SSE broadcast     │
│    goal_created      │
└──────────────────────┘
```

**Numbered steps:**
1. SA/Agent gửi `POST /api/ba/analyze` với goal text
2. BA Agent gọi LLM: phân tích goal → sinh User Stories
3. Mỗi User Story → viết AC (Given/When/Then)
4. Estimate Fibonacci story points cho mỗi story
5. Classify từng task: AUTO / HITL / SECURITY
6. Sắp xếp vào priority queue (story points cao = ưu tiên cao)
7. Persist GoalRecord + TaskRecords vào SQLite
8. SSE broadcast `goal_created` event cho tất cả agents

### Flow 2 — Harness Tự Động Execute

```
[Agent đang idle]
       │
       ▼ SSE: task_assigned / task_available
┌──────────────────────┐
│  Agent nhận task     │
│  từ priority queue   │
│  (exclusive claim)   │
└──────┬───────────────┘
       │
       ├── Task Mode: AUTO ──────────────────────────────────┐
       │                                                      │
       ├── Task Mode: HITL ──► Notify SA (dashboard/v2:tele) │
       │                  wait ≤180s                         │
       │                  No reply → auto-execute            │
       │                  (trừ DELETE/SECURITY)              │
       │                                                      │
       └── Task Mode: SECURITY ──► HITL bắt buộc            │
                                  Không timeout              │
                                                             │
                            ┌────────────────────────────────▼──┐
                            │  Execute Task                      │
                            │  ❌ NO auto-delete                 │
                            │  Minimal tools per step            │
                            │  Restrictive permissions           │
                            └──────────┬─────────────────────────┘
                                       │
                   ┌───────────────────┼───────────────────┐
                   ▼                   ▼                   ▼
             SUCCESS           INTERRUPTED            FAILED
                   │          Resume checkpoint      Retry → HITL
                   │          (no restart)
                   ▼
          ┌─────────────────┐
          │  Verify AC      │
          │  tests/linter   │
          └────────┬────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
     AC PASSED         AC FAILED
     mark done       retry / HITL
          │
          ▼
   ┌─────────────┐
   │ PostTool →  │
   │ Experience  │
   │ (học tiếp)  │
   └─────────────┘
```

**Numbered steps:**
1. Agent idle nhận SSE event `task_assigned` hoặc poll queue
2. Agent claim task (exclusive — atomic lock, agent khác skip)
3. Kiểm tra Task Mode:
   - AUTO → execute ngay
   - HITL → gửi notification, wait 180s, nếu không reply → auto-execute
   - SECURITY / DELETE → HITL bắt buộc, không bao giờ escalate
4. Execute với minimal tools scope + restrictive permissions
5. Nếu interrupted → save checkpoint → resume (không restart)
6. Nếu failed → retry 1 lần → nếu vẫn fail → flag HITL
7. Verify AC (chạy test, linter)
8. AC passed → mark complete → PostTool → save experience
9. GoalService tự động pick next task trong queue

## 6. System Behavior Deep Dive

### 6.1 Decision Points

| ID | Flow | Điều kiện | YES | NO |
|---|---|---|---|---|
| D1 | Classify task | Task liên quan xóa dữ liệu? | HITL bắt buộc (no timeout) | Tiếp tục |
| D2 | Classify task | Task liên quan bảo mật? | SECURITY (HITL no timeout) | Tiếp tục |
| D3 | HITL wait | SA reply trong 180s? | Execute theo lệnh SA | Auto-execute |
| D4 | Execute | Interrupted? | Resume from checkpoint | Continue |
| D5 | Verify | AC passed? | Mark done, PostTool | Retry → HITL |
| D6 | Priority | Nhiều task cùng story points? | Pick ngẫu nhiên trong nhóm | — |
| D7 | Notification | Feature flag ON? | Gửi webhook/Telegram | Im lặng |
| D8 | Claim | Task đã có agent claim? | Agent khác skip, pick next | Claim và lock |

### 6.2 Scenario Matrix — Task Mode × Agent Role

| Agent Role | Task: AUTO | Task: HITL (non-delete) | Task: DELETE | Task: SECURITY |
|---|---|---|---|---|
| BA Agent | Tự phân tích, sinh doc | Chờ SA nếu overwrite doc có sẵn | HITL bắt buộc | HITL bắt buộc |
| Coding Agent | Tự code + commit | Chờ 180s → auto nếu SA không reply | HITL bắt buộc, không timeout | HITL bắt buộc |
| Testing Agent | Tự chạy test | — | HITL bắt buộc | HITL bắt buộc |
| Evaluation Agent | Tự PostTool | — | HITL bắt buộc | HITL bắt buộc |

### 6.3 State Transitions

| Entity | Từ | Sang | Trigger | Quay lại? |
|---|---|---|---|---|
| Goal | `submitted` | `analyzing` | BA Agent nhận task | Không |
| Goal | `analyzing` | `planned` | BA Agent hoàn thành, tasks created | Không |
| Goal | `planned` | `executing` | Agent đầu tiên claim task | Không |
| Goal | `executing` | `verifying` | Tất cả tasks completed | Không |
| Goal | `verifying` | `done` | AC passed toàn bộ | Không |
| Goal | `*` | `failed` | Task fail quá nhiều lần | Không |
| Task | `pending` | `hitl_pending` | Task mode HITL, chờ SA | Về `pending` nếu reject |
| Task | `hitl_pending` | `claimed` | SA approve hoặc timeout 180s | Không |
| Task | `pending` | `claimed` | Agent claim exclusive | Không |
| Task | `claimed` | `in_progress` | Agent bắt đầu execute | Không |
| Task | `in_progress` | `interrupted` | Agent mất kết nối | Về `in_progress` (resume) |
| Task | `in_progress` | `verifying` | Execute xong | Không |
| Task | `verifying` | `completed` | AC passed | Không |
| Task | `verifying` | `failed` | AC fail sau retry | Không |

### 6.4 Interrupted Transaction Matrix

| Tình huống | State còn lại | Resume path | Ghi chú |
|---|---|---|---|
| Agent mất kết nối giữa task | `interrupted` + checkpoint saved | Agent reconnect → resume từ checkpoint | Không restart, bảo toàn context |
| LLM timeout trong BA analysis | `analyzing` + partial result | Resume từ step bị timeout | Ưu tiên token optimization |
| 2 agent cùng claim 1 task | Atomic lock — agent thứ 2 thấy task đã taken | Agent thứ 2 tự pick task tiếp theo | Exclusive claim, không race condition |
| HITL không có reply sau 180s | `hitl_pending` → auto-escalate | Auto-execute (trừ DELETE/SECURITY) | Notify SA "đã tự thực hiện" |
| SA reject HITL task | `hitl_pending` → `pending` | Task về queue, agent khác pick | SA có thể sửa scope rồi re-approve |
| Engine restart | All state in SQLite | Load từ DB, resume tasks `in_progress` | Không mất tiến độ |

### 6.5 Other Edge Cases

- **Goal quá mơ hồ:** BA Agent không decompose được → flag `analysis_failed`, notify SA để clarify
- **Tất cả agents offline:** Tasks ở `pending` trong queue, không expire — agent online lại thì tiếp tục
- **Story points estimate sai:** SA có thể override priority qua API sau khi goal analyzed
- **AC quá nghiêm ngặt:** Testing Agent fail liên tục → sau 3 lần → escalate HITL với báo cáo chi tiết

## 7. Validation, Limits & Wording

### 7.1 Validation Rules

- Goal text: tối thiểu 10 ký tự, tối đa 2000 ký tự
- Story points: chỉ dùng Fibonacci: 1, 2, 3, 5, 8, 13
- Task mode: chỉ `AUTO` | `HITL` | `SECURITY`
- Webhook URL: phải là valid HTTP/HTTPS URL
- Bot token Telegram: format `{bot_id}:{token}` (validate bằng Telegram API)

### 7.2 Limits & Quotas

| Giới hạn | Giá trị |
|---|---|
| HITL timeout (non-security/non-delete) | **180 giây** |
| SECURITY / DELETE task timeout | **Không có** — chờ mãi |
| Task retry trước khi escalate HITL | **3 lần** |
| Max story points per story | **13** (Fibonacci max) |
| Max tasks per goal | **20** |
| Max goals in_progress đồng thời | **5** |
| Task claim lock (exclusive hold) | Không timeout — agent giữ đến done/fail/interrupt |
| Goal history lưu trong SQLite | **90 ngày** |

### 7.3 Wording Samples

**Error messages:**
| Tình huống | Message |
|---|---|
| Goal quá ngắn | "Goal phải có ít nhất 10 ký tự để BA Agent phân tích." |
| BA analysis thất bại | "BA Agent không thể phân tích goal này. Vui lòng làm rõ mục tiêu và thử lại." |
| Task claim conflict | "Task đã được agent khác nhận. Đang chuyển sang task tiếp theo." |
| DELETE task không được auto | "Tác vụ xóa dữ liệu yêu cầu xác nhận thủ công. Vui lòng approve trong dashboard." |

**Success messages:**
| Tình huống | Message |
|---|---|
| Goal analyzed | "BA Agent đã phân tích xong. {N} user stories, tổng {P} story points." |
| Task completed | "Task '{name}' hoàn thành. AC đã verify ✓" |
| Goal done | "Goal '{goal}' hoàn thành toàn bộ. Đã lưu {N} experiences vào engine." |

**Info / Notification messages:**
| Tình huống | Message (Telegram format) |
|---|---|
| Task bắt đầu | `[Loomind] ⚙️ Task #{N} đang thực hiện: {description}` |
| HITL cần approve | `[Loomind] ⏳ Task #{N} cần xác nhận: {description}. Tự động sau 180s.` |
| HITL escalated | `[Loomind] ▶️ Task #{N} tự thực hiện (không có phản hồi sau 180s).` |
| Goal hoàn thành | `[Loomind] ✅ Goal hoàn thành: {goal_text}` |

## 8. Assumptions

- LLM hiện có (Ollama/llama.cpp) đủ khả năng decompose goal thành User Stories chất lượng
- SQLite phù hợp cho goal/task persistence trong Docker single-node deployment
- Feature flag notification mặc định OFF — không ảnh hưởng behavior hiện tại
- SA (người dùng) không cần training — hệ thống tự động, SA chỉ cần approve HITL
- Telegram API ổn định cho v2 notification (không trong scope v1)
- Exclusive task claim có thể implement bằng atomic update trong SQLite

## 9. Risks

| Rủi ro | Loại | Khả năng | Hậu quả nghiệp vụ | Cách phòng |
|---|---|---|---|---|
| **Token quota overflow** | Timeline / Budget | Thường xuyên (goal phức tạp) | Agent dừng giữa chừng, mất tiến độ, tốn thêm chi phí | Resume từ checkpoint (không restart); tối ưu prompt; giới hạn max tasks per goal = 20 |
| BA Agent sinh AC kém chất lượng | Data / Adoption | Thỉnh thoảng | Testing Agent fail liên tục, goal kéo dài | Sau 3 lần fail → escalate HITL với báo cáo; SA override AC |
| SQLite conflict khi nhiều agents ghi đồng thời | Process | Thỉnh thoảng | Task state corrupt | WAL mode + exclusive lock per write; retry on conflict |

## 10. Success Criteria

- BA Agent tự phân tích goal trong < 30s
- Tỉ lệ task AUTO thành công (không cần HITL) > 70%
- Không xảy ra trường hợp tự xóa dữ liệu
- Engine restart không mất goal/task state
- HITL timeout 180s hoạt động chính xác ± 5s
- Feature flag notification: bật/tắt không ảnh hưởng automation flow

## 11. Open Questions

- [ ] OQ-1: Telegram gửi notification fail → retry bao nhiêu lần trước khi bỏ qua? (defer /srs)
- [ ] OQ-2: Format lưu Goal/Task checkpoint trong SQLite — cần schema cụ thể (defer /srs)
- [ ] OQ-3: BA Agent xử lý goal mơ hồ thế nào — hỏi SA thêm, hay tự đặt giả định và flag OQ?
- [ ] OQ-4: Multi-webhook v2 — cấu hình format và UI quản lý nhiều endpoint (defer /prd v2)
- [ ] OQ-5: Cơ chế validate chất lượng AC trước khi task được execute (BA Agent tự review, hay SA approve?)

## 12. Next Steps

- `/srs agentic-brain` — spec kỹ thuật: SQLite schema, BA Agent prompt design, HITL timer implementation
- `/prd agentic-brain` — product scope v1 vs v2, notification roadmap
- Cập nhật `README.md` — thêm mục Agentic Brain (BA Agent + Harness v2)
- Cập nhật `index.html` — thêm tính năng vào landing page
