#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stage pinned Modrinth jars for a disposable NeoForge 1.21.1 CLIENT smoke test.

Uses only public official Modrinth metadata/CDN. This is a CI helper, not a
Minecraft installer, a general-purpose downloader or a substitute for gameplay
acceptance. SHA-256 and file size are mandatory; fail closed on any mismatch.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request


MODS = (
    {
        "mod": "waystones",
        "version_id": "6Z6MQ6os",
        "filename": "waystones-neoforge-1.21.1-21.1.46.jar",
        "sha256": "ca76a4457160e8353b1f013a21ab377b264141f466d84ec8952a123058b8af78",
        "size": 1223229,
    },
    {
        "mod": "balm",
        "version_id": "CquiaiDj",
        "filename": "balm-neoforge-1.21.1-21.0.66.jar",
        "sha256": "6be660e1f6d169553bf44f66d4f78bb9e96a1d66ce108d9608819e3ce6bfba34",
        "size": 783793,
    },
)


def request(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "TotemOps-ci-client-smoke/1.0"}),
        timeout=35,
    )


def stage_one(spec: dict, dest_dir: Path):
    meta_url = "https://api.modrinth.com/v2/version/" + spec["version_id"]
    with request(meta_url) as response:
        metadata = json.load(response)
    if metadata.get("id") != spec["version_id"]:
        raise ValueError("Modrinth version identity mismatch")
    matches = [
        row for row in metadata.get("files", [])
        if row.get("filename") == spec["filename"]
        and row.get("hashes", {}).get("sha256") == spec["sha256"]
        and row.get("size") == spec["size"]
    ]
    if len(matches) != 1:
        raise ValueError("Expected official jar not found or metadata differs: " + spec["mod"])
    url = matches[0]["url"]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cdn.modrinth.com":
        raise ValueError("Unexpected download host for " + spec["mod"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    outfile = dest_dir / spec["filename"]
    tempfile = dest_dir / (spec["filename"] + ".partial")
    h = hashlib.sha256()
    size = 0
    try:
        with request(url) as source, tempfile.open("wb") as output:
            while chunk := source.read(1 << 16):
                size += len(chunk)
                if size > spec["size"]:
                    raise ValueError("File exceeds pinned size: " + spec["mod"])
                h.update(chunk)
                output.write(chunk)
        if size != spec["size"] or h.hexdigest() != spec["sha256"]:
            raise ValueError("Downloaded jar checksum/size mismatch: " + spec["mod"])
        tempfile.replace(outfile)
        print(json.dumps({"mod": spec["mod"], "file": str(outfile), "size": size,
                          "sha256": h.hexdigest(), "verification": "PINNED_SHA256_PASS"}))
    finally:
        tempfile.unlink(missing_ok=True)


def main():
    dest = Path("run/mods")
    for mod in MODS:
        stage_one(mod, dest)


if __name__ == "__main__":
    main()
