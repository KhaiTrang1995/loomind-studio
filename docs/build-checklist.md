# Loomind — Build Checklist (Windows Installer)

> Copy-paste từng lệnh theo thứ tự. **DỪNG LẠI nếu bất kỳ bước nào fail.**

---

## Step 1: Test Engine Standalone (không cần build exe)

```powershell
cd d:\GitHub\loomind-studio\core\loomind-engine
.venv\Scripts\python launcher.py
```

**Kết quả mong đợi:**
```
[Loomind] Starting engine on http://127.0.0.1:8082
INFO:     Application startup complete.
```

**Test API (mở terminal mới):**
```powershell
curl http://127.0.0.1:8082/health
```

> ⛔ DỪNG nếu fail → sửa lỗi Python trước!

Nhấn `Ctrl+C` để tắt engine.

---

## Step 2: Build Engine .exe

```powershell
cd d:\GitHub\loomind-studio\core\loomind-engine
.venv\Scripts\python build_exe.py
```

**Kết quả mong đợi:**
```
[SUCCESS] Build complete!
  Executable: dist\loomind-engine.exe (xxx.x MB)
```

---

## Step 3: Test .exe Standalone

```powershell
cd d:\GitHub\loomind-studio\core\loomind-engine
dist\loomind-engine.exe
```

**Kết quả mong đợi:**
```
[Loomind] Standalone mode (PyInstaller)
[Loomind] Starting engine on http://127.0.0.1:8082
```

**Test API (mở terminal mới):**
```powershell
curl http://127.0.0.1:8082/health
```

> ⛔ DỪNG nếu fail → kiểm tra output console!

Nhấn `Ctrl+C` để tắt engine.

---

## Step 4: Copy .exe vào Tauri sidecar

```powershell
copy d:\GitHub\loomind-studio\core\loomind-engine\dist\loomind-engine.exe d:\GitHub\loomind-studio\apps\loomind-desktop\src-tauri\binaries\loomind-engine-x86_64-pc-windows-msvc.exe

 copy .\dist\loomind-engine.exe ..\..\apps\loomind-desktop\src-tauri\binaries\loomind-engine-x86_64-pc-windows-msvc.exe
```

**Kiểm tra file đã copy:**
```powershell
dir d:\GitHub\loomind-studio\apps\loomind-desktop\src-tauri\binaries\
```

---

## Step 5: Test Tauri Dev Mode

```powershell
$env:PATH += ";$env:USERPROFILE\.cargo\bin"
cd $PSScriptRoot\..\..\apps\loomind-desktop   # or your clone path
npx tauri dev
```

**Kết quả mong đợi:**
- Cửa sổ Loomind mở lên
- Loading screen → sau 20-60s → Dashboard hiện "Connected"
- Console Rust hiện "Engine binary found at: ..."

> ⛔ DỪNG nếu fail → kiểm tra log Rust trong terminal!

Đóng app.

---

## Step 6: Build Installer

```powershell
cd d:\GitHub\loomind-studio\apps\loomind-desktop
npx tauri build
```

**Hoặc dùng all-in-one script (bỏ qua Step 2-5):**
```powershell
cd d:\GitHub\loomind-studio
python build_all.py
```

**Output:**
```
apps\loomind-desktop\src-tauri\target\release\bundle\nsis\Loomind_0.1.0_x64-setup.exe
```

---

## Step 7: Test Installer (máy sạch hoặc cùng máy)

```powershell
# Tìm installer
dir d:\GitHub\loomind-studio\apps\loomind-desktop\src-tauri\target\release\bundle\nsis\*.exe
```

1. Chạy file `Loomind_x.x.x_x64-setup.exe`
2. Cài đặt xong → mở từ Start Menu
3. ✅ Loading → Dashboard → "Connected"
4. ✅ Tắt app → kiểm tra Task Manager không còn `loomind-engine.exe`
5. ✅ Mở lại → load nhanh hơn (5-15s)

---

## Quick: Chạy tất cả 1 lệnh

Nếu đã test Step 1 OK, chạy luôn:

```powershell
cd d:\GitHub\loomind-studio
python build_all.py
```

Script sẽ tự chạy Step 2 → 4 → 6 liên tục.

---

## Troubleshooting

| Lỗi | Nguyên nhân | Fix |
|-----|-------------|-----|
| App nháy rồi tắt | Sidecar binary không tìm thấy | Kiểm tra Step 4, file name phải chứa target triple |
| Loading treo mãi | `uvicorn.run("string")` | Đã fix: dùng `uvicorn.run(app)` object |
| Engine .exe startup 200s+ | PyInstaller `--onefile` extraction | Bình thường lần đầu, lần sau nhanh hơn |
| Import error trong .exe | Thiếu hidden import | Thêm vào `HIDDEN_IMPORTS` trong `build_exe.py` |
| Windows Defender block | False positive | Xem README → mục "Windows Defender Notice" |
| `distutils` ValueError | Exclude conflict | Không exclude `distutils`, `setuptools` |

---

## Kích thước Build (Tham khảo)

| File | Size | Ghi chú |
|------|------|---------|
| `loomind-engine.exe` | ~150-300MB | PyTorch + sentence-transformers |
| `Loomind_Setup.exe` | ~80-150MB | NSIS compressed |
| Lần chạy đầu | 20-60s | Giải nén vào %TEMP% |
| Lần chạy sau | 5-15s | Đã giải nén sẵn |
