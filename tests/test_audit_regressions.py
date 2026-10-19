"""Adversarial synthetic fixtures, not product or representative-user evidence."""

import copy
from html import escape
import json
import subprocess
import sys
import tempfile
import unittest

from test_sdd_check import Project, SCRIPT, sdd


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdd-audit-")
        self.addCleanup(self.temp.cleanup)
        self.p = Project(self.temp.name)
        self.m = self.p.manifest

    def assert_blocked(self, code, node="release"):
        report = self.p.run(node)
        self.assertEqual("blocked", report["result"], report)
        self.assertIn(code, {issue["code"] for issue in report["issues"]}, report)

    def ready(self):
        self.p.authorize()
        self.p.execute_checks()

    def test_failed_check_cannot_disappear_from_gate_index(self):
        self.ready()
        check = copy.deepcopy(self.m["verification"]["checks"][1])
        check.update(check_id="QA-05", execution_status="failed")
        self.m["verification"]["checks"].append(check)
        path = self.p.root / "docs/qa-checklist.md"
        self.p.write("docs/qa-checklist.md", path.read_text() + "QA-05 additional heuristic check\n")
        self.p.refresh()
        self.m["verification"]["source_hashes"]["docs/qa-checklist.md"] = self.p.hash("docs/qa-checklist.md")
        self.assert_blocked("unbound_check")

    def test_excluded_only_checks_cannot_satisfy_applicable_gate(self):
        self.ready()
        check = self.m["verification"]["checks"][1]
        check.update(execution_status="not_applicable", rationale="Excluded synthetic scope", evidence=[])
        self.assert_blocked("empty_applicable_gate")
        self.assert_blocked("heuristic_coverage")

    def test_duplicate_gate_check_ids_are_rejected(self):
        self.ready()
        self.m["verification"]["gates"][0]["check_ids"].append("QA-01")
        self.assert_blocked("unbound_gate")

    def test_genuinely_excluded_gate_remains_valid(self):
        self.ready()
        self.m["verification"]["gates"][2].update(applicability="not_applicable", rationale="Low-risk synthetic task")
        self.m["verification"]["checks"][2].update(execution_status="not_applicable", rationale="Low-risk synthetic task", evidence=[])
        del self.m["unit_plan"]["acceptance"]["QA-03"]
        self.m["unit_plan"]["units"]["U-1"]["required_check_ids"].remove("QA-03")
        self.p.sync_unit_contract()
        self.p.authorize()
        self.p.execute_checks()
        self.m["verification"]["checks"][2].update(execution_status="not_applicable", rationale="Low-risk synthetic task", evidence=[])
        self.assertEqual("passed", self.p.run("release")["result"])

    def freeze_shared(self):
        root = "forge/design/candidates/a/v1"
        shared = "forge/design/candidate-sets/set/v1/shared"
        self.p.write(root + "/index.html", '<link rel="stylesheet" href="../../../candidate-sets/set/v1/shared/style.css"><h1>Compare</h1>')
        self.p.write(shared + "/style.css", "h1 { color: blue; }")
        baseline = self.m["active_baseline"]
        baseline.update(hash_algorithm="sdd-render-sha256-v2", render_dependencies=[shared])
        entries = sorted([(root, sdd.tree_hash(self.p.root / root)), (shared, sdd.tree_hash(self.p.root / shared))])
        baseline["prototype_tree_hash"] = sdd.digest(json.dumps(entries, separators=(",", ":"), ensure_ascii=False).encode())
        approval = sdd.read_json(self.p.root / baseline["approval_receipt"]["path"])
        approval["prototype_tree_hash"] = baseline["prototype_tree_hash"]
        baseline["approval_receipt"] = self.p.evidence(baseline["approval_receipt"]["path"], approval)
        self.p.write("docs/design-brief.md", "## Approved Visual Baseline\n" + "\n".join(str(baseline[k]) for k in ("baseline_id", "prototype_tree_hash", "visual_target_hash")) + "\n" + baseline["approval_receipt"]["path"])
        self.p.refresh()
        return shared

    def test_shared_render_bundle_is_frozen_without_unrelated_files(self):
        shared = self.freeze_shared()
        self.assertEqual("passed", self.p.run()["result"])
        self.p.write("notes/unrelated.txt", "not a rendering dependency")
        self.assertEqual("passed", self.p.run()["result"])
        self.p.write(shared + "/style.css", "h1 { display: none; }")
        self.assert_blocked("baseline_integrity", "development-plan")

    def test_legacy_tree_cannot_hide_unbound_shared_css(self):
        self.freeze_shared()
        baseline = self.m["active_baseline"]
        baseline.update(hash_algorithm="sdd-tree-sha256-v1", render_dependencies=[])
        baseline["prototype_tree_hash"] = sdd.tree_hash(self.p.root / baseline["prototype_source_root"])
        self.assert_blocked("baseline_integrity", "development-plan")

    def test_nested_css_resource_must_be_frozen(self):
        shared = self.freeze_shared()
        self.p.write(shared + "/style.css", "@import url(https://example.invalid/mutable.css);")
        self.assert_blocked("baseline_integrity", "development-plan")

    def test_inline_srcset_data_is_already_part_of_the_frozen_file(self):
        record = self.m["active_baseline"]
        self.p.write(record["prototype_source_root"] + "/index.html", '<img srcset="data:image/png;base64,YQ== 1x">')
        observed = sdd.Checker(self.p.root, self.m).render_hash(record)
        self.assertEqual(sdd.tree_hash(self.p.root / record["prototype_source_root"]), observed)

    def test_unloaded_node_helpers_are_hashed_not_browser_dependencies(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        checker = sdd.Checker(self.p.root, self.m)
        for extension in ("js", "mjs"):
            with self.subTest(extension=extension):
                path = root + "/validate." + extension
                self.p.write(path, 'import { createHash } from "node:crypto";\n')
                try:
                    before = checker.render_hash(record)
                except ValueError as error:
                    self.fail("Unloaded Node helper was treated as browser code: " + str(error))
                self.assertEqual(sdd.tree_hash(self.p.root / root), before)
                self.p.write(path, 'import { readFileSync } from "node:fs";\n')
                after = checker.render_hash(record)
                self.assertNotEqual(before, after)
                self.assertEqual(sdd.tree_hash(self.p.root / root), after)

    def test_browser_loaded_node_helper_is_not_exempt_by_name(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        self.p.write(root + "/index.html", '<script type="module" src="./validate.mjs"></script>')
        self.p.write(root + "/validate.mjs", 'import { createHash } from "node:crypto";')
        with self.assertRaisesRegex(ValueError, "mutable render dependency.*node:crypto"):
            sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_browser_module_dependency_chain_still_rejects_unbound_resources(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        self.p.write(root + "/index.html", '<script type="module" src="./app.js"></script>')
        self.p.write(root + "/app.js", 'import "./nested.mjs";')
        for dependency in ("https://example.invalid/remote.js", "./missing.js", "node:fs"):
            with self.subTest(dependency=dependency):
                self.p.write(root + "/nested.mjs", 'import "' + dependency + '";')
                with self.assertRaises(ValueError):
                    sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_browser_module_cycle_is_validated_once(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        self.p.write(root + "/index.html", '<script src="./app.js"></script>')
        self.p.write(root + "/app.js", 'import "./nested.mjs";')
        self.p.write(root + "/nested.mjs", 'import "./app.js";')
        self.assertEqual(sdd.tree_hash(self.p.root / root), sdd.Checker(self.p.root, self.m).render_hash(record))

    def test_javascript_url_constructor_is_not_a_css_resource(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        script = 'const url = new URL(window.location.href);'
        for inline in (False, True):
            with self.subTest(inline=inline):
                self.p.write(root + "/app.js", script)
                self.p.write(root + "/index.html", '<script>' + script + '</script>' if inline else '<script src="./app.js"></script>')
                try:
                    observed = sdd.Checker(self.p.root, self.m).render_hash(record)
                except ValueError as error:
                    self.fail("Dynamic JavaScript URL was parsed as CSS: " + str(error))
                self.assertEqual(sdd.tree_hash(self.p.root / root), observed)

    def test_html_labels_attributes_comments_and_json_are_not_javascript(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        self.p.write(root + "/app.js", "document.title = 'Synthetic fixture';")
        markup = '''<button id="import">Import JSON</button><div class="from">Ready</div>
<p>from "another source"; import "./example-only.js"</p>
<!-- import "./comment-only.js"; -->
<script type="application/json">{"description": "from './data-only.js'"}</script>
<script type="application/ld+json">{"description": "new URL('./data-only.svg')"}</script>
<script type=" module ">import "./inactive-module.js";</script>
<script language="javascript ">import "./inactive-language.js";</script>
<style>.label::before { content: 'from "another label"'; }</style>
<script src="./app.js">import "./documentation-only.js";</script>'''
        for extension in ("html", "htm", "svg"):
            with self.subTest(extension=extension):
                self.p.write(root + "/index.html", "<h1>Fixture</h1>")
                self.p.write(root + "/example." + extension, markup)
                self.assertEqual(sdd.tree_hash(self.p.root / root),
                                 sdd.Checker(self.p.root, self.m).render_hash(record))

    def test_inline_javascript_types_keep_missing_and_external_resource_checks(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        attributes = ('', ' type=""', ' type="module"', ' type="MoDuLe"',
                      ' type=" text/javascript "', ' type="application/javascript"',
                      ' type="TEXT/X-JAVASCRIPT"', ' language="JavaScript1.5"')
        for attrs in attributes:
            for dependency in ("./missing.js", "https://example.invalid/mutable.js"):
                with self.subTest(attrs=attrs, dependency=dependency):
                    self.p.write(root + "/index.html", '<script' + attrs + '>import("' + dependency + '");</script>')
                    with self.assertRaises(ValueError):
                        sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_self_closing_script_cannot_hide_a_browser_executed_body(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        for dependency in ("./missing.js", "https://example.invalid/mutable.js"):
            with self.subTest(dependency=dependency):
                self.p.write(root + "/index.html", '<script/>import("' + dependency + '");</script>')
                with self.assertRaisesRegex(ValueError, "explicit </script> closing tag"):
                    sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_inline_module_from_and_url_dependencies_remain_transitive(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        self.p.write(root + "/index.html", '''<script type="module">
import { run } from "./app.mjs";
new URL("./icon.svg", import.meta.url);
</script>''')
        self.p.write(root + "/app.mjs", 'import "./nested.js"; export function run() {}')
        self.p.write(root + "/nested.js", 'export const value = 1;')
        self.p.write(root + "/icon.svg", '<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        self.assertEqual(sdd.tree_hash(self.p.root / root), sdd.Checker(self.p.root, self.m).render_hash(record))
        self.p.write(root + "/nested.js", 'import "./missing.js";')
        with self.assertRaisesRegex(ValueError, "unbound render dependency.*missing.js"):
            sdd.Checker(self.p.root, self.m).render_hash(record)
        self.p.write(root + "/nested.js", 'export const value = 1;')
        (self.p.root / root / "icon.svg").unlink()
        with self.assertRaisesRegex(ValueError, "unbound render dependency.*icon.svg"):
            sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_event_handlers_keep_static_javascript_dependencies(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        for markup in ('<button onclick="import(\'./missing.js\')">Import</button>',
                       '<button ONCLICK="import(&quot;https://example.invalid/mutable.js&quot;)">Import</button>',
                       '<svg onload="new URL(\'./missing.svg\', location.href)"></svg>'):
            with self.subTest(markup=markup):
                self.p.write(root + "/index.html", markup)
                with self.assertRaises(ValueError):
                    sdd.Checker(self.p.root, self.m).render_hash(record)
        self.p.write(root + "/handler.mjs", 'import "./missing.js";')
        self.p.write(root + "/index.html", '<button onclick="import(\'./handler.mjs\')">Import</button>')
        with self.assertRaisesRegex(ValueError, "unbound render dependency.*missing.js"):
            sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_javascript_labels_comments_strings_and_regex_are_not_dependencies(self):
        source = r'''$('#import').onclick = () => node('h2', 'Import JSON');
const text = 'import("./string-only.js")';
const escaped = "new URL(\"./quoted-only.svg\")";
// import "./line-comment.js";
/* export { item } from "./block-comment.js"; */
const pattern = /import\("regex-only.js"\)[/'"]+/gi;
const { from: label } = { from: 'A label' };
obj.import('./method-only.js'); obj?.import('./optional-method-only.js');
const data = { from: './data-only.js', import: './also-data.js' };
'''
        self.assertEqual([], sdd.javascript_references(source))
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        self.p.write(root + "/index.html", '<script>' + source + '</script>')
        self.assertEqual(sdd.tree_hash(self.p.root / root), sdd.Checker(self.p.root, self.m).render_hash(record))

    def test_javascript_literal_dependency_forms_survive_comments_and_whitespace(self):
        cases = [
            'import "./missing.js";',
            'import value from "./missing.js";',
            'import from from "./missing.js";',
            'import value, { item as renamed } from "./missing.js";',
            'import * as values from "./missing.js";',
            'export { item } /* rationale */ from "./missing.js";',
            'export * as values from "./missing.js";',
            'export * as from from "./missing.js";',
            'import /* rationale */ ("./missing.js");',
            'import("./missing.js", { with: { type: "json" } });',
            'new /* rationale */ URL("./missing.js", import.meta.url);',
        ]
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(["./missing.js"], sdd.javascript_references(source))
                self.p.write(root + "/index.html", '<script type="module">' + source + '</script>')
                with self.assertRaisesRegex(ValueError, "unbound render dependency.*missing.js"):
                    sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_template_text_is_inert_but_expressions_and_static_paths_are_inspected(self):
        cases = [
            ('const label = `import("./label-only.js")`;', []),
            ('import(`./missing.js`);', ["./missing.js"]),
            ('new URL(`./missing.svg`, import.meta.url);', ["./missing.svg"]),
            ('const label = `before ${import("./missing.js")} after`;', ["./missing.js"]),
            ('const label = `outer ${`inner ${import("./nested.js")}`}`;', ["./nested.js"]),
            ('const label = `${({ item: import("./missing.js") }).item}`;', ["./missing.js"]),
            ('const label = `${function(){} / import("./missing.js") / 2}`;', ["./missing.js"]),
            ('const label = `${class {} / import("./missing.js") / 2}`;', ["./missing.js"]),
            ('import(`./${name}.js`);', []),
            ('import("./" + name);', []),
            ('const label = `escaped \\${import("./label-only.js")}`;', []),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(expected, sdd.javascript_references(source))

    def test_division_does_not_hide_imports_and_statement_regex_is_inert(self):
        expressions = ('value', 'fn()', '({})', 'function(){}', 'class {}', 'class extends (class {}) {}', '(()=>{})',
                       'obj.return', 'obj?.await', 'obj.if()', 'obj.function()')
        for expression in expressions:
            with self.subTest(expression=expression):
                for dependency in ("./missing.js", "missing.js"):
                    self.assertEqual([dependency], sdd.javascript_references(
                        'const value = ' + expression + ' / import("' + dependency + '") / 2;'))
        for prefix in ('if (ready)', 'while (ready)', 'if (ready) {}', 'function declared() {}',
                       'async function declared() {}', 'class Declared {}'):
            with self.subTest(prefix=prefix):
                self.assertEqual([], sdd.javascript_references(prefix + ' /import("regex-only.js")/.test(text);'))

    def test_javascript_string_escapes_bind_actual_dependency_names(self):
        cases = [(r'import("./\x6dissing.js")', "./missing.js"),
                 (r'import("./\u006dissing.js")', "./missing.js"),
                 (r'import("./\u{6d}issing.js")', "./missing.js"),
                 (r'import("https:\/\/example.invalid\/mutable.js")', "https://example.invalid/mutable.js"),
                 ('import("./mis\\\nsing.js")', "./missing.js")]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual([expected], sdd.javascript_references(source))

    def test_incomplete_javascript_lexical_context_is_not_silently_accepted(self):
        for source in ('import("./missing.js)', '/* unfinished', 'const p = /unfinished',
                       'const label = `unfinished ${import("./missing.js")'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    sdd.javascript_references(source)

    def test_contextual_identifier_slash_ambiguity_fails_closed(self):
        for name in ("of", "await", "yield"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "ambiguous JavaScript slash.*parenthesize"):
                    sdd.javascript_references('const ' + name + '=2; const value=' + name + '/import("missing.js")/2;')
                self.assertEqual(["missing.js"], sdd.javascript_references(
                    'const ' + name + '=2; const value=(' + name + ')/import("missing.js")/2;'))
        self.assertEqual([], sdd.javascript_references('await (/import("regex-only.js")/);'))

    def test_javascript_navigation_urls_keep_dependencies_without_following_links(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        for markup in ('<a href="javascript:import(\'./missing.js\')">Import</a>',
                       '<a href="  JaVaScRiPt:import(\'https://example.invalid/mutable.js\')">Import</a>',
                       '<a href="java&#10;script:import(\'./missing.js\')">Import</a>',
                       '<svg><a xlink:href="javascript:import(\'./missing.js\')">Import</a></svg>',
                       '<form action="javascript:import(\'./missing.js\')"></form>'):
            with self.subTest(markup=markup):
                self.p.write(root + "/index.html", markup)
                with self.assertRaises(ValueError):
                    sdd.Checker(self.p.root, self.m).render_hash(record)
        self.p.write(root + "/index.html", '<a href="https://example.invalid/navigation">Go</a>')
        self.assertEqual(sdd.tree_hash(self.p.root / root), sdd.Checker(self.p.root, self.m).render_hash(record))

    def test_srcdoc_keeps_nested_executable_dependencies_without_scanning_data(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        for dependency in ("./missing.js", "https://example.invalid/mutable.js"):
            embedded = '<script>import("' + dependency + '");</script>'
            for depth in (1, 3):
                with self.subTest(dependency=dependency, depth=depth):
                    markup = embedded
                    for _ in range(depth):
                        markup = '<iframe srcdoc="' + escape(markup, quote=True) + '"></iframe>'
                    self.p.write(root + "/index.html", markup)
                    with self.assertRaises(ValueError):
                        sdd.Checker(self.p.root, self.m).render_hash(record)
        self.p.write(root + "/nested.mjs", 'export const value = 1;')
        markup = '''<button id="import">Import</button><p>from "another source"</p>
<script type="application/json">{"description": "import './not-code.js'"}</script>
<script type="module">import "./nested.mjs";</script>'''
        self.p.write(root + "/index.html", '<iframe srcdoc="' + escape(markup, quote=True) + '"></iframe>')
        self.assertEqual(sdd.tree_hash(self.p.root / root), sdd.Checker(self.p.root, self.m).render_hash(record))

    def test_inline_css_resources_still_require_frozen_inputs(self):
        record = self.m["active_baseline"]
        root = record["prototype_source_root"]
        for markup in ('<style>@import "https://example.invalid/remote.css";</style>',
                       '<div style="background: url(https://example.invalid/image.png)"></div>',
                       '<style>h1 { background: url(./missing.png); }</style>',
                       '<svg><rect fill="url(./missing.svg#gradient)" /></svg>'):
            with self.subTest(markup=markup):
                self.p.write(root + "/index.html", markup)
                with self.assertRaises(ValueError):
                    sdd.Checker(self.p.root, self.m).render_hash(record)

    def test_render_hash_cli_matches_shared_bundle(self):
        self.freeze_shared()
        record = self.m["active_baseline"]
        self.p.write("forge/render-record.json", json.dumps(record))
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--hash-render", "forge/render-record.json"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(record["prototype_tree_hash"], result.stdout.strip())

    def test_render_root_must_be_a_directory(self):
        record = copy.deepcopy(self.m["active_baseline"])
        record["prototype_source_root"] += "/index.html"
        with self.assertRaises(ValueError):
            sdd.Checker(self.p.root, self.m).render_hash(record)

    def promotion(self):
        self.ready()
        def git(*args):
            return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args], cwd=self.p.root)
        git("init", "-q")
        git("add", ".")
        git("commit", "-qm", "Synthetic base")
        base = git("rev-parse", "HEAD").decode().strip()
        self.p.write("src/promoted.html", "<h1>Adapted synthetic implementation</h1>")
        git("add", "src/promoted.html")
        git("commit", "-qm", "Synthetic promotion")
        head = git("rev-parse", "HEAD").decode().strip()
        baseline = self.m["active_baseline"]
        baseline.update(candidate_id="a", version="v1")
        mapping = {"source": "forge/design/candidates/a/v1/index.html", "destination": "src/promoted.html", "strategy": "adapt"}
        record = {"unit_id": "U-1", "base_commit": base, "started_at": "2026-08-20T10:04:00Z", "path_mappings": [mapping]}
        actual = {"schema_version": 1, "promotion_id": "P-1", "unit_id": "U-1", "run_id": "run-1",
                  "development_plan_ref": "docs/development-plan.md", "development_plan_hash": self.p.hash("docs/development-plan.md"),
                  **{key: baseline[key] for key in ("baseline_id", "visual_target_hash", "candidate_id", "version", "prototype_source_root", "prototype_tree_hash")},
                  "base_commit": base, "head_commit": head, "changed_paths": ["src/promoted.html"],
                  "patch_hash": sdd.digest(git("diff", "--binary", "--no-ext-diff", "--no-textconv", base, head, "--", "src/promoted.html")),
                  "path_mappings": [{**mapping, "source_hash": self.p.hash(mapping["source"]), "destination_hash": self.p.hash(mapping["destination"])}],
                  "adaptations": ["Synthetic adaptation"], "variances": [], "qa_ids": ["QA-01"],
                  "visual_evidence": [x for x in self.m["verification"]["checks"][0]["evidence"] if x["kind"] == "visual"],
                  "verification_status": "passed", "completed_at": "2026-08-20T10:06:00Z"}
        record["receipt"] = self.p.evidence("forge/runs/U-1/run-1/prototype-promotion.json", actual)
        self.m["prototype_promotions"] = [record]
        return record, actual, git

    def test_promotion_requires_git_and_destination_provenance(self):
        record, actual, _ = self.promotion()
        for key in ("head_commit", "patch_hash", "completed_at", "visual_evidence", "qa_ids"):
            with self.subTest(key=key):
                incomplete = copy.deepcopy(actual)
                del incomplete[key]
                record["receipt"] = self.p.evidence(record["receipt"]["path"], incomplete)
                self.assert_blocked("promotion_receipt")

    def test_promotion_validates_actual_destination_bytes_and_scoped_diff(self):
        _, _, git = self.promotion()
        self.assertEqual("passed", self.p.run("release")["result"])
        self.p.write("unrelated.txt", "Unrelated later change")
        git("add", "unrelated.txt")
        git("commit", "-qm", "Unrelated work")
        self.assertEqual("passed", self.p.run("release")["result"])
        self.p.write("src/promoted.html", "Drift after verified promotion")
        self.assert_blocked("promotion_receipt")

    def test_promotion_patch_cannot_be_invented(self):
        record, actual, _ = self.promotion()
        actual["patch_hash"] = "0" * 64
        record["receipt"] = self.p.evidence(record["receipt"]["path"], actual)
        self.assert_blocked("promotion_receipt")

    def test_promotion_unit_must_exist_in_the_plan(self):
        record, actual, _ = self.promotion()
        record["unit_id"] = actual["unit_id"] = "U-MISSING"
        record["receipt"] = self.p.evidence(record["receipt"]["path"], actual)
        self.assert_blocked("promotion_receipt")

    def headless(self):
        scope = {"profile": "headless", "capabilities": {"ui": False, "api": True, "persistence": True, "payments": False, "sensitive_data": True}}
        self.p.write("docs/product-idea.md", (self.p.root / "docs/product-idea.md").read_text() + "\n## Scope\n```json\n" + json.dumps(scope) + "\n```\n")
        # The same required function still has a real, nonvisual check.
        self.m["verification"]["checks"][0]["gate_id"] = "functional_delivery"
        self.m["verification"]["gates"][0]["check_ids"] = []
        self.m["verification"]["gates"].append({"gate_id": "functional_delivery", "active": True, "required": True,
            "applicability": "applicable", "check_ids": ["QA-01"], "definition_ref": {"path": "docs/dod-evals.md", "heading": "## Gates"}})
        self.p.write("docs/dod-evals.md", (self.p.root / "docs/dod-evals.md").read_text() + "\nfunctional_delivery\n")
        self.p.refresh()
        self.m["verification"]["source_hashes"]["docs/dod-evals.md"] = self.p.hash("docs/dod-evals.md")
        self.m["product_scope"] = {**scope, "definition_ref": {"path": "docs/product-idea.md", "heading": "## Scope"}}
        ui_artifacts = {"screen-map", "wireframes", "design-brief"}
        for key in ui_artifacts:
            del self.m["artifacts"][key]
            (self.p.root / ("docs/" + key + ".md")).unlink()
        for artifact in self.m["artifacts"].values():
            artifact["dependencies"] = [key for key in artifact["dependencies"] if key not in ui_artifacts]
            for key in ui_artifacts:
                artifact["source_hashes"].pop("docs/" + key + ".md", None)
                artifact["source_usage"].pop("docs/" + key + ".md", None)
            if "traceability" in artifact:
                artifact["traceability"]["links"] = [link for link in artifact["traceability"]["links"] if link["to"] != "STATE-01"]
        self.m.pop("active_baseline")
        self.m["approved_baseline_id"] = None
        for gate in self.m["verification"]["gates"]:
            if gate["gate_id"] in sdd.GATE_KINDS:
                gate.update(applicability="not_applicable", rationale="Source-bound headless scope")
        for check in self.m["verification"]["checks"]:
            if check["gate_id"] in sdd.GATE_KINDS:
                check.update(execution_status="not_applicable", rationale="Source-bound headless scope")
        eligible = {x["check_id"] for x in self.m["verification"]["checks"] if x["execution_status"] != "not_applicable"}
        self.m["unit_plan"]["acceptance"] = {key: {**value, "obligation_ids": [x for x in value["obligation_ids"] if x != "STATE-01"]}
            for key, value in self.m["unit_plan"]["acceptance"].items() if key in eligible}
        self.m["unit_plan"]["units"]["U-1"]["required_check_ids"] = sorted(eligible)
        self.p.sync_unit_contract()

    def test_headless_plan_has_no_fabricated_ui_documents_or_approval(self):
        self.headless()
        report = self.p.run(after=True)
        self.assertEqual("passed", report["result"], report)
        self.assertNotIn("design-brief", report["checked_artifacts"])
        self.assert_blocked("implementation_not_authorized", "implementation")

    def test_headless_scope_must_match_canonical_product_idea(self):
        self.headless()
        self.m["product_scope"]["capabilities"]["api"] = False
        self.assert_blocked("product_scope", "development-plan")

    def test_ui_profile_cannot_disable_baseline_with_excluded_checks(self):
        self.m.pop("active_baseline")
        self.m["approved_baseline_id"] = None
        self.assert_blocked("missing_baseline", "development-plan")

    def test_dangling_use_case_is_rejected_after_fresh_document_hashes(self):
        path = self.p.root / "docs/prd.md"
        self.p.write("docs/prd.md", path.read_text().replace("UC-01", "Removed use case"))
        self.p.refresh()
        self.assert_blocked("trace_definition", "development-plan")

    def test_required_clause_needs_a_real_qa_mapping(self):
        trace = self.m["artifacts"]["qa-checklist"]["traceability"]
        trace["links"] = [link for link in trace["links"] if link["to"] != "FR-01"]
        self.assert_blocked("trace_coverage", "development-plan")

    def test_plan_units_cannot_omit_required_clause(self):
        trace = self.m["artifacts"]["development-plan"]["traceability"]
        trace["links"] = [link for link in trace["links"] if link["to"] != "FR-01"]
        self.assert_blocked("trace_coverage", "implementation")

    def test_excluded_checks_cannot_cover_a_required_clause(self):
        for check in self.m["verification"]["checks"]:
            check.update(execution_status="not_applicable", rationale="Synthetic exclusion")
        self.assert_blocked("trace_coverage", "development-plan")

    def test_verification_cannot_reference_an_unknown_job(self):
        self.m["verification"]["checks"][0]["job_ids"] = ["JOB-MISSING"]
        self.assert_blocked("trace_link", "development-plan")

    def test_headless_implementation_requires_explicit_null_baseline(self):
        self.headless()
        self.p.authorize()
        gate = self.m["implementation_gate"]
        gate["approved_baseline_id"] = None
        scope = self.m["product_scope"]
        gate["product_scope_hash"] = sdd.digest(json.dumps({key: scope[key] for key in ("profile", "capabilities")}, sort_keys=True, separators=(",", ":")).encode())
        receipt = sdd.read_json(self.p.root / gate["prompt_receipt"]["path"])
        receipt["approved_baseline_id"] = None
        receipt["product_scope_hash"] = gate["product_scope_hash"]
        gate["prompt_receipt"] = self.p.evidence(gate["prompt_receipt"]["path"], receipt)
        report = self.p.run("implementation")
        self.assertEqual("passed", report["result"], report)
        gate["product_scope_hash"] = "0" * 64
        self.assert_blocked("prompt_receipt", "implementation")
        gate["product_scope_hash"] = receipt["product_scope_hash"]
        del gate["approved_baseline_id"]
        self.assert_blocked("prompt_receipt", "implementation")

    def test_project_root_is_not_a_frozen_source_path(self):
        with self.assertRaises(ValueError):
            sdd.Checker(self.p.root, self.m).path(".", no_links=True)

    def test_stale_parallel_owner_return_is_rejected(self):
        self.m["dispatches"] = {"architecture": {"invocation_id": "new-run", "outputs": ["docs/architecture.md"]}}
        self.assert_blocked("stale_owner_return", "development-plan")

    def test_explicit_in_app_review_surface_is_supported(self):
        self.p.candidates()
        self.m["design_execution"]["review_surface"] = "in_app"
        for candidate in self.m["prototype_candidates"]:
            reference = candidate["browser_receipt"]
            receipt = sdd.read_json(self.p.root / reference["path"])
            receipt["browser_kind"] = "in_app"
            candidate["browser_receipt"] = self.p.evidence(reference["path"], receipt)
        self.assertEqual("passed", self.p.run("design-approval")["result"])

    def test_metadata_snapshot_never_manufactures_validation(self):
        self.p.save()
        before = (self.p.root / "forge/sdd-manifest.json").read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(self.p.root), "--snapshot", "architecture"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual("unvalidated", record["status"])
        self.assertEqual(self.p.hash("docs/prd.md"), record["source_hashes"]["docs/prd.md"])
        self.assertEqual(before, (self.p.root / "forge/sdd-manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
