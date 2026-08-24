from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_openapi_schema_is_valid_yaml_with_unique_operation_ids():
    schema = yaml.safe_load(
        (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    )

    assert schema["openapi"] == "3.1.0"

    operation_ids = []

    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
            }:
                operation_ids.append(operation["operationId"])

    assert len(operation_ids) == len(set(operation_ids))
    assert "createHandCommand" in operation_ids
    assert "getHandCommandStatus" in operation_ids
    assert "execute_anything" not in str(schema)
    assert "run_tasker_command" not in str(schema)


def test_tasker_only_claim_and_result_routes_are_not_exposed_to_gpt():
    schema = yaml.safe_load(
        (PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8")
    )

    assert "/hand/commands/next" not in schema["paths"]
    assert "/hand/commands/{command_id}/result" not in schema["paths"]


def test_migration_has_required_fields_states_and_indexes():
    migration = (
        PROJECT_ROOT
        / "migrations"
        / "20260824_001_create_hand_commands.sql"
    ).read_text(encoding="utf-8")

    for field in (
        "id UUID PRIMARY KEY",
        "action TEXT",
        "parameters JSONB",
        "status TEXT",
        "created_at TIMESTAMPTZ",
        "delivered_at TIMESTAMPTZ",
        "executed_at TIMESTAMPTZ",
        "result JSONB",
        "error TEXT",
    ):
        assert field in migration

    for status in (
        "pending",
        "delivered",
        "executed",
        "failed",
        "expired",
    ):
        assert f"'{status}'" in migration

    assert "idx_hand_commands_pending" in migration

