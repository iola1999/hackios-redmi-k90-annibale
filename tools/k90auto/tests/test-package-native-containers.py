#!/usr/bin/env python3
"""Check that packaging leaves app container identity to MobileContainerManager."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = (ROOT / "tools/k90auto/package.py").read_text()
SKELETON_EXTRA = (ROOT / "hackios-xnu-userland/userland/var.skel.extra").read_text()

assert "DEFAULT_APP_ENV" not in PACKAGE
assert "APP_CONTAINER_LINES" not in PACKAGE
assert "CFFIXED_USER_HOME=/private/var/mobile/Containers" not in PACKAGE
for fragment in (
    "group.com.apple.weather",
    "group.com.apple.Maps",
    "/private/var/mobile/Library/Weather",
    "/private/var/mobile/Library/Maps",
    "/private/var/mobile/Library/Caches/GeoServices",
):
    assert fragment not in SKELETON_EXTRA, fragment
for required in (
    "/private/var/mobile/Containers/Data/Application",
    "/private/var/mobile/Containers/Shared/AppGroup",
):
    assert required in SKELETON_EXTRA, required
print("PASS: app container identity is created by the native container service")
