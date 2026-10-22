"""Bounded foreground handoff to an authenticated Codex or Claude Drive tool.

Python cannot borrow the host's login. Instead the already-running agent services
one native tool request at a time while its foreground evidence command waits.
The queue contains no credentials and starts no server, daemon or new agent.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
import tempfile
import uuid
import urllib.error
import urllib.parse
import urllib.request

from .io import EvidenceError, _open_regular, _verify_stable, atomic_json, read_json
from .transports import (_directory, _destination, _locator_string, _outside_git,
                         _positive, _transport_key)

MAX_CONTROL_BYTES = 1024 * 1024
TOOLS = ("list_folder", "upload_file", "get_file_metadata", "fetch", "delete_file")
CAPABILITIES = ["upload", "download_original", "metadata", "lookup", "list", "delete",
                "stable_object_id", "bounded_original_download"]
FIELDS = "id,name,size,mimeType,parents,trashed"
SESSION_FILES = {"session.json", "request.json", "response.json", "owner.json"}
CONTROL_PEAK_BYTES = 2 * MAX_CONTROL_BYTES + 8192
MAX_DOWNLOAD_SECONDS = 120
MAX_NATIVE_FOLDER_SCAN = 1000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise EvidenceError("authenticated original download redirected; request a fresh file reference")


def _materialize_original(session, request, raw_result):
    """Consume a host-issued signed file reference without persisting its URL."""
    result = _unwrap(raw_result)
    reference = result.get("file_uri")
    if not isinstance(reference, dict) or not isinstance(reference.get("download_url"), str):
        return None
    url = reference["download_url"]
    try:
        parsed = urllib.parse.urlsplit(url)
        allowed_host = parsed.hostname == "oaiusercontent.com" or (parsed.hostname or "").endswith(".oaiusercontent.com")
        if (parsed.scheme != "https" or not allowed_host or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError("unsupported authenticated download host")
    except (ValueError, TypeError) as error:
        raise EvidenceError("authenticated original reference has an unsupported HTTPS destination; use the host's materialized local file") from None
    requirements = request.get("requirements", {})
    maximum = _positive(requirements.get("max_bytes"), "original download bound", zero=True)
    expected = _positive(requirements.get("expected_size"), "expected original size", zero=True)
    declared = result.get("file_size_bytes", reference.get("file_size_bytes"))
    if declared is not None and (isinstance(declared, bool) or not isinstance(declared, int) or declared != expected):
        raise EvidenceError("authenticated original reference has a different size")
    deadline = min(request["expires_at"], time.time() + MAX_DOWNLOAD_SECONDS)
    if expected > maximum or deadline <= time.time():
        raise EvidenceError("original download exceeds size or time allowance")
    target = session / ("original-" + request["request_id"] + ".bin")
    descriptor = None
    succeeded = False
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(urllib.request.Request(url, headers={"Accept-Encoding": "identity"}),
                         timeout=min(10, max(0.1, deadline - time.time()))) as response:
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    announced = int(length)
                except ValueError:
                    raise EvidenceError("original download returned invalid size metadata") from None
                if announced != expected or announced > maximum:
                    raise EvidenceError("original download exceeds reserved bytes or differs from metadata")
            count = 0
            while True:
                if time.time() >= deadline:
                    raise EvidenceError("original download exceeded the bounded timeout")
                block = response.read(min(64 * 1024, maximum + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > maximum:
                    raise EvidenceError("original download exceeded reserved bytes")
                with memoryview(block) as view:
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
            if count != expected:
                raise EvidenceError("original download differs from verified metadata size")
            os.fsync(descriptor)
        succeeded = True
        return str(target)
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("authenticated original download failed; request a fresh file reference and retry") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
            if not succeeded:
                target.unlink(missing_ok=True)


def _pid_alive(pid):
    """Read process liveness without sending a signal on Windows."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists
                return False
            raise EvidenceError("cannot read connected host process status")
        try:
            status = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)):
                raise EvidenceError("cannot read connected host process status")
            return status.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError as error:
        raise EvidenceError("cannot prove connected host command has exited") from error
    return True


