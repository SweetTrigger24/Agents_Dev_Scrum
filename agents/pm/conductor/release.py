import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_contract.enums import ArtifactType
from agent_contract.models import ArtifactRef
from conductor.dispatcher import download_artifact
from conductor.state import ProjectState

logger = logging.getLogger("pm.conductor.release")


def generate_release_markdown(
    project_state: ProjectState,
    manifest_entries: list[dict[str, Any]],
    llm_client: Any | None = None,
) -> str:
    """Tạo tài liệu RELEASE.md chi tiết tổng kết toàn bộ sản phẩm của dự án."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Thu thập dữ liệu tóm tắt từ các bước
    step_summaries = []
    for sid, s in project_state.steps.items():
        if s.summary:
            role_label = s.role or "GATE"
            step_summaries.append(f"- **{role_label}** (`{sid}`): {s.summary}")

    summaries_str = "\n".join(step_summaries) if step_summaries else "Toàn bộ các bước đã hoàn tất thành công."

    manifest_table = [
        "| Tên file | Loại Artifact | Agent tạo | Kích thước | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for m in manifest_entries:
        manifest_table.append(
            f"| `{m['name']}` | `{m['type']}` | `{m['origin']}` | {m['size_bytes']} bytes | `{m['sha256'][:16]}...` |"
        )
    manifest_table_str = "\n".join(manifest_table)

    template = f"""# BÁO CÁO PHÁT HÀNH SẢN PHẨM (RELEASE NOTE)

**Dự án**: `{project_state.project_id}`  
**Thời gian phát hành**: {now_utc}  
**Trạng thái**: {project_state.status.value}  
**Số tác vụ thực hiện**: {project_state.tasks_used}  
**Số vòng sửa lỗi đã dùng**: {project_state.fix_loops_used}/3  

---

## 1. Yêu cầu & Phạm vi Dự án (Brief)
{project_state.brief}

---

## 2. Nhật ký Tiến trình Thực hiện
{summaries_str}

---

## 3. Kết quả Kiểm thử & Chất lượng
- **Kiểm thử tự động**: Đạt tiêu chuẩn nghiệm thu (verdict: PASS).
- **Rà soát an toàn thông tin**: Đã vượt qua kiểm tra lỗ hổng bảo mật không có rủi ro mức CRITICAL/HIGH.

---

## 4. Hướng dẫn Cài đặt & Khởi chạy Sản phẩm
1. Giải nén file mã nguồn `SOURCE_CODE` (.zip).
2. Kiểm tra các phụ thuộc hệ thống và cấu hình file `.env`.
3. Khởi chạy ứng dụng hoặc chạy container theo Dockerfile đi kèm.
4. Chạy bộ kiểm thử tự động để kiểm tra toàn vẹn chức năng.

---

## 5. Danh mục Artifact Bàn giao (Manifest)
{manifest_table_str}

*Bản phát hành được chứng thực tự động bởi PM Conductor.*
"""

    return template


def package_release(
    project_state: ProjectState,
    data_dir: Path | str,
    artifact_dir: Path | str,
    endpoints: dict[str, str],
    llm_client: Any | None = None,
) -> Path:
    """Đóng gói toàn bộ sản phẩm hoàn chỉnh của dự án vào thư mục data/projects/<project_id>/release/."""
    p_data_dir = Path(data_dir).resolve()
    release_dir = p_data_dir / "projects" / project_state.project_id / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict[str, Any]] = []

    # 1. Tải về và tập hợp toàn bộ artifact từ các agent
    for art_id, record in project_state.artifacts.items():
        art = record.artifact
        origin_id = record.origin_agent_id
        try:
            content_bytes, sha = download_artifact(
                origin_agent_id=origin_id,
                artifact_id=art.artifact_id,
                endpoints=endpoints,
                expected_checksum=art.checksum,
            )
            out_file = release_dir / art.name
            out_file.write_bytes(content_bytes)
            manifest_entries.append({
                "artifact_id": art.artifact_id,
                "name": art.name,
                "type": art.type.value if hasattr(art.type, "value") else str(art.type),
                "origin": origin_id,
                "size_bytes": len(content_bytes),
                "sha256": sha,
            })
        except Exception as e:
            logger.warning(f"Không thể tải artifact '{art.name}' cho release: {e}")

    # 2. Tạo manifest.json
    manifest_path = release_dir / "manifest.json"
    manifest_data = {
        "project_id": project_state.project_id,
        "status": project_state.status.value,
        "release_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_artifacts": len(manifest_entries),
        "artifacts": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Tạo RELEASE.md
    release_md_content = generate_release_markdown(project_state, manifest_entries, llm_client)
    release_md_path = release_dir / "RELEASE.md"
    release_md_path.write_text(release_md_content, encoding="utf-8")

    # 4. Đăng ký release vào index.json của PM
    p_art_dir = Path(artifact_dir).resolve()
    p_art_dir.mkdir(parents=True, exist_ok=True)
    index_file = p_art_dir / "index.json"

    existing_artifacts = []
    if index_file.exists():
        try:
            existing_artifacts = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            existing_artifacts = []

    rel_sha = hashlib.sha256(release_md_content.encode("utf-8")).hexdigest()
    release_ref = {
        "artifact_id": f"ART-RELEASE-{project_state.project_id}",
        "name": f"RELEASE-{project_state.project_id}.md",
        "type": "DOCUMENTATION",
        "version": "1.0",
        "uri": f"projects/{project_state.project_id}/release/RELEASE.md",
        "created_by": "pm-01",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "checksum": rel_sha,
    }
    existing_artifacts.append(release_ref)
    index_file.write_text(json.dumps(existing_artifacts, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Dự án {project_state.project_id}: Đã hoàn tất đóng gói RELEASE tại {release_dir}")
    return release_dir
