#!/usr/bin/env python3
"""
scripts/lan_check.py
Công cụ kiểm tra kết nối mạng LAN và tính tuân thủ Agent API v1 giữa các máy.

Kiểm tra:
1. Gọi GET /health: đo độ trễ (latency ms), trạng thái hoạt động.
2. So khớp agent_id trả về với định danh trong endpoints.yaml.
3. Kiểm tra tính đồng nhất của contract_version giữa các agent.
4. Thử gọi GET /agent không có token để xác nhận trả HTTP 401 Unauthorized.
5. Xuất bảng tổng hợp và tạo báo cáo docs/lan-check-report.md.
"""

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def _setup_console_encoding() -> None:
    if "pytest" in sys.modules:
        return
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

import httpx
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
REPORT_FILE = ROOT_DIR / "docs" / "lan-check-report.md"


def load_endpoints() -> dict[str, str]:
    yaml_path = ROOT_DIR / "scripts" / "endpoints.yaml"
    if not yaml_path.exists():
        yaml_path = ROOT_DIR / "scripts" / "endpoints.example.yaml"

    if not yaml_path.exists():
        print("Lỗi: Không tìm thấy file endpoints.yaml hoặc endpoints.example.yaml", file=sys.stderr)
        sys.exit(1)

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        print("Lỗi: File endpoints YAML không hợp lệ.", file=sys.stderr)
        sys.exit(1)
    return {str(k): str(v).rstrip("/") for k, v in data.items()}


def get_troubleshooting_hint(error_msg: str, base_url: str) -> str:
    err_lower = error_msg.lower()
    if "connection refused" in err_lower or "connect" in err_lower:
        return (
            f"Không thể kết nối tới {base_url}. "
            "Gợi ý: 1) Agent chưa được khởi động; 2) Agent bind 127.0.0.1 thay vì 0.0.0.0; "
            "3) Firewall trên máy đích chưa mở cổng; 4) Sai địa chỉ IP/cổng."
        )
    if "timed out" in err_lower or "timeout" in err_lower:
        return f"Kết nối tới {base_url} bị timeout. Gợi ý: Firewall đang DROP gói tin hoặc sai IP."
    return f"Lỗi kết nối: {error_msg}"


