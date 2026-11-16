import unittest


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    raise SystemExit(not result.wasSuccessful())
