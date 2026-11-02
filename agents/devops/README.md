# DevOps Agent (`devops-01`)

Agent chịu trách nhiệm quản lý Git, đóng gói Docker, sinh cấu hình CI/CD, chạy test tự động, triển khai dịch vụ (Deployment), kiểm tra sức khỏe hệ thống và thiết lập giám sát.

---

## 1. Cơ chế An toàn Tuyệt đối

DevOps Agent áp dụng chính sách bảo mật đa tầng nghiêm ngặt:
1. **Lớp thực thi duy nhất**: Toàn bộ thao tác chạy lệnh đều đi qua `tools/terminal.py` sử dụng `subprocess.run(shell=False)`.
2. **Whitelist lệnh (ALLOWED_COMMANDS)**: Chỉ cho phép các binary:
   - `git`, `docker`, `pytest`, `npm`, `mvn`, `python`.
   - Bất kỳ lệnh nào ngoài danh sách sẽ bị từ chối với lỗi `SecurityViolationError`.
3. **Chặn Shell Operators**: Từ chối tuyệt đối các toán tử `&&`, `||`, `;`, `|`, `>`, `<`, `$(`, `` ` ``.
4. **Chặn mẫu nguy hiểm**: Tự động phát hiện và chặn `rm -rf`, `git push --force/-f`, `docker system prune`, `DROP`, `curl|sh`, `sudo`.
5. **Giới hạn không gian làm việc**: Chỉ cho phép `cwd` nằm trong `WORKSPACE_DIR`, ngăn chặn `..` và symlink thoát ra ngoài.
6. **Che giấu Secret**: Tự động che các giá trị nhạy cảm có tên chứa `KEY`, `TOKEN`, `SECRET`, `PASSWORD` thành `***REDACTED***`.
7. **Chặn môi trường Production**: Lệnh deploy lên `prod` luôn bị chặn và trả về `BLOCKED` + `PERMISSION_DENIED` để con người phê duyệt.
8. **Mặc định An toàn (DRY_RUN=true)**: Terminal chỉ in ra lệnh dự kiến chạy mà không thực thi thật.

---

## 2. Cách bật chế độ chạy thật an toàn

Để kích hoạt thực thi lệnh thật, bắt buộc phải thỏa mãn **cả 2 điều kiện**:
1. Đặt `DRY_RUN=false` trong file `.env`.
2. Trong yêu cầu `TaskRequest`, trường `context.execute` phải được gán giá trị `true`:
   ```json
   {
     "action": "run_tests",
     "context": {
       "execute": true
     }
   }
   ```
Nếu thiếu một trong hai điều kiện trên, hệ thống sẽ tự động chỉ chạy ở chế độ **DRY-RUN**.

---

## 3. Danh sách 7 Action hỗ trợ

| Action | Capability tương ứng | Artifact đầu ra | Next Actions gợi ý |
|---|---|---|---|
| `git_operation` | `git` | Không | Không |
| `build_image` | `docker` | Không | `run_tests`, `deploy` |
| `generate_ci_config` | `ci_cd` | `ci.yml` / `Dockerfile` (`DEPLOYMENT`) | `build_image` |
| `run_tests` | `ci_cd` | Không | `deploy` |
| `deploy` | `deployment` | `deployment-report.md` (`DEPLOYMENT`) | `health_check` |
| `health_check` | `health_check` | Không | `setup_monitoring` |
| `setup_monitoring` | `monitoring` | `prometheus.yml` (`DEPLOYMENT`) | PM (`report_status`) |

---

## 4. Hướng dẫn chạy thử nghiệm

### Chạy chuỗi Demo (Dry-Run an toàn)
```bash
python demo.py --mock
```

### Chạy qua CLI
```bash
# Xem identity
python -m cli identity

# Chạy một action cụ thể
python -m cli run examples/task_build_image.json --mock
```

### Chạy API Service
```bash
uvicorn api:app --reload --port 8002
```

### Chạy Unit Test
```bash
python -m pytest tests/ -v
```
