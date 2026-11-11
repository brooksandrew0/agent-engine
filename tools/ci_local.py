#!/usr/bin/env python3
"""Run a repo's checks locally. With no config: unit tests, the private-term scan, and gitleaks.

    python3 -I tools/ci_local.py                  the pre-push set
    python3 -I tools/ci_local.py --history        also scan full history (run before the repo goes public)
    python3 -I tools/ci_local.py --config FILE    run the checks listed in FILE instead
    python3 -I tools/ci_local.py --root DIR       run in DIR (default: the repo this file is in)

Checks come from --config, else ci_local.json at the root if it exists, else the built-in set.
The config is JSON, either a list of checks or {"checks": [...]}. Each check:

    {"name": "lint",                      shown in the output
     "command": ["ruff", "check", "."],   argv list, run from the root
     "requires": "ruff",                  optional: an executable; if it isn't on PATH the check is
                                          skipped (exit 2 below)
     "history_command": [...]}            optional: run instead of "command" under --history

In a command, "{python}" is replaced with this Python and "{root}" with the root directory,
anywhere inside an argument. The first line of output names the config in use: a committed
ci_local.json replaces the whole built-in set, deny-scan and gitleaks included.

Exit codes: 0 every check passed; 1 a check failed, or the config is missing or invalid; 2 nothing
failed but a check was skipped because its tool isn't installed (not a pass: for the built-in set,
the PR verifier still runs gitleaks on every PR).
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG_NAME = "ci_local.json"
PASS, FAIL, SKIP = "pass", "FAIL", "skipped"
KEYS = {"name", "command", "requires", "history_command"}


class ConfigError(Exception):
    pass


def builtin_checks():
    """This repo's own set, used when there is no config file. The deny scan is found next to this
    file, so it still runs when --root points somewhere else."""
    deny = str(HERE / "deny_scan.py")
    return [
        {"name": "tests",
         "command": ["{python}", "-I", "-m", "unittest", "discover", "-s", "tests", "-t", "."]},
        {"name": "deny-scan",
         "command": ["{python}", "-I", deny, "--repo", "{root}"],
         "history_command": ["{python}", "-I", deny, "--repo", "{root}", "--history"]},
        {"name": "gitleaks", "requires": "gitleaks",
         "command": ["gitleaks", "dir", "--redact", "--no-banner", "{root}"],
         "history_command": ["gitleaks", "git", "--redact", "--no-banner", "{root}"]},
    ]


def _argv(check, key):
    value = check.get(key)
    if (not isinstance(value, list) or not value or not all(isinstance(a, str) for a in value)
            or not value[0]):
        raise ConfigError(f"check {check.get('name')!r}: {key!r} must be a non-empty list of strings "
                          "with a program name first")
    return value


def validate(data):
    """Return the list of checks in a parsed config, or raise ConfigError."""
    if isinstance(data, dict):
        if set(data) != {"checks"}:
            raise ConfigError('the top level must be a list of checks or {"checks": [...]}')
        data = data["checks"]
    if not isinstance(data, list) or not data:
        raise ConfigError("the config lists no checks")
    names = set()
    for i, check in enumerate(data):
        if not isinstance(check, dict):
            raise ConfigError(f"check {i + 1} is not an object")
        extra = set(check) - KEYS
        if extra:
            raise ConfigError(f"check {i + 1}: unknown key(s) {', '.join(sorted(extra))}")
        name = check.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"check {i + 1}: 'name' must be a non-empty string")
        if name in names:
            raise ConfigError(f"check {name!r} is listed twice")
        names.add(name)
        _argv(check, "command")
        if "history_command" in check:
            _argv(check, "history_command")
        req = check.get("requires")
        if req is not None and (not isinstance(req, str) or not req.strip()):
            raise ConfigError(f"check {name!r}: 'requires' must be a non-empty string")
    return data


def find_config(root, config=None):
    """The config file to use: `config`, else root/ci_local.json if present, else None (built-in)."""
    if config is not None:
        return Path(config)
    default = Path(root) / CONFIG_NAME
    return default if default.is_file() else None


def load_checks(root, config=None):
    """Checks from `config`, else root/ci_local.json if present, else the built-in set."""
    config = find_config(root, config)
    if config is None:
        return builtin_checks()
    try:
        data = json.loads(Path(config).read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"can't read {config}: {e.strerror or e}")
    except ValueError as e:
        raise ConfigError(f"{config} is not valid JSON: {e}")
    return validate(data)


def expand(argv, root):
    out = []
    for a in argv:
        out.append(a.replace("{python}", sys.executable).replace("{root}", str(root)))
    return out


def run_check(check, root, history=False):
    name = check["name"]
    req = check.get("requires")
    if req and not shutil.which(req):
        print(f"== {name}: {req} not installed, skipped", flush=True)
        return SKIP
    key = "history_command" if history and "history_command" in check else "command"
    cmd = expand(check[key], root)
    print(f"== {name}: {' '.join(cmd)}", flush=True)
    try:
        code = subprocess.run(cmd, cwd=str(root)).returncode
    except OSError as e:
        print(f"== {name}: can't run {cmd[0]}: {e.strerror or e}", flush=True)
        return FAIL
    return PASS if code == 0 else FAIL


def run_checks(checks, root, history=False):
    results = {c["name"]: run_check(c, root, history) for c in checks}
    print("\n" + "  ".join(f"{name}: {result}" for name, result in results.items()))
    if FAIL in results.values():
        return 1
    if SKIP in results.values():
        return 2
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", action="store_true", help="scan every commit too")
    parser.add_argument("--config", type=Path, help=f"checks file (default: {CONFIG_NAME} at the root)")
    parser.add_argument("--root", type=Path, default=ROOT, help="directory the checks run in")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    config = find_config(root, args.config)
    print(f"== config: {config if config else 'built-in set (tests, deny-scan, gitleaks)'}", flush=True)
    try:
        checks = load_checks(root, args.config)
    except ConfigError as e:
        print(f"ci_local: {e}", file=sys.stderr)
        return 1
    return run_checks(checks, root, args.history)


if __name__ == "__main__":
    sys.exit(main())
