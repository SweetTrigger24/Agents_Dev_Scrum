"""Thiết lập .env riêng cho Developer + Scrum Master trên một máy (chạy từ gốc repo)."""
import secrets
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for role in ("dev", "scrum_master"):
    agent_dir = ROOT / "agents" / role
    src, dst = agent_dir / ".env.example", agent_dir / ".env"
    if dst.exists():
        print(f"[SKIP] {dst.relative_to(ROOT)} đã tồn tại, không ghi đè")
        continue
    contents = src.read_text(encoding="utf-8")
    contents = contents.replace("AGENT_API_KEY=\n", "AGENT_API_KEY=" + secrets.token_urlsafe(32) + "\n")
    dst.write_text(contents, encoding="utf-8")
    print(f"[OK] Đã tạo {dst.relative_to(ROOT)} (HOST=127.0.0.1; token riêng)")
print("Không gửi file .env lên GitHub. Chỉ chia sẻ token với người làm PM qua kênh riêng.")
