#!/usr/bin/env python3
"""Read-only, stage-aware SDD consistency checks. Python 3.12+, standard library."""

import argparse
import copy
import hashlib
import importlib.util
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from datetime import datetime
from urllib.parse import unquote, urlsplit

# Resource-local imports also work when a host loads this script through importlib.
sys.dont_write_bytecode = True  # A validation-only CLI must not generate resource caches.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence.io import hash_file, read_json as safe_read_json
from evidence.resolver import EvidenceResolver, evidence_reference, _regular
from evidence.policy import validate_policy
from acceptance_revalidation import validate_revalidation
from construction import validate_architecture_construction, validate_construction
from observation_receipts import validate_observation_receipt
from progress import implementation_progress, validate_intake_progress, validate_ready_projection, workflow_progress


CONTRACT = Path(__file__).resolve().parent.parent / "references/pipeline-contract.json"
ASVS_CATALOG = Path(__file__).resolve().parents[2] / "to-sdd-prd/references/owasp/ASVS-5.0.0.json"
ASVS_CATALOG_SHA256 = "bcdbec214d70abcfad9284a31d4f9e5134305831d628aad3aa85d7e26626cb35"
SECURITY_GATE = "product_security_requirements"
SECURITY_OWNERS = {"architecture", "dod-evals", "qa-checklist", "development-plan"}
HASH_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
UNIT_ID_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)-([0-9]+)")
EXECUTION_STATES = {"not_run", "passed", "failed", "blocked", "deferred", "not_applicable"}
GATE_KINDS = {
    "approved_visual_baseline_fidelity": "visual",
    "heuristic_usability_review": "heuristic",
    "representative_user_task_validation": "representative_user",
}
VISUAL_GATE = "approved_visual_baseline_fidelity"


def history_api():
    """Load the sibling helper for direct CLI and spec_from_file_location callers."""
    name = "_sdd_unit_history"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("sdd_history.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    path = Path(path)
    return safe_read_json(path.parent.resolve() / path.name, 64 * 1024 * 1024)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hash_matches(recorded, observed):
    match = HASH_RE.fullmatch(recorded) if isinstance(recorded, str) else None
    return bool(match and match.group(1).lower() == observed)


def toolchain_identity(skills_root=None):
    """Content-address the installed sources, including uncommitted edits; no Git needed."""
    root = Path(skills_root).resolve() if skills_root is not None else Path(__file__).resolve().parents[2]
    contract = read_json(root / "to-sdd-pipeline/references/pipeline-contract.json")
    names = {"to-sdd-pipeline"} | {item["owner_skill"] for item in contract["artifacts"].values()}
    entries = []
    for name in sorted(names):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("invalid skill owner in toolchain identity")
        skill = root / name
        if not (skill / "SKILL.md").is_file():
            raise ValueError("skill sources unavailable for toolchain identity: " + name)
        for path in sorted(skill.rglob("*")):
            relative = path.relative_to(root)
            if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo") or path.name == ".DS_Store":
                continue
            if path.is_file():
                entries.append((relative.as_posix(), hash_file(path)[0]))
    entries.sort(key=lambda entry: entry[0].encode("utf-8"))
    return {"algorithm": "sdd-toolchain-sha256-v1",
            "checker_sha256": hash_file(root / "to-sdd-pipeline/scripts/sdd_check.py")[0],
            "skillset_sha256": digest("".join(path + "\n" + value + "\n" for path, value in entries).encode("utf-8")),
            "source_file_count": len(entries)}


def is_link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def tree_hash(root, hasher=None, stable_directories=None):
    """sdd-tree-sha256-v1: byte-sorted POSIX paths; every regular file, no exclusions."""
    root = Path(root)
    if is_link(root):
        raise ValueError("prototype root must be a frozen real directory")
    root = root.resolve()
    if not root.is_dir() or is_link(root):
        raise ValueError("prototype root must be a frozen real directory")
    entries, directories = [], {}
    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        directory_path = Path(directory)
        info = directory_path.lstat()
        if not stat.S_ISDIR(info.st_mode) or is_link(directory_path):
            raise ValueError("prototype directory changed into a link/special file")
        directories[directory_path] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        for name in dirs + files:
            path = Path(directory) / name
            if is_link(path):
                raise ValueError("freeze link/reparse target as regular files: " + str(path))
        for name in files:
            path = Path(directory) / name
            if not path.is_file():
                raise ValueError("not a regular prototype file: " + str(path))
            relative = path.relative_to(root).as_posix()
            if "\n" in relative or "\r" in relative:
                raise ValueError("newline in prototype path")
            entries.append((relative, hasher(path) if hasher else hash_file(path)[0]))
    for path, expected in directories.items():
        info = path.lstat()
        if is_link(path) or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != expected:
            raise ValueError("prototype directory changed while hashing")
        if stable_directories is not None:
            if path in stable_directories and stable_directories[path] != expected:
                raise ValueError("prototype directory changed during checker invocation")
            stable_directories[path] = expected
    if not entries:
        raise ValueError("empty prototype source tree")
    entries.sort(key=lambda item: item[0].encode("utf-8"))
    return digest("".join(path + "\n" + value + "\n" for path, value in entries).encode("utf-8"))


class RenderReferences(HTMLParser):
    """Static render resources, not navigation links. Never execute source content."""
    # HTML classic script types (including legacy MIME aliases), plus modules.
    javascript_types = {
        "application/ecmascript", "application/javascript", "application/x-ecmascript",
        "application/x-javascript", "text/ecmascript", "text/javascript",
        "text/javascript1.0", "text/javascript1.1", "text/javascript1.2",
        "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
        "text/jscript", "text/livescript", "text/x-ecmascript", "text/x-javascript",
    }

    def __init__(self):
        super().__init__()
        self.urls = []
        self.styles = []
        self.scripts = []
        self.documents = []
        self.in_style = False
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "style":
            self.in_style = True
        if tag == "script":
            script_type = (attrs.get("type") or "text/javascript") if "type" in attrs else (
                "text/" + attrs["language"] if attrs.get("language") else "text/javascript")
            script_type = script_type.lower()
            self.in_script = "src" not in attrs and (
                script_type in self.javascript_types or script_type == "module" or
                "type" in attrs and script_type.strip(" \t\r\n\f") in self.javascript_types)
        # Event attributes are executable JavaScript; other attributes and page
        # text (including script data blocks) must not become module references.
        self.scripts.extend(value for name, value in attrs.items() if value and name.startswith("on"))
        for name in ("href", "xlink:href", "action", "formaction"):
            value = attrs.get(name, "") or ""
            value = value.replace("\t", "").replace("\r", "").replace("\n", "")
            javascript = re.match(r"^[\x00-\x20]*javascript:", value, re.I)
            if javascript:
                self.scripts.append(value[javascript.end():])
        if tag == "iframe" and attrs.get("srcdoc"):
            self.documents.append(attrs["srcdoc"])
        # CSS occurs in style attributes/elements and SVG presentation attributes,
        # not in JavaScript's unrelated URL(...) constructor.
        self.styles.extend(value for name, value in attrs.items() if value and name in (
            "style", "fill", "stroke", "filter", "clip-path", "mask", "cursor",
            "marker", "marker-start", "marker-mid", "marker-end"))
        if tag == "base":
            raise ValueError("freeze without a base URL override")
        for name in ("src", "poster") + (("data",) if tag == "object" else ()):
            if attrs.get(name):
                self.urls.append(attrs[name])
        if tag in ("link", "use", "image"):
            self.urls.extend(attrs[name] for name in ("href", "xlink:href") if attrs.get(name))
        if attrs.get("srcset"):
            # URL tokens can contain commas (notably inline data). Descriptors
            # follow whitespace; a trailing comma separates URL-only candidates.
            remaining = attrs["srcset"].lstrip(" ,\t\r\n")
            while remaining:
                match = re.match(r"\S+", remaining)
                url = match[0]
                self.urls.append(url.rstrip(","))
                remaining = remaining[len(url):]
                if not url.endswith(","):
                    remaining = remaining.partition(",")[2]
                remaining = remaining.lstrip(" ,\t\r\n")

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)
        if self.in_script:
            self.scripts.append(data)

    def handle_startendtag(self, tag, attrs):
        # HTML browsers ignore a script's self-closing flag, unlike this parser
        # and XML/SVG. Require an unambiguous boundary rather than miss its body.
        if tag == "script":
            raise ValueError("freeze script elements with an explicit </script> closing tag")
        super().handle_startendtag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "script":
            self.in_script = False


