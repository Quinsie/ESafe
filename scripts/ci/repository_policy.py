#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable

MAX_GIT_BLOB_BYTES = 100 * 1024 * 1024
MAX_SECRET_SCAN_BYTES = 2 * 1024 * 1024
ALLOWED_MARKDOWN = {"README.md"}
ALLOWED_WORKFLOWS = {".github/workflows/trusted-required-gates.yml"}
PROTECTED_CI_PATHS = {
    ".github/workflows/trusted-required-gates.yml",
    "scripts/ci/repository_policy.py",
    "scripts/ci/test_repository_policy.py",
}
FORBIDDEN_ROOTS = {"artifacts", "backups", "data", "docs", "secrets", "storage"}
CONVENTIONAL_SUBJECT = re.compile(
    r"^(?:feat|fix|perf|refactor|test|docs|build|ci|chore|revert)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?!?: .+"
)
SENSITIVE_NAME = re.compile(
    r"(?i)(?:api[_-]?key|client[_-]?secret|private[_-]?key|password|passwd|"
    r"secret|access[_-]?token|refresh[_-]?token|auth[_-]?token)"
)
ASSIGNMENT = re.compile(
    r"""(?ix)
    ^\s*(?:export\s+|--env\s+)?
    ["']?([a-z][a-z0-9_.-]{2,})["']?
    \s*(?::|=)\s*
    ["']?([^"'#,\s]+)
    """
)
KNOWN_SECRET = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
SAFE_VALUE = re.compile(
    r"""(?ix)^(
    |none|null|true|false
    |change_me(?:_[a-z0-9_-]+)?
    |replace_me(?:_[a-z0-9_-]+)?
    |example|placeholder|redacted|masked
    |test(?:ing)?(?:[_-].*)?
    |dev(?:elopment)?(?:[_-].*)?
    |\$\{[^}]+\}
    |\{\{[^}]+\}\}
    |<[^>]+>
    |\*+
    )$"""
)
AI_ENDPOINTS = {"/embeddings", "/chat/completions", "/document-digitization"}
AI_CALLS_REQUIRING_ATTESTATION = {
    "complete_json",
    "digitize_document",
    "embed_passages",
    "embed_query",
}
UPSTAGE_GATE_PATH = PurePosixPath("backend/app/upstage.py")
UPSTAGE_CONFIG_PATH = PurePosixPath("backend/app/config.py")


