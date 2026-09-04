#!/usr/bin/env python3
"""Apply and verify the Whick product package dependency map."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path


PRODUCT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = PRODUCT / "product-application-map.json"
HOOK_MARKER = "apply-product-map.py"
LIVE_ROOT = Path("/data")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProductMap:
    def __init__(self, map_path: Path) -> None:
        self.map_path = map_path
        self.data = json.loads(map_path.read_text())
        self.roots = {key: str(value) for key, value in self.data["roots"].items()}
        self.errors: list[str] = []
        self.changes: list[str] = []
        # 테스트 전용 빌드(예: build-test-install-usb.sh)가 실차 /data 산출물을
        # 덮어쓰지 못하게 한다. 2026-07-29 테스트 USB 빌드가 실차 릴리스 lock 3개를
        # 다시 쓴 사고 이후 도입.
        self.protect_live = os.environ.get("WHICK_PRODUCT_MAP_PROTECT_LIVE") == "1"
        self.protected: list[str] = []
        self.warnings: list[str] = []

    def expand(self, value: str, **extra: str) -> Path:
        values = {**self.roots, **extra}
        return Path(value.format(**values))

    def is_protected(self, target: Path) -> bool:
        if not self.protect_live:
            return False
        try:
            Path(os.path.abspath(target)).relative_to(LIVE_ROOT)
        except ValueError:
            return False
        return True

    def write_blocked(self, target: Path) -> bool:
        if not self.is_protected(target):
            return False
        self.protected.append(str(target))
        return True

    def fail(self, message: str) -> None:
        self.errors.append(message)

    def fail_unless_protected(self, target: Path, message: str) -> None:
        """실차 보호 모드에서 /data 산출물의 어긋남은 경고로만 남긴다.

        테스트 빌드는 실차를 고칠 권한이 없으므로 실패시키지 않는다. 실제 정합은
        실차 배포 절차(ensure-music01-release-artifacts.sh 등)에서 맞춘다.
        """
        if self.is_protected(target):
            self.warnings.append(message)
        else:
            self.fail(message)

    def apply_sources(self) -> None:
        for item in self.data.get("exact_mirrors", []):
            source = self.expand(item["source"])
            if not source.is_file():
                self.fail(f"{item['id']}: source missing: {source}")
                continue
            source_bytes = source.read_bytes()
            source_mode = source.stat().st_mode
            for raw_target in item.get("targets", []):
                target = self.expand(raw_target)
                if target.is_file() and target.read_bytes() == source_bytes:
                    continue
                if self.write_blocked(target):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.product-map.tmp")
                temporary.write_bytes(source_bytes)
                os.chmod(temporary, source_mode)
                os.replace(temporary, target)
                self.changes.append(f"mirror {item['id']}: {target}")

    def apply_release_lock(self) -> dict:
        config = self.data["release_lock"]
        source = self.expand(config["source"])
        if not source.is_file():
            self.fail(f"release lock missing: {source}")
            return {}
        try:
            lock = json.loads(source.read_text())
        except Exception as error:
            self.fail(f"invalid release lock {source}: {error}")
            return {}
        source_bytes = source.read_bytes()
        source_mode = source.stat().st_mode
        for raw_target in config.get("targets", []):
            target = self.expand(raw_target)
            if target.is_file() and target.read_bytes() == source_bytes:
                continue
            if self.write_blocked(target):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # These lock files are mounted into CC containers as individual bind
            # mounts. Preserve the inode so running containers see the new bytes.
            with target.open("wb") as handle:
                handle.write(source_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(target, source_mode)
            self.changes.append(f"release lock: {target}")
        return lock

    @staticmethod
    def artifact_contract(lock: dict, item: dict) -> tuple[str, str, int]:
        component = str(item.get("lock_component") or "").strip()
        release_component = (lock.get("components") or {}).get(component) or {}
        file_field = str(item.get("file_field") or "file").strip() or "file"
        sha_field = str(item.get("sha_field") or "sha256").strip() or "sha256"
        size_field = str(item.get("size_field") or "size_bytes").strip() or "size_bytes"
        return (
            str(release_component.get(file_field) or "").strip(),
            str(release_component.get(sha_field) or "").strip().lower(),
            int(release_component.get(size_field) or 0),
        )

    def artifact_valid(self, path: Path, expected_sha: str, expected_size: int) -> bool:
        if not path.is_file():
            return False
        if expected_size and path.stat().st_size != expected_size:
            return False
        if expected_sha and sha256(path) != expected_sha:
            return False
        return True

    def find_artifact_source(
        self,
        item: dict,
        file_name: str,
        version: str,
        expected_sha: str,
        expected_size: int,
    ) -> Path | None:
        for template in item.get("source_candidates", []):
            expanded = str(self.expand(template, file=file_name, version=version))
            for match in sorted(glob.glob(expanded)):
                candidate = Path(match)
                if self.artifact_valid(candidate, expected_sha, expected_size):
                    return candidate
        return None

    def publish_artifact(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() == target.resolve():
            return
        temporary = target.with_name(f".{target.name}.product-map.tmp")
        temporary.unlink(missing_ok=True)
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        os.replace(temporary, target)

    def apply_artifacts(self, lock: dict) -> None:
        if not lock:
            return
        version = str(lock.get("version") or "").strip()
        for item in self.data.get("artifacts", []):
            file_name, expected_sha, expected_size = self.artifact_contract(lock, item)
            if not file_name or len(expected_sha) != 64 or expected_size <= 0:
                self.fail(f"{item['id']}: incomplete artifact contract in release lock")
                continue
            targets = [
                self.expand(raw, file=file_name, version=version)
                for raw in item.get("serve_targets", [])
            ]
            if all(self.artifact_valid(p, expected_sha, expected_size) for p in targets):
                continue
            source = self.find_artifact_source(
                item, file_name, version, expected_sha, expected_size
            )
            if source is None:
                self.fail(
                    f"{item['id']}: no source matches {file_name} "
                    f"sha={expected_sha} size={expected_size}"
                )
                continue
            for target in targets:
                if self.artifact_valid(target, expected_sha, expected_size):
                    source = target
                    continue
                if self.write_blocked(target):
                    continue
                self.publish_artifact(source, target)
                if not self.artifact_valid(target, expected_sha, expected_size):
                    self.fail(f"{item['id']}: publish verification failed: {target}")
                else:
                    self.changes.append(f"artifact {item['id']}: {target}")
                    source = target

    def verify_sources(self) -> None:
        for item in self.data.get("exact_mirrors", []):
            source = self.expand(item["source"])
            if not source.is_file():
                self.fail(f"{item['id']}: source missing: {source}")
                continue
            source_sha = sha256(source)
            for raw_target in item.get("targets", []):
                target = self.expand(raw_target)
                if not target.is_file():
                    self.fail_unless_protected(target, f"{item['id']}: mirror missing: {target}")
                elif sha256(target) != source_sha:
                    self.fail_unless_protected(target, f"{item['id']}: stale mirror: {target}")

    def verify_release(self) -> None:
        config = self.data["release_lock"]
        source = self.expand(config["source"])
        if not source.is_file():
            self.fail(f"release lock missing: {source}")
            return
        source_sha = sha256(source)
        try:
            lock = json.loads(source.read_text())
        except Exception as error:
            self.fail(f"invalid release lock {source}: {error}")
            return
        for raw_target in config.get("targets", []):
            target = self.expand(raw_target)
            if not target.is_file():
                self.fail_unless_protected(target, f"release lock mirror missing: {target}")
            elif sha256(target) != source_sha:
                self.fail_unless_protected(target, f"release lock mirror stale: {target}")

        version = str(lock.get("version") or "").strip()
        for item in self.data.get("artifacts", []):
            file_name, expected_sha, expected_size = self.artifact_contract(lock, item)
            if not file_name or len(expected_sha) != 64 or expected_size <= 0:
                self.fail(f"{item['id']}: incomplete artifact contract")
                continue
            for raw_target in item.get("serve_targets", []):
                target = self.expand(raw_target, file=file_name, version=version)
                if not self.artifact_valid(target, expected_sha, expected_size):
                    self.fail_unless_protected(
                        target, f"{item['id']}: install API artifact missing/stale: {target}"
                    )

    def verify_hooks(self) -> None:
        for hook in self.data.get("pipeline_hooks", []):
            path = self.expand(hook["path"])
            if not path.is_file():
                self.fail(f"pipeline hook target missing: {path}")
                continue
            if HOOK_MARKER not in path.read_text(errors="replace"):
                self.fail(f"pipeline is not map-gated: {path}")

    def read_canonical_version(self, item: dict) -> str:
        source = self.expand(item["canonical"])
        if not source.is_file():
            self.fail(f"{item['id']}: canonical missing: {source}")
            return ""
        try:
            data = json.loads(source.read_text())
        except Exception as error:
            self.fail(f"{item['id']}: invalid canonical {source}: {error}")
            return ""
        version = str(data.get(item.get("field") or "version") or "").strip()
        if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
            self.fail(f"{item['id']}: invalid version in {source}: {version!r}")
            return ""
        return version

    def project_version_text(self, text: str, projection: dict, version: str) -> str:
        version_numeric = version[1:] if version.startswith("v") else version
        kind = projection.get("kind")
        if kind == "js_object_string":
            key = re.escape(str(projection.get("key") or "version"))
            pattern = re.compile(rf"({key}\s*:\s*')v\d+\.\d+\.\d+(')")
            updated, count = pattern.subn(rf"\1{version}\2", text, count=1)
            if count != 1:
                raise ValueError(f"js_object_string key not found: {projection.get('key')}")
            return updated
        if kind == "html_text_ids":
            updated = text
            for html_id in projection.get("ids") or []:
                pattern = re.compile(
                    rf'(id="{re.escape(html_id)}"[^>]*>)v\d+\.\d+\.\d+(</)'
                )
                updated, count = pattern.subn(rf"\g<1>{version}\g<2>", updated, count=1)
                if count != 1:
                    raise ValueError(f"html id not found: {html_id}")
            return updated
        if kind == "regex_replace":
            pattern = re.compile(str(projection["pattern"]))
            replacement = str(projection["replacement"])
            # Expand placeholders first so group refs like \g<1> stay intact.
            replacement = replacement.replace("{version_numeric}", version_numeric)
            replacement = replacement.replace("{version}", version)
            updated, count = pattern.subn(replacement, text)
            if count < 1:
                raise ValueError(f"regex_replace matched nothing: {projection['pattern']}")
            return updated
        raise ValueError(f"unknown version projection kind: {kind}")

    def version_display_items(self, version_id: str | None = None) -> list[dict]:
        items = list(self.data.get("version_displays") or [])
        if not version_id:
            return items
        selected = [item for item in items if item.get("id") == version_id]
        if not selected:
            self.fail(f"unknown version display id: {version_id}")
        return selected

    def apply_version_displays(self, version_id: str | None = None) -> None:
        for item in self.version_display_items(version_id):
            version = self.read_canonical_version(item)
            if not version:
                continue
            for projection in item.get("projections", []):
                target = self.expand(projection["path"])
                if not target.is_file():
                    self.fail(f"{item['id']}: projection missing: {target}")
                    continue
                original = target.read_text()
                try:
                    updated = self.project_version_text(original, projection, version)
                except Exception as error:
                    self.fail(f"{item['id']}: {target}: {error}")
                    continue
                if updated == original:
                    continue
                if self.write_blocked(target):
                    continue
                target.write_text(updated)
                self.changes.append(f"version {item['id']}: {target} -> {version}")

    def verify_version_displays(self, version_id: str | None = None) -> None:
        for item in self.version_display_items(version_id):
            version = self.read_canonical_version(item)
            if not version:
                continue
            version_numeric = version[1:] if version.startswith("v") else version
            for projection in item.get("projections", []):
                target = self.expand(projection["path"])
                if not target.is_file():
                    self.fail(f"{item['id']}: projection missing: {target}")
                    continue
                text = target.read_text()
                kind = projection.get("kind")
                if kind == "js_object_string":
                    key = re.escape(str(projection.get("key") or "version"))
                    if not re.search(rf"{key}\s*:\s*'{re.escape(version)}'", text):
                        self.fail_unless_protected(
                            target, f"{item['id']}: stale js version in {target}"
                        )
                elif kind == "html_text_ids":
                    for html_id in projection.get("ids") or []:
                        if not re.search(
                            rf'id="{re.escape(html_id)}"[^>]*>{re.escape(version)}<',
                            text,
                        ):
                            self.fail_unless_protected(
                                target, f"{item['id']}: stale html id {html_id} in {target}"
                            )
                elif kind == "regex_replace":
                    # After apply, the replacement value must appear; reject other patch versions nearby.
                    if "{version_numeric}" in str(projection.get("replacement") or ""):
                        if f"?v={version_numeric}" not in text and f"?v={version}" not in text:
                            self.fail_unless_protected(
                                target, f"{item['id']}: stale cache-bust version in {target}"
                            )
                    elif version not in text:
                        self.fail(f"{item['id']}: version {version} missing in {target}")
                    stale = re.findall(r"v\d+\.\d+\.\d+", text)
                    # Allow other versions in file only if this projection's pattern region is current.
                    # Soft check: ensure no obvious old portal fallback remains for this item.
                    if item["id"] == "remote-portal-ui" and any(
                        v != version for v in stale if v.startswith("v0.9.")
                    ):
                        # portal files should only carry the canonical remote-mobile version
                        bad = sorted({v for v in stale if v != version})
                        if bad:
                            self.fail(
                                f"{item['id']}: mixed versions in {target}: {', '.join(bad)}"
                            )
                else:
                    self.fail(f"{item['id']}: unknown kind {kind}")

    def explain(self, changed_path: str) -> None:
        changed = str(Path(changed_path).resolve())
        matches = []
        for item in self.data.get("exact_mirrors", []):
            source = str(self.expand(item["source"]).resolve())
            targets = [str(self.expand(p).resolve()) for p in item.get("targets", [])]
            if changed == source or changed in targets:
                matches.append(
                    {
                        "group": item["id"],
                        "canonical": source,
                        "targets": targets,
                        "reason": item.get("reason", ""),
                    }
                )
        lock = self.data.get("release_lock", {})
        lock_source = str(self.expand(lock["source"]).resolve())
        lock_targets = [str(self.expand(p).resolve()) for p in lock.get("targets", [])]
        if changed == lock_source or changed in lock_targets:
            matches.append(
                {
                    "group": "release-lock",
                    "canonical": lock_source,
                    "targets": lock_targets,
                    "reason": lock.get("reason", ""),
                }
            )
        print(json.dumps(matches, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "verify", "explain"))
    parser.add_argument("path", nargs="?", help="changed path for explain")
    parser.add_argument(
        "--scope",
        choices=("sources", "release", "versions", "all"),
        default="all",
    )
    parser.add_argument(
        "--version-id",
        default="",
        help="Apply/verify only one independent version_displays entry (e.g. remote-portal-ui)",
    )
    parser.add_argument("--map", dest="map_path", default=str(DEFAULT_MAP))
    args = parser.parse_args()

    product_map = ProductMap(Path(args.map_path))
    version_id = str(args.version_id or "").strip() or None
    if version_id and args.scope not in ("versions", "all"):
        parser.error("--version-id requires --scope versions (or all)")
    if args.action == "explain":
        if not args.path:
            parser.error("explain requires a path")
        product_map.explain(args.path)
        return 0

    if args.action == "apply":
        if args.scope in ("sources", "all"):
            product_map.apply_sources()
        if args.scope in ("release", "all"):
            lock = product_map.apply_release_lock()
            product_map.apply_artifacts(lock)
        if args.scope in ("versions", "all"):
            product_map.apply_version_displays(version_id)

    if args.scope in ("sources", "all"):
        product_map.verify_sources()
    if args.scope in ("release", "all"):
        product_map.verify_release()
    if args.scope in ("versions", "all"):
        product_map.verify_version_displays(version_id)
    if args.scope == "all" and not version_id:
        product_map.verify_hooks()

    for change in product_map.changes:
        print(f"APPLIED {change}")
    for target in product_map.protected:
        print(f"SKIP (실차 보호) {target}")
    for warning in product_map.warnings:
        print(f"WARN (실차 보호) {warning}")
    if product_map.errors:
        for error in product_map.errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    suffix = f", version-id={version_id}" if version_id else ""
    print(f"PASS product application map ({args.action}, scope={args.scope}{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
