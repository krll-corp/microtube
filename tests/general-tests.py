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
AI_CASES = ("registration", "guest-search", "watch", "mobile", "keyboard")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", nargs="?", choices=("all", *SUITES, "frontend-ai"), default="all")
    parser.add_argument("--case", choices=AI_CASES)
    args = parser.parse_args()
    if args.case and args.suite != "frontend-ai":
        parser.error("--case is only available for frontend-ai")
    if args.suite == "frontend-ai":
        from test_frontend_ai import provider_settings

        try:
            provider_settings()
        except ValueError as error:
            parser.error(str(error))
        modules = ["test_frontend_ai"]
        if args.case:
            modules = [f"test_frontend_ai.VisualTests.test_{args.case.replace('-', '_')}"]
    elif args.suite == "all":
        modules = [module for group in SUITES.values() for module in group]
    else:
        modules = SUITES[args.suite]

    spec = json.loads(compose("config", "--format", "json", capture_output=True).stdout)
    volumes = spec["volumes"].values()
    if not all(v["name"].startswith(PROJECT + "_") and not v.get("external") for v in volumes):
        raise RuntimeError("Test volumes must belong to the test project")

    passed = False
    try:
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "120")
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        passed = result.testsRun > 0 and result.wasSuccessful()
    finally:
        if not passed:
            compose("ps", "-a", check=False)
            compose("logs", "--no-color", "--tail", "40", check=False)
        cleanup = compose("down", "--volumes", "--rmi", "local", check=False)
    raise SystemExit(not passed or cleanup.returncode != 0)
