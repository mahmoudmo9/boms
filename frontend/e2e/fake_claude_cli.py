#!/usr/bin/env python3
"""Stand-in for the Claude Code CLI in the browser check (BOMS_CLAUDE_CLI points here): answers `auth status --json`
and `auth logout` from a state file next to it, and contacts nothing."""
import json
import sys
from pathlib import Path

state = Path(__file__).with_name(".fake_claude_signed_in")
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    signed = state.exists()
    print(json.dumps({"loggedIn": signed, "authMethod": "claude.ai" if signed else None,
                      "email": "owner@example.com" if signed else None, "configDirectory": str(Path.home() / ".claude")}))
    sys.exit(0 if signed else 1)
if args[:2] == ["auth", "logout"]:
    state.unlink(missing_ok=True)
    print("Signed out")
    sys.exit(0)
sys.exit(2)