def _bounded(value, maximum=MAX_CONTROL_BYTES):
    try:
        raw = json.dumps(value, sort_keys=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise EvidenceError("invalid connected host JSON") from error
    if len(raw) > maximum:
        raise EvidenceError("connected host control data exceeds metadata bound")
    return raw


def _session(path):
    path = _directory(path)
    _outside_git(path)
    info = path.stat()
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise EvidenceError("connected host session belongs to another user")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise EvidenceError("connected host session must be private (mode 0700)")
    data = read_json(path / "session.json", 4096)
    if data.get("version") != 1 or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("session_id", ""))):
        raise EvidenceError("invalid connected host session")
    return path, data


def start_session(parent):
    """Create a new explicitly selected, external, private foreground session."""
    parent = _directory(parent, create=True)
    _outside_git(parent)
    ident = uuid.uuid4().hex
    path = parent / ("connected-host-" + ident)
    path.mkdir(mode=0o700)
    atomic_json(path / "session.json", {"version": 1, "session_id": ident})
    return path


def next_request(session_dir):
    path, session = _session(session_dir)
    request_path = path / "request.json"
    if (path / "response.json").exists():
        return None
    if not request_path.exists():
        return None
    request = read_json(request_path, MAX_CONTROL_BYTES)
    if (request.get("version") != 1 or request.get("session_id") != session["session_id"]
            or not re.fullmatch(r"[0-9a-f]{32}", str(request.get("request_id", "")))):
        raise EvidenceError("connected host request identity mismatch")
    if request.get("expires_at", 0) <= time.time():
        raise EvidenceError("connected host request expired; stop the evidence command before closing its session")
    if (path / "response.json").exists():
        return None
    return request


def respond(session_dir, request_id, raw_result, *, materialized_path=None):
    """Submit the actual native tool result; never author a success by hand.

    Native authenticated file references are streamed into a bounded private
    file. A host that already materializes files can pass its local path instead.
    """
    path, session = _session(session_dir)
    request = read_json(path / "request.json", MAX_CONTROL_BYTES)
    if (request.get("session_id") != session["session_id"] or request.get("request_id") != request_id
            or request.get("expires_at", 0) <= time.time()):
        raise EvidenceError("stale or mismatched connected host response")
    target = path / "response.json"
    if target.exists():
        previous = read_json(target, MAX_CONTROL_BYTES)
        if previous.get("request_id") != request_id:
            raise EvidenceError("connected host response already supplied for another request")
        return
    managed_original = False
    if request.get("tool") == "fetch" and materialized_path is None:
        try:
            materialized_path = _materialize_original(path, request, raw_result)
            managed_original = materialized_path is not None
            if materialized_path is None:
                materialized_path = _unwrap(raw_result).get("workspace_path")
            if materialized_path is None:
                raise EvidenceError("host must supply an authenticated original file reference or materialized local path")
        except EvidenceError as error:
            # Wake the waiting command with a sanitized failure instead of
            # retaining a bearer URL or leaving it blocked until timeout.
            raw_result = {"error": str(error)}
    if materialized_path is not None:
        if request.get("tool") != "fetch":
            raise EvidenceError("only an original-byte fetch can supply a materialized file")
        materialized_path = str(Path(materialized_path).absolute())
    # Authenticated bearer URLs never enter the durable queue or error output.
    if materialized_path is not None:
        raw_result = {"original_materialized": True}
    response = {"version": 1, "session_id": session["session_id"], "request_id": request_id,
                "request_sha256": hashlib.sha256(_bounded(request)).hexdigest(),
                "result": raw_result, "materialized_path": materialized_path,
                "managed_original": managed_original}
    _bounded(response)
    atomic_json(target, response)


