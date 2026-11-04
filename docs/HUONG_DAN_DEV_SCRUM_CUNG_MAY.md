# HƯỚNG DẪN CHẠY DEV + SCRUM MASTER TRÊN CÙNG MÁY (WINDOWS)

## 0. Đây là bản nào?
Đây là **bản sao AGENT-main của nhóm** và chỉ thêm hai thư mục `agents/dev` và `agents/scrum_master`, hai script nhỏ trong `scripts/`, và file requirements cài đặt. Code PM, DevOps, Contract gốc được giữ nguyên. Mỗi agent dùng API v1, Agent Contract 1.1.0.

## 1. Giải nén ZIP
Giải nén vào ví dụ `C:\AI_TEAM\AGENT-main`, mở thư mục `AGENT-main` trong VS Code.
Chú ý: không giải nén một ZIP khác chồng lên bản đang làm việc trên Git nếu chưa sao lưu. Nếu đã có repo Git, chỉ copy hai thư mục `agents/dev`, `agents/scrum_master` và script mới.

## 2. Chuẩn bị
Mở PowerShell tại `C:\AI_TEAM\AGENT-main`:

```powershell
python --version
node --version
npm --version
git --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-scrum.txt
.\.venv\Scripts\python.exe scripts\setup_dev_scrum.py
```

Nếu cài Codex để Developer tạo code thật:

```powershell
npm install -g @openai/codex
codex login
codex login status
```

Chọn **Sign in with ChatGPT** để sử dụng quyền lợi ChatGPT Plus trong hạn mức, không dùng OpenAI API key. Đảm bảo `codex --version` chạy được trong PowerShell mới. Chế độ `DRY_RUN=true` chưa dùng Codex.

## 3. Khởi chạy 2 agent (mỗi lệnh trong MỘT terminal riêng)
Tại thư mục gốc dự án (`C:\AI_TEAM\AGENT-main`):

Terminal 1:

```powershell
cd agents\dev
..\..\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8006
```

Terminal 2 (mở terminal mới ở thư mục gốc):

```powershell
cd agents\scrum_master
..\..\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8009
```

Đừng đóng các Terminal. Chỉ mở đường mạng sau khi kiểm tra localhost. Tắt bằng Ctrl+C.

## 4. Smoke test
Mở Terminal thứ 3 ở thư mục gốc `AGENT-main`:

```powershell
.\.venv\Scripts\python.exe scripts\check_dev_scrum.py
```

- `Developer /health`: phải là DEV, 8006. Với DRY_RUN=true, action implement_project trả `BLOCKED` có giải thích: đây là đúng theo chế độ an toàn, chưa sinh code.
- `Scrum /health`: phải là SCRUM_MASTER, 8009. Action track_blockers trả `COMPLETED` và tạo file `agents/scrum_master/artifacts/scrum_<task-id>.md`.
- Script tạo một task_id mới mỗi lần để tránh bộ cache theo task_id của API trả lại kết quả cũ.

## 5. Cho Developer tạo code thật
Dừng Terminal Dev bằng Ctrl+C. Mở `agents/dev/.env`, sửa:

```ini
DRY_RUN=false
DEV_BACKEND=codex
DEV_TIMEOUT_SECONDS=600
```

Với Conductor hiện tại, workflow `dev_implement_project` có timeout **180 giây** nên Developer thực tế bị chặn bởi giới hạn thấp hơn đó (trừ khoảng đệm 15s). Cần phối hợp người làm PM để tăng `timeout_seconds` của bước DEV trong YAML nếu model cần lâu hơn. KHÔNG được khai báo project bất kỳ sẽ xong ngay.

Chạy lại Developer terminal như ở bước 3, mở terminal thứ 3 và chạy lại `check_dev_scrum.py`.
- Khi Codex tạo được file, DEV trả `COMPLETED` kèm artifact `SOURCE_CODE` (`agents/dev/artifacts/source_<task-id>.zip`).
- `COMPLETED` ở đây nghĩa Developer đã sinh source, **không có nghĩa build/test đạt**. Tester và DevOps phải kiểm tra riêng.
- Codex dùng sandbox `workspace-write`, thư mục riêng theo task. Không dùng sandbox `danger-full-access`.