def main() -> int:
    _setup_console_encoding()
    endpoints = load_endpoints()
    print("=" * 95)
    print(" KIỂM TRA KẾT NỐI MẠNG LAN VÀ BẢO MẬT AGENT API v1 (Prompt 7)")
    print("=" * 95)

    results = []
    contract_versions = {}
    has_failure = False

    for agent_id, base_url in endpoints.items():
        row = {
            "agent_id": agent_id,
            "base_url": base_url,
            "health_pass": False,
            "auth_pass": False,
            "latency_ms": 0,
            "contract_version": "N/A",
            "message": "",
            "troubleshoot": "",
        }

        # 1. Kiểm tra GET /health
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=5.0) as client:
                res_health = client.get(f"{base_url}/health")
                latency_ms = int((time.perf_counter() - start) * 1000)
                row["latency_ms"] = latency_ms

                if res_health.status_code == 200:
                    health_json = res_health.json()
                    ret_aid = health_json.get("agent_id")
                    ret_cver = health_json.get("contract_version", "unknown")
                    row["contract_version"] = ret_cver
                    contract_versions[agent_id] = ret_cver

                    if ret_aid != agent_id:
                        row["message"] = f"Sai agent_id: nhận '{ret_aid}', mong đợi '{agent_id}'"
                        has_failure = True
                    else:
                        row["health_pass"] = True
                else:
                    row["message"] = f"/health trả HTTP {res_health.status_code}"
                    has_failure = True
        except Exception as e:
            row["latency_ms"] = int((time.perf_counter() - start) * 1000)
            row["message"] = f"Lỗi kết nối: {e}"
            row["troubleshoot"] = get_troubleshooting_hint(str(e), base_url)
            has_failure = True

        # 2. Kiểm tra xác thực: Gọi GET /agent không có token phải nhận 401
        try:
            with httpx.Client(timeout=5.0) as client:
                res_auth = client.get(f"{base_url}/agent")
                if res_auth.status_code == 401:
                    row["auth_pass"] = True
                else:
                    row["auth_pass"] = False
                    row["message"] += f" | /agent không có token trả HTTP {res_auth.status_code} (mong đợi 401)"
                    has_failure = True
        except Exception as e:
            if row["health_pass"]:
                row["message"] += f" | Lỗi gọi /agent: {e}"
                has_failure = True

        results.append(row)

    # 3. Kiểm tra tính đồng nhất của contract_version
    distinct_cvers = set(contract_versions.values())
    cver_mismatch = len(distinct_cvers) > 1

    # In kết quả dạng bảng ra màn hình
    print(f"| {'AGENT ID':<16} | {'ENDPOINT':<28} | {'HEALTH':<8} | {'AUTH 401':<10} | {'ĐỘ TRỄ':<8} | {'VERSION':<8} |")
    print("|" + "-" * 18 + "|" + "-" * 30 + "|" + "-" * 10 + "|" + "-" * 12 + "|" + "-" * 10 + "|" + "-" * 10 + "|")

    for r in results:
        h_str = "PASS" if r["health_pass"] else "FAIL"
        a_str = "PASS" if r["auth_pass"] else "FAIL"
        lat_str = f"{r['latency_ms']}ms" if r["health_pass"] else "-"
        print(f"| {r['agent_id']:<16} | {r['base_url']:<28} | {h_str:<8} | {a_str:<10} | {lat_str:<8} | {r['contract_version']:<8} |")
        if r["troubleshoot"]:
            print(f"  👉 GỢI Ý: {r['troubleshoot']}")

    print("=" * 95)

    if cver_mismatch:
        print(f"[!] CẢNH BÁO: Phát hiện phiên bản contract_version không đồng nhất: {distinct_cvers}", file=sys.stderr)
        has_failure = True

    # 4. Xuất báo cáo Markdown docs/lan-check-report.md
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    report_lines = [
        "# Báo cáo kiểm tra kết nối mạng LAN (LAN Connectivity Report)",
        f"*Thời gian kiểm tra:* {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}\n",
        "## 1. Kết quả kiểm tra từng Agent\n",
        "| Agent ID | Endpoint URL | /health | Bảo mật Auth (401) | Độ trễ | Contract Version | Ghi chú / Lỗi |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in results:
        h_badge = "✅ PASS" if r["health_pass"] else "❌ FAIL"
        a_badge = "✅ PASS" if r["auth_pass"] else "❌ FAIL"
        lat = f"{r['latency_ms']} ms" if r["health_pass"] else "N/A"
        msg = r["message"] or "Hoạt động bình thường"
        report_lines.append(f"| `{r['agent_id']}` | `{r['base_url']}` | {h_badge} | {a_badge} | {lat} | `{r['contract_version']}` | {msg} |")

    report_lines.append("\n## 2. Đánh giá tính đồng nhất Contract Version")
    if cver_mismatch:
        report_lines.append(f"- ❌ **LỆCH PHIÊN BẢN**: Các agent đang sử dụng các phiên bản khác nhau: {distinct_cvers}")
    else:
        ver_str = list(distinct_cvers)[0] if distinct_cvers else "N/A"
        report_lines.append(f"- ✅ **ĐỒNG NHẤT**: Tất cả các agent đang chạy chung phiên bản: `{ver_str}`")

    report_lines.append("\n## 3. Hướng dẫn khắc phục sự cố (Troubleshooting)")
    report_lines.append("- **Lỗi `Connection Refused`**: Kiểm tra Agent đã chạy chưa (`python -m uvicorn api:app`), Agent có bind `0.0.0.0` không, và cổng có đúng không.")
    report_lines.append("- **Lỗi `Timeout`**: Kiểm tra Firewall trên máy đích đã mở cổng cho dải IP mạng LAN chưa.")
    report_lines.append("- **Lỗi `Auth không trả 401`**: Kiểm tra file `api.py` đã kích hoạt dependency `verify_bearer_token` cho endpoint `/agent` chưa.")

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")

    print(f"\n[✓] Đã xuất báo cáo chi tiết ra file: {REPORT_FILE.resolve()}")

    if has_failure:
        print("\n[!] Kết quả kiểm tra: Có Agent KHÔNG ĐẠT hoặc chưa kết nối được.", file=sys.stderr)
        return 1
    else:
        print("\n[✓] Kết quả kiểm tra: Tất cả Agent hoạt động và tuân thủ Agent API v1 thành công!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