def close_session(session_dir, *, cancel=False):
    """Remove only known session files after the foreground command has exited."""
    path, _ = _session(session_dir)
    owner = path / "owner.json"
    if owner.exists():
        value = read_json(owner, 4096)
        pid = value.get("pid")
        if isinstance(pid, int) and pid > 0:
            if _pid_alive(pid):
                raise EvidenceError("connected host command is still running; close it first")
        else:
            raise EvidenceError("invalid connected host owner; no cleanup performed")
    if (path / "request.json").exists() and not cancel:
        raise EvidenceError("connected host request remains pending; inspect its outcome before explicit --cancel")
    entries = list(path.iterdir())
    if any((item.name not in SESSION_FILES and not re.fullmatch(r"original-[0-9a-f]{32}\.bin", item.name))
           or not item.is_file() or item.is_symlink() for item in entries):
        raise EvidenceError("unexpected files in connected host session; no cleanup performed")
    for item in entries:
        item.unlink()
    path.rmdir()


def _unwrap(value):
    """Accept native JSON or ordinary MCP structured/text response envelopes."""
    for _ in range(6):
        if not isinstance(value, dict):
            raise EvidenceError("connected Drive tool returned no JSON object")
        if value.get("isError") is True:
            raise EvidenceError("connected Drive tool failed; inspect the host tool result")
        if isinstance(value.get("structuredContent"), dict):
            value = value["structuredContent"]
            continue
        if isinstance(value.get("content"), list):
            texts = [item.get("text") for item in value["content"]
                     if isinstance(item, dict) and item.get("type") == "text"]
            decoded = []
            for item in texts:
                if isinstance(item, str):
                    try:
                        parsed = json.loads(item)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        decoded.append(parsed)
            if len(decoded) != 1:
                raise EvidenceError("connected Drive needs one structured JSON tool result")
            value = decoded[0]
            continue
        if isinstance(value.get("result"), dict) and len(value) == 1:
            value = value["result"]
            continue
        return value
    raise EvidenceError("connected Drive tool result nesting exceeds bound")


