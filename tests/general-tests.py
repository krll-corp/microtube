import argparse
import json
import unittest

from support import PROJECT, compose

# Run browser checks before the backend suite seeds enough videos to paginate.
SUITES = {
    "db": ("test_database",),
    "frontend": ("test_frontend", "test_monitor"),
    "backend": ("test_auth_upload", "test_discovery", "test_video"),
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", nargs="?", choices=("all", *SUITES), default="all")
    selected = parser.parse_args().suite

    spec = json.loads(compose("config", "--format", "json", capture_output=True).stdout)
    volumes = spec["volumes"].values()
    if not all(v["name"].startswith(PROJECT + "_") and not v.get("external") for v in volumes):
        raise RuntimeError("Test volumes must belong to the test project")

    passed = False
    try:
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "120")
        if selected == "all":
            modules = [module for group in SUITES.values() for module in group]
        else:
            modules = SUITES[selected]
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        passed = result.testsRun > 0 and result.wasSuccessful()
    finally:
        if not passed:
            compose("ps", "-a", check=False)
            compose("logs", "--no-color", "--tail", "40", check=False)
        cleanup = compose("down", "--volumes", "--rmi", "local", check=False)
    raise SystemExit(not passed or cleanup.returncode != 0)
