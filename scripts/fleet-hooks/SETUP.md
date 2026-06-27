# Fleet Monitor — Hook Setup Guide

Sau khi setup, Fleet Monitor tại `/fleet` sẽ tự động track trạng thái của tất cả CLIs.

---

## Claude CLI

Thêm vào `.claude/settings.json` (trong project root hoặc `~/.claude/settings.json` cho global):

```json
"hooks": {
  "UserPromptSubmit": [{ "matcher": "", "hooks": [{ "type": "command",
    "command": "curl -sf -X PATCH \"http://localhost:8082/api/agents/claude/status\" -H \"Content-Type: application/json\" -d \"{\\\"status\\\":\\\"busy\\\",\\\"task\\\":\\\"processing prompt\\\"}\" >nul 2>&1 || exit 0" }] }],
  "Stop": [{ "matcher": "", "hooks": [{ "type": "command",
    "command": "curl -sf -X PATCH \"http://localhost:8082/api/agents/claude/status\" -H \"Content-Type: application/json\" -d \"{\\\"status\\\":\\\"idle\\\"}\" >nul 2>&1 || exit 0" }] }],
  "PreToolCall": [{ "matcher": "", "hooks": [{ "type": "command",
    "command": "curl -sf -X POST \"http://localhost:8082/api/agents/heartbeat?agent_id=claude\" >nul 2>&1 || exit 0" }] }]
}
```

---

## Grok CLI

Thêm vào `C:\Users\Chanx\.grok\config.toml`:

```toml
[hooks]

[[hooks.UserPromptSubmit]]
command = 'curl -sf -X PATCH "http://localhost:8082/api/agents/grok/status" -H "Content-Type: application/json" -d "{\"status\":\"busy\",\"task\":\"processing prompt\"}" >nul 2>&1 || exit 0'

[[hooks.Stop]]
command = 'curl -sf -X PATCH "http://localhost:8082/api/agents/grok/status" -H "Content-Type: application/json" -d "{\"status\":\"idle\"}" >nul 2>&1 || exit 0'

[[hooks.PreToolCall]]
command = 'curl -sf -X POST "http://localhost:8082/api/agents/heartbeat?agent_id=grok" >nul 2>&1 || exit 0'
```

---

## AGY CLI

AGY không có native hooks. Dùng PowerShell wrapper:

1. Mở PowerShell profile:
   ```powershell
   notepad $PROFILE
   ```

2. Thêm function alias:
   ```powershell
   function agy { & "D:\GitHub\loomind-studio\scripts\fleet-hooks\tsx-agy.ps1" @args }
   ```

3. Reload profile:
   ```powershell
   . $PROFILE
   ```

Sau đó gõ `agy` như bình thường — wrapper tự báo trạng thái về engine.

---

## Codex CLI

Tương tự AGY — dùng PowerShell wrapper:

1. Mở PowerShell profile:
   ```powershell
   notepad $PROFILE
   ```

2. Thêm function alias:
   ```powershell
   function codex { & "D:\GitHub\loomind-studio\scripts\fleet-hooks\tsx-codex.ps1" @args }
   ```

3. Reload profile:
   ```powershell
   . $PROFILE
   ```

---

## Verify setup

Sau khi setup, chạy engine rồi mở Fleet Monitor (`/fleet`):

```bash
# Start engine
cd core/loomind-engine
python -m uvicorn src.main:app --host 0.0.0.0 --port 8082

# Test manual status update
curl -X PATCH http://localhost:8082/api/agents/claude/status \
  -H "Content-Type: application/json" \
  -d '{"status":"online"}'

# Check fleet
curl http://localhost:8082/api/agents
```

Fleet Monitor sẽ hiển thị tất cả CLIs với trạng thái realtime.
