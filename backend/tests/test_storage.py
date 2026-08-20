from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from backend.app.storage import ComparisonStore


class ComparisonStoreTests(unittest.TestCase):
    def test_recreates_runtime_root_if_maintenance_removed_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "runtime"
            store = ComparisonStore(root)
            shutil.rmtree(root)

            comparison_id, session_path = store.create_session()

            self.assertTrue(root.is_dir())
            self.assertTrue(session_path.is_dir())
            self.assertEqual(session_path.name, comparison_id)


if __name__ == "__main__":
    unittest.main()
