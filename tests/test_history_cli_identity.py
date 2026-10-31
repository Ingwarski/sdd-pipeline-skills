"""CLI/module identity on isolated synthetic history; no provider or product data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from test_sdd_check import SCRIPT
import test_unit_history as history_fixture


HISTORY = SCRIPT.with_name("sdd_history.py")


class HistoryCLIIdentityTests(unittest.TestCase):
    def child(self, body, *arguments):
        bootstrap = "import sys; sys.path.insert(0, sys.argv.pop(1))\n"
        return subprocess.run([sys.executable, "-B", "-c", bootstrap + textwrap.dedent(body),
                               str(SCRIPT.parent), str(HISTORY), *map(str, arguments)],
                              capture_output=True, text=True)

    def assert_child_passed(self, result):
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_preloaded_same_sdk_helper_keeps_active_owner_and_dispatch(self):
        result = self.child("""
            import runpy
            from unittest import mock
            import sdd_check
            helper = sdd_check.history_api()
            checker = helper.api()
            with helper.snapshot_hash_scope() as owner:
                def entry():
                    assert sdd_check.history_api() is helper
                    assert helper._snapshot_hash_owner.get() is owner
                    assert owner.depth == 1
                    return 37
                with mock.patch.object(helper, 'main', side_effect=entry):
                    try:
                        runpy.run_path(sys.argv[1], run_name='__main__')
                    except SystemExit as error:
                        assert error.code == 37, error.code
                assert sys.modules['_sdd_unit_history'] is helper
                with mock.patch.object(helper.Path, 'resolve', side_effect=AssertionError('repeated module stat')):
                    assert helper.api() is checker
                assert helper._snapshot_hash_owner.get() is owner
            assert owner.depth == 0 and not owner.hashes
            assert helper._snapshot_hash_owner.get() is None
        """)
        self.assert_child_passed(result)

    def test_conflicting_history_aliases_are_preserved_and_blocked(self):
        for source in ("foreign-history.py", str(HISTORY)):
            with self.subTest(source=source):
                result = self.child("""
                    import contextlib, io, json, runpy, types
                    foreign = types.ModuleType('_sdd_unit_history')
                    foreign.__file__ = sys.argv[2]
                    foreign.sentinel = object()
                    sys.modules['_sdd_unit_history'] = foreign
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        try:
                            runpy.run_path(sys.argv[1], run_name='__main__')
                        except SystemExit as error:
                            assert error.code == 1, error.code
                    assert sys.modules['_sdd_unit_history'] is foreign
                    report = json.loads(output.getvalue())
                    assert report['result'] == 'blocked', report
                    assert 'conflicting history module alias' in report['detail'], report
                    assert not hasattr(foreign, '_snapshot_hash_owner')
                """, source)
                self.assert_child_passed(result)

    def test_foreign_checker_alias_is_preserved_and_blocked(self):
        result = self.child("""
            import types
            import sdd_check
            helper = sdd_check.history_api()
            original = helper.api()
            original_path = original.__file__
            original.__file__ = 'foreign-sdk/sdd_check.py'
            try:
                try:
                    helper.api()
                except ValueError as error:
                    assert 'conflicting checker module alias' in str(error), error
                else:
                    raise AssertionError('changed declared checker source accepted')
                assert sys.modules['_sdd_history_checker'] is original
            finally:
                original.__file__ = original_path
            assert helper.api() is original
            foreign = types.ModuleType('_sdd_history_checker')
            foreign.__file__ = 'foreign-sdk/sdd_check.py'
            sys.modules['_sdd_history_checker'] = foreign
            try:
                helper.api()
            except ValueError as error:
                assert 'conflicting checker module alias' in str(error), error
            else:
                raise AssertionError('foreign checker accepted')
            assert sys.modules['_sdd_history_checker'] is foreign
        """)
        self.assert_child_passed(result)

    def fixture(self):
        base = history_fixture.UnitHistoryTests('test_version_one_retains_original_acceptance_and_plan_binding_rules')
        base.setUp()
        self.addCleanup(base.doCleanups)
        helper, inventory, context, completion = base.capture_alpha()
        for path, value in (('completion', completion), ('inventory', base.inventory()),
                            ('pending', base.pending_map())):
            base.p.write('forge/cli-' + path + '.json', json.dumps(value))
        return base, base.read(completion)

    def assess(self, root, trace, mutate=False):
        # run_path runs the actual __main__ guard. A passive profiler observes
        # real checker boundaries; only the drift case changes synthetic bytes.
        return self.child("""
            import json, pathlib, runpy
            script, root, trace, mutate = sys.argv[1:]
            sys.argv = [script, '--project', root, 'assess',
                        '--completion-ref', 'forge/cli-completion.json',
                        '--inventory', 'forge/cli-inventory.json',
                        '--pending-map', 'forge/cli-pending.json']
            observed = {'boundaries': 0, 'audits': 0, 'mismatches': [], 'owners': [], 'mutated': False}
            cli = None
            owners = []
            def profile(frame, event, value):
                global cli
                if event != 'call':
                    return
                name = frame.f_code.co_name
                if name == 'main' and frame.f_code.co_filename == script:
                    cli = frame.f_globals
                if name == '_run_invocation' and cli is not None:
                    observed['boundaries'] += 1
                    helper = sys.modules['_sdd_unit_history']
                    owner = cli['_snapshot_hash_owner'].get()
                    if helper.__dict__ is not cli or helper._snapshot_hash_owner.get() is not owner:
                        observed['mismatches'].append('module or ContextVar owner differs')
                    if owner is not None:
                        owners.append(owner)
                        observed['owners'].append(id(owner))
                if name == 'audit' and frame.f_globals.get('__file__', '').endswith('sdd_check.py'):
                    observed['audits'] += 1
                    owner = frame.f_locals['self']
                    if mutate == 'True' and not observed['mutated'] and owner.depth > 1 and owner.hashes:
                        path = next(iter(owner.hashes))
                        path.write_bytes(b'changed at synthetic checker audit boundary')
                        observed['mutated'] = True
            sys.setprofile(profile)
            try:
                runpy.run_path(script, run_name='__main__')
            except SystemExit as error:
                status = error.code
            finally:
                sys.setprofile(None)
                observed['expired'] = all(owner.depth == 0 and not owner.hashes
                                          and not owner.history_results for owner in owners)
                pathlib.Path(trace).write_text(json.dumps(observed))
            sys.exit(status)
        """, root, trace, mutate)

    def test_direct_assess_shares_owner_audits_expires_and_rechecks_next_process(self):
        base, completion = self.fixture()
        originals = {path: (base.p.root / path).read_bytes()
                     for path in ('forge/sdd-manifest.json',
                                  completion['context_ref']['path'],
                                  json.loads((base.p.root / 'forge/cli-completion.json').read_text())['path'])}
        with tempfile.TemporaryDirectory(prefix='sdd-cli-identity-') as temporary:
            trace = Path(temporary) / 'trace.json'
            first = self.assess(base.p.root, trace)
            self.assert_child_passed(first)
            observed = json.loads(trace.read_text())
            self.assertGreater(observed['boundaries'], 0, observed)
            self.assertGreaterEqual(observed['audits'], observed['boundaries'], observed)
            self.assertFalse(observed['mismatches'], observed)
            self.assertTrue(observed['owners'] and observed['expired'], observed)
            applicability = base.read(json.loads(first.stdout))
            self.assertEqual('applicable', applicability['outcome'])
            for path, data in originals.items():
                self.assertEqual(data, (base.p.root / path).read_bytes(), path)
            snapshot = base.p.root / completion['files']['docs/prd.md']['path']
            snapshot.write_text('changed between independent CLI observations')
            second = self.assess(base.p.root, trace)
            self.assertEqual(1, second.returncode, second.stdout + second.stderr)
            self.assertEqual('blocked', json.loads(second.stdout)['result'])

    def test_direct_assess_checker_end_audit_still_blocks_snapshot_drift(self):
        base, _ = self.fixture()
        with tempfile.TemporaryDirectory(prefix='sdd-cli-identity-') as temporary:
            trace = Path(temporary) / 'trace.json'
            result = self.assess(base.p.root, trace, mutate=True)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual('blocked', json.loads(result.stdout)['result'])
            observed = json.loads(trace.read_text())
            self.assertTrue(observed['mutated'], observed)
            self.assertFalse(observed['mismatches'], observed)
            self.assertTrue(observed['expired'], observed)


if __name__ == '__main__':
    unittest.main()