def _quote(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _file_id(value):
    identity = value.get("id", value.get("file_id", value.get("object_id")))
    if identity is None:
        url = value.get("url", value.get("webViewLink", ""))
        match = re.search(r"(?:/d/|[?&]id=)([A-Za-z0-9_-]+)", str(url))
        identity = match.group(1) if match else None
    identity = _locator_string(identity, "Drive object ID")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
        raise EvidenceError("invalid Drive object ID")
    return identity


class ConnectedHostAdapter:
    """Use installed authenticated host tools through the bundled handoff queue."""

    safe_error_messages = True
    control_peak_bytes = CONTROL_PEAK_BYTES

    def working_overhead(self, *, upload_bytes=0, download_bytes=0):
        # An immutable upload retry independently reads an existing remote object.
        return self.control_peak_bytes + max(_positive(download_bytes, "download overhead", zero=True),
                                             _positive(upload_bytes, "upload overhead", zero=True))

    def __init__(self, session_dir, *, timeout_seconds=300, max_metadata_bytes=MAX_CONTROL_BYTES,
                 max_objects=100_000):
        self.path, self.session = _session(session_dir)
        self.host_session_path = self.path
        self.timeout_seconds = _positive(timeout_seconds, "host timeout_seconds")
        self.maximum = min(_positive(max_metadata_bytes, "host metadata bound"), MAX_CONTROL_BYTES)
        self.max_objects = _positive(max_objects, "host object bound")
        self.lock = threading.Lock()
        self.closed = False
        owner = self.path / "owner.json"
        if owner.exists():
            previous = read_json(owner, 4096)
            pid = previous.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                raise EvidenceError("invalid connected host owner; start a fresh session")
            if _pid_alive(pid):
                raise EvidenceError("connected host session is already in use; start a fresh session")
            owner.unlink()
        # Exclusive acquisition also stops two processes from mixing responses.
        try:
            descriptor = os.open(self.path / "owner.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise EvidenceError("connected host session is already in use; start a fresh session") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "version": 1}, stream)
        self._folder = None
        self._response_bytes = 0

    def close(self):
        if not self.closed:
            (self.path / "owner.json").unlink(missing_ok=True)
            self.closed = True

    def _native(self, tool, arguments, **requirements):
        if self.closed:
            raise EvidenceError("connected host adapter is closed")
        if (self.path / "request.json").exists() or (self.path / "response.json").exists():
            raise EvidenceError("connected host has an unresolved request; inspect and start a fresh session")
        request = {"version": 1, "session_id": self.session["session_id"], "request_id": uuid.uuid4().hex,
                   "expires_at": time.time() + self.timeout_seconds, "tool": tool,
                   "arguments": arguments, "requirements": requirements}
        _bounded(request, self.maximum)
        atomic_json(self.path / "request.json", request)
        deadline = time.monotonic() + self.timeout_seconds
        target = self.path / "response.json"
        while True:
            # The host rejects wall-expired requests; the monotonic bound also
            # prevents a backward clock change from extending this wait.
            # Check both before accepting even an already-present response.
            if time.time() >= request["expires_at"] or time.monotonic() >= deadline:
                raise EvidenceError("connected Drive is waiting for the active agent to service evidence_host.py next/respond; request timed out and was retained")
            if target.exists():
                break
            time.sleep(0.05)
        response = read_json(target, self.maximum)
        self._response_bytes += len(_bounded(response))
        if self._response_bytes > self.maximum:
            raise EvidenceError("connected host operation exceeds combined metadata bound")
        if (response.get("request_id") != request["request_id"] or response.get("session_id") != self.session["session_id"]
                or response.get("request_sha256") != hashlib.sha256(_bounded(request)).hexdigest()):
            raise EvidenceError("connected host response does not match the pending request")
        # Read the response before clearing; a failed upload still retains the
        # transport's immutable-key checkpoint independently of this session.
        (self.path / "request.json").unlink()
        target.unlink()
        result = _unwrap(response.get("result"))
        if response.get("materialized_path") is not None:
            result = dict(result, materialized_path=response["materialized_path"],
                          managed_original=response.get("managed_original") is True)
        if result.get("error"):
            raise EvidenceError("connected Drive tool reported an error; no success was recorded")
        return result

    def _metadata(self, identity, folder, key=None):
        raw = self._native("get_file_metadata", {"fileId": identity, "fields": FIELDS})
        if isinstance(raw.get("file"), dict):
            raw = raw["file"]
        if _file_id(raw) != identity:
            raise EvidenceError("Drive metadata returned a different stable ID")
        name = raw.get("name", raw.get("title"))
        actual_key = _transport_key(name)
        parents = raw.get("parents", raw.get("parent_ids"))
        if not isinstance(parents, list) or folder not in parents or raw.get("trashed") is True:
            raise EvidenceError("Drive object is outside the selected live folder")
        mime = raw.get("mimeType", raw.get("mime_type", ""))
        if not isinstance(mime, str) or mime.startswith("application/vnd.google-apps."):
            raise EvidenceError("evidence requires stored original binary bytes, not a native Google document")
        if key is not None and actual_key != key:
            raise EvidenceError("Drive metadata name differs from the immutable key")
        size = raw.get("size")
        if isinstance(size, str) and re.fullmatch(r"[0-9]+", size):
            size = int(size)
        return {"object_id": identity, "key": actual_key, "size": _positive(size, "Drive object size", zero=True)}

    def _search(self, folder, *, key=None, prefix="", page_token=None, max_objects=None):
        # Current native search omits stored binary archives. list_folder returns
        # them, but exposes one provider page and no continuation argument.
        if page_token is not None:
            raise EvidenceError("connected Drive folder listing does not expose continuation; use a capable paginated adapter")
        bound = self.max_objects if max_objects is None else max_objects
        _positive(bound, "folder object bound", zero=True)
        scan = min(self.max_objects + 1, MAX_NATIVE_FOLDER_SCAN)
        raw = self._native("list_folder", {"url": "https://drive.google.com/drive/folders/" + folder, "top_k": scan},
                           complete_listing_required=True, reject_saturated_scan=True)
        rows = raw.get("files", raw.get("results", raw.get("items")))
        if not isinstance(rows, list):
            raise EvidenceError("Drive folder listing returned no complete metadata page")
        continuation = raw.get("next_page_token", raw.get("nextPageToken"))
        partial = any(raw.get(flag) is True for flag in ("partial", "truncated", "has_more", "incompleteSearch", "incomplete_search"))
        if len(rows) >= scan or continuation or partial:
            raise EvidenceError("complete binary folder enumeration unavailable: native list_folder is saturated or partial (maximum 1000 scanned items); use a folder below the scan bound or a capable paginated adapter")
        if len(rows) > bound:
            raise EvidenceError("Drive folder listing exceeds configured object bound")
        objects, identities = [], set()
        for item in rows:
            if not isinstance(item, dict):
                raise EvidenceError("Drive folder listing item is not metadata")
            identity = _file_id(item)
            if identity in identities:
                raise EvidenceError("Drive folder listing repeats an object ID")
            identities.add(identity)
            name = item.get("name", item.get("title"))
            if key is not None and name != key:
                continue
            if not isinstance(name, str) or not name.startswith(prefix):
                continue
            info = self._metadata(identity, folder, key)
            if info["key"].startswith(prefix):
                objects.append(info)
        return {"objects": objects, "next_page_token": None, "scanned_count": len(rows), "scan_limit": scan}

    def preflight_upload(self, folder, key):
        with self.lock:
            self._response_bytes = 0
            self._upload_capacity(folder, key)

    def _upload_capacity(self, folder, key):
        page = self._search(folder, key=key)
        if page["objects"]:
            raise EvidenceError("immutable key appeared before upload; resume verified lookup instead")
        if page["scanned_count"] + 1 >= page["scan_limit"]:
            raise EvidenceError("new upload would saturate the native binary folder scan; select a folder with capacity or a capable paginated adapter before writing")

    def __call__(self, request):
        with self.lock:
            self._response_bytes = 0
            if request.get("version") != 1:
                raise EvidenceError("unsupported connected host protocol")
            folder = _file_id({"id": request.get("folder_id")})
            if self._folder is None:
                self._folder = folder
            elif folder != self._folder:
                raise EvidenceError("one host session cannot switch Drive folders")
            operation = request.get("operation")
            if operation == "capabilities":
                result = self._native("host_capabilities", {"required_tools": list(TOOLS)},
                                      authenticated_google_drive=True, independent_original_bytes=True)
                names = result.get("tools")
                if (not isinstance(names, list) or not set(TOOLS).issubset(names)
                        or result.get("original_download") is not True):
                    raise EvidenceError("installed Drive integration lacks required original-byte upload/download, metadata, binary folder listing or delete tools")
                raw = self._native("get_file_metadata", {"fileId": folder, "fields": "id,mimeType,trashed"})
                if isinstance(raw.get("file"), dict):
                    raw = raw["file"]
                if (_file_id(raw) != folder or raw.get("mimeType", raw.get("mime_type")) != "application/vnd.google-apps.folder"
                        or raw.get("trashed") is True):
                    raise EvidenceError("selected Drive destination is not a live folder")
                return {"version": 1, "provider": "google_drive", "capabilities": CAPABILITIES}
            if operation == "lookup":
                key, token, tokens, objects, total = _transport_key(request["key"]), None, set(), [], 0
                while True:
                    page = self._search(folder, key=key, page_token=token)
                    total += len(_bounded(page))
                    if total > self.maximum:
                        raise EvidenceError("Drive exact lookup exceeds combined metadata bound")
                    objects.extend(page["objects"])
                    if len(objects) > 1:
                        raise EvidenceError("duplicate Drive object identity for immutable key; reconciliation required")
                    token = page["next_page_token"]
                    if token is None:
                        return {"objects": objects}
                    if token in tokens or len(tokens) >= self.max_objects:
                        raise EvidenceError("Drive lookup continuation loop or page bound exceeded")
                    tokens.add(token)
            if operation == "list":
                result = self._search(folder, prefix=request.get("prefix", ""), page_token=request.get("page_token"),
                                      max_objects=request.get("max_objects", self.max_objects))
                return dict(result, metadata_bytes=self._response_bytes)
            key = _transport_key(request.get("key"))
            if operation == "upload":
                self._upload_capacity(folder, key)
                result = self._native("upload_file", {"file_uri": request["source_path"], "file_name": key,
                                                      "parent_folder_id": folder, "mime_type": "application/octet-stream"},
                                      size=request["size"], sha256=request["sha256"], preserve_original_bytes=True)
                if isinstance(result.get("file"), dict):
                    result = result["file"]
                return self._metadata(_file_id(result), folder, key)
            identity = _file_id({"id": request.get("object_id")})
            if operation == "metadata":
                return self._metadata(identity, folder, key)
            if operation == "download_original":
                info = self._metadata(identity, folder, key)
                maximum = _positive(request.get("max_bytes"), "download bound", zero=True)
                if info["size"] > maximum:
                    raise EvidenceError("Drive original exceeds reserved download bound")
                result = self._native("fetch", {"url": "https://drive.google.com/file/d/" + identity + "/view",
                                               "download_raw_file": True, "include_base64": False},
                                      max_bytes=maximum, expected_size=info["size"], independent_fetch=True,
                                      materialize_original_file=True)
                source = result.get("materialized_path", result.get("workspace_path"))
                if not isinstance(source, str) or not Path(source).is_absolute():
                    raise EvidenceError("host must materialize the authenticated original file and pass --download PATH; URLs and inline bytes are unsupported")
                target = _destination(request["destination_path"])
                source_path, descriptor, before = _open_regular(source)
                try:
                    if before.st_size > maximum or before.st_size != info["size"]:
                        raise EvidenceError("materialized Drive original exceeds byte bound or has wrong size")
                    if source_path == target or (target.exists() and os.path.samefile(source_path, target)):
                        raise EvidenceError("Drive readback must be independent of the requested destination")
                    # Never reopen a host-visible path for writing: copy through
                    # a newly created private file, then atomically install it.
                    out_fd, temporary = tempfile.mkstemp(prefix=".host-original-", dir=target.parent)
                    try:
                        try:
                            copied = 0
                            while True:
                                block = os.read(descriptor, min(1024 * 1024, maximum + 1 - copied))
                                if not block:
                                    break
                                copied += len(block)
                                if copied > maximum:
                                    raise EvidenceError("Drive original grew past the download byte bound")
                                with memoryview(block) as view:
                                    while view:
                                        written = os.write(out_fd, view)
                                        view = view[written:]
                            os.fsync(out_fd)
                            _verify_stable(source_path, descriptor, before)
                        finally:
                            os.close(out_fd)
                        _destination(target)
                        os.replace(temporary, target)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                finally:
                    os.close(descriptor)
                    if result.get("managed_original") is True:
                        owned = Path(source)
                        if owned.parent != self.path or not re.fullmatch(r"original-[0-9a-f]{32}\.bin", owned.name):
                            raise EvidenceError("managed original file escaped its host session")
                        owned.unlink(missing_ok=True)
                return {"object_id": identity, "size": copied, "original_bytes": True}
            if operation == "delete":
                existing = self._search(folder, key=key)
                if not existing["objects"] and existing["next_page_token"] is None:
                    return {"deleted": True}
                self._metadata(identity, folder, key)
                self._native("delete_file", {"url": "https://drive.google.com/file/d/" + identity + "/view"},
                             permanent_delete_only_selected_registered_id=True)
                # ConnectedDriveTransport independently verifies exact-key absence.
                return {"deleted": True}
            raise EvidenceError("unsupported connected Drive host operation")
