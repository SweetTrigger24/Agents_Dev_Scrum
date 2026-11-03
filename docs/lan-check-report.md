# Báo cáo kiểm tra kết nối mạng LAN (LAN Connectivity Report)
*Thời gian kiểm tra:* 2026-11-03T02:31:12.976995Z

## 1. Kết quả kiểm tra từng Agent

| Agent ID | Endpoint URL | /health | Bảo mật Auth (401) | Độ trễ | Contract Version | Ghi chú / Lỗi |
|---|---|---|---|---|---|---|
| `devops-01` | `http://127.0.0.1:51021` | ✅ PASS | ✅ PASS | 53 ms | `1.0.0` | Hoạt động bình thường |
| `pm-01` | `http://127.0.0.1:51020` | ✅ PASS | ✅ PASS | 43 ms | `1.0.0` | Hoạt động bình thường |

## 2. Đánh giá tính đồng nhất Contract Version
- ✅ **ĐỒNG NHẤT**: Tất cả các agent đang chạy chung phiên bản: `1.0.0`

## 3. Hướng dẫn khắc phục sự cố (Troubleshooting)
- **Lỗi `Connection Refused`**: Kiểm tra Agent đã chạy chưa (`python -m uvicorn api:app`), Agent có bind `0.0.0.0` không, và cổng có đúng không.
- **Lỗi `Timeout`**: Kiểm tra Firewall trên máy đích đã mở cổng cho dải IP mạng LAN chưa.
- **Lỗi `Auth không trả 401`**: Kiểm tra file `api.py` đã kích hoạt dependency `verify_bearer_token` cho endpoint `/agent` chưa.