def git(*args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ("git", *args),
        check=True,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def tracked_files() -> list[PurePosixPath]:
    return [
        PurePosixPath(value)
        for value in git("ls-files", "-z").split("\0")
        if value
    ]


def forbidden_path_reason(path: PurePosixPath) -> str | None:
    value = path.as_posix()
    if path.name == "AGENTS.md":
        return "AGENTS.md is a local control document"
    if path.parts and path.parts[0] in FORBIDDEN_ROOTS:
        return f"{path.parts[0]}/ is runtime, source-data, or local-control storage"
    if path.name.startswith(".env") and value != ".env.example":
        return "runtime environment files must not be tracked"
    if path.parts[:2] == (".github", "workflows") and value not in ALLOWED_WORKFLOWS:
        return "only the trusted base-controlled required workflow is allowed"
    if path.suffix.lower() == ".md" and value not in ALLOWED_MARKDOWN:
        return "the remote repository keeps README.md as its only independent document"
    return None


def check_repository_boundaries(paths: Iterable[PurePosixPath]) -> list[str]:
    errors = []
    for path in paths:
        reason = forbidden_path_reason(path)
        if reason:
            errors.append(f"{path}: {reason}")
    return errors


def secret_findings(path: PurePosixPath, text: str) -> list[str]:
    errors: list[str] = []
    for pattern in KNOWN_SECRET:
        if pattern.search(text):
            errors.append(f"{path}: contains a recognized private credential")
            break
    assignment_scanned_suffixes = {
        ".conf",
        ".env",
        ".ini",
        ".json",
        ".properties",
        ".ps1",
        ".sh",
        ".toml",
        ".yaml",
        ".yml",
    }
    if (
        (path.suffix.lower() not in assignment_scanned_suffixes and not path.name.startswith(".env"))
        or "test" in path.name.lower()
        or "tests" in path.parts
    ):
        return errors
    for line_number, line in enumerate(text.splitlines(), 1):
        for name, value in ASSIGNMENT.findall(line):
            if not SENSITIVE_NAME.search(name):
                continue
            normalized = value.strip().rstrip(")]};")
            if SAFE_VALUE.fullmatch(normalized):
                continue
            if (
                normalized.startswith(("os.getenv(", "getenv(", "SecretStr(", "Field("))
                or normalized.endswith((".get_secret_value(",))
                or "$" in normalized
            ):
                continue
            errors.append(
                f"{path}:{line_number}: possible committed value for sensitive field {name}"
            )
    return errors


def check_current_tree_secrets(paths: Iterable[PurePosixPath]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        local_path = Path(path.as_posix())
        try:
            payload = local_path.read_bytes()
        except OSError as error:
            errors.append(f"{path}: cannot read tracked file: {error}")
            continue
        if len(payload) > MAX_SECRET_SCAN_BYTES or b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        errors.extend(secret_findings(path, text))
    return errors


def check_history_blob_sizes() -> list[str]:
    objects = git("rev-list", "--objects", "--all")
    if not objects.strip():
        return []
    inspected = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize) %(rest)",
        input_text=objects,
    )
    errors = []
    for line in inspected.splitlines():
        fields = line.split(" ", 3)
        if len(fields) < 3 or fields[1] != "blob":
            continue
        size = int(fields[2])
        if size <= MAX_GIT_BLOB_BYTES:
            continue
        label = fields[3] if len(fields) == 4 and fields[3] else fields[0]
        errors.append(f"{label}: Git history blob is {size} bytes (>100 MiB)")
    return errors


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def function_has_privacy_guard(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    arguments = {
        argument.arg
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    }
    if "privacy_verified" not in arguments:
        return False
    return any(
        isinstance(child, ast.Constant)
        and child.value == "UPSTAGE_PRIVACY_NOT_VERIFIED"
        for child in ast.walk(node)
    )


class ExternalAiVisitor(ast.NodeVisitor):
    def __init__(self, path: PurePosixPath) -> None:
        self.path = path
        self.functions: list[ast.AsyncFunctionDef | ast.FunctionDef] = []
        self.errors: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)
        self.functions.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append(node)
        self.generic_visit(node)
        self.functions.pop()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr == "upstage_base_url"
            and self.path not in {UPSTAGE_GATE_PATH, UPSTAGE_CONFIG_PATH}
        ):
            self.errors.append(
                f"{self.path}:{node.lineno}: Upstage credentials and transport are restricted "
                "to backend/app/upstage.py"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name in AI_CALLS_REQUIRING_ATTESTATION:
                keywords = {keyword.arg for keyword in node.keywords}
                if "privacy_verified" not in keywords:
                    self.errors.append(
                        f"{self.path}:{node.lineno}: {method_name} requires an explicit "
                        "privacy_verified attestation"
                    )
            endpoint = literal_string(node.args[0]) if node.args else None
            if method_name == "post" and endpoint in AI_ENDPOINTS:
                if self.path != UPSTAGE_GATE_PATH:
                    self.errors.append(
                        f"{self.path}:{node.lineno}: direct Upstage endpoint call bypasses "
                        "the central privacy and cost gate"
                    )
                elif not self.functions or not function_has_privacy_guard(self.functions[-1]):
                    self.errors.append(
                        f"{self.path}:{node.lineno}: outbound Upstage method lacks a "
                        "fail-closed privacy guard"
                    )
        self.generic_visit(node)


def check_external_ai_source(path: PurePosixPath, text: str) -> list[str]:
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(text, filename=path.as_posix())
    except SyntaxError as error:
        return [f"{path}:{error.lineno}: Python syntax cannot be inspected"]
    visitor = ExternalAiVisitor(path)
    visitor.visit(tree)
    return visitor.errors


def check_external_ai_policy(paths: Iterable[PurePosixPath]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        local_path = Path(path.as_posix())
        try:
            text = local_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"{path}: cannot inspect Python source: {error}")
            continue
        errors.extend(check_external_ai_source(path, text))
    return errors


def assignment_value(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        target_name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            target_name = target.id if isinstance(target, ast.Name) else None
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target_name = node.target.id if isinstance(node.target, ast.Name) else None
            value = node.value
        if target_name == name and value is not None:
            return ast.literal_eval(value)
    raise ValueError(f"{name} not found")


def check_migration_graph() -> list[str]:
    migration_root = Path("backend/alembic/versions")
    revisions: dict[str, tuple[str, ...]] = {}
    errors: list[str] = []
    for path in sorted(migration_root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = assignment_value(tree, "revision")
            down_revision = assignment_value(tree, "down_revision")
        except (OSError, SyntaxError, ValueError) as error:
            errors.append(f"{path}: invalid migration metadata: {error}")
            continue
        if not isinstance(revision, str) or not revision:
            errors.append(f"{path}: revision must be a non-empty string")
            continue
        if revision in revisions:
            errors.append(f"{path}: duplicate revision {revision}")
            continue
        if down_revision is None:
            parents: tuple[str, ...] = ()
        elif isinstance(down_revision, str):
            parents = (down_revision,)
        elif isinstance(down_revision, tuple) and all(
            isinstance(parent, str) for parent in down_revision
        ):
            parents = down_revision
        else:
            errors.append(f"{path}: unsupported down_revision {down_revision!r}")
            continue
        revisions[revision] = parents
    if errors:
        return errors
    referenced = {parent for parents in revisions.values() for parent in parents}
    missing = sorted(referenced - revisions.keys())
    if missing:
        errors.append(f"migration graph references missing revisions: {', '.join(missing)}")
    heads = sorted(revisions.keys() - referenced)
    if len(heads) != 1:
        errors.append(f"migration graph must have one head, found {heads}")
    return errors


def check_diff_and_commits(base_sha: str, pr_title: str) -> list[str]:
    errors: list[str] = []
    if pr_title and not CONVENTIONAL_SUBJECT.fullmatch(pr_title):
        errors.append(f"PR title is not Conventional Commits compatible: {pr_title!r}")
    if not base_sha:
        return errors
    try:
        changed_paths = set(
            git("diff", "--name-only", f"{base_sha}...HEAD").splitlines()
        )
        subprocess.run(
            ("git", "diff", "--check", f"{base_sha}...HEAD"),
            check=True,
        )
        subjects = git("log", "--format=%s", f"{base_sha}..HEAD").splitlines()
    except subprocess.CalledProcessError as error:
        errors.append(f"cannot validate PR range from {base_sha}: {error}")
        return errors
    protected_changes = sorted(changed_paths & PROTECTED_CI_PATHS)
    if protected_changes:
        errors.append(
            "protected CI policy files cannot be changed by a normal PR: "
            + ", ".join(protected_changes)
        )
    for subject in subjects:
        if subject.startswith("Merge "):
            continue
        if not CONVENTIONAL_SUBJECT.fullmatch(subject):
            errors.append(f"commit subject is not Conventional Commits compatible: {subject!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--pr-title", default="")
    arguments = parser.parse_args()
    paths = tracked_files()
    groups = (
        ("repository boundaries", check_repository_boundaries(paths)),
        ("current-tree secrets", check_current_tree_secrets(paths)),
        ("Git history blob sizes", check_history_blob_sizes()),
        ("external AI privacy", check_external_ai_policy(paths)),
        ("migration graph", check_migration_graph()),
        (
            "diff and commit conventions",
            check_diff_and_commits(arguments.base_sha, arguments.pr_title),
        ),
    )
    failure_count = 0
    for name, errors in groups:
        if not errors:
            print(f"PASS: {name}")
            continue
        print(f"FAIL: {name}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        failure_count += len(errors)
    if failure_count:
        print(f"Repository policy failed with {failure_count} finding(s).", file=sys.stderr)
        return 1
    print("All repository policies passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
