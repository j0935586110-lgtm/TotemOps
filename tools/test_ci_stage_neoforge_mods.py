# SPDX-License-Identifier: Apache-2.0
"""Offline regression tests for the exact CI download failure seen 2026-10-15."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ci_stage_neoforge_mods as ci


BLOB = b"neoforge-minecraft-synthetic-jar-fixture"
SPEC = {
    "mod": "fixture",
    "filename": "sample-neoforge-1.21.1.jar",
    "version_id": "sample",
    "size": len(BLOB),
    "sha256": hashlib.sha256(BLOB).hexdigest(),
    "sha512": hashlib.sha512(BLOB).hexdigest(),
}


def metadata(*, hashes=None, host="cdn.modrinth.com"):
    return {
        "id": "sample",
        "files": [{
            "filename": SPEC["filename"],
            "size": SPEC["size"],
            "hashes": SPEC["sha512"] if hashes is None else hashes,
            "url": "https://" + host + "/data/sample.jar",
        }],
    }


class CiModrinthDigestTests(unittest.TestCase):
    def fetch(self, data, blob=BLOB):
        def fake_request(url):
            if "/v2/version/" in url:
                return io.BytesIO(json.dumps(data).encode())
            return io.BytesIO(blob)
        return fake_request

    def test_actual_modrinth_metadata_sha512_without_sha256_is_supported(self):
        meta = metadata(hashes={"sha1": "not_relevant", "sha512": SPEC["sha512"]})
        with tempfile.TemporaryDirectory() as td:
            with patch.object(ci, "request", side_effect=self.fetch(meta)):
                ci.stage_one(SPEC, Path(td))
            self.assertEqual((Path(td) / SPEC["filename"]).read_bytes(), BLOB)

    def test_corrupt_download_fails_closed_and_removes_partial(self):
        meta = metadata(hashes={"sha512": SPEC["sha512"]})
        with tempfile.TemporaryDirectory() as td:
            with patch.object(ci, "request", side_effect=self.fetch(meta, BLOB[:-1] + b"Z")):
                with self.assertRaisesRegex(ValueError, "checksum/size mismatch"):
                    ci.stage_one(SPEC, Path(td))
            self.assertFalse((Path(td) / SPEC["filename"]).exists())
            self.assertFalse((Path(td) / (SPEC["filename"] + ".partial")).exists())

    def test_missing_sha512_from_official_metadata_is_not_trusted(self):
        meta = metadata(hashes={"sha1": "only-sha1"})
        with tempfile.TemporaryDirectory() as td:
            with patch.object(ci, "request", side_effect=self.fetch(meta)):
                with self.assertRaisesRegex(ValueError, "metadata differs"):
                    ci.stage_one(SPEC, Path(td))

    def test_unexpected_cdn_domain_is_rejected(self):
        meta = metadata(hashes={"sha512": SPEC["sha512"]}, host="example.com")
        with tempfile.TemporaryDirectory() as td:
            with patch.object(ci, "request", side_effect=self.fetch(meta)):
                with self.assertRaisesRegex(ValueError, "Unexpected download host"):
                    ci.stage_one(SPEC, Path(td))


if __name__ == "__main__":
    unittest.main()
