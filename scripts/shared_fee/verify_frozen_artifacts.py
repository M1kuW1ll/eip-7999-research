"""Snapshot and verify artifacts protected from the shared-fee experiment.

The manifest records the current working-tree bytes.  This is deliberate: the
existing EIP-7999 and Glamsterdam work may contain valuable uncommitted changes,
so protection must not be defined relative to ``HEAD``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "data/shared_fee/frozen_artifact_manifest.json"

PROTECTED_PATHS = (
    "src/dynamics/glamsterdam_replay.py",
    "src/mechanisms/glamsterdam_only.py",
    "src/mechanisms/configs.py",
    "scripts/run_glamsterdam_comparison.py",
    "scripts/run_mechanism_comparison.py",
    "data/glamsterdam",
    "data/7999/glamsterdam_comparison.csv",
    "data/7999/mechanism_comparison.csv",
    "plots/dynamic_mechanism_comparison.png",
    "plots/dynamic_mechanism_frontier.png",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_files() -> list[Path]:
    files: list[Path] = []
    for relative in PROTECTED_PATHS:
        path = ROOT / relative
        if not path.exists():
            raise FileNotFoundError(f"Protected path is missing: {relative}")
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
        else:
            files.append(path)
    return sorted(set(files))


def current_records() -> dict[str, dict[str, int | str]]:
    return {
        str(path.relative_to(ROOT)): {
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in protected_files()
    }


def snapshot(manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Protect the current working-tree EIP-7999 and Glamsterdam artifacts "
            "during the independent shared-fee experiment."
        ),
        "protected_roots": list(PROTECTED_PATHS),
        "files": current_records(),
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {manifest_path.relative_to(ROOT)} with {len(payload['files'])} files")


def verify(manifest_path: Path) -> None:
    expected = json.loads(manifest_path.read_text())
    current = current_records()
    expected_files = expected["files"]
    missing = sorted(set(expected_files) - set(current))
    added = sorted(set(current) - set(expected_files))
    changed = sorted(
        path
        for path in set(expected_files).intersection(current)
        if expected_files[path] != current[path]
    )
    if missing or added or changed:
        details = {
            "missing": missing,
            "added": added,
            "changed": changed,
        }
        raise SystemExit(
            "Frozen-artifact verification failed:\n" + json.dumps(details, indent=2)
        )
    print(f"Verified {len(current)} frozen files against {manifest_path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "verify"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest = args.manifest
    if not manifest.is_absolute():
        manifest = ROOT / manifest
    if args.mode == "snapshot":
        snapshot(manifest)
    else:
        verify(manifest)


if __name__ == "__main__":
    main()
