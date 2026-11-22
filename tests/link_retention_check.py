#!/usr/bin/env python3
"""Read-only regression test for retaining previously verified links."""
import ast
from pathlib import Path

source = Path("monitor.py").read_text(encoding="utf-8")
tree = ast.parse(source)
assert "prior_by_id" in source, "Missing prior game lookup"
assert 'old.get("date") != game.get("date")' in source, "Missing same-date safeguard"
assert "Retained previously verified" in source, "Missing retention handling"
assert 'old.get(key) == expected_url' in source
assert 'expected_url = report_url(game["id"], kind)' in source
print("PASS: official-link retention safeguards present and monitor syntax valid")
