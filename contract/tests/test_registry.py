from collections import Counter

from agent_contract.enums import AgentRole
from agent_contract.registry import ACTION_MAP, CAPABILITY_REGISTRY


def test_all_10_roles_in_capability_registry():
    """Kiểm tra cả 10 AgentRole đều có trong CAPABILITY_REGISTRY."""
    assert len(CAPABILITY_REGISTRY) == 10
    for role in AgentRole:
        assert role in CAPABILITY_REGISTRY
        assert len(CAPABILITY_REGISTRY[role]) > 0


def test_capabilities_are_mutually_exclusive_across_roles():
    """Kiểm tra không có capability nào bị trùng lặp giữa các role khác nhau."""
    cap_to_roles: dict[str, list[AgentRole]] = {}
    for role, caps in CAPABILITY_REGISTRY.items():
        for cap in caps:
            cap_to_roles.setdefault(cap, []).append(role)

    duplicates = {cap: roles for cap, roles in cap_to_roles.items() if len(roles) > 1}
    assert not duplicates, f"Phát hiện capability bị trùng giữa các role: {duplicates}"


def test_action_map_for_pm_and_devops():
    """Kiểm tra ACTION_MAP của PM và DevOps ánh xạ đúng tới capability của role đó."""
    # PM: 6 actions
    assert len(ACTION_MAP[AgentRole.PM]) == 6
    for action, cap in ACTION_MAP[AgentRole.PM].items():
        assert cap in CAPABILITY_REGISTRY[AgentRole.PM], (
            f"Action '{action}' của PM ánh xạ tới capability '{cap}' không có trong registry"
        )

    # DEVOPS: 7 actions
    assert len(ACTION_MAP[AgentRole.DEVOPS]) == 7
    for action, cap in ACTION_MAP[AgentRole.DEVOPS].items():
        assert cap in CAPABILITY_REGISTRY[AgentRole.DEVOPS], (
            f"Action '{action}' của DEVOPS ánh xạ tới capability '{cap}' không có trong registry"
        )


def test_other_roles_have_empty_action_maps_with_todo():
    """Kiểm tra 8 role còn lại có key trong ACTION_MAP và mang giá trị dict rỗng."""
    other_roles = [
        AgentRole.BA,
        AgentRole.SA,
        AgentRole.DBA,
        AgentRole.DEV,
        AgentRole.TESTER,
        AgentRole.SECURITY,
        AgentRole.PO,
        AgentRole.SCRUM_MASTER,
    ]
    for role in other_roles:
        assert role in ACTION_MAP
        assert ACTION_MAP[role] == {}, f"Role {role} phải có action map rỗng khi chưa được định nghĩa"
