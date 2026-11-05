# dev Agent

Prompt chính nằm trong [prompt.py](prompt.py): `DEV_SYSTEM_PROMPT` và `build_dev_prompt()`. `agent.py` điều khiển action; `tools/` thực hiện thao tác và kiểm tra dữ liệu.

Skill tự nạp theo action: xem [DEV_SCRUM_SKILLS.md](../../docs/DEV_SCRUM_SKILLS.md).

Tự dùng source đã bàn giao của cùng dự án khi PM không gửi được ZIP: xem [DEV_LOCAL_SOURCE.md](../../docs/DEV_LOCAL_SOURCE.md).

Sử dụng Agent Contract 1.2.0 từ ../../contract. Các action: implement_project, fix_bugs, review_code, refactor_code. Xem docs/HUONG_DAN_DEV_SCRUM_CUNG_MAY.md để khởi chạy.
