"""Reject destructive schema changes from the automated pilot release path."""

import ast
import hashlib
import pathlib
import sys

FORBIDDEN = {
    "alter_column",
    "drop_column",
    "drop_constraint",
    "drop_index",
    "drop_table",
    "execute",
    "rename_table",
}
# These two immutable hashes form the fresh-install baseline. Their constraint
# transition runs before any pilot data exists; a changed file loses the
# exemption and is inspected like every future migration.
APPROVED_BASELINE = {
    "44b52b36cbd71b052976e3ada86fb9eeca8f27b68c46efc9c7d365d97942e5ed",
    "14c70e468a397dc959c40f6e1e02aa28c22540ff9fa5d111ac26aec8c99c7bcf",
}
violations: list[str] = []
for path in sorted(pathlib.Path("backend/migrations/versions").glob("*.py")):
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() in APPROVED_BASELINE:
        continue
    tree = ast.parse(source, filename=str(path))
    approval = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "AUTOMATED_ROLLBACK_SAFE" for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
        for node in tree.body
    )
    if not approval:
        violations.append(
            f"{path}: missing AUTOMATED_ROLLBACK_SAFE = True after expand/contract review"
        )
    upgrade = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"),
        None,
    )
    if not upgrade:
        continue
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN:
            violations.append(f"{path}:{node.lineno}: op.{node.func.attr} is not allowed in automated upgrades")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_column":
            column = node.args[1] if len(node.args) > 1 else None
            if isinstance(column, ast.Call):
                keywords = {item.arg: item.value for item in column.keywords if item.arg}
                nullable = keywords.get("nullable")
                if isinstance(nullable, ast.Constant) and nullable.value is False and "server_default" not in keywords:
                    violations.append(
                        f"{path}:{node.lineno}: required added columns need a backward-compatible server_default"
                    )

if violations:
    print("\n".join(violations), file=sys.stderr)
    print("Use a manually reviewed maintenance/restore procedure for destructive migrations.", file=sys.stderr)
    raise SystemExit(1)
