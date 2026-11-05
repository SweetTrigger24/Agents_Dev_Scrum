# scrum_master Agent

Prompt chính nằm trong [prompt.py](prompt.py): `SCRUM_SYSTEM_PROMPT` và `build_scrum_review_prompt()`. `agent.py` điều khiển action; `tools/` tổng hợp dữ liệu, kiểm tra module, gọi AI và lưu báo cáo.

Skill tự nạp theo action: xem [DEV_SCRUM_SKILLS.md](../../docs/DEV_SCRUM_SKILLS.md).

Sử dụng Agent Contract 1.3.0 từ ../../contract. Hỗ trợ review_module, track_blockers và run_retrospective. Review module tạo báo cáo DOCUMENTATION trước khi chuyển module; xem [SCRUM_MODULE_REVIEW.md](../../docs/SCRUM_MODULE_REVIEW.md). Xem docs/HUONG_DAN_DEV_SCRUM_CUNG_MAY.md để khởi chạy.
