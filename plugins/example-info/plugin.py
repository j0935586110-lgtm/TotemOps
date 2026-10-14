#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sample plugin. No network and no changes to the server."""
import json
import sys

command = sys.argv[1] if len(sys.argv) > 1 else ""
payload = json.load(sys.stdin)
if command == "about":
    print(json.dumps({"message": "TotemOps example plugin", "reads_input": True}))
elif command == "echo":
    print(json.dumps({"echo": payload.get("message", "")}))
else:
    sys.exit(2)
