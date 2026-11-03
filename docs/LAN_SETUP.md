# HƯỚNG DẪN THIẾT LẬP KẾT NỐI MẠNG LAN CHO CÁC AI AGENT (LAN SETUP GUIDE)

Tài liệu hướng dẫn 5 thành viên thiết lập mạng nội bộ (LAN) hoặc VPN Tailscale để các AI Agent trên 5 máy khác nhau giao tiếp mượt mà và bảo mật qua **Agent API v1**.

---

## 1. THIẾT LẬP ĐỊA CHỈ IP TĨNH HOẶC VPN TAILSCALE

### Cách A: Cùng mạng Wi-Fi / LAN nội bộ (Khuyên dùng khi ngồi cùng phòng)
1. Cấu hình DHCP Reservation trên Router Wi-Fi hoặc đặt IP tĩnh (Static IP) cho card mạng:
   - **Máy 1:** `192.168.1.101` (PM: 8001, DevOps: 8002)
   - **Máy 2:** `192.168.1.102` (BA: 8003, SA: 8004)
   - **Máy 3:** `192.168.1.103` (PO: 8005, DEV: 8006)
   - **Máy 4:** `192.168.1.104` (TESTER: 8007, DBA: 8008)
   - **Máy 5:** `192.168.1.105` (SCRUM_MASTER: 8009, SECURITY: 8010)
2. Điền IP thực tế vào file [`docs/AGENT_ENDPOINTS.md`](file:///c:/Users/Admin/Desktop/qldapm-4(5)/AGENT/docs/AGENT_ENDPOINTS.md).

### Cách B: Khác mạng Wi-Fi / Làm việc từ xa (Khuyên dùng Tailscale VPN)
- Cài đặt [Tailscale](https://tailscale.com/) trên cả 5 máy và đăng nhập chung 1 Tailnet.
- Mỗi máy sẽ nhận một IP dạng `100.x.y.z`. Điền IP Tailscale này vào `scripts/endpoints.yaml`.
- Tailscale tự động mã hóa đầu-cuối (End-to-End Encryption) mà không cần mở cổng Router.

---

## 2. MỞ CỔNG FIREWALL CHO DẢI MẠNG LAN

Agent lắng nghe trên `0.0.0.0`, do đó Firewall trên hệ điều hành phải cho phép kết nối đến:

### Trên Windows (PowerShell với quyền Administrator):
```powershell
# Mở cổng cho Máy 1 (8001 và 8002) từ dải mạng LAN 192.168.1.0/24:
New-NetFirewallRule -DisplayName "AI-Team Agents (8001-8002)" -Direction Inbound -LocalPort 8001,8002 -Protocol TCP -Action Allow -RemoteAddress 192.168.1.0/24
```

### Trên Linux (UFW):
```bash
# Mở cổng cho dải IP LAN:
sudo ufw allow from 192.168.1.0/24 to any port 8003 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 8004 proto tcp
sudo ufw reload
```

### Trên macOS:
- Vào **System Settings** $\rightarrow$ **Network** $\rightarrow$ **Firewall** $\rightarrow$ Thêm quyền cho Python / Uvicorn nhận kết nối đến (Allow incoming connections).

---

## 3. SINH VÀ CẤU HÌNH AGENT_API_KEY BẢO MẬT

Để ngăn chặn truy cập trái phép qua mạng, mọi request tới Agent (trừ `/health`) bắt buộc phải có Bearer token.

### Bước 1: Sinh Token ngẫu nhiên (32 bytes an toàn):
Chạy lệnh Python:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
*Ví dụ token sinh ra:* `7QW8b9A_1xYZ...k8m0`

### Bước 2: Cấu hình vào file `.env` của Agent trên từng máy:
Mỗi Agent có một token riêng trong file `.env` cá nhân của nó (đã được gitignore):
```properties
HOST=0.0.0.0
PORT=8001
AGENT_API_KEY=7QW8b9A_1xYZ...k8m0
MAX_UPLOAD_MB=10
```

> [!WARNING]
> Nếu `HOST` khác `127.0.0.1` (ví dụ `0.0.0.0`) mà thiếu `AGENT_API_KEY`, Agent sẽ **từ chối khởi động** để bảo vệ an toàn cho máy của bạn!

### Bước 3: Cấu hình token vào `.env.lan` để gọi chéo:
Tạo file `.env.lan` tại gốc repo (đã được gitignore) để lưu token của các agent khác:
```properties
AGENT_API_KEY_PM_01=pm-secret-token-key
AGENT_API_KEY_DEVOPS_01=devops-secret-token-key
AGENT_API_KEY_BA_01=ba-secret-token-key
AGENT_API_KEY_SA_01=sa-secret-token-key
```

---

## 4. CHẠY VÀ KIỂM TRA TỪ MÁY KHÁC

### Khởi động Agent trên máy của bạn:
```powershell
cd agents/pm
python -m uvicorn api:app --host 0.0.0.0 --port 8001
```

### Kiểm tra từ máy khác qua mạng LAN:
1. Tạo file `scripts/endpoints.yaml` (copy từ `scripts/endpoints.example.yaml`) và điền IP thực tế:
   ```yaml
   pm-01: "http://192.168.1.101:8001"
   devops-01: "http://192.168.1.101:8002"
   ```
2. Chạy script kiểm tra tự động toàn mạng:
   ```powershell
   python scripts/lan_check.py
   ```
3. Thử nghiệm gửi task qua mạng LAN:
   ```powershell
   python scripts/lan_client.py task pm-01 agents/pm/examples/task.json
   ```
4. Thử nghiệm đẩy artifact qua mạng vào inbox của agent:
   ```powershell
   python scripts/lan_client.py push-artifact pm-01 sample_requirements.md --type REQUIREMENT --created-by ba-01
   ```
