#!/usr/bin/env python3
"""LEVIX PWA installability checker — run before/after deploy."""

from __future__ import annotations

import json
import struct
import sys
import urllib.error
import urllib.request

BASE = "https://levixapp.in"
UA = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


def fetch(url: str) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.status, dict(res.headers), res.read()


def png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def check_manifest() -> list[str]:
    errors: list[str] = []
    status, headers, body = fetch(f"{BASE}/manifest.webmanifest")
    if status != 200:
        errors.append(f"manifest HTTP {status}")
        return errors
    ct = headers.get("Content-Type", "")
    if "manifest" not in ct and "json" not in ct:
        errors.append(f"manifest content-type unexpected: {ct}")
    manifest = json.loads(body.decode("utf-8"))
    for key in ("name", "short_name", "start_url", "display", "icons"):
        if key not in manifest:
            errors.append(f"manifest missing {key}")
    if manifest.get("display") not in ("standalone", "fullscreen", "minimal-ui"):
        errors.append(f"invalid display: {manifest.get('display')}")
    if manifest.get("prefer_related_applications") is True:
        errors.append("prefer_related_applications must not be true")
    icons = manifest.get("icons") or []
    sizes_found = set()
    for icon in icons:
        sizes_found.update(str(icon.get("sizes", "")).split())
    if "192x192" not in sizes_found:
        errors.append("missing 192x192 icon in manifest")
    if "512x512" not in sizes_found:
        errors.append("missing 512x512 icon in manifest")
    for icon in icons:
        src = icon.get("src", "")
        if not src:
            continue
        if "sizes" in icon and icon.get("sizes") == "any":
            errors.append("invalid icon sizes:any (breaks Android WebAPK)")
        url = src if src.startswith("http") else f"{BASE}{src}"
        try:
            istatus, _, ibody = fetch(url)
            if istatus != 200:
                errors.append(f"icon failed {url} HTTP {istatus}")
                continue
            dim = png_size(ibody)
            if not dim:
                errors.append(f"icon not PNG {url}")
                continue
            w, h = dim
            expected = icon.get("sizes", "").split()[0]
            if expected and "x" in expected:
                ew, eh = expected.split("x")
                if (w, h) != (int(ew), int(eh)):
                    errors.append(f"icon size mismatch {url}: {w}x{h} vs {expected}")
        except urllib.error.HTTPError as e:
            errors.append(f"icon HTTP error {url}: {e.code}")
    return errors


def check_sw() -> list[str]:
    errors: list[str] = []
    status, headers, body = fetch(f"{BASE}/sw.js")
    if status != 200:
        errors.append(f"sw.js HTTP {status}")
        return errors
    text = body.decode("utf-8", errors="replace")
    if "addEventListener(\"fetch\"" not in text and "addEventListener('fetch'" not in text:
        errors.append("sw.js missing fetch handler")
    if "skipWaiting" not in text:
        errors.append("sw.js missing skipWaiting")
    cc = headers.get("Cache-Control", "")
    if "no-store" not in cc and "no-cache" not in cc:
        errors.append(f"sw.js should not be long-cached: Cache-Control={cc}")
    return errors


def check_pages() -> list[str]:
    errors: list[str] = []
    pages = ["/", "/login", "/dashboard"]
    for path in pages:
        status, _, body = fetch(f"{BASE}{path}")
        if status != 200:
            errors.append(f"{path} HTTP {status}")
            continue
        html = body.decode("utf-8", errors="replace")
        if 'rel="manifest"' not in html and "rel='manifest'" not in html:
            errors.append(f"{path} missing manifest link")
        if "/sw.js" not in html:
            errors.append(f"{path} missing sw.js registration")
        if path in ("/", "/login") and "pwa-install.js" not in html:
            errors.append(f"{path} missing pwa-install.js")
        if path == "/dashboard" and "__levixSwReady" not in html and "/sw.js" not in html:
            errors.append(f"{path} missing service worker bootstrap")
    return errors


def main() -> int:
    print(f"Checking PWA installability for {BASE}\n")
    all_errors: list[str] = []
    for name, fn in (
        ("manifest", check_manifest),
        ("service worker", check_sw),
        ("pages", check_pages),
    ):
        errs = fn()
        if errs:
            print(f"[FAIL] {name}")
            for e in errs:
                print(f"  - {e}")
            all_errors.extend(errs)
        else:
            print(f"[OK] {name}")
    print()
    if all_errors:
        print(f"FAILED: {len(all_errors)} issue(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
