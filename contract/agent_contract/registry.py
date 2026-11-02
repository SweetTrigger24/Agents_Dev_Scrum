from agent_contract.enums import AgentRole

CAPABILITY_REGISTRY: dict[AgentRole, list[str]] = {
    AgentRole.PM: [
        "project_planning",
        "task_decomposition",
        "task_assignment",
        "progress_tracking",
    ],
    AgentRole.BA: [
        "requirement_analysis",
        "user_story",
        "use_case",
        "acceptance_criteria",
    ],
    AgentRole.SA: [
        "system_architecture",
        "api_design",
        "technology_selection",
    ],
    AgentRole.DBA: [
        "database_design",
        "schema_design",
        "sql",
        "query_optimization",
    ],
    AgentRole.DEV: [
        "coding",
        "refactoring",
        "bug_fixing",
        "code_review",
    ],
    AgentRole.TESTER: [
        "test_planning",
        "test_case_generation",
        "automated_testing",
        "bug_reporting",
    ],
    AgentRole.DEVOPS: [
        "git",
        "docker",
        "ci_cd",
        "deployment",
        "monitoring",
        "health_check",
    ],
    AgentRole.SECURITY: [
        "security_analysis",
        "vulnerability_scan",
        "dependency_scan",
        "security_review",
    ],
    AgentRole.PO: [
        "product_vision",
        "feature_prioritization",
        "backlog_management",
        "acceptance",
    ],
    AgentRole.SCRUM_MASTER: [
        "sprint_management",
        "scrum_management",
        "blocker_tracking",
        "retrospective",
    ],
}

ACTION_MAP: dict[AgentRole, dict[str, str]] = {
    AgentRole.PM: {
        "analyze_requirement": "project_planning",
        "create_plan": "project_planning",
        "decompose_tasks": "task_decomposition",
        "assign_tasks": "task_assignment",
        "track_progress": "progress_tracking",
        "report_status": "progress_tracking",
    },
    AgentRole.DEVOPS: {
        "git_operation": "git",
        "build_image": "docker",
        "generate_ci_config": "ci_cd",
        "run_tests": "ci_cd",
        "deploy": "deployment",
        "health_check": "health_check",
        "setup_monitoring": "monitoring",
    },
    # TODO: BA - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.BA: {},
    # TODO: SA - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.SA: {},
    # TODO: DBA - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.DBA: {},
    # TODO: DEV - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.DEV: {},
    # TODO: TESTER - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.TESTER: {},
    # TODO: SECURITY - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.SECURITY: {},
    # TODO: PO - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.PO: {},
    # TODO: SCRUM_MASTER - 4 thành viên còn lại tự định nghĩa action theo mẫu bảng và gửi duyệt để gộp vào registry
    AgentRole.SCRUM_MASTER: {},
}
