#!/usr/bin/env python3
"""Build the local Cognesia macOS app; optionally install it in Applications."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "macos"
IDENTIFIER = "org.cognesia.desktop"


def run(*args: str | Path) -> None:
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Install Cognesia.app in Applications")
    parser.add_argument("--destination", type=Path, help="Applications folder override")
    parser.add_argument("--port", type=int, default=8794, help="Local server port (default: 8794)")
    parser.add_argument("--research-port", type=int, default=8797, help="Local research console port (default: 8797)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not 1024 <= args.research_port <= 65535 or args.research_port == args.port:
        parser.error("research-port must be 1024–65535 and different from the viewer port")
    BUILD.mkdir(parents=True, exist_ok=True)
    bundle = BUILD / "Cognesia.app"
    contents = bundle / "Contents"
    executables = contents / "MacOS"
    resources = contents / "Resources"
    executables.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    architecture = os.uname().machine
    run("/usr/bin/swiftc", "-O", "-warnings-as-errors", "-parse-as-library", "-swift-version", "5", "-target", f"{architecture}-apple-macosx13.0",
        "-framework", "AppKit", "-framework", "WebKit", "-framework", "UniformTypeIdentifiers",
        ROOT / "macos/Sources/Cognesia.swift", ROOT / "macos/Sources/ResearchWorkspace.swift", "-o", executables / "Cognesia")
    run("/usr/bin/swift", ROOT / "macos/Tools/GenerateIcon.swift", BUILD / "artwork")
    run("/usr/bin/iconutil", "-c", "icns", BUILD / "artwork/Cognesia.iconset", "-o", resources / "Cognesia.icns")
    shutil.copy2(BUILD / "artwork/Cognesia.png", resources / "Cognesia.png")
    info = {
        "CFBundleName": "Cognesia",
        "CFBundleDisplayName": "Cognesia",
        "CFBundleExecutable": "Cognesia",
        "CFBundleIdentifier": IDENTIFIER,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
        "CFBundleVersion": "2",
        "CFBundleIconFile": "Cognesia",
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHumanReadableCopyright": "Cognesia — local experimental neuroscience workbench",
        "CognesiaProjectRoot": str(ROOT),
        "CognesiaServerPort": args.port,
        "CognesiaResearchPort": args.research_port,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    }
    with (contents / "Info.plist").open("wb") as output:
        plistlib.dump(info, output)
    (contents / "PkgInfo").write_bytes(b"APPL????")
    run("/usr/bin/plutil", "-lint", contents / "Info.plist")
    run("/usr/bin/codesign", "--force", "--sign", "-", bundle)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", bundle)
    print(f"Built: {bundle}")
    if not args.install:
        return
    applications = (args.destination or (Path("/Applications") if os.access("/Applications", os.W_OK) else Path.home() / "Applications")).expanduser().resolve()
    applications.mkdir(parents=True, exist_ok=True)
    installed = applications / "Cognesia.app"
    if installed.resolve() == bundle.resolve():
        raise RuntimeError("The installation destination must be different from the build directory")
    if installed.exists():
        plist = installed / "Contents/Info.plist"
        if not plist.is_file() or plistlib.loads(plist.read_bytes()).get("CFBundleIdentifier") != IDENTIFIER:
            raise RuntimeError(f"Refusing to replace an unrelated app at {installed}")
    # Stage on the destination volume and verify before replacing a working app.
    with tempfile.TemporaryDirectory(prefix=".cognesia-install-", dir=applications) as staging:
        staged = Path(staging) / "Cognesia.app"
        shutil.copytree(bundle, staged)
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", staged)
        backup = applications / f".Cognesia-backup-{datetime.now():%Y%m%d-%H%M%S-%f}.app"
        had_previous = installed.exists()
        if had_previous:
            installed.rename(backup)
        try:
            staged.rename(installed)
        except BaseException:
            if had_previous:
                backup.rename(installed)
            raise
        if had_previous:
            print(f"Previous app preserved: {backup}")
    launch_services = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    run(launch_services, "-f", installed)
    print(f"Installed: {installed}")


if __name__ == "__main__":
    main()