def javascript_tokens(source):
    """Bounded static contexts, not a JS parser; ambiguous slash goals require parentheses."""
    length = len(source)
    unary = {"return", "throw", "case", "delete", "void", "typeof", "new", "yield", "await", "in", "instanceof", "of"}
    controls = {"if", "while", "for", "with", "switch", "catch"}

    def quoted(index, quote):
        value = []
        index += 1
        while index < length:
            char = source[index]
            if char == quote:
                return "".join(value), index + 1
            if quote == "`" and source.startswith("${", index):
                return "".join(value), index
            if char in "\r\n" and quote != "`":
                raise ValueError("unterminated JavaScript string in frozen render source")
            if char != "\\":
                value.append(char)
                index += 1
                continue
            index += 1
            if index >= length:
                break
            escaped = source[index]
            index += 1
            if escaped in "\r\n":
                if escaped == "\r" and index < length and source[index] == "\n":
                    index += 1
                continue
            if escaped in ("x", "u"):
                size = 2 if escaped == "x" else 4
                if escaped == "u" and index < length and source[index] == "{":
                    end = source.find("}", index + 1)
                    digits = source[index + 1:end] if end >= 0 else ""
                    index = end + 1
                else:
                    digits = source[index:index + size]
                    index += size
                    if len(digits) != size:
                        digits = ""
                if not re.fullmatch(r"[0-9a-fA-F]{1,6}", digits) or int(digits, 16) > 0x10ffff:
                    raise ValueError("invalid JavaScript string escape in frozen render source")
                value.append(chr(int(digits, 16)))
            elif escaped in "01234567":
                digits = escaped
                while len(digits) < (3 if escaped < "4" else 2) and index < length and source[index] in "01234567":
                    digits += source[index]
                    index += 1
                value.append(chr(int(digits, 8)))
            else:
                value.append({"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}.get(escaped, escaped))
        raise ValueError("unterminated JavaScript string/template in frozen render source")

    def scan(index, template_expression=False, depth=0):
        if depth > 100:
            raise ValueError("JavaScript template nesting exceeds static render inspection limit")
        tokens, stack = [], []
        operand, statement = True, not template_expression
        pending_function = None
        pending_classes = []
        closed = None
        while index < length:
            char = source[index]
            if char.isspace():
                index += 1
                continue
            if source.startswith("//", index) or (index == 0 and source.startswith("#!", index)):
                newline = re.search(r"[\r\n\u2028\u2029]", source[index:])
                index = index + newline.end() if newline else length
                continue
            if source.startswith("/*", index):
                end = source.find("*/", index + 2)
                if end < 0:
                    raise ValueError("unterminated JavaScript comment in frozen render source")
                index = end + 2
                continue
            if char == "}" and template_expression and not stack:
                return tokens, index + 1
            previous = tokens[-1][1] if tokens else None
            # These contextual words can also be ordinary bindings in classic
            # scripts. Guessing regex here could swallow an executable import.
            if char == "/" and tokens and tokens[-1][0] == "id" and previous in ("of", "await", "yield"):
                raise ValueError("ambiguous JavaScript slash after " + previous +
                                 "; parenthesize the operand for static render dependency inspection")
            if char in "\"'`":
                value, following = quoted(index, char)
                if char == "`" and source.startswith("${", following):
                    tokens.append(("dynamic", None))
                    while source.startswith("${", following):
                        expression, following = scan(following + 2, True, depth + 1)
                        tokens.extend([("punct", "("), *expression, ("punct", ")")])
                        # Resume the same template after its expression's closing brace.
                        _, following = quoted(following - 1, "`")
                    index = following
                else:
                    tokens.append(("template" if char == "`" else "string", value))
                    index = following
                operand, statement, closed = False, False, None
                continue
            if char == "/" and operand:
                index += 1
                in_class = False
                while index < length:
                    current = source[index]
                    if current in "\r\n\u2028\u2029":
                        raise ValueError("unterminated JavaScript regular expression in frozen render source")
                    if current == "\\":
                        index += 2
                        continue
                    if current == "[":
                        in_class = True
                    elif current == "]":
                        in_class = False
                    elif current == "/" and not in_class:
                        index += 1
                        while index < length and (source[index].isalnum() or source[index] in "_$"):
                            index += 1
                        break
                    index += 1
                else:
                    raise ValueError("unterminated JavaScript regular expression in frozen render source")
                tokens.append(("regex", None))
                operand, statement, closed = False, False, None
                continue
            if char.isalpha() or char in "_$":
                end = index + 1
                while end < length and (source[end].isalnum() or source[end] in "_$"):
                    end += 1
                value = source[index:end]
                property_name = previous in (".", "?.")
                if value == "function" and not property_name:
                    pending_function = (len(stack), "function_decl" if statement else "function_expr")
                elif value == "class" and not property_name:
                    pending_classes.append((len(stack), "class_decl" if statement else "class_expr"))
                tokens.append(("property" if property_name else "id", value))
                operand = not property_name and (value in unary or value in ("else", "do"))
                statement = not property_name and (value in ("else", "do", "export", "default") or value == "async" and statement)
                index, closed = end, None
                continue
            if char.isdigit():
                end = index + 1
                while end < length and (source[end].isalnum() or source[end] in "._"):
                    end += 1
                tokens.append(("number", source[index:end]))
                index, operand, statement, closed = end, False, False, None
                continue
            punctuation = next((item for item in ("=>", "?.", "++", "--", "**", "&&", "||", "??")
                                if source.startswith(item, index)), char)
            index += len(punctuation)
            if punctuation in ("(", "[", "{"):
                context = "group"
                if punctuation == "(":
                    if pending_function and pending_function[0] == len(stack):
                        _, context = pending_function
                        pending_function = None
                    elif tokens and tokens[-1][0] == "id" and previous in controls:
                        context = "control"
                elif punctuation == "{":
                    if pending_classes and pending_classes[-1][0] == len(stack):
                        _, context = pending_classes.pop()
                    elif previous == "=>":
                        context = "function_expr"
                    elif previous == ")" and closed in ("function_expr", "function_decl"):
                        context = closed
                    else:
                        context = "block" if statement or previous in (")", "else", "try", "finally", "do") else "object"
                stack.append((punctuation, context))
                operand, statement = True, punctuation == "{" and context != "object"
            elif punctuation in (")", "]", "}"):
                opening = {")": "(", "]": "[", "}": "{"}[punctuation]
                if not stack or stack[-1][0] != opening:
                    raise ValueError("unbalanced JavaScript delimiters in frozen render source")
                _, context = stack.pop()
                operand = context in ("control", "block", "function_decl", "class_decl")
                statement = operand
                closed = context
            else:
                operand = punctuation not in (".", "?.") if punctuation not in ("++", "--") else operand
                statement = punctuation == ";"
            tokens.append(("punct", punctuation))
            if punctuation not in (")", "]", "}"):
                closed = None
        if template_expression:
            raise ValueError("unterminated JavaScript template expression in frozen render source")
        return tokens, index

    return scan(0)[0]


def javascript_references(source):
    """Literal import/export/new URL references; computed values still require browser discovery."""
    tokens = javascript_tokens(source)
    urls = []
    for index, (kind, value) in enumerate(tokens):
        if kind != "id" or value not in ("import", "export", "new") or (index and tokens[index - 1] in (("punct", "."), ("punct", "?."))):
            continue
        following = tokens[index + 1:]
        if value == "new" and following[:2] == [("id", "URL"), ("punct", "(")]:
            following = following[2:]
        elif value == "import" and following[:1] == [("punct", "(")]:
            following = following[1:]
        else:
            if value == "import" and following and following[0][0] == "string":
                urls.append(following[0][1])
            elif value in ("import", "export") and following and (
                    following[0] in (("punct", "{"), ("punct", "*")) or
                    value == "import" and following[0][0] == "id"):
                nesting = 0
                for offset, token in enumerate(following):
                    if token == ("punct", "{"):
                        nesting += 1
                    elif token == ("punct", "}"):
                        nesting -= 1
                    elif token == ("punct", ";") or nesting < 0:
                        break
                    elif nesting == 0 and token == ("id", "from"):
                        if offset + 1 < len(following) and following[offset + 1][0] == "string":
                            urls.append(following[offset + 1][1])
                            break
            continue
        if len(following) >= 2 and following[0][0] in ("string", "template") and following[1] in (("punct", ","), ("punct", ")")):
            urls.append(following[0][1])
    return urls


def validate_render_files(root, files):
    """Reject detectable unbound resources; runtime dependency discovery remains browser work."""
    # Documents/styles are render roots. Follow their module references rather
    # than interpreting unloaded Node tooling as browser code. Every file still
    # contributes to the frozen hash, whether or not the browser references it.
    pending = sorted((path for path in files if path.suffix.lower() in (".html", ".htm", ".css", ".svg")), reverse=True)
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        if path.suffix.lower() not in (".html", ".htm", ".css", ".js", ".mjs", ".svg"):
            continue
        text = path.read_text(encoding="utf-8-sig")
        urls = []
        styles = [text] if path.suffix.lower() == ".css" else []
        scripts = [text] if path.suffix.lower() in (".js", ".mjs") else []
        if path.suffix.lower() in (".html", ".htm", ".svg"):
            documents = [text]
            while documents:
                parser = RenderReferences()
                parser.feed(documents.pop())
                parser.close()
                urls.extend(parser.urls)
                styles.extend(parser.styles)
                scripts.extend(parser.scripts)
                documents.extend(parser.documents)
        for style in styles:
            urls.extend(re.findall(r"url\(\s*['\"]?([^'\"\s)]+)", style, re.I))
            urls.extend(re.findall(r"@import\s+['\"]([^'\"]+)", style, re.I))
        for script in scripts:
            urls.extend(javascript_references(script))
        for url in urls:
            parsed = urlsplit(url)
            if url.startswith("#") or parsed.scheme == "data":
                continue
            if parsed.scheme or parsed.netloc:
                raise ValueError("vendor mutable render dependency before freezing: " + url)
            local = unquote(parsed.path)
            target = (root / local.lstrip("/") if local.startswith("/") else path.parent / local).resolve()
            if target not in files:
                raise ValueError("unbound render dependency: " + str(path) + " -> " + url)
            if target not in visited:
                pending.append(target)


def section_bytes(path, heading):
    """Exact unique Markdown ATX heading, through the next equal/higher heading."""
    return section_from_bytes(Path(path).read_bytes(), heading)


def section_from_bytes(data, heading):
    """The same exact section rules for a verified immutable archived source."""
    if not isinstance(heading, str) or not re.match(r"^#{1,6} \S", heading):
        raise ValueError("fragment requires an exact Markdown heading, including #")
    lines = data.splitlines(keepends=True)
    headings, fence = [], None
    for index, line in enumerate(lines):
        text = line.decode("utf-8").rstrip("\r\n").lstrip("\ufeff")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            continue
        match = re.match(r"^(#{1,6})[ \t]+", text) if fence is None else None
        if match:
            headings.append((index, len(match[1]), text))
    matches = [index for index, _, text in headings if text == heading]
    if len(matches) != 1:
        raise ValueError("fragment heading must occur exactly once: " + heading)
    start = matches[0]
    level = len(heading.split(" ", 1)[0])
    end = len(lines)
    for index, depth, _ in headings:
        if index > start and depth <= level:
            end = index
            break
    return b"".join(lines[start:end])


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return parsed


def contains_id(text, value):
    return isinstance(value, str) and bool(value) and bool(
        re.search(r"(?<![\w.-])" + re.escape(value) + r"(?![\w-]|\.[\w])", text))


def read_contract():
    contract = read_json(CONTRACT)
    nodes = {key: {"required_before": list(spec["required_before"]), "outputs": [key]}
             for key, spec in contract["artifacts"].items()}
    for key, spec in contract["nodes"].items():
        owner = spec.get("owner_artifact")
        if owner and owner not in nodes:
            raise ValueError("unknown node owner artifact: " + owner)
        nodes[key] = {**(nodes[owner] if owner else {}), **spec}
    contract["nodes"] = nodes
    return contract


def validate_contract(contract):
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported pipeline contract")
    artifacts = contract["artifacts"]
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("required-before dependency cycle: " + key)
        if key not in artifacts:
            raise ValueError("unknown prerequisite: " + key)
        if key in visited:
            return
        visiting.add(key)
        for dependency in artifacts[key]["required_before"]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in artifacts:
        visit(key)
    for node in contract["nodes"].values():
        for key in node["required_before"] + node["outputs"]:
            if key not in artifacts:
                raise ValueError("unknown node artifact: " + key)


def _cached_file_hash(path, cache):
    """Hash once while retaining fresh regular-file checks on every use."""
    path = Path(path)
    signature = _regular(path)
    if path not in cache:
        cache[path] = (signature, hash_file(path)[0])
    saved, value = cache[path]
    if signature != saved or _regular(path) != saved:
        raise ValueError("input changed during checker invocation: " + str(path))
    return value


class SnapshotFileHashes:
    """Only historical snapshot hashes; scopes own their short lifetime."""
    def __init__(self):
        self.hashes = {}
        self.depth = 0
        self.history_results = []

    def history_result(self, cache, key, remember=False):
        # The semantic cache stays with its caller. Only a result validated in
        # this hash lifetime may reuse the snapshot union already registered.
        for known, keys in self.history_results:
            if known is cache:
                if remember:
                    keys[key] = (cache[key], self._result_hash(cache[key]))
                return (key in keys and key in cache and keys[key][0] is cache[key]
                        and keys[key][1] == self._result_hash(cache[key]))
        if remember:
            self.history_results.append((cache, {key: (cache[key], self._result_hash(cache[key]))}))
        return remember

    @staticmethod
    def _result_hash(value):
        return digest(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False).encode("utf-8"))

    def file_hash(self, path):
        return _cached_file_hash(path, self.hashes)

    def audit(self):
        for path, (signature, _) in self.hashes.items():
            if _regular(path) != signature:
                raise ValueError("historical snapshot changed during checker invocation: " + str(path))


class Checker:
    def __init__(self, project, manifest, contract=None, evidence_cache=None):
        self.project = Path(project).resolve()
        self.manifest = manifest
        self._source_manifest = manifest
        if evidence_cache is not None and Path(evidence_cache).resolve().is_relative_to(self.project):
            raise ValueError("prepared evidence cache must be outside the repository")
        self.evidence_resolver = EvidenceResolver(evidence_cache)
        self.hash_cache, self.json_cache, self.section_cache, self.directory_cache = {}, {}, {}, {}
        self.accounted_refs = {}
        self.accounting_reference_id = None
        self._invocation_active = False
        self.contract = copy.deepcopy(contract or read_contract())
        validate_contract(self.contract)
        scope = manifest.get("product_scope", {})
        self.ui = scope.get("capabilities", {}).get("ui") is not False
        self.skipped = set() if self.ui else set(self.contract.get("ui_only_artifacts", []))
        if self.skipped:
            for spec in list(self.contract["artifacts"].values()) + list(self.contract["nodes"].values()):
                spec["required_before"] = [key for key in spec["required_before"] if key not in self.skipped]
                if "outputs" in spec:
                    spec["outputs"] = [key for key in spec["outputs"] if key not in self.skipped]
                spec["baseline_required"] = False
        self.specs = self.contract["artifacts"]
        self.artifacts = manifest.get("artifacts", {})
        if not isinstance(self.artifacts, dict):
            raise ValueError("artifacts must be an object")
        self.issues, self.warnings = [], []
        self.checked, self.affected = set(), set()
        self.security_requirements = {}

    def issue(self, code, target, detail):
        item = {"code": code, "target": target, "detail": detail}
        if item not in self.issues:
            self.issues.append(item)
        if target in self.specs:
            self.affected.add(target)

    def product_scope(self):
        scope = self.manifest.get("product_scope")
        if scope is None:
            return  # Legacy projects retain the full UI workflow; no silent opt-out.
        try:
            profile, capabilities = scope["profile"], scope["capabilities"]
            if profile not in self.contract["profiles"] or not isinstance(capabilities, dict):
                raise ValueError("unknown product profile/capabilities")
            if "ui" not in capabilities or any(type(value) is not bool for value in capabilities.values()):
                raise ValueError("capabilities need explicit booleans including ui")
            if (profile == "headless") != (capabilities["ui"] is False):
                raise ValueError("headless profile and ui capability disagree")
            reference = scope["definition_ref"]
            text = self.reference(reference, "product-idea")
            if self.reference_path(reference) != "docs/product-idea.md":
                raise ValueError("product scope belongs to product idea")
            blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
            expected = {"profile": profile, "capabilities": capabilities}
            if len(blocks) != 1 or json.loads(blocks[0], object_pairs_hook=unique_object) != expected:
                raise ValueError("scope projection differs from the canonical scope JSON")
        except (KeyError, TypeError, ValueError) as error:
            self.issue("product_scope", "product-idea", str(error))

    def path(self, relative, no_links=False, observation=False):
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError("use a nonempty repository-relative POSIX path")
        parsed = PurePosixPath(relative)
        if not parsed.parts or parsed.is_absolute() or ".." in parsed.parts or ":" in parsed.parts[0]:
            raise ValueError("path escapes project: " + relative)
        if observation and hasattr(self, "_history_observation_overlay"):
            reference = self._history_observation_overlay.get(relative)
            destination = reference["path"] if reference else self._history_observation_snapshot_root + "/" + relative
            return history_api().physical(self.project, destination)
        if hasattr(self, "_history_overlay"):
            reference = self._history_overlay.get(relative)
            destination = reference["path"] if reference else self._history_snapshot_root + "/" + relative
            return history_api().physical(self.project, destination)
        resolved = (self.project / relative).resolve()
        if not resolved.is_relative_to(self.project):
            raise ValueError("link escapes project: " + relative)
        if no_links:
            current = self.project
            for part in parsed.parts:
                current = current / part
                if (current.exists() or current.is_symlink()) and is_link(current):
                    raise ValueError("frozen source path contains a link/reparse point: " + relative)
        return resolved

    def snapshot(self, relative, recorded, target, code="stale_source", observation=False):
        try:
            observed = self.file_hash(self.path(relative, no_links=True, observation=observation))
            if not hash_matches(recorded, observed):
                self.issue(code, target, "missing/changed hash: " + relative)
                return False
            return True
        except (ValueError, OSError) as error:
            self.issue(code, target, str(error))
            return False

    def file_hash(self, path):
        """Memoize stable regular files; any later mutation blocks this invocation."""
        path = Path(path)
        owner = getattr(self, "_history_hash_owner", None)
        if owner is not None and owner.depth and path in owner.hashes:
            return owner.file_hash(path)
        return _cached_file_hash(path, self.hash_cache)

    def history_hash_scope(self):
        return history_api().snapshot_hash_scope(getattr(self, "_history_hash_owner", None), audit=True)

    def document(self, path):
        path = Path(path)
        signature = _regular(path)
        if path not in self.json_cache:
            self.json_cache[path] = (signature, read_json(path))
        saved, value = self.json_cache[path]
        if signature != saved or _regular(path) != saved:
            raise ValueError("document changed during checker invocation: " + str(path))
        return value

    def section(self, relative, heading):
        path = self.path(relative, no_links=True)
        identity = self.file_hash(path)
        key = (path, heading)
        if key not in self.section_cache:
            self.section_cache[key] = (identity, section_bytes(path, heading))
        saved, value = self.section_cache[key]
        if saved != identity or self.file_hash(path) != identity:
            raise ValueError("source fragment changed during checker invocation")
        return value

    def evidence_snapshot(self, record, target, code="invalid_evidence", bindings=None):
        try:
            ref = evidence_reference(record)
            if ref is None:
                if not isinstance(record, dict):
                    raise ValueError("evidence record must be an object")
                if not self.snapshot(record.get("path"), record.get("content_hash"), target, code):
                    return False
                # Compact receipts remain in Git, but their captures can be
                # external. A local pathname must not bypass that dependency
                # closure, including for QA results consumed only as snapshots.
                if record.get("schema") not in ("evidence-bytes-v1", "archive-attachment-v1") and (
                    Path(record["path"]).suffix.lower() == ".json" or "schema" in record
                ):
                    self.evidence_json(record)
                return True
            self.evidence_resolver.resolve(ref)
            self.evidence_accounting(ref)
            if record is not ref and "content_hash" in record and not hash_matches(record["content_hash"], ref["sha256"]):
                raise ValueError("evidence reference differs from recorded content hash")
            if record is not ref and record.get("kind", ref["kind"]) != ref["kind"]:
                raise ValueError("evidence wrapper kind differs from original reference")
            self.evidence_resolver.validate_bindings(ref, bindings or {})
            return True
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.issue(code, target, str(error))
            return False

    def evidence_accounting(self, ref=None, *, run_id=None, unit_id=None):
        """Verify compact reconciled records; validation never opens a mutable ledger."""
        if ref is None and "evidence_storage" not in self.manifest:
            return
        storage = self.manifest.get("evidence_storage", {})
        if not isinstance(storage, dict):
            raise ValueError("evidence storage declaration must be an object")
        policy_path = self.path(storage.get("policy_path", "forge/evidence-policy.json"), no_links=True)
        policy = validate_policy(self.document(policy_path))
        self.evidence_resolver.metadata_limit = policy["limits"]["metadata_stop_bytes"]
        self.evidence_resolver.closure_limit = policy["limits"]["metadata_stop_files"]
        if self.evidence_resolver.json_bytes > self.evidence_resolver.metadata_limit or len(self.evidence_resolver.references) > self.evidence_resolver.closure_limit:
            raise ValueError("prepared metadata/reference closure exceeds project allowance")
        receipt = self.manifest.get("evidence_accounting")
        if receipt is None:
            raise ValueError("missing required reconciled evidence accounting")
        accounting_ref = evidence_reference(receipt)
        self.accounting_reference_id = accounting_ref.get("artifact_id") if accounting_ref is not None else None
        if accounting_ref is not None:
            receipt = self.evidence_resolver.json(accounting_ref)
        if not isinstance(receipt, dict) or type(receipt.get("version")) is not int or receipt["version"] not in (1, 2):
            raise ValueError("unsupported evidence accounting version")
        for flag in ("accounting_complete", "incomplete"):
            if flag in receipt and type(receipt[flag]) is not bool:
                raise ValueError("invalid evidence accounting completeness flag: " + flag)
        scoped = receipt["version"] == 2
        if not scoped and (receipt.get("accounting_complete") is False or receipt.get("incomplete") is True):
            raise ValueError("evidence accounting is incomplete; reconcile missing durable accounting history")
        if receipt.get("project_id") != policy["project_id"] or not hash_matches(receipt.get("policy_sha256"), self.file_hash(policy_path)):
            raise ValueError("evidence accounting belongs to another project or policy")
        runs = receipt.get("runs")
        if not isinstance(runs, dict):
            raise ValueError("evidence accounting run index required")
        scope = None
        if scoped:
            scope = self.scoped_evidence_accounting(receipt, policy, runs)
        def reconciled(original_run, original_unit):
            if not isinstance(original_run, str) or not original_run or not isinstance(original_unit, str) or not original_unit:
                raise ValueError("original stable run/unit accounting identities required")
            if scope is not None and original_run not in scope:
                raise ValueError("required evidence is outside the complete current accounting scope")
            observed = runs.get(original_run)
            if not isinstance(observed, dict) or observed.get("unit_id") != original_unit or observed.get("status") != "complete":
                raise ValueError("missing/incomplete accounting for original run/unit")
            for field in ("gross_generated_bytes", "original_logical_files", "pending_reservations", "unreconciled_outputs"):
                value = observed.get(field)
                if type(value) is not int or value < 0:
                    raise ValueError("invalid reconciled accounting amount: " + field)
            if observed["pending_reservations"] or observed["unreconciled_outputs"]:
                raise ValueError("evidence accounting has outstanding reservations or outputs")
            return observed
        if ref is not None:
            # Every current prepared dependency is required; archival history stays unloaded.
            for reference in list(self.evidence_resolver.references.values()):
                if reference["artifact_id"] == self.accounting_reference_id:
                    continue
                provenance = reference["provenance"]
                original_run, original_unit = provenance.get("run_id"), provenance.get("unit_id")
                observed = reconciled(original_run, original_unit)
                if observed.get("mode") == "imported-existing":
                    if not (reference.get("retention", {}).get("imported") is True or provenance.get("accounting_mode") == "imported-existing") or observed["gross_generated_bytes"] or observed["original_logical_files"]:
                        raise ValueError("imported accounting requires explicit existing-data provenance and zero new generation")
                    continue
                if observed.get("mode", "generated") != "generated":
                    raise ValueError("unsupported evidence accounting mode")
                associated = self.accounted_refs.setdefault(original_run, {})
                original_path = reference.get("original_path")
                logical_file = (original_unit, original_path if isinstance(original_path, str) and original_path else reference["artifact_id"], reference["sha256"])
                associated[logical_file] = reference["size"]
                if observed["gross_generated_bytes"] < sum(associated.values()) or observed["original_logical_files"] < len(associated):
                    raise ValueError("required evidence exceeds reconciled original generation accounting")
        elif run_id is not None or unit_id is not None:
            reconciled(run_id, unit_id)

    @staticmethod
    def scoped_evidence_accounting(receipt, policy, runs):
        """Validate declared known-run scope without concealing historical gaps.

        This checker does not inspect or repair a live ledger. The storage owner
        must establish disposition and readiness before issuing this receipt.
        Required evidence still passes every original per-run binding check.
        """
        from evidence.quarantine import validate_quarantine_descriptor
        flags = {"accounting_complete": False, "incomplete": True,
                 "totals_are_lower_bounds": True, "history_complete": False,
                 "generation_ready": True}
        if receipt.get("kind") != "scoped-known-generation" or any(
                type(receipt.get(key)) is not bool or receipt[key] is not value
                for key, value in flags.items()):
            raise ValueError("scoped accounting must disclose incomplete historical accounting")
        quarantines = receipt.get("quarantines")
        if not isinstance(quarantines, list) or not quarantines:
            raise ValueError("scoped accounting requires preserved quarantine descriptors")
        isolated = {}
        reservations = set()
        for descriptor in quarantines:
            validate_quarantine_descriptor(descriptor, policy)
            ident = descriptor["intent_id"]
            if (ident in isolated or descriptor["reservation_id"] in reservations
                    or not isinstance(ident, str) or not ident):
                raise ValueError("duplicate or missing scoped quarantine identity")
            reservations.add(descriptor["reservation_id"])
            isolated[ident] = descriptor
            row = runs.get(descriptor["run_id"])
            if (not isinstance(row, dict) or row.get("unit_id") != descriptor["unit_id"]
                    or row.get("status") != "incomplete"
                    or type(row.get("pending_reservations")) is not int
                    or row["pending_reservations"] < 1
                    or type(row.get("gross_generated_bytes")) is not int
                    or row["gross_generated_bytes"] < descriptor["run"]["gross_bytes"]
                    or type(row.get("original_logical_files")) is not int
                    or row["original_logical_files"] < descriptor["run"]["gross_files"]):
                raise ValueError("quarantined run must remain incomplete with its full pending hold")
        pending = receipt.get("pending_generation_intents")
        if not isinstance(pending, dict) or set(pending) != set(isolated):
            raise ValueError("scoped accounting has unisolated pending generation intents")
        for ident, intent in pending.items():
            gap = isolated[ident]
            if (not isinstance(intent, dict) or intent.get("settled")
                    or intent.get("run_id") != gap["run_id"]
                    or intent.get("unit_id") != gap["unit_id"]
                    or intent.get("reserve_bytes") != gap["reservation"]["bytes"]
                    or intent.get("reserve_files") != gap["reservation"]["files"]):
                raise ValueError("quarantined generation intent changed or was settled")
        selected = receipt.get("selected_scope")
        if (not isinstance(selected, dict) or selected.get("complete") is not True
                or not isinstance(selected.get("run_ids"), list)
                or any(not isinstance(item, str) or not item for item in selected["run_ids"])
                or len(set(selected["run_ids"])) != len(selected["run_ids"])):
            raise ValueError("complete current accounting scope requires unique run identities")
        scope = set(selected["run_ids"])
        complete_runs = {ident for ident, row in runs.items()
                         if isinstance(row, dict) and row.get("status") == "complete"}
        if scope != complete_runs or scope.intersection(gap["run_id"] for gap in quarantines):
            raise ValueError("current accounting scope differs from complete known runs")
        quarantined_runs = {gap["run_id"] for gap in quarantines}
        if len({gap["ledger_id"] for gap in quarantines}) != 1:
            raise ValueError("scoped quarantines must retain one authoritative original ledger")
        for ident, row in runs.items():
            if not isinstance(ident, str) or not ident or not isinstance(row, dict):
                raise ValueError("invalid scoped accounting run identity")
            for field in ("gross_generated_bytes", "original_logical_files",
                          "pending_reservations", "unreconciled_outputs"):
                if type(row.get(field)) is not int or row[field] < 0:
                    raise ValueError("invalid scoped accounting run amount: " + field)
            if ident not in quarantined_runs and (row["pending_reservations"] or row["unreconciled_outputs"]):
                raise ValueError("scoped accounting has unisolated outstanding reservations or outputs")
            if ident in quarantined_runs and row["pending_reservations"] != sum(
                    gap["run_id"] == ident for gap in quarantines):
                raise ValueError("scoped accounting pending hold count differs from preserved quarantines")
        return scope

    def evidence_json(self, record):
        ref = evidence_reference(record)
        value = self.evidence_resolver.json(ref) if ref is not None else self.evidence_resolver.json_file(
            self.path(record["path"], no_links=True), record.get("schema", "evidence-json-v1"))
        # Only references need managed accounting; a legacy contained receipt
        # with no external dependencies requires no invented run history.
        if self.evidence_resolver.visited:
            dependency = self.evidence_resolver.references[next(iter(self.evidence_resolver.visited))]
            self.evidence_accounting(dependency)
        return value

    @staticmethod
    def bytes_hash(data):
        return digest(data)

    def evidence_bytes(self, record):
        """Read verified original bytes without assigning a new execution context."""
        ref = evidence_reference(record)
        path = self.evidence_resolver.resolve(ref) if ref is not None else self.path(record["path"], no_links=True)
        before = self.file_hash(path)
        data = path.read_bytes()
        if digest(data) != before or self.file_hash(path) != before:
            raise ValueError("evidence changed while reading original bytes")
        return data

    @staticmethod
    def capture_record(record, stem):
        if stem + "_ref" in record:
            supplied = record[stem + "_ref"]
            ref = evidence_reference(supplied)
            if ref is None:
                raise ValueError("versioned evidence reference required for " + stem + "_ref")
            wrapper = {"evidence_ref": ref}
            if record.get(stem + "_hash") is not None:
                wrapper["content_hash"] = record[stem + "_hash"]
            return wrapper
        return {"path": record.get(stem + "_path"), "content_hash": record.get(stem + "_hash")}

    @staticmethod
    def evidence_kind(record):
        ref = evidence_reference(record)
        return ref["kind"] if ref is not None else record.get("kind")

    @staticmethod
    def evidence_hash(record):
        ref = evidence_reference(record)
        return ref["sha256"] if ref is not None else record.get("content_hash")

    @staticmethod
    def evidence_label(record):
        ref = evidence_reference(record)
        return ref["artifact_id"] if ref is not None else record.get("path")

    def source_inventory(self, entry, key="source_hashes"):
        inline = entry.get(key, {})
        if not isinstance(inline, dict):
            raise ValueError("source hash map must be an object")
        reference = entry.get("source_inventory_ref")
        if reference is None:
            return inline, entry.get("consumed_source_fragments", {})
        ref = evidence_reference(reference)
        if ref is None or ref.get("schema") != "source-inventory-v1":
            raise ValueError("shared source inventory reference schema required")
        record = self.evidence_resolver.json(ref)
        self.evidence_accounting(ref)
        hashes, fragments = record["source_hashes"], record.get("consumed_source_fragments", {})
        if not isinstance(fragments, dict):
            raise ValueError("source inventory fragments must be an object")
        if inline and inline != hashes or entry.get("consumed_source_fragments") and entry["consumed_source_fragments"] != fragments:
            raise ValueError("inline and shared source inventory differ")
        for path, value in hashes.items():
            self.path(path)
            if not isinstance(value, str) or not HASH_RE.fullmatch(value):
                raise ValueError("source inventory contains an invalid source hash")
        return hashes, fragments

    def check_bindings(self, check, evidence=None):
        expected = {key: check[key] for key in ("check_id", "executed_at", "evaluated_plan_hash", "baseline_id", "target_hash") if key in check}
        hashes, _ = self.source_inventory(check, "evaluated_source_hashes")
        inventory = evidence_reference(check.get("source_inventory_ref"))
        if evidence is None:
            if inventory is not None:
                expected["evaluated_source_inventory_sha256"] = inventory["sha256"]
            elif hashes:
                expected["evaluated_source_hashes"] = hashes
            return expected
        reference = evidence_reference(evidence)
        supplied = reference.get("bindings", {}) if reference is not None else {}
        if not isinstance(supplied, dict):
            raise ValueError("evidence bindings must be an object")
        compact = "evaluated_source_inventory_sha256" in supplied
        full = "evaluated_source_hashes" in supplied
        if compact:
            if inventory is None:
                raise ValueError("compact evaluated-source binding requires a declared source inventory")
            # Resolving this root proves its own closure; unrelated prepared inventories cannot cover it.
            self.evidence_resolver.resolve(reference)
            if not any(key != reference["artifact_id"] and
                       self.evidence_resolver.references[key].get("schema") == "source-inventory-v1" and
                       self.evidence_resolver.references[key].get("sha256") == inventory["sha256"]
                       for key in self.evidence_resolver.visited):
                raise ValueError("compact evaluated-source binding requires its verified source-inventory dependency")
            expected["evaluated_source_inventory_sha256"] = inventory["sha256"]
        if full or hashes and not compact:
            expected["evaluated_source_hashes"] = hashes
        return expected

    @staticmethod
    def reference_path(reference):
        return reference.get("path", "") if isinstance(reference, dict) else str(reference).split("#", 1)[0]

    def reference(self, reference, target):
        try:
            if isinstance(reference, dict):
                path, heading = reference["path"], reference["heading"]
            else:
                path, heading = reference.split("#", 1)
            return self.section(path, heading).decode("utf-8")
        except (AttributeError, KeyError, ValueError, OSError) as error:
            self.issue("invalid_reference", target, str(error))
            return ""

    def sources(self, entry, target, required=()):
        try:
            hashes, fragments = self.source_inventory(entry)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.issue("invalid_provenance", target, str(error))
            return
        if not isinstance(hashes, dict) or not isinstance(fragments, dict):
            self.issue("invalid_provenance", target, "source hashes/fragments must be objects")
            return
        for path, value in hashes.items():
            self.snapshot(path, value, target)
        for path, records in fragments.items():
            if path in hashes:
                self.issue("duplicate_provenance", target, "use a full hash OR fragments: " + path)
            if not isinstance(records, list) or not records:
                self.issue("invalid_fragment", target, "expected a nonempty fragment list: " + path)
                continue
            for record in records:
                try:
                    current = digest(self.section(path, record["heading"]))
                    if not hash_matches(record.get("content_hash"), current):
                        self.issue("stale_fragment", target, path + "#" + record["heading"])
                except (TypeError, KeyError, ValueError, OSError) as error:
                    self.issue("invalid_fragment", target, str(error))
        for dependency in required:
            # Context is relevance-scoped; its presence never requires invented consumption.
            if dependency in self.contract["context_bundle"]:
                continue
            path = self.specs[dependency]["path"]
            if path not in hashes and path not in fragments:
                self.issue("missing_source_snapshot", target, path)

    def artifact(self, key):
        if key in self.checked:
            return
        self.checked.add(key)
        spec = self.specs[key]
        for dependency in spec["required_before"]:
            self.artifact(dependency)
        entry = self.artifacts.get(key)
        if not isinstance(entry, dict):
            self.issue("missing_artifact", key, spec["path"])
            return
        if entry.get("path") != spec["path"] or entry.get("owner_skill") != spec["owner_skill"]:
            self.issue("wrong_owner_or_path", key, "expected " + spec["owner_skill"] + " -> " + spec["path"])
        self.snapshot(spec["path"], entry.get("content_hash"), key, "stale_artifact")
        if entry.get("status") != "validated":
            self.issue("not_validated", key, "artifact status is not validated")
        validation = entry.get("validation", {})
        if not isinstance(validation, dict) or validation.get("result", validation.get("status")) not in ("passed", "validated"):
            self.issue("missing_validation", key, "owner must record document-validation result")
        if not entry.get("owner_invocation_id"):
            self.issue("missing_invocation", key, "owner invocation is required")
        dispatch = self.manifest.get("dispatches", {}).get(key)
        if dispatch is not None:
            if dispatch.get("invocation_id") != entry.get("owner_invocation_id") or set(dispatch.get("outputs", [])) != set(entry.get("declared_output_set", [])):
                self.issue("stale_owner_return", key, "return does not match the current dispatch identity/output set")
            self.sources(dispatch, key)
        language = self.manifest.get("language", {}).get("working_language")
        if language and validation.get("working_language") != language:
            self.issue("language_revalidation", key, "validate prose against current working_language")
        declared = entry.get("dependencies", [])
        if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
            self.issue("invalid_dependencies", key, "dependencies must be artifact IDs")
        else:
            expanded = set()
            for item in declared:
                if item in self.contract["nodes"]:
                    expanded.update(self.contract["nodes"][item]["outputs"])
                else:
                    expanded.add(item)
            for item in expanded - set(spec["required_before"]):
                if item in spec["consulted_later"]:
                    self.warnings.append(key + ": later reference is not a prerequisite: " + item)
                else:
                    self.issue("unexpected_dependency", key, item)
            for item in set(spec["required_before"]) - expanded:
                self.issue("missing_dependency", key, item)
        self.sources(entry, key, spec["required_before"])
        self.source_usage(entry, key, spec["required_before"])
        observation = entry.get("repository_observation_id")
        if observation:
            record = self.manifest.get("repository_observations", {}).get(observation, {})
            if not record.get("commands") or not record.get("observed_at") or not record.get("paths"):
                self.issue("missing_observation", key, str(observation))
            else:
                for path, value in record["paths"].items():
                    if value is None:
                        try:
                            if self.path(path, observation=True).exists():
                                self.issue("stale_observation", key, "formerly absent: " + path)
                        except ValueError as error:
                            self.issue("stale_observation", key, str(error))
                    else:
                        self.snapshot(path, value, key, "stale_observation", observation=True)

        if key == "prd":
            self.security_review(entry)
        elif key in SECURITY_OWNERS:
            self.security_coverage(entry, key)
        if key == "architecture":
            try:
                validate_architecture_construction(self)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
                self.issue("construction", key, str(error))

    def source_usage(self, entry, target, required):
        """Check owner-declared consumption against bindings, not inferred prose meaning."""
        usage = entry.get("source_usage")
        if not isinstance(usage, dict):
            self.issue("source_usage_missing", target, "owner must review consumed sources and unused context; do not infer from old hashes")
            return
        try:
            hashes, fragments = self.source_inventory(entry)
        except (ValueError, OSError, KeyError, TypeError):
            return  # sources() reports a malformed or missing prepared inventory.
        if not isinstance(hashes, dict) or not isinstance(fragments, dict):
            return  # sources() reports the malformed binding containers.
        required_paths = {self.specs[key]["path"]: key for key in required}
        for path in required_paths.keys() - usage.keys():
            self.issue("source_decision_missing", target, path)
        for path in (hashes.keys() | fragments.keys()) - usage.keys():
            self.issue("unreviewed_source", target, path)
        for path, decision in usage.items():
            try:
                self.path(path)
            except (ValueError, TypeError) as error:
                self.issue("invalid_source_usage", target, str(error))
                continue
            if isinstance(decision, dict) and set(decision) == {"unused"}:
                reason = decision["unused"]
                if not isinstance(reason, str) or not reason.strip():
                    self.issue("invalid_source_usage", target, "unused needs a reason: " + path)
                if path in hashes or path in fragments or (path in required_paths and required_paths[path] not in self.contract["context_bundle"]):
                    self.issue("source_usage_conflict", target, "unused source is bound or mandatory: " + path)
            elif decision == "full":
                if path not in hashes:
                    self.issue("unbound_consumed_source", target, "full file: " + path)
            elif isinstance(decision, list) and decision and all(isinstance(heading, str) and heading.strip() for heading in decision) and len(set(decision)) == len(decision):
                bound = fragments.get(path, [])
                headings = {item.get("heading") for item in bound if isinstance(item, dict) and isinstance(item.get("heading"), str)} if isinstance(bound, list) else set()
                for heading in decision:
                    try:
                        self.section(path, heading)
                    except (ValueError, OSError) as error:
                        self.issue("invalid_source_usage", target, str(error))
                    if path not in hashes and heading not in headings:
                        self.issue("unbound_consumed_source", target, path + "#" + heading)
                if headings - set(decision):
                    self.issue("unreviewed_source", target, "fragment not in source_usage: " + path)
            else:
                self.issue("invalid_source_usage", target, "choose full, exact headings or an unused reason: " + path)

    def source_proposal(self, node, consumed=(), unused=()):
        """Read-only hash assistance; unresolved context remains an explicit review task."""
        spec = self.contract["nodes"][node]
        usage = {self.specs[key]["path"]: {"review_required": True} if key in self.contract["context_bundle"] else "full"
                 for key in spec["required_before"]}
        selected = {}
        for value in consumed:
            path, separator, heading = value.partition("#")
            self.path(path)
            if separator:
                if not heading or selected.get(path) == "full":
                    raise ValueError("choose full file OR nonempty headings: " + path)
                headings = selected.setdefault(path, [])
                if heading in headings:
                    raise ValueError("duplicate consumed heading: " + value)
                headings.append(heading)
            else:
                if path in selected:
                    raise ValueError("duplicate/mixed full-file consumption: " + path)
                selected[path] = "full"
        usage.update(selected)
        exclusions = set()
        for value in unused:
            path, separator, reason = value.partition("=")
            self.path(path)
            if not separator or not reason.strip() or path in selected or path in exclusions:
                raise ValueError("unused needs a unique PATH=reason, without consumption: " + path)
            if path in usage and usage[path] == "full":
                raise ValueError("cannot exclude a required non-context source: " + path)
            usage[path] = {"unused": reason.strip()}
            exclusions.add(path)
        hashes, fragments = {}, {}
        for path, decision in usage.items():
            if decision == "full":
                hashes[path] = self.file_hash(self.path(path, no_links=True))
            elif isinstance(decision, list):
                fragments[path] = [{"heading": heading, "content_hash": digest(self.section(path, heading))} for heading in decision]
        return {"node": node, "status": "unvalidated", "outputs": spec["outputs"], "source_usage": usage,
                "source_hashes": hashes, "consumed_source_fragments": fragments,
                "limits": "Hash proposal only. Resolve review_required from actual reading, include shared scope/terms/evidence sections, and return owner validation; no inferred consumption or approval."}

    def security_reference(self, reference, owner, identifier=None):
        text = self.reference(reference, owner)
        if self.reference_path(reference) != self.specs[owner]["path"] or (identifier and not contains_id(text, identifier)):
            self.issue("security_reference", owner, "security reference must resolve its ID in the owner's document")
        return text

    def security_review(self, entry):
        review = entry.get("security_review")
        if not isinstance(review, dict):
            self.issue("security_review_missing", "prd", "PRD owner must assess OWASP requirements; do not invent a historical review")
            return
        if type(review.get("version")) is not int or review["version"] != 1 or review.get("asvs_version") != "5.0.0":
            self.issue("security_profile", "prd", "expected security record version 1 and ASVS 5.0.0")
        scope, level = review.get("scope"), review.get("level")
        if (scope == "web-api" and (type(level) is not int or level not in (1, 2, 3))) or (scope == "adapted" and level is not None) or scope not in ("web-api", "adapted"):
            self.issue("security_profile", "prd", "web-api needs level 1-3; adapted scope must not claim an ASVS level")
        text = self.security_reference(review.get("definition_ref"), "prd")
        rationale = review.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip() or rationale not in text or "5.0.0" not in text:
            self.issue("security_profile", "prd", "canonical security section needs the recorded rationale and standard version")
        if review.get("status") != "complete":
            self.issue("security_review_incomplete", "prd", "resolve material security specification gaps before advancement")
        try:
            if self.file_hash(ASVS_CATALOG) != ASVS_CATALOG_SHA256:
                raise ValueError("ASVS catalog does not match the reviewed pin; repair the skill resources")
            catalog = self.document(ASVS_CATALOG)
            if catalog.get("Version") != "5.0.0":
                raise ValueError("expected bundled ASVS 5.0.0")
            known = {"v5.0.0-" + item["Shortcode"][1:]
                     for chapter in catalog["Requirements"] for section in chapter["Items"] for item in section["Items"]}
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.issue("security_catalog", "prd", str(error))
            return
        requirements = review.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            self.issue("security_requirements", "prd", "explicit protective requirements are required")
            return
        for requirement in requirements:
            if not isinstance(requirement, dict):
                self.issue("security_requirements", "prd", "security requirement record must be an object")
                continue
            key = requirement.get("requirement_id")
            if not isinstance(key, str) or not re.fullmatch(r"(?:FR|NFR)-[A-Za-z0-9][A-Za-z0-9_.-]*", key) or key in self.security_requirements:
                self.issue("security_requirements", "prd", "unique existing FR/NFR obligation IDs required")
                continue
            self.security_requirements[key] = requirement
            text = self.security_reference(requirement.get("definition_ref"), "prd", key)
            ids = requirement.get("asvs_ids")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                self.issue("security_asvs_id", "prd", key + ": ASVS IDs must be a list of strings")
                continue
            if len(set(ids)) != len(ids) or any(item not in known or not contains_id(text, item) for item in ids):
                self.issue("security_asvs_id", "prd", key + ": cite unique, real versioned controls in the canonical requirement")
            if not ids:
                rationale = requirement.get("rationale")
                if not isinstance(rationale, str) or not rationale.strip() or rationale not in text:
                    self.issue("security_supplement", "prd", key + ": supplemental controls need a canonical rationale")

    def security_coverage(self, entry, owner):
        if not self.security_requirements:
            return
        coverage = entry.get("security_coverage")
        if not isinstance(coverage, dict) or set(coverage) != set(self.security_requirements):
            self.issue("security_coverage", owner, "map every current PRD security obligation to this owner's local consequence")
            return
        for key, reference in coverage.items():
            self.security_reference(reference, owner, key)

    def security_verification(self, checks, gates):
        if not self.security_requirements:
            return
        expected = set(self.security_requirements)
        matches = [gate for gate in gates if gate.get("gate_id") == SECURITY_GATE]
        if len(matches) != 1:
            self.issue("security_gate", "dod-evals", "one required product_security_requirements gate must cover the PRD security obligations")
            return
        gate = matches[0]
        ids = gate.get("security_requirement_ids")
        if gate.get("active") is not True or gate.get("required") is not True or gate.get("applicability") != "applicable":
            self.issue("security_gate", "dod-evals", "applicable security obligations cannot be inactive, advisory or excluded")
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids) or len(set(ids)) != len(ids) or set(ids) != expected:
            self.issue("security_gate_coverage", "dod-evals", "security gate must cover every current PRD security obligation")
        text = self.reference(gate.get("definition_ref"), "dod-evals")
        if any(not contains_id(text, key) for key in expected):
            self.issue("security_gate_coverage", "dod-evals", "canonical security gate must cite its requirement IDs")
        covered = set()
        for check in checks:
            if check.get("gate_id") != SECURITY_GATE:
                continue
            ids = check.get("security_requirement_ids")
            if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
                self.issue("security_check_coverage", "qa-checklist", "each security check needs PRD security obligation IDs")
                continue
            if len(set(ids)) != len(ids) or set(ids) - expected:
                self.issue("security_check_coverage", "qa-checklist", "unknown or duplicate security obligation IDs")
            if check.get("check_id") not in gate.get("check_ids", []):
                self.issue("security_check_coverage", "qa-checklist", "security check must be bound to the required gate")
                continue
            text = self.reference(check.get("definition_ref"), "qa-checklist")
            if any(not contains_id(text, key) for key in ids):
                self.issue("security_check_coverage", "qa-checklist", "canonical checks must cite their security obligation IDs")
            if check.get("phase") not in ("implementation", "both") or check.get("execution_status") == "not_applicable":
                self.issue("security_check_scope", "qa-checklist", "applicable product security needs implementation-level checks")
            covered.update(ids)
        if covered != expected:
            self.issue("security_check_coverage", "qa-checklist", "concrete checks must cover every PRD security obligation")

    def bundle(self):
        keys = self.contract["context_bundle"]
        if not self.checked.intersection(keys):
            return
        for key in keys:
            self.artifact(key)
        records = [self.artifacts.get(key, {}) for key in keys]
        invocations = {record.get("owner_invocation_id") for record in records}
        outputs = {self.specs[key]["path"] for key in keys}
        if len(invocations) != 1 or None in invocations or any(set(record.get("declared_output_set", [])) != outputs for record in records):
            for key in keys:
                self.issue("incomplete_context_bundle", key, "both outputs need one invocation and the same two-file output set")

    def traceability(self):
        owners = {"job": "product-idea", "use_case": "prd", "requirement": "prd", "surface": "screen-map",
                  "state": "screen-map", "unit": "development-plan", "check": "qa-checklist"}
        active = set(owners.values()) & self.checked
        if not active:
            return
        if type(self.manifest.get("traceability_version")) is not int or self.manifest["traceability_version"] != 1:
            self.issue("migration_required", "manifest", "owners must return verified traceability version 1; preserve IDs and history")
            return
        definitions, links = {}, []
        for owner in sorted(active):
            trace = self.artifacts.get(owner, {}).get("traceability")
            if not isinstance(trace, dict) or not isinstance(trace.get("definitions"), list) or not isinstance(trace.get("links"), list):
                self.issue("trace_definition", owner, "owner needs definitions and links")
                continue
            for item in trace["definitions"]:
                key, kind = item.get("id"), item.get("kind")
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", key) or key in definitions or owners.get(kind) != owner:
                    self.issue("trace_definition", owner, "unique ID with its canonical kind/owner required")
                    continue
                definitions[key] = item
                text = self.reference(item.get("definition_ref"), owner)
                if self.reference_path(item.get("definition_ref")) != self.specs[owner]["path"] or not contains_id(text, key):
                    self.issue("trace_definition", owner, key + ": missing canonical definition")
                if type(item.get("required")) is not bool or (not item.get("required") and not item.get("rationale")):
                    self.issue("trace_definition", owner, key + ": required flag or exclusion rationale missing")
            links.extend((owner, link) for link in trace["links"])
            # Declared primary IDs in canonical source cannot silently fall out of its index.
            prefix = r"JOB" if owner == "product-idea" else r"UC|FR|NFR" if owner == "prd" else None
            if prefix:
                text = self.path(self.specs[owner]["path"]).read_text(encoding="utf-8")
                mentioned = {value.rstrip(".") for value in re.findall(r"(?<![\w.-])(?:" + prefix + r")-[A-Za-z0-9][A-Za-z0-9_.-]*", text)}
                for key in mentioned - set(definitions):
                    self.issue("trace_definition", owner, key + ": canonical ID is not indexed")
        kinds = {key: value["kind"] for key, value in definitions.items()}
        allowed = {"realizes_job": ({"use_case"}, {"job"}), "specifies": ({"requirement"}, {"use_case"}),
                   "supports": ({"surface"}, {"use_case"}), "state_of": ({"state"}, {"surface"}),
                   "implements": ({"unit"}, {"requirement", "state"}), "verifies": ({"check"}, {"requirement", "state"})}
        checks = {check.get("check_id"): check for check in self.manifest.get("verification", {}).get("checks", [])}
        valid = set()
        for owner, link in links:
            source, target, relation = link.get("from"), link.get("to"), link.get("relation")
            types = allowed.get(relation)
            text = self.reference(link.get("definition_ref"), owner)
            if not types or kinds.get(source) not in types[0] or kinds.get(target) not in types[1] or owners.get(kinds.get(source)) != owner:
                self.issue("trace_link", owner, str(source) + " -> " + str(target) + ": unresolved or wrongly typed link")
            elif self.reference_path(link.get("definition_ref")) != self.specs[owner]["path"] or not all(contains_id(text, key) for key in (source, target)):
                self.issue("trace_link", owner, "relationship must be cited in its owner's document")
            elif relation != "verifies" or (source in checks and checks[source].get("execution_status") != "not_applicable"):
                valid.add((source, target, relation))
        for key, item in definitions.items():
            if not item.get("required"):
                continue
            kind = item["kind"]
            incoming = {relation for _, target, relation in valid if target == key}
            outgoing = {relation for source, _, relation in valid if source == key}
            expected = set()
            if kind == "job" and "prd" in active:
                expected.add("realizes_job")
            if kind == "use_case":
                expected.add("specifies")
                if "realizes_job" not in outgoing:
                    self.issue("trace_coverage", "prd", key + ": use case must realize a job")
            if kind == "requirement" and not item.get("cross_cutting") and "specifies" not in outgoing:
                self.issue("trace_coverage", "prd", key + ": map a use case or explicitly declare cross-cutting scope")
            if kind == "surface" and "supports" not in outgoing or kind == "state" and "state_of" not in outgoing:
                self.issue("trace_coverage", "screen-map", key + ": missing structural relationship")
            if kind in ("requirement", "state"):
                if "qa-checklist" in active:
                    expected.add("verifies")
                if "development-plan" in active:
                    expected.add("implements")
            for relation in expected - incoming:
                owner = "qa-checklist" if relation == "verifies" else "development-plan" if relation == "implements" else "prd"
                self.issue("trace_coverage", owner, key + ": missing " + relation)
        if "qa-checklist" in active:
            declared = {key for key, kind in kinds.items() if kind == "check"}
            for key in declared.symmetric_difference(checks):
                self.issue("trace_link", "qa-checklist", str(key) + ": trace and verification indexes must agree")
            for check in checks.values():
                for field, kind in (("job_ids", "job"), ("use_case_ids", "use_case")):
                    ids = check.get(field, [])
                    if not isinstance(ids, list) or any(not isinstance(key, str) or kinds.get(key) != kind for key in ids):
                        self.issue("trace_link", "qa-checklist", str(check.get("check_id")) + ": unresolved " + field)

    def render_hash(self, record):
        if not self._invocation_active:
            self.hash_cache.clear()  # Standalone utility calls are separate observations.
            self.directory_cache.clear()
        root_name = record.get("prototype_source_root")
        root = self.path(root_name, no_links=True)
        if not root.is_dir():
            raise ValueError("prototype source root must be a directory")
        algorithm = record.get("hash_algorithm")
        dependencies = record.get("render_dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(p, str) for p in dependencies):
            raise ValueError("render dependencies must be project-relative paths")
        if algorithm not in ("sdd-tree-sha256-v1", "sdd-render-sha256-v2") or (algorithm == "sdd-tree-sha256-v1" and dependencies):
            raise ValueError("shared assets require sdd-render-sha256-v2")
        names = [root_name] + dependencies
        paths = [self.path(name, no_links=True) for name in names]
        if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i + 1:]):
            raise ValueError("duplicate or overlapping render roots")
        entries, files = [], set()
        for name, path in zip(names, paths):
            if not path.is_dir() and not path.is_file():
                raise ValueError("render input must be a regular file or directory")
            value = tree_hash(path, self.file_hash, self.directory_cache) if path.is_dir() else self.file_hash(path)
            entries.append((name, value))
            files.update(p.resolve() for p in path.rglob("*") if p.is_file()) if path.is_dir() else files.add(path)
        validate_render_files(root, files)
        if algorithm == "sdd-tree-sha256-v1":
            return entries[0][1]
        entries.sort(key=lambda item: item[0].encode("utf-8"))
        return digest(json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def frozen(self, record, target):
        try:
            observed = self.render_hash(record)
            if not hash_matches(record.get("prototype_tree_hash"), observed):
                self.issue("baseline_integrity", target, "prototype source tree changed")
            self.evidence_snapshot(self.capture_record(record, "visual_target"), target, "visual_target_integrity")
        except (ValueError, OSError) as error:
            self.issue("baseline_integrity", target, str(error))

    def baseline(self):
        record = self.manifest.get("active_baseline", {})
        baseline_id = record.get("baseline_id")
        if not baseline_id or baseline_id != self.manifest.get("approved_baseline_id"):
            self.issue("missing_baseline", "design-brief", "current approved Baseline ID required")
            return
        self.frozen(record, "design-brief")
        text = self.reference(record.get("canonical_ref"), "design-brief")
        if self.reference_path(record.get("canonical_ref")) != "docs/design-brief.md":
            self.issue("baseline_projection_mismatch", "design-brief", "canonical baseline must be in the design brief")
        for value in (baseline_id, record.get("visual_target_hash"), record.get("prototype_tree_hash")):
            if not isinstance(value, str) or value not in text:
                self.issue("baseline_projection_mismatch", "design-brief", "canonical section must contain current ID and hashes")
        receipt = record.get("approval_receipt", {})
        if not isinstance(receipt, dict) or not self.evidence_snapshot(receipt, "design-brief", "approval_receipt", {key: record.get(key) for key in ("baseline_id", "visual_target_hash", "prototype_tree_hash")}):
            return
        try:
            approval = self.evidence_json(receipt)
            if approval.get("event") not in ("approve_design_baseline", "accepted_scoped_baseline_override") or not approval.get("actor"):
                raise ValueError("explicit operator approval/accepted override event required")
            for field in ("baseline_id", "visual_target_hash", "prototype_tree_hash"):
                if approval.get(field) != record.get(field):
                    raise ValueError("approval does not match current " + field)
            timestamp(approval.get("approved_at"))
            if self.evidence_label(receipt) not in text:
                raise ValueError("approval receipt must be referenced by the canonical design section")
        except (ValueError, OSError, KeyError) as error:
            self.issue("approval_receipt", "design-brief", str(error))

    def source_access(self):
        handoff = self.manifest.get("design_execution", {})
        if handoff.get("mode") != "claude_design":
            return
        records = {}
        for key in ("source_manifest", "codex_access_receipt", "claude_source_read_receipt"):
            try:
                current = self.capture_record(handoff, key)
                if not self.evidence_snapshot(current, "design", "source_access_receipt"):
                    return
                records[key] = self.evidence_json(current)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.issue("source_access_receipt", "design", str(error))
                return
        try:
            inventory = records["source_manifest"]
            materials = inventory["materials"]
            indexed = {item["material_id"]: item for item in materials}
            if not materials or len(indexed) != len(materials) or any(not key for key in indexed):
                raise ValueError("complete unique material IDs required")
            if inventory.get("language") != self.manifest.get("language"):
                raise ValueError("source manifest language must match the current handoff")
            if any(type(item.get("required")) is not bool for item in materials):
                raise ValueError("every material needs an explicit required flag")
            required = {key for key, item in indexed.items() if item["required"]}
            if not required or handoff.get("unresolved_required_source_ids") or any(
                type(handoff.get(key)) is not int or handoff[key] != len(required)
                for key in ("required_source_count", "codex_accessible_required_source_count", "claude_read_required_source_count")
            ):
                raise ValueError("required source counts must match the actual material IDs")
            manifest_record = self.capture_record(handoff, "source_manifest")
            manifest_hash = self.evidence_hash(manifest_record)
            manifest_hash = HASH_RE.fullmatch(manifest_hash).group(1).lower()
            for key, success in (("codex_access_receipt", "accessible"), ("claude_source_read_receipt", "read")):
                receipt = records[key]
                results = receipt["results"]
                by_id = {item["material_id"]: item for item in results}
                if len(by_id) != len(results) or set(by_id) != set(indexed) or required.intersection(receipt.get("unresolved_material_ids", [])):
                    raise ValueError(key + ": missing, duplicate or unresolved material IDs")
                if not hash_matches(receipt.get("manifest_hash"), manifest_hash):
                    raise ValueError(key + ": stale source manifest")
                for material_id in required:
                    observed, source = by_id[material_id], indexed[material_id]
                    field = "content_hash" if source.get("content_hash") else "capture_id"
                    if observed.get("status") != success or not source.get(field) or observed.get(field) != source[field]:
                        raise ValueError(key + ": unread or mismatched source " + material_id)
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            self.issue("source_access_incomplete", "design", str(error))

    def candidates(self):
        records = [item for item in self.manifest.get("prototype_candidates", [])
                   if item.get("status") != "superseded" and not item.get("superseded_by")]
        active_set = self.manifest.get("design_execution", {}).get("active_candidate_set_id")
        if active_set:
            records = [item for item in records if item.get("candidate_set_id") == active_set]
        mode = self.manifest.get("design_execution", {}).get("mode")
        if mode == "claude_design":
            handoff = self.manifest["design_execution"]
            references = handoff.get("claude_candidate_references", [])
            selected = handoff.get("selected_candidate_version")
            if len(references) != 3 or len(set(references)) != 3 or len(records) != 1:
                self.issue("candidate_coverage", "design", "three Claude references and one selected normalized import required")
            if selected not in references or any(item.get("origin_reference") != selected for item in records):
                self.issue("candidate_selection", "design", "normalized import must match the exact selected Claude reference")
            self.source_access()
        elif mode != "codex" or len(records) != 3:
            self.issue("candidate_coverage", "design", "exactly three Codex candidates required")
        identities = set()
        for record in records:
            identity = (record.get("candidate_id"), record.get("version"))
            if not all(identity) or identity in identities:
                self.issue("candidate_identity", "design", "missing or duplicate candidate/version")
            identities.add(identity)
            self.frozen(record, "design")
            self.sources(record, "design", self.contract["nodes"]["prototype-candidates"]["required_before"])
            if not record.get("route") or not str(record.get("preview_url", "")).startswith(("http://", "https://")):
                self.issue("candidate_scope", "design", "stable live URL and route required")
            for field in ("browser_receipt", "visual_qa_evidence"):
                receipt = record.get(field, {})
                if not self.evidence_snapshot(receipt, "design", field, {key: record[key] for key in ("candidate_id", "version", "visual_target_hash", "prototype_tree_hash", "preview_url") if key in record}):
                    continue
                try:
                    actual = self.evidence_json(receipt)
                    for key in ("candidate_id", "version", "visual_target_hash", "prototype_tree_hash", "preview_url"):
                        if not record.get(key) or actual.get(key) != record[key]:
                            raise ValueError("receipt does not match current " + key)
                    timestamp(actual.get("observed_at"))
                    validate_observation_receipt(self, actual)
                    if actual.get("result") != "passed":
                        raise ValueError("candidate observation has not passed")
                    surface = self.manifest.get("design_execution", {}).get("review_surface", "external_default")
                    if field == "browser_receipt" and (surface not in ("external_default", "external_named", "in_app") or actual.get("browser_kind") != surface):
                        raise ValueError("browser receipt must match the selected visible review surface")
                    if any(item.get("release_effect") == "blocking" and item.get("status") != "closed" for item in actual.get("findings", [])):
                        raise ValueError("candidate has an open blocking finding")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    self.issue(field, "design", str(error))

    def verification(self, release=False, baseline_required=True):
        record = self.manifest.get("verification", {})
        release_claim = record.get("release_readiness") == "passed"
        if record.get("release_readiness") not in ("not_evaluated", "passed", "blocked"):
            self.issue("release_status", "qa-checklist", "release readiness must be not_evaluated, passed or blocked")
        if record.get("definition_status") != "prepared":
            self.issue("checks_not_prepared", "qa-checklist", "checks must be prepared, not assumed executed")
        self.sources(record, "qa-checklist", ("qa-checklist", "dod-evals"))
        checks, gates = record.get("checks", []), record.get("gates", [])
        if not isinstance(checks, list) or not isinstance(gates, list) or not checks or not gates:
            self.issue("missing_check_index", "qa-checklist", "nonempty hash-bound gate/check index required")
            return
        check_map = {}
        baseline_id = self.manifest.get("approved_baseline_id")
        for check in checks:
            key = check.get("check_id")
            if not key or key in check_map:
                self.issue("check_id", "qa-checklist", "missing or duplicate check ID")
                continue
            check_map[key] = check
            text = self.reference(check.get("definition_ref"), "qa-checklist")
            if key not in text or self.reference_path(check.get("definition_ref")) != "docs/qa-checklist.md":
                self.issue("unresolved_check", "qa-checklist", key)
            status = check.get("execution_status")
            if status not in EXECUTION_STATES or check.get("definition_status") != "prepared":
                self.issue("check_status", "qa-checklist", key)
            if check.get("phase") not in ("prototype", "implementation", "both"):
                self.issue("check_phase", "qa-checklist", key)
            if status in ("blocked", "deferred", "not_applicable") and not check.get("rationale"):
                self.issue("missing_rationale", "qa-checklist", key)
            if check.get("gate_id") in GATE_KINDS and status != "not_applicable":
                scope = check.get("interaction_scope")
                nonvisual = isinstance(scope, dict) and scope.get("kind") == "nonvisual"
                if scope is not None and not nonvisual:
                    self.issue("invalid_check_scope", "qa-checklist", key + ": explicit scope must be nonvisual")
                if nonvisual:
                    if check.get("gate_id") == VISUAL_GATE:
                        self.issue("invalid_check_scope", "qa-checklist", key + ": visual fidelity cannot use nonvisual scope")
                    if not all(isinstance(scope.get(field), str) and scope[field].strip() and scope[field] in text
                               for field in ("context", "rationale")):
                        self.issue("invalid_check_scope", "qa-checklist", key + ": canonical nonvisual context and applicability rationale required")
                else:
                    if not self.ui:
                        self.issue("contradictory_applicability", "qa-checklist", key + ": headless interaction checks need explicit nonvisual scope")
                    if baseline_required and (check.get("baseline_id") != baseline_id or check.get("target_hash") != self.manifest.get("active_baseline", {}).get("visual_target_hash")):
                        self.issue("stale_check_binding", "qa-checklist", key)
                    if not all(check.get(field) for field in ("route", "state", "viewport")):
                        self.issue("missing_check_scope", "qa-checklist", key)
                if not all(check.get(field) for field in ("task", "user_group")):
                    self.issue("missing_check_scope", "qa-checklist", key)
            if status in ("passed", "failed"):
                evidence = check.get("evidence", [])
                if not evidence or not check.get("executor"):
                    self.issue("unsupported_result", "qa-checklist", key + ": execution evidence/executor required")
                try:
                    timestamp(check.get("executed_at"))
                except ValueError as error:
                    self.issue("unsupported_result", "qa-checklist", key + ": " + str(error))
                kinds = set()
                for item in evidence:
                    try:
                        bindings = self.check_bindings(check, evidence=item)
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        self.issue("invalid_evidence", "qa-checklist", str(error))
                        bindings = {}
                    self.evidence_snapshot(item, "qa-checklist", "invalid_evidence", bindings)
                    kinds.add(self.evidence_kind(item))
                expected_kind = "security" if check.get("gate_id") == SECURITY_GATE else GATE_KINDS.get(check.get("gate_id"))
                if expected_kind and expected_kind not in kinds:
                    self.issue("wrong_evidence_class", "qa-checklist", key + ": expected " + expected_kind)
                try:
                    evaluated, _ = self.source_inventory(check, "evaluated_source_hashes")
                except (ValueError, OSError, KeyError, TypeError) as error:
                    self.issue("invalid_evidence", "qa-checklist", str(error))
                    evaluated = {}
                if check.get("phase") in ("implementation", "both") and not evaluated:
                    self.issue("missing_evaluated_revision", "qa-checklist", key)
                if hasattr(self, "_unit_history") and key in self._unit_history.checks:
                    canonical = {spec["path"] for spec in self.specs.values()}
                    evaluated = {path: value for path, value in evaluated.items() if path not in canonical}
                    # Original complete doc hashes were checked in the archived run.
                    # Current acceptance uses the reviewed relevant sections, not old whole-plan bytes.
                elif hasattr(self, "_unit_history") and key in self._unit_history.canonical_evidence:
                    alternatives = self._unit_history.canonical_evidence[key]
                    remaining = {}
                    for path, value in evaluated.items():
                        if path in alternatives and any(hash_matches(value, observed) for observed in alternatives[path]):
                            continue  # Exact archived before/after canonical bytes, with unchanged reviewed acceptance.
                        remaining[path] = value
                    evaluated = remaining
                try:
                    inherited = hasattr(self, "_unit_history") and key in self._unit_history.checks
                    review = None if inherited else validate_revalidation(self, check=check)
                    current = review["current_source_hashes"] if review is not None else evaluated
                    self.sources({"source_hashes": current}, "qa-checklist")
                except (ValueError, OSError, KeyError, TypeError) as error:
                    self.issue("invalid_revalidation", "qa-checklist", str(error))
            elif status == "not_run" and check.get("evidence"):
                self.issue("ambiguous_execution", "qa-checklist", key + ": not_run cannot claim executed evidence")
            for finding in check.get("findings", []):
                severity, effect = finding.get("severity"), finding.get("release_effect")
                if severity not in ("P0", "P1", "P2", "P3") or effect not in ("blocking", "advisory"):
                    self.issue("finding_classification", "qa-checklist", key)
                if severity in ("P0", "P1") and effect != "blocking":
                    self.issue("finding_classification", "qa-checklist", key + ": P0/P1 must block")
                if severity == "P3" and effect != "advisory":
                    self.issue("finding_classification", "qa-checklist", key + ": P3 is advisory")
                if (release or release_claim) and effect == "blocking" and finding.get("status") != "closed":
                    self.issue("open_blocking_finding", "qa-checklist", key)
        gate_ids = set()
        for gate in gates:
            key = gate.get("gate_id")
            if not key or key in gate_ids:
                self.issue("gate_id", "dod-evals", "missing or duplicate gate ID")
                continue
            gate_ids.add(key)
            if not self.ui and key == VISUAL_GATE and gate.get("applicability") != "not_applicable":
                self.issue("contradictory_applicability", "dod-evals", "UI gate in headless scope: " + key)
            text = self.reference(gate.get("definition_ref"), "dod-evals")
            if key not in text or self.reference_path(gate.get("definition_ref")) != "docs/dod-evals.md":
                self.issue("unresolved_gate", "dod-evals", key)
            ids = gate.get("check_ids", [])
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                self.issue("unbound_gate", "dod-evals", key)
                ids = []
            if len(ids) != len(set(ids)) or any(item not in check_map or check_map[item].get("gate_id") != key for item in ids):
                self.issue("unbound_gate", "dod-evals", key)
            for check in checks:
                if check.get("gate_id") == key and check.get("check_id") not in ids:
                    self.issue("unbound_check", "qa-checklist", str(check.get("check_id")))
            if gate.get("applicability") == "not_applicable":
                if not gate.get("rationale"):
                    self.issue("missing_rationale", "dod-evals", key)
                if any(check.get("gate_id") == key and check.get("execution_status") != "not_applicable" for check in checks):
                    self.issue("contradictory_applicability", "dod-evals", key)
                continue
            if gate.get("applicability") != "applicable" or type(gate.get("required")) is not bool:
                self.issue("gate_applicability", "dod-evals", key)
            if gate.get("active") is False:
                self.issue("inactive_load_bearing_gate", "dod-evals", key)
            if not ids:
                self.issue("unbound_gate", "dod-evals", key)
            applicable_checks = [check_map[item] for item in ids if item in check_map
                                 and check_map[item].get("execution_status") != "not_applicable"]
            if not applicable_checks:
                self.issue("empty_applicable_gate", "dod-evals", key + ": resolve applicability; excluded checks cannot satisfy it")
            if key == "heuristic_usability_review":
                applicable = {h for check in applicable_checks for h in check.get("heuristic_ids", [])}
                excluded = gate.get("not_applicable_heuristics", {})
                if not isinstance(excluded, dict) or any(not reason for reason in excluded.values()):
                    self.issue("heuristic_coverage", "qa-checklist", "excluded heuristics need reasons")
                    excluded = {}
                expected = {"H" + str(i) for i in range(1, 11)}
                if applicable.intersection(excluded) or applicable.union(excluded) != expected:
                    self.issue("heuristic_coverage", "qa-checklist", "account for H1-H10 without contradictory applicability")
            if (release or release_claim) and gate.get("required"):
                for item in ids:
                    check = check_map.get(item, {})
                    if check.get("execution_status") not in ("passed", "not_applicable"):
                        self.issue("required_check_incomplete" if release else "unsupported_release_claim", "qa-checklist", str(item))
        for check in checks:
            if check.get("gate_id") not in gate_ids:
                self.issue("unknown_gate", "qa-checklist", str(check.get("check_id")))
        for key in GATE_KINDS:
            if key not in gate_ids:
                self.issue("missing_ui_gate", "dod-evals", key + ": declare applicable or source-backed not_applicable")
        self.security_verification(checks, gates)

    def promotions(self, release=False):
        for record in self.manifest.get("prototype_promotions", []):
            if not release and not record.get("started_at"):
                continue
            mappings = record.get("path_mappings", [])
            if not mappings:
                self.issue("promotion_mapping", "implementation", "declared reuse requires path mappings")
                continue
            try:
                destinations = [self.path(item["destination"]).exists() for item in mappings]
                if release and not all(destinations):
                    self.issue("promotion_destination", "implementation", str(record.get("unit_id")))
                if not any(destinations):
                    continue
                receipt = record.get("receipt", {})
                if not self.evidence_snapshot(receipt, "implementation", "promotion_receipt", {"unit_id": record.get("unit_id"), "baseline_id": self.manifest.get("approved_baseline_id"), "development_plan_hash": self.artifacts.get("development-plan", {}).get("content_hash")}):
                    continue
                actual = self.evidence_json(receipt)
                if not record.get("unit_id") or actual.get("unit_id") != record["unit_id"] or actual.get("baseline_id") != self.manifest.get("approved_baseline_id") or actual.get("development_plan_hash") != self.artifacts.get("development-plan", {}).get("content_hash"):
                    raise ValueError("promotion receipt does not match current unit/plan/baseline")
                observed = actual.get("path_mappings", [])
                mapping_key = lambda item: tuple(item.get(key) for key in ("source", "destination", "strategy"))
                if sorted(mapping_key(item) for item in observed) != sorted(mapping_key(item) for item in mappings):
                    raise ValueError("promotion strategy/path mismatch")
                for item in mappings:
                    self.path(item["source"])
                    if item.get("strategy") not in ("copy", "adapt", "reimplement"):
                        raise ValueError("unknown promotion strategy")
                self.promotion_provenance(record, actual, release)
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.issue("promotion_receipt", "implementation", str(error))

    def promotion_provenance(self, record, actual, release):
        units = self.artifacts.get("development-plan", {}).get("traceability", {}).get("definitions", [])
        if not any(item.get("id") == record.get("unit_id") and item.get("kind") == "unit" for item in units):
            raise ValueError("promotion unit is not defined in the current plan")
        if type(actual.get("schema_version")) is not int or actual["schema_version"] != 1:
            raise ValueError("promotion schema_version 1 required")
        for key in ("promotion_id", "run_id", "candidate_id", "version"):
            if not isinstance(actual.get(key), str) or not actual[key].strip():
                raise ValueError("missing promotion field: " + key)
        baseline = self.manifest.get("active_baseline", {})
        for key in ("visual_target_hash", "candidate_id", "version", "prototype_source_root", "prototype_tree_hash"):
            if not baseline.get(key) or actual.get(key) != baseline[key]:
                raise ValueError("promotion baseline mismatch: " + key)
        if actual.get("development_plan_ref") != self.specs["development-plan"]["path"]:
            raise ValueError("promotion needs canonical plan reference")
        if timestamp(actual.get("completed_at")) < timestamp(record.get("started_at")):
            raise ValueError("promotion completion precedes execution")
        for key in ("adaptations", "variances"):
            if not isinstance(actual.get(key), list):
                raise ValueError("promotion needs explicit " + key)
        if actual.get("verification_status") not in ("passed", "failed", "blocked") or (release and actual["verification_status"] != "passed"):
            raise ValueError("promotion verification is not complete")
        qa = {item["check_id"]: item for item in self.manifest.get("verification", {}).get("checks", [])}
        ids = actual.get("qa_ids")
        if not isinstance(ids, list) or not ids or any(key not in qa for key in ids):
            raise ValueError("promotion needs real QA IDs")
        if release and any(qa[key].get("execution_status") != "passed" for key in ids):
            raise ValueError("promotion QA has not passed")
        evidence = actual.get("visual_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("promotion needs actual visual evidence")
        for item in evidence:
            if self.evidence_kind(item) != "visual" or not self.evidence_snapshot(item, "implementation", "promotion_receipt"):
                raise ValueError("invalid promotion visual evidence")
        base, head = actual.get("base_commit"), actual.get("head_commit")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) for value in (base, head)) or base != record.get("base_commit"):
            raise ValueError("promotion needs planned base and actual full commit IDs")
        def git(*args):
            try:
                return subprocess.run(["git", "--literal-pathspecs", *args], cwd=self.project,
                                      capture_output=True, check=True, timeout=30).stdout
            except (subprocess.SubprocessError, OSError) as error:
                raise ValueError("promotion Git provenance unavailable: " + str(error)) from error
        git("merge-base", "--is-ancestor", base, head)
        git("merge-base", "--is-ancestor", head, "HEAD")
        destinations = []
        source_roots = [self.path(baseline["prototype_source_root"])] + [self.path(p) for p in baseline.get("render_dependencies", [])]
        for item in actual["path_mappings"]:
            source = self.path(item["source"], no_links=True)
            destination = self.path(item["destination"], no_links=True)
            if not any(source == root or root in source.parents for root in source_roots):
                raise ValueError("promotion source is not in the frozen render bundle")
            if not source.is_file() or not destination.is_file():
                raise ValueError("promotion mappings must enumerate regular files")
            if not hash_matches(item.get("source_hash"), self.file_hash(source)) or not hash_matches(item.get("destination_hash"), self.file_hash(destination)):
                raise ValueError("promotion source/destination bytes changed")
            if digest(git("show", head + ":" + item["destination"])) != self.file_hash(destination):
                raise ValueError("destination differs from promoted commit")
            if item["strategy"] == "copy" and self.file_hash(source) != self.file_hash(destination):
                raise ValueError("copy strategy changed source bytes")
            destinations.append(item["destination"])
        if len(destinations) != len(set(destinations)):
            raise ValueError("duplicate promotion destination")
        paths = sorted(destinations)
        changed = git("diff", "--name-only", "-z", "--no-renames", base, head, "--", *paths).decode().strip("\0").split("\0")
        if sorted(actual.get("changed_paths", [])) != sorted(p for p in changed if p):
            raise ValueError("promotion changed paths mismatch")
        patch = git("diff", "--binary", "--no-ext-diff", "--no-textconv", base, head, "--", *paths)
        if not hash_matches(actual.get("patch_hash"), digest(patch)):
            raise ValueError("promotion patch hash mismatch")

    def authorization(self):
        gate = self.manifest.get("implementation_gate", {})
        plan = self.artifacts.get("development-plan", {})
        return self.authorization_record(gate, plan.get("content_hash"), self.manifest.get("approved_baseline_id"))

    def authorization_record(self, gate, plan_hash, baseline):
        """Check current or preserved original authorization; review grants none."""
        if not isinstance(gate, dict):
            self.issue("implementation_not_authorized", "implementation", "implementation_gate must be an object")
            return False
        if gate.get("state") != "authorized_for_phase3" or gate.get("development_plan_hash") != plan_hash or gate.get("approved_baseline_id") != baseline:
            self.issue("implementation_not_authorized", "implementation", "separate prompt must match current plan and baseline")
            return False
        receipt = gate.get("prompt_receipt", {})
        if not self.evidence_snapshot(receipt, "implementation", "prompt_receipt", {key: gate.get(key) for key in ("prompt_id", "approved_baseline_id")}):
            return False
        try:
            prompt = self.evidence_json(receipt)
            # A verified correction retains the original event and its original
            # plan binding, even when that receipt lives in an evidence archive.
            original_bindings = {key: prompt.get(key) for key in ("prompt_id", "development_plan_hash", "approved_baseline_id")}
            if not self.evidence_snapshot(receipt, "implementation", "prompt_receipt", original_bindings):
                return False
            if prompt.get("event") != "implementation_prompt" or prompt.get("intent") != "start_production_implementation" or prompt.get("role") != "user":
                raise ValueError("explicit user implementation event required")
            scope = self.manifest.get("product_scope")
            if scope is not None:
                scope_hash = digest(json.dumps({key: scope[key] for key in ("profile", "capabilities")}, sort_keys=True, separators=(",", ":")).encode())
                if not hash_matches(gate.get("product_scope_hash"), scope_hash) or prompt.get("product_scope_hash") != gate.get("product_scope_hash"):
                    raise ValueError("implementation prompt must bind the current product_scope_hash")
            for field in ("prompt_id", "approved_baseline_id"):
                missing = field not in gate or (not gate.get(field) and (field != "approved_baseline_id" or self.ui))
                if missing or field not in prompt or prompt.get(field) != gate.get(field):
                    raise ValueError("prompt receipt mismatch: " + field)
            if not isinstance(prompt.get("development_plan_hash"), str) or not HASH_RE.fullmatch(prompt["development_plan_hash"]):
                raise ValueError("prompt receipt missing/invalid development_plan_hash")
            if str(prompt.get("message", "")).strip().lower().rstrip(".! ") in ("", "continue", "продовжуй", "продовжити"):
                raise ValueError("generic continuation does not authorize implementation")
            if not (timestamp(gate.get("awaiting_at")) < timestamp(gate.get("prompt_received_at")) <= timestamp(gate.get("released_at"))):
                raise ValueError("implementation prompt must be later than the completed-plan pause")
            if timestamp(gate.get("released_at")) > datetime.now().astimezone():
                raise ValueError("future implementation authorization cannot permit execution")
            if timestamp(prompt.get("received_at")) != timestamp(gate.get("prompt_received_at")):
                raise ValueError("prompt timestamp mismatch")
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            self.issue("prompt_receipt", "implementation", str(error))
            return False
        corrections = gate.get("correction_receipts", [])
        if corrections or "correction_receipts" in gate:
            try:
                self.authorization_corrections(gate, prompt, corrections)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
                self.issue("authorization_correction", "implementation", str(error))
                return False
        elif prompt["development_plan_hash"] != gate["development_plan_hash"]:
            self.issue("prompt_receipt", "implementation", "prompt receipt mismatch: development_plan_hash; verified correction chain required")
            return False
        return True

    def correction_snapshot(self, reference):
        """Read a hash-bound immutable correction input without following links."""
        path = self.path(reference["path"], no_links=True)
        observed = self.file_hash(path)
        if not hash_matches(reference.get("content_hash"), observed):
            raise ValueError("missing/changed correction snapshot: " + reference["path"])
        return path, observed

    @staticmethod
    def correction_json_equal(observed, expected):
        # Python equality treats True == 1; unchanged JSON must retain its types.
        return json.dumps(observed, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)

    @staticmethod
    def correction_projection(path, heading, expected):
        blocks = re.findall(r"```json\s*\n(.*?)\n```", section_bytes(path, heading).decode("utf-8"), re.S)
        if len(blocks) != 1:
            raise ValueError(str(path) + ": correction changed the canonical acceptance/unit contract")
        observed = json.loads(blocks[0], object_pairs_hook=unique_object)
        if not Checker.correction_json_equal(observed, expected):
            raise ValueError(str(path) + ": correction changed the canonical acceptance/unit contract")

    def authorization_corrections(self, gate, prompt, references):
        """Permit only independently reviewed documentation continuity from the original prompt."""
        def require(condition, message):
            if not condition:
                raise ValueError(message)

        def nonempty(value):
            return isinstance(value, str) and bool(value.strip())

        def ids(values, label):
            require(isinstance(values, list) and values and all(nonempty(value) for value in values), label + ": nonempty ID list required")
            require(len(values) == len(set(values)), label + ": duplicate IDs")
            return set(values)

        def normalized(value):
            require(isinstance(value, str) and HASH_RE.fullmatch(value), "invalid correction plan hash")
            return HASH_RE.fullmatch(value)[1].lower()

        require(isinstance(references, list), "correction_receipts must be an ordered list")
        if not references:
            require(prompt["development_plan_hash"] == gate["development_plan_hash"], "verified correction chain required for changed plan")
            return
        require(prompt.get("product_scope_hash") == gate.get("product_scope_hash"), "correction must retain original authorized product scope")
        if self.manifest.get("product_scope") is None:
            require(prompt.get("product_scope_hash") is None, "absent product scope requires null correction scope binding")
        now = datetime.now().astimezone()
        received, released = timestamp(prompt["received_at"]), timestamp(gate["released_at"])
        baseline = None
        if self.ui:
            active = self.manifest["active_baseline"]
            require(active.get("baseline_id") == prompt["approved_baseline_id"], "correction baseline differs from original authorization")
            baseline = {key: active[key] for key in ("prototype_tree_hash", "visual_target_hash")}
            approval_path, _ = self.correction_snapshot(active["approval_receipt"])
            approval = read_json(approval_path)
            require(approval.get("event") in ("approve_design_baseline", "accepted_scoped_baseline_override") and nonempty(approval.get("actor")), "original baseline approval required")
            require(all(approval.get(key) == active.get(key) for key in ("baseline_id", "prototype_tree_hash", "visual_target_hash")), "original baseline approval changed")
            require(timestamp(approval.get("approved_at")) < received, "original baseline approval must predate implementation prompt")
        else:
            require(prompt["approved_baseline_id"] is None, "headless correction requires null baseline")
        # Both canonical projections remain unchanged; execution results are deliberately excluded.
        unit_plan = self.manifest["unit_plan"]
        qa_ref = self.manifest["verification"]["acceptance_ref"]
        projections = {
            "docs/development-plan.md": (unit_plan["definition_ref"]["heading"], unit_plan),
            "docs/qa-checklist.md": (qa_ref["heading"], {
                check["check_id"]: check["acceptance"] for check in self.manifest["verification"]["checks"]
                if check.get("phase") in ("implementation", "both") and check.get("execution_status") != "not_applicable"})}
        for path, (heading, expected) in projections.items():
            self.correction_projection(self.path(path), heading, expected)
        owners = {spec["path"]: (key, spec["owner_skill"]) for key, spec in self.specs.items() if key not in self.skipped}
        current_hash = normalized(prompt["development_plan_hash"])
        visited, receipt_paths, latest_owners = {current_hash}, set(), {}
        previous_inventory = None
        previous_time = released
        for reference in references:
            receipt_path, _ = self.correction_snapshot(reference)
            require(receipt_path not in receipt_paths, "duplicate correction receipt")
            receipt_paths.add(receipt_path)
            correction = read_json(receipt_path)
            require(correction.get("event") == "approved_decision_documentation_correction" and type(correction.get("version")) is int and correction["version"] == 1, "unsupported correction event/version")
            author = correction.get("author")
            require(nonempty(author), "correction author required")
            recorded = timestamp(correction.get("recorded_at"))
            require(released < recorded <= now and previous_time <= recorded, "correction chain must be chronological after original release")
            require(normalized(correction.get("from_plan_hash")) == current_hash, "discontinuous correction plan chain")
            next_hash = normalized(correction.get("to_plan_hash"))
            require(next_hash not in visited, "cyclic/unchanged correction plan chain")
            require("approved_baseline_id" in correction and correction["approved_baseline_id"] == prompt["approved_baseline_id"], "correction baseline differs from original authorization")
            require("product_scope_hash" in correction and correction["product_scope_hash"] == prompt.get("product_scope_hash"), "correction product scope differs from original authorization")
            require("baseline" in correction and correction["baseline"] == baseline, "correction frozen baseline changed")
            inventory = correction["source_snapshots"]
            require(isinstance(inventory, dict) and set(inventory) == set(owners), "complete canonical source snapshot inventory required")
            inventory_hashes, changed_paths = {}, set()
            for path, snapshots in inventory.items():
                require(isinstance(snapshots, dict) and set(snapshots) == {"before", "after"}, "source inventory needs before/after snapshots: " + path)
                before_path, before_hash = self.correction_snapshot(snapshots["before"])
                after_path, after_hash = self.correction_snapshot(snapshots["after"])
                if previous_inventory is not None:
                    require(before_hash == normalized(previous_inventory[path]["after_hash"]), "discontinuous canonical source inventory: " + path)
                if before_hash != after_hash:
                    changed_paths.add(path)
                if path in projections:
                    heading, expected = projections[path]
                    self.correction_projection(before_path, heading, expected)
                    self.correction_projection(after_path, heading, expected)
                inventory_hashes[path] = {"before_hash": snapshots["before"]["content_hash"], "after_hash": snapshots["after"]["content_hash"]}
            if previous_inventory is None:
                original_path, _ = self.correction_snapshot(correction["original_manifest"])
                original = read_json(original_path)
                original_gate = original["implementation_gate"]
                require(original_gate.get("state") == "authorized_for_phase3" and original_gate.get("correction_receipts", []) == [], "original manifest must preserve initial authorization")
                require(normalized(original_gate.get("development_plan_hash")) == current_hash, "original manifest does not bind original authorized plan")
                for field in ("prompt_id", "prompt_receipt", "awaiting_at", "prompt_received_at", "released_at", "approved_baseline_id", "product_scope_hash"):
                    require(original_gate.get(field) == gate.get(field), "original manifest authorization mismatch: " + field)
                require("approved_baseline_id" in original_gate, "original authorization must bind an explicit baseline, including null for headless scope")
                require(original.get("approved_baseline_id") == prompt["approved_baseline_id"], "original manifest baseline mismatch")
                original_scope, current_scope = original.get("product_scope"), self.manifest.get("product_scope")
                require(self.correction_json_equal(
                    {key: original_scope[key] for key in ("profile", "capabilities")} if original_scope is not None else None,
                    {key: current_scope[key] for key in ("profile", "capabilities")} if current_scope is not None else None), "original manifest product scope mismatch")
                if self.ui:
                    require(all(original["active_baseline"].get(key) == self.manifest["active_baseline"].get(key) for key in ("baseline_id", "prototype_tree_hash", "visual_target_hash")), "original manifest frozen baseline mismatch")
                supported_original = (original.get("checker_contract_version"), original.get("unit_contract_version")) in ((1, 1), (2, 2))
                require(supported_original and all(type(original.get(k)) is int for k in ("checker_contract_version", "unit_contract_version")) and self.correction_json_equal(original["unit_plan"], unit_plan), "original manifest unit contract changed")
                original_verification = original["verification"]
                original_qa = {check["check_id"]: check["acceptance"] for check in original_verification["checks"]
                    if check.get("phase") in ("implementation", "both") and check.get("execution_status") != "not_applicable"}
                require(len(original_qa) == sum(check.get("phase") in ("implementation", "both") and check.get("execution_status") != "not_applicable" for check in original_verification["checks"]), "duplicate original manifest QA acceptance checks")
                require(self.correction_json_equal(original_qa, projections["docs/qa-checklist.md"][1]) and original_verification["acceptance_ref"] == qa_ref, "original manifest QA acceptance contract changed")
                for path, (key, owner) in owners.items():
                    artifact = original["artifacts"][key]
                    require(artifact.get("path") == path and artifact.get("owner_skill") == owner and nonempty(artifact.get("owner_invocation_id")), "original manifest owner/path mismatch: " + path)
                    require(normalized(artifact.get("content_hash")) == normalized(inventory_hashes[path]["before_hash"]), "original manifest source differs from first before snapshot: " + path)
            else:
                require("original_manifest" not in correction, "later correction cannot replace original manifest")
            decisions = correction["decisions"]
            require(isinstance(decisions, list) and decisions, "original approved decisions required")
            decision_ids = []
            for decision_ref in decisions:
                decision_path, _ = self.correction_snapshot(decision_ref)
                decision = read_json(decision_path)
                require(decision.get("event") == "approved_decision" and decision.get("role") == "user" and nonempty(decision.get("decision_id")) and nonempty(decision.get("message")), "explicit original user decision required")
                require(timestamp(decision.get("approved_at")) <= received, "decision must predate original implementation prompt")
                decision_ids.append(decision["decision_id"])
            decision_set = ids(decision_ids, "decisions")
            documents = correction["documents"]
            require(isinstance(documents, list) and documents, "changed canonical documents required")
            bindings, used_decisions = {}, set()
            for document in documents:
                path = document["path"]
                require(path in owners and path not in bindings, "noncanonical/duplicate correction document")
                key, owner = owners[path]
                require(document.get("owner_skill") == owner and nonempty(document.get("owner_invocation_id")), "correction document owner/invocation mismatch")
                cited = ids(document.get("decision_ids"), path)
                require(cited <= decision_set, "correction document references unknown decision")
                used_decisions.update(cited)
                require(document["before"] == inventory[path]["before"] and document["after"] == inventory[path]["after"], "document snapshots differ from complete source inventory: " + path)
                bindings[path] = {"before_hash": document["before"]["content_hash"], "after_hash": document["after"]["content_hash"]}
                latest_owners[path] = (document["owner_invocation_id"], key)
            require(used_decisions == decision_set, "unused correction decisions")
            require(set(bindings) == changed_paths, "correction documents must equal exactly the changed canonical source inventory")
            require("docs/development-plan.md" in bindings, "correction must include development plan")
            plan_binding = bindings["docs/development-plan.md"]
            require(normalized(plan_binding["before_hash"]) == current_hash and normalized(plan_binding["after_hash"]) == next_hash, "correction plan snapshots do not bind chain")
            review_path, _ = self.correction_snapshot(correction["review"])
            review = read_json(review_path)
            require(review.get("event") == "documentation_correction_review" and nonempty(review.get("reviewer")) and review["reviewer"].strip() != author.strip(), "independent correction reviewer required")
            reviewed = timestamp(review.get("reviewed_at"))
            require(recorded <= reviewed <= now, "correction review timestamp invalid")
            require(review.get("result") == "preserves_approved_intent" and nonempty(review.get("rationale")), "review must preserve approved intent with rationale")
            require(review.get("documents") == bindings, "review must bind exactly every correction diff")
            require(review.get("source_snapshots") == inventory_hashes, "review must bind the complete canonical source inventory")
            require(ids(review.get("decision_ids"), "review decisions") == decision_set, "review decision set mismatch")
            dimensions = {"scope", "behavior", "design", "security", "cost", "acceptance", "unit_contract", "permissions"}
            unchanged = review.get("unchanged")
            require(isinstance(unchanged, dict) and set(unchanged) == dimensions and all(value is True for value in unchanged.values()), "review must preserve every authorization dimension")
            current_hash = next_hash
            visited.add(current_hash)
            previous_time = reviewed
            previous_inventory = inventory_hashes
        require(current_hash == normalized(gate["development_plan_hash"]), "correction chain does not reach current plan")
        for path, hashes in previous_inventory.items():
            require(hash_matches(hashes["after_hash"], self.file_hash(self.path(path, no_links=True))), "latest correction snapshot differs from current canonical bytes: " + path)
        for path, (invocation, key) in latest_owners.items():
            require(self.artifacts[key].get("owner_invocation_id") == invocation, "latest correction owner invocation differs from current owner return: " + path)

    def canonical_json(self, path, heading, expected):
        text = self.reference({"path": path, "heading": heading}, "development-plan")
        blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
        if len(blocks) != 1 or json.loads(blocks[0], object_pairs_hook=unique_object) != expected:
            raise ValueError(path + ": canonical JSON and projection differ")

    @staticmethod
    def canonical_json_bytes(data, heading, expected):
        text = section_from_bytes(data, heading).decode("utf-8")
        blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
        if len(blocks) != 1 or json.loads(blocks[0], object_pairs_hook=unique_object) != expected:
            raise ValueError("original plan canonical JSON and projection differ")

    def units(self, action=None, unit_id=None, release=False):
        """Validate planning separately from recorded runs and requested transitions."""
        if type(self.manifest.get("unit_contract_version")) is not int or self.manifest["unit_contract_version"] not in (1, 2):
            self.issue("migration_required", "development-plan", "owner-reviewed supported unit contract records required; do not infer completed units")
            return
        try:
            self.validate_units(action, unit_id, release)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            self.issue("unit_contract", "development-plan", str(error))

    def validate_units(self, action, unit_id, release):
        def require(condition, message):
            if not condition:
                raise ValueError(message)

        def ids(value, label, nonempty=False):
            require(isinstance(value, list) and all(isinstance(x, str) and x for x in value), label + ": ID/path list required")
            require(len(value) == len(set(value)) and (value or not nonempty), label + ": empty or duplicate entries")
            return set(value)

        plan = self.manifest["unit_plan"]
        require(plan.get("policy") == "strict_sequential", "unsupported unit execution policy")
        require(plan["definition_ref"]["path"] == "docs/development-plan.md", "unit contract belongs to development plan")
        self.canonical_json("docs/development-plan.md", plan["definition_ref"]["heading"], plan)
        order = plan["order"]
        unit_ids = ids(order, "order", True)
        units, acceptance = plan["units"], plan["acceptance"]
        require(isinstance(units, dict) and set(units) == unit_ids, "order must contain every unit exactly once")
        require(isinstance(acceptance, dict) and acceptance, "acceptance ownership required")
        numbered = [UNIT_ID_RE.fullmatch(key) for key in order]
        require(all(numbered), "unit IDs require one shared prefix and a final ASCII integer, e.g. UNIT-001; reconcile legacy IDs")
        require(len({match[1] for match in numbered}) == 1, "unit IDs must use one shared prefix across the plan")
        numbers = [int(match[2]) for match in numbered]
        require(len(set(numbers)) == len(numbers), "unit numbers must be unique, including zero-padded aliases")
        positions = {key: index for index, key in enumerate(order)}
        trace = self.artifacts["development-plan"]["traceability"]
        defined_units = {x["id"] for x in trace["definitions"] if x.get("kind") == "unit"}
        require(defined_units == unit_ids, "unit IDs must match the plan traceability index")
        obligations = {x["id"] for name in ("prd", "screen-map") for x in self.artifacts.get(name, {}).get("traceability", {}).get("definitions", [])
                       if x.get("kind") in ("requirement", "state") and x.get("required")}
        contributions = {(x["from"], x["to"]) for x in trace["links"] if x.get("relation") == "implements"}
        verifies = {(x["from"], x["to"]) for x in self.artifacts["qa-checklist"]["traceability"]["links"] if x.get("relation") == "verifies"}
        checks = {x["check_id"]: x for x in self.manifest["verification"]["checks"]}
        # Every implementation check has an owner, including advisory and deferred work.
        eligible = {key for key, value in checks.items() if value.get("phase") in ("implementation", "both") and value.get("execution_status") != "not_applicable"}
        require(set(acceptance) == eligible, "every applicable implementation check needs exactly one acceptance owner; unknown/excluded check")
        qa_contract = {key: checks[key]["acceptance"] for key in sorted(eligible)}
        qa_ref = self.manifest["verification"]["acceptance_ref"]
        require(qa_ref["path"] == "docs/qa-checklist.md", "acceptance definitions belong to QA")
        self.canonical_json("docs/qa-checklist.md", qa_ref["heading"], qa_contract)
        edges = {key: set() for key in unit_ids}
        check_edges = {}
        for key, unit in units.items():
            require(isinstance(unit.get("scope"), str) and unit["scope"].strip(), key + ": scope required")
            require(unit.get("kind") in ("implementation", "integration", "release"), key + ": invalid kind")
            require(isinstance(unit.get("owner"), str) and unit["owner"].strip(), key + ": responsible owner required")
            deps = ids(unit["construction_dependencies"], key + " construction")
            require(deps <= unit_ids and key not in deps, key + ": unknown/self construction dependency")
            edges[key].update(deps)
            sources = ids(unit["implementation_paths"], key + " implementation paths", True)
            for path in sources:
                self.path(path)  # Files may be absent at planning time; execution hashes cannot be absent.
            required = ids(unit["required_check_ids"], key + " required checks", True)
            require(required <= eligible, key + ": unknown required acceptance check")
            for check_id in required:
                require(acceptance[check_id]["owner_unit"] == key, check_id + ": missing/invalid acceptance owner")
        for key, record in acceptance.items():
            owner = record["owner_unit"]
            require(owner in units, key + ": unknown acceptance owner")
            qa = qa_contract[key]
            require(type(qa.get("required")) is bool, key + ": QA required flag missing")
            require(qa.get("level") in ("unit", "integration", "release"), key + ": acceptance level required")
            require(qa.get("evidence_mode") in ("component", "real_consumers"), key + ": evidence mode required")
            if qa["level"] != "unit":
                require(qa["evidence_mode"] == "real_consumers" and units[owner]["kind"] in ("integration", "release"), key + ": integration/release acceptance needs integration ownership and real consumers")
            if qa["level"] == "release":
                require(units[owner]["kind"] == "release", key + ": release owner required")
            require((key in units[owner]["required_check_ids"]) == qa["required"], key + ": required membership differs from QA")
            gates = {x["gate_id"]: x for x in self.manifest["verification"]["gates"]}
            if gates.get(checks[key]["gate_id"], {}).get("required"):
                require(qa["required"], key + ": required gate cannot become advisory unit acceptance")
            deps = ids(record["prerequisite_units"], key + " prerequisites")
            require(deps <= unit_ids and owner not in deps, key + ": unknown/self acceptance prerequisite")
            prerequisites = ids(record["prerequisite_checks"], key + " prerequisite checks")
            require(prerequisites <= eligible and key not in prerequisites, key + ": unknown/self prerequisite check")
            check_edges[key] = prerequisites
            bound = ids(record["obligation_ids"], key + " obligations")
            require(bound <= obligations and all((key, obligation) in verifies and (owner, obligation) in contributions for obligation in bound), key + ": acceptance obligation lacks verification/contribution trace")
            edges[owner].update(deps)
            for prerequisite in prerequisites:
                other = acceptance[prerequisite]["owner_unit"]
                require(other in units, prerequisite + ": unknown acceptance owner")
                if other != owner:
                    edges[owner].add(other)
            ids(qa["required_source_paths"], key + " evidence source paths", True)
            for path in qa["required_source_paths"]:
                self.path(path)
        # No required product clause/state may disappear into mere contribution coverage.
        covered = {obligation for key, record in acceptance.items() if qa_contract[key]["required"] and qa_contract[key]["level"] in ("integration", "release") for obligation in record["obligation_ids"]}
        require(obligations <= covered, "required obligation lacks full integration/release acceptance ownership; component contribution is insufficient")
        validate_construction(self, plan, obligations, contributions, checks)

        def acyclic(graph, label):
            pending = {key: set(value) for key, value in graph.items()}
            while pending:
                ready = {key for key, value in pending.items() if not value}
                require(ready, label + ": dependency cycle")
                pending = {key: value - ready for key, value in pending.items() if key not in ready}
        acyclic(check_edges, "acceptance checks")
        for key, prerequisites in check_edges.items():
            if qa_contract[key]["required"]:
                require(all(qa_contract[prior]["required"] for prior in prerequisites), key + ": required check prerequisites must be required acceptance of their owners")
        acyclic(edges, "combined construction/acceptance")
        for key, deps in edges.items():
            require(all(positions[dep] < positions[key] for dep in deps), key + ": forward acceptance/construction prerequisite under strict sequential execution")
        require(numbers == sorted(numbers), "unit numbers must increase in execution order; a lower-numbered unit cannot depend on a higher-numbered unit by reordering the list")
        self._unit_progress_state = {"total_units": len(order), "accepted_unit_ids": None,
                                     "eligible_unit_ids": [], "run_blockers": []}

        runs = self.manifest.get("unit_runs", {})
        require(isinstance(runs, dict) and set(runs) <= unit_ids, "unknown unit run")
        exceptions = self.manifest.get("unit_sequence_exceptions", [])
        require(isinstance(exceptions, list), "sequence exceptions must be receipts")
        plan_hash = self.artifacts["development-plan"]["content_hash"]
        baseline = self.manifest.get("approved_baseline_id")
        now = datetime.now().astimezone()
        reviews = {key: validate_revalidation(self, unit_id=key) for key, run in runs.items()
                   if run.get("revalidation_ref") is not None and not (hasattr(self, "_unit_history") and key in self._unit_history.preserved)}
        waivers = []
        for receipt in exceptions:
            require(self.evidence_snapshot(receipt, "implementation", "unit_exception"), "invalid sequencing receipt")
            event = self.evidence_json(receipt)
            require(event.get("event") == "unit_sequence_exception" and event.get("role") == "user" and event.get("message") and event.get("prompt_id"), "explicit original user sequencing event required")
            require(str(event["message"]).strip().lower().rstrip(".! ") not in ("", "continue", "продовжуй", "продовжити"), "generic continuation is not a sequencing exception")
            require(event.get("development_plan_hash") == plan_hash and "approved_baseline_id" in event and event["approved_baseline_id"] == baseline, "sequencing exception is stale")
            target = event["unit_id"]
            require(target in units, "exception targets unknown unit")
            skipped = ids(event["prior_unit_ids"], "exception prior units", True)
            require(skipped <= {x for x in order[:positions[target]]} and not skipped & edges[target], "exception cannot waive construction/acceptance prerequisites")
            received = timestamp(event["received_at"])
            require(timestamp(self.manifest["implementation_gate"]["prompt_received_at"]) <= received <= now, "exception event time invalid")
            waivers.append((target, skipped, received))

        def blocking(findings):
            require(isinstance(findings, list) and all(isinstance(x, dict) for x in findings), "findings list required")
            for finding in findings:
                require(finding.get("severity") in ("P0", "P1", "P2", "P3") and finding.get("release_effect") in ("blocking", "advisory") and finding.get("status") in ("open", "closed"), "invalid unit finding")
            return any((x["severity"] in ("P0", "P1") or x["release_effect"] == "blocking") and x["status"] != "closed" for x in findings)

        def passed(check_id, started, finished, seen=None):
            seen = set() if seen is None else seen
            if check_id in seen:
                return
            seen.add(check_id)
            check, record, qa = checks[check_id], acceptance[check_id], qa_contract[check_id]
            if hasattr(self, "_unit_history") and check_id in self._unit_history.checks:
                require(timestamp(check.get("executed_at")) <= finished, check_id + ": inherited evidence postdates dependent execution")
                require(record["owner_unit"] in self._unit_history.preserved, check_id + ": historical acceptance has no applicable completed owner")
                return  # Full original QA/chronology plus current freshness were validated by the shared resolver.
            review = reviews.get(record["owner_unit"])
            require(check.get("execution_status") == "passed" and check.get("definition_status") == "prepared", check_id + ": required acceptance is not passed")
            require(review is not None or check.get("evaluated_plan_hash") == plan_hash, check_id + ": evidence belongs to another plan")
            executed = timestamp(check.get("executed_at"))
            require(started <= executed <= finished, check_id + ": evidence outside current unit run")
            require(check.get("executor") and check.get("evidence"), check_id + ": missing executed evidence")
            require(not blocking(check.get("findings", [])), check_id + ": unresolved blocking finding")
            paths = set(qa["required_source_paths"])
            for dep in {record["owner_unit"]} | edges[record["owner_unit"]]:
                paths.update(units[dep]["implementation_paths"])
            hashes, _ = self.source_inventory(check, "evaluated_source_hashes")
            require(isinstance(hashes, dict) and paths <= set(hashes), check_id + ": evidence does not cover required implementation/consumer paths")
            for path, value in hashes.items():
                if hasattr(self, "_unit_history"):
                    alternatives = self._unit_history.canonical_evidence.get(check_id, {}).get(path, set())
                    if any(hash_matches(value, observed) for observed in alternatives):
                        continue
                current_value = review["current_source_hashes"][path] if review is not None else value
                require(self.snapshot(path, current_value, "implementation", "unit_stale_evidence"), check_id + ": stale implementation evidence")
            for evidence in check["evidence"]:
                ref = evidence_reference(evidence)
                if ref is not None:
                    require(ref.get("provenance", {}).get("unit_id") == record["owner_unit"], check_id + ": evidence provenance belongs to another unit")
                    if check.get("run_id"):
                        require(ref.get("provenance", {}).get("run_id") == check["run_id"], check_id + ": evidence provenance belongs to another run")
                require(self.evidence_snapshot(evidence, "implementation", "unit_stale_evidence", self.check_bindings(check, evidence=evidence)), check_id + ": unreadable/changed evidence")
            if qa["evidence_mode"] == "real_consumers":
                require(check.get("execution_mode") == "real_consumers" and any(self.evidence_kind(x) == "integration" for x in check["evidence"]), check_id + ": mocks/fixtures cannot replace real-consumer integration evidence")
            for prerequisite in check_edges[check_id]:
                prior_owner = acceptance[prerequisite]["owner_unit"]
                prior_run = runs.get(prior_owner, {})
                prior_review = reviews.get(prior_owner)
                current_acceptance = review["reviewed_at"] if review is not None else executed
                prior_acceptance = prior_review["reviewed_at"] if prior_review is not None else timestamp(checks[prerequisite].get("executed_at"))
                if review is not None or prior_review is not None:
                    require(prior_acceptance <= current_acceptance, check_id + ": prerequisite acceptance/review is later than consumer")
                prior_started = timestamp(prior_run.get("started_at"))
                prior_finished = min(executed, timestamp(prior_run.get("completed_at"))) if prior_owner != record["owner_unit"] else executed
                passed(prerequisite, prior_started, prior_finished, seen)

        completed, original_completed = {}, {}
        def clear_unit_findings(key, run):
            require(not blocking(run.get("findings", [])), key + ": unresolved blocking finding")
            for check_id, allocation in acceptance.items():
                if allocation["owner_unit"] == key:
                    require(not blocking(checks[check_id].get("findings", [])), check_id + ": unresolved blocking finding")

        for key, run in runs.items():
            require(run.get("status") in ("pending", "running", "blocked", "completed"), key + ": invalid unit status")
            if run["status"] == "pending":
                require(not run.get("started_at") and not run.get("completed_at"), key + ": pending run cannot claim execution")
                continue
            if hasattr(self, "_unit_history") and key in self._unit_history.preserved:
                clear_unit_findings(key, run)
                completed[key] = original_completed[key] = timestamp(run["completed_at"])
                continue
            review = reviews.get(key)
            require((review is not None or run.get("development_plan_hash") == plan_hash) and "approved_baseline_id" in run and run["approved_baseline_id"] == baseline, key + ": stale run binding")
            started = timestamp(run.get("started_at"))
            original_gate = review["original_gate"] if review is not None else self.manifest["implementation_gate"]
            require(timestamp(original_gate["released_at"]) <= started <= now, key + ": invalid start time")
            if run["status"] == "blocked":
                require(run.get("reason"), key + ": blocked run needs a reason")
            if run["status"] == "completed":
                if "evidence_storage" in self.manifest:
                    self.evidence_accounting(run_id=run.get("run_id"), unit_id=key)
                finished = timestamp(run.get("completed_at"))
                require(started <= finished <= now, key + ": completion time blocks unit")
                clear_unit_findings(key, run)
                for check_id in units[key]["required_check_ids"]:
                    passed(check_id, started, finished)
                original_completed[key] = finished
                completed[key] = review["reviewed_at"] if review is not None else finished
            else:
                require(not run.get("completed_at"), key + ": unfinished run cannot claim completion time")

        for key, review in reviews.items():
            for prior in edges[key]:
                require(prior in completed and completed[prior] <= review["reviewed_at"], key + ": construction/acceptance prerequisite review is later or incomplete")

        def can_start(key, at, original=False):
            accepted = original_completed if original else completed
            for prior in order[:positions[key]]:
                if prior in accepted and accepted[prior] <= at:
                    continue
                require(prior not in edges[key] and any(target == key and prior in skipped and received <= at for target, skipped, received in waivers), key + ": prior unit " + prior + " incomplete at start without explicit exception")
        for key, run in runs.items():
            if run["status"] != "pending" and not (hasattr(self, "_unit_history") and key in self._unit_history.preserved):
                can_start(key, timestamp(run["started_at"]), original=key in reviews)
        eligible, run_blockers = [], []
        for key in order:
            if key in completed:
                continue
            run = runs.get(key, {})
            if run.get("status") == "blocked":
                run_blockers.append({"unit_id": key, "reason": run["reason"]})
                continue
            try:
                can_start(key, now)
                eligible.append(key)
            except ValueError:
                pass
        self._unit_progress_state.update(
            accepted_unit_ids=[key for key in order if key in completed],
            eligible_unit_ids=eligible, run_blockers=run_blockers)
        if action:
            require(unit_id in units, "unknown boundary unit")
            run = runs.get(unit_id, {"status": "pending"})
            if action == "start":
                require(run["status"] != "completed", unit_id + ": already complete")
                can_start(unit_id, now)
            elif action == "complete":
                if "evidence_storage" in self.manifest:
                    self.evidence_accounting(run_id=run.get("run_id"), unit_id=unit_id)
                require(run["status"] in ("running", "completed"), unit_id + ": unit must be running before completion")
                clear_unit_findings(unit_id, run)
                for check_id in units[unit_id]["required_check_ids"]:
                    passed(check_id, timestamp(run.get("started_at")), now)
        if release:
            require(set(completed) == unit_ids, "release requires every unit, including integration, completed")

    def run(self, node, after=False, audit=False, unit_action=None, unit_id=None, *, require_current=False, projections=True):
        report = None
        try:
            with self.history_hash_scope() as owner:
                self._history_hash_owner = owner
                for record in getattr(self, "_history_snapshot_records", ()):
                    history_api().validate_files(self.project, record, hash_owner=owner)
                report = self._run_invocation(node, after, audit, unit_action, unit_id,
                                              require_current=require_current, projections=projections)
        except (ValueError, OSError) as error:
            if report is None:
                raise
            self.issue("changing_input", "manifest", str(error))
            report["result"] = "blocked"
            if "implementation_progress" in report:
                report["implementation_progress"] = implementation_progress(self, unit_id, unit_action)
        return report

    def _run_invocation(self, node, after=False, audit=False, unit_action=None, unit_id=None, *, require_current=False, projections=True):
        # Resolution is a per-invocation view. Reuse the caller's actual source
        # manifest rather than treating a previous expanded history view as input.
        self.manifest = self._source_manifest
        self.artifacts = self.manifest.get("artifacts", {})
        if hasattr(self, "_unit_history"):
            del self._unit_history
        if hasattr(self, "_unit_progress_state"):
            del self._unit_progress_state
        if not hasattr(self, "_history_stack"):
            self._history_cache = {}
        self.hash_cache.clear()
        self.json_cache.clear()
        self.section_cache.clear()
        self.directory_cache.clear()
        self.accounted_refs.clear()
        self.issues, self.warnings = [], []
        self.checked, self.affected = set(), set()
        self.security_requirements = {}
        self.evidence_resolver = EvidenceResolver(self.evidence_resolver.cache)
        self._invocation_active = True
        try:
            report = self._run(node, after, audit, unit_action, unit_id, require_current=require_current, projections=projections)
            try:
                for cache in (self.hash_cache, self.json_cache, self.evidence_resolver.hashes, self.evidence_resolver.documents):
                    for path, (signature, _) in cache.items():
                        if _regular(path) != signature:
                            raise ValueError("input changed during checker invocation: " + str(path))
                for path, signature in self.directory_cache.items():
                    info = path.lstat()
                    if is_link(path) or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != signature:
                        raise ValueError("prototype directory changed during checker invocation: " + str(path))
            except (ValueError, OSError) as error:
                self.issue("changing_input", "manifest", str(error))
                report["result"] = "blocked"
                if "implementation_progress" in report:
                    report["implementation_progress"] = implementation_progress(self, unit_id, unit_action)
            return report
        finally:
            self._invocation_active = False

    def _run(self, node, after=False, audit=False, unit_action=None, unit_id=None, *, require_current=False, projections=True):
        # Historical snapshots and legacy import validation remain readable. All
        # operational CLI entrypoints require current records before proceeding.
        checker_version, unit_version = self.manifest.get("checker_contract_version"), self.manifest.get("unit_contract_version")
        if require_current:
            versions = (checker_version, unit_version)
            if all(type(value) is int for value in versions) and versions == (2, 2):
                pass
            elif all(value is None or type(value) is int and value == 1 for value in versions):
                self.issue("migration_required", "manifest", "resume with the latest tested workflow: preserve existing work and approvals, migrate legacy records, and reverify before continuing")
            else:
                self.issue("unsupported_contract_version", "manifest", "checker and unit contracts must both be version 2; reconcile mixed, malformed or unsupported versions without rewriting history")
        if checker_version == 1 and history_api().contains_v2_fields(self.manifest):
            self.issue("migration_required", "manifest", "v2 history fields require verified checker/unit contract version 2 migration")
        if checker_version == 2 and unit_version == 2:
            self.manifest = copy.deepcopy(self.manifest)
            self.artifacts = self.manifest.get("artifacts", {})
            self._unit_history = history_api().HistoryView(self)
            try:
                self._unit_history.resolve(node in ("implementation", "release"), unit_action, unit_id)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
                self.issue("unit_history", "development-plan", str(error))
        if "evidence_storage" in self.manifest and not isinstance(self.manifest["evidence_storage"], dict):
            self.issue("evidence_storage", "manifest", "evidence storage declaration must be an object")
        if unit_action is not None and (unit_action not in ("start", "complete") or node != "implementation" or audit or after or not unit_id):
            self.issue("unit_boundary", "implementation", "unit transitions require implementation node, start/complete action and unit ID")
        self.product_scope()
        if type(checker_version) is not int or checker_version not in (1, 2) or (checker_version == 2) != (unit_version == 2):
            self.issue("migration_required", "manifest", "retain existing documents/history; add verified metadata using manifest-contract.md")
        language = self.manifest.get("language", {})
        if not language.get("working_language") or language.get("artifact_language") != language.get("working_language"):
            self.issue("language_record", "manifest", "working and artifact language must agree; UI locales are separate")
        spec = self.contract["nodes"][node] if not audit else {
            "required_before": [key for key in self.artifacts if key not in self.skipped], "outputs": [],
            "baseline_required": self.ui and bool(self.manifest.get("approved_baseline_id")),
            "authorization_required": self.manifest.get("implementation_gate", {}).get("state") == "authorized_for_phase3",
        }
        if not self.ui and (node in self.skipped or node in ("prototype-candidates", "design-approval", "architecture-approved", "dod-evals-approved", "qa-checklist-approved")):
            self.issue("inapplicable_node", "manifest", "headless scope skips UI nodes and uses ordinary owner nodes")
        for key in spec["required_before"] + (spec["outputs"] if after else []):
            if key in self.specs:
                self.artifact(key)
            else:
                self.issue("unknown_artifact", "manifest", key)
        self.bundle()
        self.traceability()
        if spec.get("baseline_required"):
            self.baseline()
            for key in ("architecture", "dod-evals", "qa-checklist", "development-plan"):
                if key in self.checked and self.artifacts.get(key, {}).get("validated_baseline_id") != self.manifest.get("approved_baseline_id"):
                    self.issue("baseline_reconciliation_required", key, "owner must revalidate against the active baseline")
        if spec.get("source_access_required"):
            if self.manifest.get("design_execution", {}).get("mode") not in ("codex", "claude_design"):
                self.issue("design_executor_required", "design", "record the explicit executor choice before generation")
            self.source_access()
        if spec.get("candidates_required") or (after and spec.get("candidates_after")):
            self.candidates()
        if spec.get("verification_required") or "qa-checklist" in self.checked:
            self.verification(release=spec.get("release_required", False), baseline_required=spec.get("baseline_required", False))
        if spec.get("authorization_required"):
            self.authorization()
            self.promotions(release=spec.get("release_required", False))
        if "development-plan" in self.checked:
            if self.manifest.get("unit_contract_version") == 1 and not spec.get("authorization_required") and any(x.get("status") not in (None, "pending") for x in self.manifest.get("unit_runs", {}).values()):
                self.authorization()
            self.units(unit_action, unit_id, release=spec.get("release_required", False) or self.manifest.get("verification", {}).get("release_readiness") == "passed")
        if projections and not hasattr(self, "_history_snapshot_root") and not hasattr(self, "_history_capturing"):
            validate_intake_progress(self)
            validate_ready_projection(self, require_current=require_current)
        result = "blocked" if self.issues else "passed"
        if self.issues and all(item["code"] == "migration_required" for item in self.issues):
            result = "migration_required"
        return {"result": result, "node": node, "mode": "audit" if audit else "after" if after else "before",
                "unit_action": unit_action, "unit_id": unit_id,
                "skipped_artifacts": sorted(self.skipped),
                "checked_artifacts": sorted(self.checked), "affected_artifacts": sorted(self.affected),
                "issues": self.issues, "warnings": sorted(set(self.warnings)),
                **({"implementation_progress": implementation_progress(self, unit_id, unit_action)}
                   if "development-plan" in self.checked else {}),
                **({"unit_history": {"units": self._unit_history.units}, "execution_authority": history_api().current_authority(self)} if hasattr(self, "_unit_history") else {}),
                "limits": "Checks declared metadata, file integrity, stages and evidence references; not semantic quality, research authenticity or runner enforcement."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--before")
    group.add_argument("--after")
    group.add_argument("--start-unit", metavar="UNIT_ID", help="validate authorization, plan and unit start/resume; read-only")
    group.add_argument("--complete-unit", metavar="UNIT_ID", help="validate fresh evidence before recording unit completion; read-only")
    group.add_argument("--audit", action="store_true")
    group.add_argument("--progress", action="store_true", help="derive current next node and unit progress with bounded read-only gate checks")
    group.add_argument("--hash", dest="hash_path")
    group.add_argument("--hash-render", metavar="RECORD", help="hash a candidate/baseline JSON record and its declared render resources")
    group.add_argument("--snapshot", metavar="NODE", help="emit unvalidated owner/source metadata without writing files or claiming review")
    parser.add_argument("--evidence-cache", type=Path, help="read-only prepared evidence cache outside the project; manager performs preparation")
    parser.add_argument("--heading", help="with --hash: exact Markdown heading for a fragment")
    parser.add_argument("--worked-unit", metavar="UNIT_ID", help="with --progress: identify the unit just worked on without inferring it from order")
    parser.add_argument("--consume", action="append", default=[], metavar="PATH[#HEADING]", help="with --snapshot: consumed full file or exact heading; repeat for every consumed section, including shared definitions")
    parser.add_argument("--unused", action="append", default=[], metavar="PATH=REASON", help="with --snapshot: explicitly unused context/optional source; cannot waive other required inputs")
    args = parser.parse_args()
    args.project = args.project.resolve()
    if (args.consume or args.unused) and not args.snapshot:
        parser.error("--consume and --unused require --snapshot")
    if args.worked_unit and not args.progress:
        parser.error("--worked-unit requires --progress")
    if sys.version_info < (3, 12):
        parser.error("Python 3.12+ is required")
    try:
        contract = read_contract()
        validate_contract(contract)
        if args.hash_render:
            checker = Checker(args.project, {}, contract, evidence_cache=args.evidence_cache)
            print(checker.render_hash(read_json(checker.path(args.hash_render))))
            return 0
        if args.hash_path:
            checker = Checker(args.project, {}, contract, evidence_cache=args.evidence_cache)
            path = checker.path(args.hash_path)
            value = digest(section_bytes(path, args.heading)) if args.heading else tree_hash(checker.path(args.hash_path, no_links=True)) if path.is_dir() else hash_file(path)[0]
            print(value)
            return 0
        unit_action = "start" if args.start_unit else "complete" if args.complete_unit else None
        node = "implementation" if unit_action else args.before or args.after or args.snapshot or "audit"
        if not args.audit and not args.progress and node not in contract["nodes"]:
            raise ValueError("unknown node; choose: " + ", ".join(contract["nodes"]))
        manifest_path = args.project / "forge/sdd-manifest.json"
        manifest_signature = _regular(manifest_path)
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        if args.snapshot:
            checker = Checker(args.project, manifest, contract, evidence_cache=args.evidence_cache)
            checker.product_scope()
            if checker.issues:
                raise ValueError("resolve product scope before snapshotting")
            # Escape JSON Unicode for locale-dependent Windows output pipes; decoding preserves text.
            print(json.dumps(checker.source_proposal(node, args.consume, args.unused), ensure_ascii=True, indent=2))
            return 0
        if args.progress:
            with history_api().snapshot_hash_scope():
                checker = Checker(args.project, manifest, contract, evidence_cache=args.evidence_cache)
                report = workflow_progress(checker, worked_unit=args.worked_unit, require_current=True)
                validate_intake_progress(checker)
                validate_ready_projection(checker, derived=report["progress"], require_current=True)
                report["issues"].extend(issue for issue in checker.issues if issue not in report["issues"])
                if report["issues"]:
                    report["result"] = ("migration_required" if all(item["code"] == "migration_required" for item in report["issues"])
                                        else "blocked")
                if _regular(manifest_path) != manifest_signature:
                    raise ValueError("manifest changed during checker invocation")
                report["toolchain"] = toolchain_identity()
            print(json.dumps(report, ensure_ascii=True, indent=2))
            return 0 if report["result"] == "passed" else 2 if report["result"] == "migration_required" else 1
        with history_api().snapshot_hash_scope():
            report = Checker(args.project, manifest, contract, evidence_cache=args.evidence_cache).run(node, bool(args.after), args.audit, unit_action, args.start_unit or args.complete_unit, require_current=True)
            if _regular(manifest_path) != manifest_signature:
                raise ValueError("manifest changed during checker invocation")
            report["toolchain"] = toolchain_identity()
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["result"] == "passed" else 2 if report["result"] == "migration_required" else 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"result": "blocked", "issues": [{"code": "invalid_input", "detail": str(error)}]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
