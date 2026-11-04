# Bật AI thật cho Scrum Master Agent (chạy trên cùng máy với Developer)

## Mục tiêu
- Giữ nguyên Agent ID `scrum_master-01`, role `SCRUM_MASTER`, API port `8009` và Agent Contract v1.1.0.
- Giữ hai action `track_blockers` và `run_retrospective` để PM gọi qua `/tasks`.
- Python tính số liệu từ `request.context.tasks`; Antigravity CLI (tài khoản Google AI Pro) chỉ phân tích rủi ro, đề xuất hướng xử lý và viết thông điệp cho PM.
- Khi AI bị lỗi/hết quota, báo cáo vẫn được tạo nhưng `metadata.ai_used=false`, `metadata.ai_status=fallback`, không báo sai rằng AI đã chạy.

## 1. Copy patch
Giải nén `SCRUM_MASTER_AI_PATCH.zip` rồi copy các file trong thư mục `AGENT-main/` vào đúng thư mục tương ứng trong repository gốc (không chép nguyên cả thư mục AGENT-main thành thư mục lồng nhau):

- `agents/scrum_master/agent.py` — thay thế `agent.py` hiện tại (sao lưu/git commit trước).
- `agents/scrum_master/tools/ai_review.py` — thêm file mới.
- `agents/scrum_master/tests/test_ai_review.py` — thêm file kiểm thử.
- `docs/BAT_AI_CHO_SCRUM_MASTER.md` — hướng dẫn này.

Không thay đổi `agents/dev/`, `agents/pm/`, `agents/devops/` hay `contract/`.

## 2. Cài Antigravity CLI và đăng nhập
Xem hướng dẫn cài trên Windows: https://antigravity.google/docs/getting-started?tab=cli

- Cài công cụ `agy` theo trang chính thức.
- Đóng mở lại Terminal rồi chạy: `agy --version`.
- Chạy `agy`, đăng nhập bằng Google Account có Google AI Pro, rồi thoát phiên tương tác.
- Thử chạy trong PowerShell:

```powershell
agy -p "Đề xuất một cách xử lý khi Developer đang BLOCKED" --output-format json
```

Nếu trả về JSON với `status: SUCCESS` và có nội dung `response`, CLI đã chạy được ở chế độ headless. Hãy chọn **AI Credit Overages = Never** trong Settings để không dùng AI credits khi hết quota gói.

## 3. Đổi cấu hình ở `agents/scrum_master/.env`

```ini
HOST=127.0.0.1
PORT=8009
AGENT_ID=scrum_master-01
AGENT_ROLE=SCRUM_MASTER
DRY_RUN=false
SM_BACKEND=antigravity
SM_TIMEOUT_SECONDS=120
```

Giữ nguyên `AGENT_API_KEY` đã sinh; **không** gửi hoặc commit file `.env` lên GitHub. Không cần điền `LLM_API_KEY` cho backend CLI này.

## 4. Khởi động Scrum Master
Trong Terminal riêng, tại repo gốc:

```powershell
cd C:\Users\hoang\Downloads\qldapm\AGENT\agents\scrum_master
python -m uvicorn api:app --host 127.0.0.1 --port 8009
```

Developer ở Terminal khác vẫn dùng port `8006`, không ảnh hưởng.

## 5. Gửi task test riêng Scrum Master
Mở Terminal mới, chuyển về thư mục gốc và chạy:

```powershell
cd C:\Users\hoang\Downloads\qldapm\AGENT
$key = ((Get-Content .\agents\scrum_master\.env | Select-String '^AGENT_API_KEY=').Line -split '=',2)[1].Trim()
$task = Get-Content .\agents\scrum_master\examples\track.json -Raw | ConvertFrom-Json
$task.task_id = 'SM-AI-' + (Get-Date -Format 'yyyyMMddHHmmss')
$task.constraints.timeout_seconds = 180
$body = $task | ConvertTo-Json -Depth 20
$res = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8009/tasks' -Headers @{Authorization="Bearer $key"} -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$res.status
$res.metadata
$res.artifacts
```

Kỳ vọng `status=COMPLETED` và `metadata.ai_used=True`, `metadata.ai_status=success`. Báo cáo ở `agents/scrum_master/artifacts/scrum_SM-AI-....md`, có mục `## Nhận xét của AI Scrum Master`.

Nếu `ai_used=False` thì xem `metadata.ai_reason`:
- `agy_not_installed_or_not_on_PATH`: chưa cài `agy` hoặc Terminal chưa nhận PATH mới.
- `cli_returned_error`: chạy thử lệnh `agy -p ... --output-format json` để xem lỗi đăng nhập/quota.
- `ai_timeout`: tăng `SM_TIMEOUT_SECONDS` và đồng bộ timeout ở PM, nếu phù hợp.
- `invalid_ai_json`: CLI có phản hồi nhưng không đúng JSON Schema, cần kiểm tra phiên bản CLI.

## 6. Test code không cần tài khoản AI

```powershell
cd C:\Users\hoang\Downloads\qldapm\AGENT
python -m pytest -q agents\scrum_master\tests\test_ai_review.py
```

## 7. PM muốn theo dõi tiến độ theo thời gian thực
PM phải gọi action `track_blockers` trong khi các agent khác đang làm, kèm snapshot dữ liệu trong `context.tasks`. Chỉ gọi `run_retrospective` ở cuối pipeline thì Scrum Master chỉ phân tích được trạng thái cuối; tự chạy API trên máy không khiến Scrum Master tự đọc Linear/Jira hoặc theo dõi mọi task.

Lưu ý: Antigravity phân tích bằng cloud; nếu demo offline không có Internet, báo cáo `rules` vẫn hoạt động nhưng AI cloud không chạy.