Để thử cơ chế đóng gói source mà không tốn lượt Codex, tạm dùng `DRY_RUN=false` + `DEV_BACKEND=sample`. Lúc này source ZIP chỉ có HTML mẫu **không phải AI tạo**; phải chuyển lại `DEV_BACKEND=codex` trước demo thật.

## 6. Khi đưa cho PM qua LAN
Dừng cả hai terminal, sửa hai file `agents/dev/.env`, `agents/scrum_master/.env`:

```ini
HOST=0.0.0.0
```

Chạy lại lệnh Uvicorn ở bước 3, thay `--host 127.0.0.1` bằng `--host 0.0.0.0`.

Lấy IP IPv4 của máy bạn bằng `ipconfig`. Ví dụ IP `192.168.1.103`; PM điền vào `scripts/endpoints.yaml` bên máy PM:

```yaml
dev-01: "http://192.168.1.103:8006"
scrum_master-01: "http://192.168.1.103:8009"
```

Trên máy PM, trong `.env.lan` đặt giá trị token tương ứng `AGENT_API_KEY_DEV_01=` và `AGENT_API_KEY_SCRUM_MASTER_01=`. Lấy token từ `.env` trên máy bạn; chỉ gửi riêng cho người PM, không commit Git.

Nếu Windows Firewall chặn, chạy PowerShell Administrator **trên máy của bạn** (thay IP PM thật):

```powershell
New-NetFirewallRule -DisplayName "AI Team DEV SCRUM" -Direction Inbound -Protocol TCP -LocalPort 8006,8009 -RemoteAddress 192.168.1.101 -Profile Private -Action Allow
```

Lưu ý `scripts/configure_lan.py setup-machine 3` bản gốc **tạo PO+DEV**, còn `setup-machine 5` **tạo Scrum+Security**. **Không dùng hai lệnh đó trên máy bạn**; sử dụng script `scripts/setup_dev_scrum.py` mới, chỉ tạo đúng hai agent.

## 7. Bốn action đã có
- DEV: `implement_project`, `fix_bugs`.
- Scrum: `track_blockers`, `run_retrospective`.

Scrum có hai chế độ:
- `SM_BACKEND=rules` (mặc định): Python tổng hợp dữ liệu `context.tasks` và blocker, không cần API hay Gemini.
- `SM_BACKEND=antigravity` và `DRY_RUN=false`: nếu đã cài và đăng nhập Google Antigravity CLI `agy`, agent thử lấy thêm lời bình bằng `agy -p`. Nếu lỗi, vẫn trả báo cáo quy tắc. Điều này **không biến Scrum thành giám sát thời gian thực**; PM cần chủ động gọi `track_blockers` với snapshot. Workflow PM hiện chỉ gọi `run_retrospective` ở cuối, với `brief` và `project_id`, nên phần báo cáo cuối có thể thiếu số liệu.

## 8. Nếu lỗi
| Lỗi | Kiểm tra |
|---|---|
| ModuleNotFoundError agent_contract | Chạy `.\.venv\Scripts\python.exe -m pip install -e .\contract` từ gốc repo |
| ModuleNotFoundError multipart | Chạy `.\.venv\Scripts\python.exe -m pip install python-multipart` |
| 401 | Token trong `agents/<role>/.env` không khớp Authorization header |
| 409 | Agent đang xử lý task khác, đừng gửi cùng lúc |
| Task cũ không cập nhật | Dùng task_id mới; API có cache theo task_id |
| Cổng bị chiếm | `netstat -ano | findstr :8006` hoặc `:8009` |
| Codex CLI chưa thấy | Tạo PowerShell mới; kiểm tra `codex --version` và `codex login status` |
| Script check DEV BLOCKED | Đây là kỳ vọng nếu DRY_RUN=true; chuyển false và đăng nhập Codex để viết thật |
| Gemini Pro | Không tự cấp Gemini API token trả phí; dùng SM_BACKEND=rules trước, Antigravity nếu đã sẵn có |

## 9. Trạng thái xác minh
Đã kiểm thử tại môi trường chạy thử (không phải máy Windows của bạn): đồng thời /health 2 agent, DEV DRY_RUN trả BLOCKED đúng, Scrum trả DOCUMENTATION, DEV SAMPLE tạo ZIP SOURCE_CODE và tải được ZIP qua API. Chưa kiểm thử Codex thực bằng tài khoản người dùng, chưa kiểm thử mạng LAN/PM Conductor đủ 10 agent và chưa xác minh build/deploy thật.
