import json
import unittest
from pathlib import Path

from support import PROJECT, compose


if __name__ == "__main__":
    spec = json.loads(compose("config", "--format", "json", capture_output=True).stdout)
    volumes = spec["volumes"].values()
    if not all(v["name"].startswith(PROJECT + "_") and not v.get("external") for v in volumes):
        raise RuntimeError("Test volumes must belong to the test project")

    passed = False
    try:
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "120")
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        passed = result.testsRun > 0 and result.wasSuccessful()
    finally:
        if not passed:
            compose("ps", "-a", check=False)
            compose("logs", "--no-color", "--tail", "40", check=False)
        cleanup = compose("down", "--volumes", "--rmi", "local", check=False)
    raise SystemExit(not passed or cleanup.returncode != 0)
