"""v0.10.1 milestone 2: the demo dataset runs only on boms_demo and BOMS says when it runs on it."""
import os
import subprocess
import sys
from pathlib import Path

from app.modules.system.demo import is_demo_database

BACKEND = Path(__file__).resolve().parents[1]


def test_only_the_demo_database_names_are_accepted():
    assert is_demo_database("boms_demo") and is_demo_database("boms_demo_screens")
    for name in ("boms", "boms_dev", "boms_test", "boms_demox", "demo", "boms_demo2"):
        assert not is_demo_database(name), name


def test_demo_seed_refuses_any_other_database():
    env = {**os.environ, "BOMS_DB_NAME": os.environ.get("BOMS_DB_NAME", "boms_test")}
    r = subprocess.run([sys.executable, "-m", "app.cli", "demo-seed"], cwd=BACKEND, env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode != 0 and "refuses to run on database" in (r.stderr + r.stdout)


def test_health_says_whether_this_is_the_demo_database(anon_client):
    body = anon_client.get("/api/health").json()
    assert body["status"] == "ok" and body["demo"] is False
