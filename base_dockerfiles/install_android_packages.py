#!/usr/bin/env python3
"""Install the exact Android packages needed by the Kotlin remediation image.

The original build environment can reach dl.google.com through curl, but the Java
client used by sdkmanager cannot fetch its repository manifests there.  These
archive names and SHA-1 digests come from Google's repository2-3.xml.  Keeping
the package list here makes the build deterministic and still verifies every
download before extraction.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile


REPOSITORY = "https://dl.google.com/android/repository"

# (package path, archive, SHA-1, directory within the archive, destination)
PACKAGES = (
    (
        "platforms;android-34",
        "platform-34-ext7_r03.zip",
        "1f2e9478d6a7601425ceaa553311dc43191f103d",
        "android-34",
        "platforms/android-34",
    ),
    (
        "platforms;android-35",
        "platform-35_r02.zip",
        "0bb560a90a7a2cbd0dd8348224d518b638fe7949",
        "android-35",
        "platforms/android-35",
    ),
    (
        "platforms;android-37.0",
        "platform-37.0_r02.zip",
        "ed8ebf7f8822a4de5686d427f237d2fa30ff7410",
        "android-37.0",
        "platforms/android-37.0",
    ),
    (
        "build-tools;34.0.0",
        "build-tools_r34-linux.zip",
        "d6d58e0c6925a9e4d9a541e84cd1f405c2f9d2a9",
        "android-14",
        "build-tools/34.0.0",
    ),
    (
        "build-tools;35.0.0",
        "build-tools_r35_linux.zip",
        "2cfaa0bbb2336e9ec18ed3ecea84fa2e2af607bc",
        "android-15",
        "build-tools/35.0.0",
    ),
    (
        "ndk;28.1.13356709",
        "android-ndk-r28b-linux.zip",
        "f574d3165405bd59ffc5edaadac02689075a729f",
        "android-ndk-r28b",
        "ndk/28.1.13356709",
    ),
    (
        "cmake;3.22.1",
        "cmake-3.22.1-linux.zip",
        "fd0a48b4a758310df8c7aa51f59840ed48fe7ed8",
        "",
        "cmake/3.22.1",
    ),
)


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    """Extract a ZIP after rejecting absolute paths and parent traversal."""

    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe path in {archive.name}: {member.filename}")
        bundle.extractall(destination)


def install_package(
    sdk_root: Path,
    package: str,
    archive_name: str,
    expected_sha1: str,
    archive_root: str,
    relative_destination: str,
    temporary_root: Path,
) -> None:
    archive = temporary_root / archive_name
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "5",
            "--retry-all-errors",
            f"{REPOSITORY}/{archive_name}",
            "-o",
            str(archive),
        ],
        check=True,
    )
    actual_sha1 = sha1(archive)
    if actual_sha1 != expected_sha1:
        raise RuntimeError(
            f"checksum mismatch for {package}: expected {expected_sha1}, got {actual_sha1}"
        )

    expanded = temporary_root / f"expanded-{archive_name}"
    expanded.mkdir()
    safe_extract(archive, expanded)
    source = expanded / archive_root if archive_root else expanded
    if not source.is_dir():
        raise RuntimeError(f"missing expected archive root for {package}: {archive_root}")

    destination = sdk_root / relative_destination
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
    print(f"installed {package} at {destination}", flush=True)


def main() -> None:
    sdk_root_value = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk_root_value:
        raise RuntimeError("ANDROID_SDK_ROOT or ANDROID_HOME must be set")
    sdk_root = Path(sdk_root_value)
    if not sdk_root.is_dir():
        raise RuntimeError(f"Android SDK root does not exist: {sdk_root}")

    with tempfile.TemporaryDirectory(prefix="kotlin-android-packages-") as temporary:
        temporary_root = Path(temporary)
        for definition in PACKAGES:
            install_package(sdk_root, *definition, temporary_root)

    # API 37 is published as platforms;android-37.0.  Gradle versions differ
    # in whether compileSdk 37 resolves android-37 or android-37.0, so support
    # both names without duplicating the platform archive.
    api_37_alias = sdk_root / "platforms/android-37"
    if not api_37_alias.exists():
        api_37_alias.symlink_to("android-37.0")


if __name__ == "__main__":
    main()
