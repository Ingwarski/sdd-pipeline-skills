"""Native no-replace publication over isolated files, without relaxed readers."""
from concurrent.futures import ThreadPoolExecutor
import errno
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from test_sdd_check import sdd
from evidence.io import hash_file


def _competing_native_writer(staged, target, ready, start, results):
    """Spawnable worker; no shared Python lock can arbitrate these writers."""
    try:
        helper = sdd.history_api()
        ready.put(staged)
        if not start.wait(10):
            raise RuntimeError("publication start barrier timed out")
        try:
            helper._rename_noreplace(Path(staged), Path(target))
        except FileExistsError:
            results.put((staged, "existing"))
        else:
            results.put((staged, "published"))
    except BaseException as error:
        results.put((staged, type(error).__name__ + ": " + str(error)))


class ImmutablePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdd-immutable-publication-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.h = sdd.history_api()
        self.logical = "forge/unit-history/publication/record.json"
        self.data = b'{"event":"synthetic_publication","version":1}\n'

    @staticmethod
    def signature(path):
        info = path.stat()
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)

    def assert_no_pending_aliases(self):
        self.assertEqual([], list(self.root.rglob("*.pending-*")))

    def test_real_native_no_replace_keeps_existing_winner(self):
        reference = self.h.publish_immutable(self.root, self.logical, self.data)
        target = self.root / self.logical
        before = self.signature(target)
        self.assertEqual(reference, self.h.publish_immutable(self.root, self.logical, self.data))
        with self.assertRaisesRegex(ValueError, "immutable publication differs"):
            self.h.publish_immutable(self.root, self.logical, b"different bytes")
        self.assertEqual(reference, self.h.publish_immutable(
            self.root, self.logical, b"different candidate", existing_winner=True))
        contender = target.with_name("contender.json")
        contender.write_bytes(b"must not replace the winner")
        with self.assertRaises(FileExistsError):
            self.h._rename_noreplace(contender, target)
        self.assertEqual(b"must not replace the winner", contender.read_bytes())
        self.assertEqual(self.data, target.read_bytes())
        self.assertEqual(before, self.signature(target))
        self.assertEqual(1, target.stat().st_nlink)
        self.assert_no_pending_aliases()

    def test_readers_see_stable_bytes_before_publisher_returns(self):
        published, release = threading.Event(), threading.Event()
        native = self.h._rename_noreplace

        def paused(staged, target):
            native(staged, target)
            published.set()
            if not release.wait(10):
                raise RuntimeError("publication reader barrier timed out")

        with mock.patch.object(self.h, "_rename_noreplace", side_effect=paused):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.h.publish_immutable, self.root, self.logical, self.data)
                try:
                    self.assertTrue(published.wait(10), "native publication boundary was not reached")
                    target = self.root / self.logical
                    before = self.signature(target)
                    self.assertEqual(1, target.stat().st_nlink, "published target still has a temporary hardlink alias")
                    self.assert_no_pending_aliases()
                    # These are the unchanged ordinary stable-byte readers.
                    self.assertEqual((self.h.sha(self.data), len(self.data)), hash_file(target))
                    reference = {"path": self.logical, "content_hash": self.h.sha(self.data)}
                    self.assertEqual({"event": "synthetic_publication", "version": 1},
                                     self.h.read_ref(self.root, reference))
                finally:
                    release.set()
                self.assertEqual(reference, future.result(timeout=10))
        self.assertEqual(before, self.signature(target), "publisher changed visible target metadata after publication")
        self.assert_no_pending_aliases()

    def test_independent_processes_choose_one_immutable_winner(self):
        context = multiprocessing.get_context("spawn")
        ready, results = context.Queue(), context.Queue()
        start = context.Event()
        target = self.root / "winner.json"
        sources = [self.root / "candidate-a.json", self.root / "candidate-b.json"]
        contents = {str(path): ("candidate-" + str(index)).encode() for index, path in enumerate(sources)}
        for path in sources:
            path.write_bytes(contents[str(path)])
        processes = [context.Process(target=_competing_native_writer,
                     args=(str(path), str(target), ready, start, results), name="sdd-publication-" + str(index))
                     for index, path in enumerate(sources)]
        try:
            for process in processes:
                process.start()
            self.assertEqual({str(path) for path in sources}, {ready.get(timeout=10), ready.get(timeout=10)})
            start.set()
            outcomes = dict([results.get(timeout=10), results.get(timeout=10)])
            for process in processes:
                process.join(timeout=10)
                self.assertFalse(process.is_alive(), "publication worker did not exit")
                self.assertEqual(0, process.exitcode)
            self.assertEqual(["existing", "published"], sorted(outcomes.values()), outcomes)
            winner = next(path for path, outcome in outcomes.items() if outcome == "published")
            loser = next(path for path, outcome in outcomes.items() if outcome == "existing")
            self.assertEqual(contents[winner], target.read_bytes())
            self.assertFalse(Path(winner).exists())
            self.assertEqual(contents[loser], Path(loser).read_bytes())
            self.assertEqual(1, target.stat().st_nlink)
        finally:
            start.set()
            for process in processes:
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=10)
            for queue in (ready, results):
                queue.close()
                queue.join_thread()

    def test_interruption_before_or_after_publication_retries_cleanly(self):
        native = self.h._rename_noreplace
        for after in (False, True):
            with self.subTest(after_publication=after):
                logical = "forge/unit-history/interrupted-" + str(after) + "/record.json"
                def interrupted(staged, target):
                    if after:
                        native(staged, target)
                    raise RuntimeError("synthetic publication interruption")
                with mock.patch.object(self.h, "_rename_noreplace", side_effect=interrupted):
                    with self.assertRaisesRegex(RuntimeError, "publication interruption"):
                        self.h.publish_immutable(self.root, logical, self.data)
                target = self.root / logical
                self.assertEqual(after, target.exists())
                self.assert_no_pending_aliases()
                reference = self.h.publish_immutable(self.root, logical, self.data)
                self.assertEqual(self.h.sha(self.data), reference["content_hash"])
                self.assertEqual(self.data, target.read_bytes())
                self.assertEqual(1, target.stat().st_nlink)
                self.assert_no_pending_aliases()

    def test_corrupt_or_link_target_is_never_replaced(self):
        self.h.publish_immutable(self.root, self.logical, self.data)
        target = self.root / self.logical
        target.write_bytes(b"corrupt existing record")
        with self.assertRaisesRegex(ValueError, "immutable publication differs"):
            self.h.publish_immutable(self.root, self.logical, self.data)
        self.assertEqual(b"corrupt existing record", target.read_bytes())
        protected = self.root / "protected.json"
        protected.write_bytes(self.data)
        linked = target.with_name("linked.json")
        try:
            linked.symlink_to(protected)
        except OSError:
            if os.name == "nt":
                self.skipTest("host does not permit creating the symlink rejection fixture")
            raise
        with self.assertRaisesRegex(ValueError, "cannot follow links"):
            self.h.publish_immutable(self.root, linked.relative_to(self.root).as_posix(), self.data)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(self.data, protected.read_bytes())
        self.assert_no_pending_aliases()

    def test_unsupported_native_publication_has_no_unsafe_fallback(self):
        failure = OSError(errno.ENOTSUP, "synthetic unsupported exclusive rename")
        with mock.patch.object(self.h, "_rename_noreplace", side_effect=failure), \
                mock.patch.object(self.h.os, "link", side_effect=AssertionError("hardlink fallback is forbidden")), \
                mock.patch.object(self.h.os, "rename", side_effect=AssertionError("ordinary rename fallback is forbidden")):
            with self.assertRaises(OSError) as caught:
                self.h.publish_immutable(self.root, self.logical, self.data)
        self.assertEqual(errno.ENOTSUP, caught.exception.errno)
        self.assertFalse((self.root / self.logical).exists())
        self.assert_no_pending_aliases()
        reference = self.h.publish_immutable(self.root, self.logical, self.data)
        self.assertEqual(self.h.sha(self.data), reference["content_hash"])


if __name__ == "__main__":
    unittest.main()
