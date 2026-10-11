# Google Drive evidence transport

Local users need only Python 3.12+. Selecting Drive requires explicit account and
folder authorization, an authenticated plugin/connector or optional rclone, and the evidence
manager's successful synthetic upload, independent original-byte retrieval, hash
verification, and original-byte restoration probe. A successful connector response, browser
preview, exported document, or local synchronization folder is not that proof.

Both Drive transports implement immutable `put(key, source_path)`,
`stat(locator_or_key)`, `get(locator, destination_path, max_bytes)`,
`delete(locator)`, and bounded `keys(prefix)`. A locator contains `object_id`,
`key`, and original byte `size`; the versioned evidence reference also binds the
actual SHA-256 and provenance. Pack verification belongs to the evidence manager.

## Standalone rclone

Install rclone separately when choosing this option; the installer does not add
it for ordinary local users. Follow [rclone's current Google Drive authentication
instructions](https://rclone.org/drive/#making-your-own-client-id). Checked on
2026-10-11: rclone's shared OAuth client is retiring in 2026, so create your own
Google OAuth client or use an appropriately authorized service account. Configure
the selected remote interactively, with secrets in an external file:

```text
rclone config --config /absolute/external/rclone.conf
```

The account holder enables the Drive API, creates the OAuth client, supplies its
credentials directly to rclone, and completes Google's browser authorization.
For an existing remote changed to a custom client, reauthorize it using
`rclone config reconnect REMOTE: --config /absolute/external/rclone.conf`.
Choose scopes that cover required archive access. `drive.file` is limited to files
created by that application and may not permit adopting existing archives.

Select a dedicated destination such as `REMOTE:sdd-evidence`; machine
configuration keeps `destination`, `rclone_config`, and optional
`rclone_executable` outside Git. Do not paste tokens or config contents into
project documents. Keep rclone configuration and authorized archive-folder access
available for cold recovery. Archive objects must remain at their recorded key;
external renaming/moving makes metadata lookup fail explicitly.

The implementation uses exact [lsjson](https://rclone.org/commands/rclone_lsjson/)
names and stable IDs, detects duplicate names instead of arbitrarily selecting one,
uploads immutable objects, and downloads original binary bytes with
[Drive `backend copyid`](https://rclone.org/drive/#copyid). It never mounts Drive
or treats a cached synchronization directory as verification. Command timeout,
retries, metadata bytes, object counts, and transfer byte bounds are finite;
[rclone's hard transfer cutoff](https://rclone.org/docs/#max-transfer-sizesuffix)
and manager reservations bound readback. Output is suppressed on failures because
third-party diagnostics can contain credentials.

## Connected host bridge

The bundled `ConnectedHostAdapter` lets an active Codex/Claude agent use its
already authenticated Google Drive tools. It requires no user-written bridge,
separate OAuth client or rclone installation. The user chooses the folder and
retention; the agent performs the following session workflow from the skill's
real script directory. Keep temporary session/response files outside Git.

1. Inspect the host's available Drive tools. Start a private session with
   `python3 evidence_host.py start --parent /external/host-sessions` and retain
   the returned absolute `session` path.
2. Start the authorized setup/manager command with `--host-session SESSION`,
   or set `SDD_EVIDENCE_HOST_SESSION=SESSION` for that command. Keep the command
   running while servicing requests; a blocking wait that prevents tool calls
   will time out. The adapter waits at most 300 seconds per tool request.
3. Call `python3 evidence_host.py next --session SESSION`. For a non-null
   `request`, use its `request_id`, `tool`, `arguments` and `requirements`.
   `host_capabilities` is a local handshake: return the discovered tool basenames
   in `tools` and `original_download:true` only after confirming original binary
   download is available. Required basenames are `list_folder`, `upload_file`,
   `get_file_metadata`, `fetch` and `delete_file`. Other requests call the
   corresponding authenticated Drive tool with the supplied arguments.
4. Save the raw tool result as bounded JSON, then run
   `python3 evidence_host.py respond --session SESSION --request REQUEST_ID --response /external/tool-result.json`.
   For Codex `fetch`, pass the unchanged result: the bundled helper materializes
   its authenticated `file_uri.download_url` automatically, enforcing the byte
   limit and download deadline. Other hosts may provide an accessible
   `workspace_path` or add `--download /external/original-file` for an original
   already materialized through that host's download facility. Respect
   `max_bytes`; never substitute a preview, document export or source upload.
   The adapter independently copies and verifies the original file. The manager
   reserves space for the control queue and independent downloaded copy.
5. Repeat until the command exits. Close the session with
   `python3 evidence_host.py close --session SESSION`, remove task-owned response
   and download files, and report the command's verification result. In a
   `finally` path, first stop/wait for the owned command; inspect unresolved
   remote operations before using `close --cancel`. The upload journal remains
   available for reconciliation. Do not delete unrelated Drive objects.

Start a separate private session for each concurrent foreground command, and a
fresh session for a later operation/chat. One command owns each request queue;
do not share its session between parallel commands. Session paths never enter saved
bindings or portable policy; account authentication remains with the plugin.
Without an active session, the manager reports the missing host action instead
of prompting for custom code or switching to rclone. A different connector must
expose the listed tool interface and compatible arguments/results as well as
equivalent capabilities. In Claude Code, `/mcp` establishes connector discovery,
not compatibility with this adapter or successful archive verification; inspect
the actual exposed tools before starting setup. Unavailable raw downloads or
incomplete listings fail explicitly.

The bundled adapter enumerates binary files with `list_folder`; native search
can omit archived binary objects. The current folder tool accepts `top_k:1000`
but exposes no continuation argument. The adapter rejects saturated, partial or
continuation-bearing listings and stops before an upload would add the 1,000th
direct folder item. Its supported folder capacity is therefore at most 999
direct items, including catalog/accounting objects and unrelated existing items;
the 1 MiB control-response limit or configured object bound can lower that limit.
Use a compatible paginated custom adapter or explicitly choose rclone for a
larger folder. A successful small-folder probe does not prove arbitrary-size
folder support, and the manager never silently changes the selected transport.

Custom integrations remain supported: a host may inject a Python callable
`adapter(request) -> response`, or explicitly configure a `bridge_command`
argument array for `JsonCommandAdapter` using `--bridge-command '["python3", "/external/bridge.py"]'`.
That adapter starts one process per request, writes one UTF-8 JSON object on stdin,
and expects one bounded JSON object on stdout. The transport protocol below is
implemented by the bundled adapter as well as custom adapters.

The first request is:

```json
{"version":1,"operation":"capabilities","folder_id":"USER_SELECTED_FOLDER_ID"}
```

The required response is:

```json
{"version":1,"provider":"google_drive","capabilities":["upload","download_original","metadata","lookup","list","delete","stable_object_id","bounded_original_download"]}
```

Each request retains `version`, `operation`, and `folder_id`. Implement these
operations by mapping them to the host's exposed connected Drive tools:

| Operation | Additional request fields | Required response |
| --- | --- | --- |
| `lookup` | `key` | `{"objects":[...]}` containing every exact match in the selected folder; zero is absent, multiple is an error |
| `metadata` | `object_id`, `key` | `{"object_id":"ID","key":"packs/name","size":123}` from that stable ID |
| `upload` | `key`, `source_path`, `size`, `sha256`, `idempotency_key` | The same metadata object from an original binary upload; do not convert to a Google document |
| `download_original` | `object_id`, `key`, `destination_path`, `max_bytes`, `bypass_cache:true` | Write original bytes independently to the supplied path and return `{"object_id":"ID","size":123,"original_bytes":true}` |
| `list` | `prefix`, `page_token`, `max_objects` | `{"objects":[...],"next_page_token":null}` or a nonempty continuation token |
| `delete` | `object_id`, `key` | `{"deleted":true}` after deleting that registered object and checking absence |

Metadata objects use a nonnegative original integer byte size and a stable string
ID. Object IDs, keys, and provider object names are limited to 4096 UTF-8 bytes
each, reject control characters and invalid UTF-8, and are checked before locator
persistence. This bounds catalog locator overhead independently of payload size.
`key` is a safe portable relative path; it is an identity in the selected
archive namespace, not an arbitrary query. A host whose Drive tools cannot upload
original files, download original bytes, obtain stable metadata, enumerate exact
matches, or delete selected test objects must report those missing capabilities.
The handshake fails with their exact names and setup guidance. It never switches
to rclone or another account automatically. Text excerpts and native-Doc exports
must not advertise `download_original`.

For example, an authorized tool host can map upload to its file-upload tool,
metadata to its file-metadata tool, original retrieval to the connector's raw
file-download operation, and lookup/list/delete to their corresponding tools.
The exposed connector may return normalized metadata: read `name` or `title` for
the exact key, `mimeType` or `mime_type` for binary-file validation, and `parents`
or `parent_ids` to verify the selected folder. Parse the original `size` as a
nonnegative integer and retain `id` unchanged as `object_id`.
Every `lookup` must enumerate all exact matches; a paginated custom adapter must
include duplicate IDs across pages, and every `list` must reach the final page.
The bundled adapter supports only a demonstrably unsaturated single-page folder.
Never set `next_page_token:null`
merely because a connector's result cap was reached. Refuse truncation, unknown
pagination completeness, or a namespace beyond the host's explicit supported
limit before claiming absence, cold recovery, or safe deletion. A small synthetic
folder test verifies that bounded namespace; it cannot establish arbitrary-size
production pagination capability.
Adapters must enforce `max_bytes` while writing, propagate operation failure, and
keep tokens and account details out of responses. The command bridge additionally
supervises timeout, output size, and downloaded size; injected callables depend on
the host honoring that advertised bound. Tests use a synthetic host and actual
subprocess bridge fixtures; those tests do not establish live connector capability.
Request writes share the command deadline even if the bridge never reads stdin.
Cleanup signals only the owned child or its verified original process group,
falls back to direct child termination if a group signal is denied, and waits for
the child and input writer. An unverified helper shutdown reports incomplete
cleanup with the original operation failure; a host bridge owns any separately
detached helper lifecycle.

## Interrupted uploads and recovery

Before upload, the transport durably records the deterministic key, hash, size,
and pending state under external `state_dir`. On success it records the stable
locator. After an interruption or unknown response, bounded exact lookup attempts
recover an uploaded object and independently compare its bytes. Retrying with
the same key does not blindly upload again. A missing object retains its pending
checkpoint and blocks with an unknown-outcome error, including after restart.

Resume at the verified pack boundary. If the account holder has inspected the
selected destination and confirmed the upload never created an object, run
`python3 evidence_store.py acknowledge-missing-upload --project PATH --key EXACT_PENDING_KEY`
with an active host session for connected Drive. This explicitly clears that one
pending checkpoint after fresh absence checks; retry the original archive command
to resume. Existing objects cannot be abandoned through this action. Duplicate remote names require reconciliation and are never
automatically deduplicated or deleted. This favors recoverable failure over
duplicate payloads when a remote listing is delayed.

If the initial generation-authority upload was interrupted before setup published
its project policy/binding, repeat the original `evidence_setup.py configure`
command with the same project, evidence home, destination, policy choices and
`--acknowledge-missing-upload EXACT_PENDING_KEY` from the error. Supply a fresh
active `--host-session` for connected Drive. The setup checkpoint restores the
original project/store IDs, verifies absence of that one registered upload, then
retries the probe and authority initialization. Another project's key or a remote
object that exists cannot be acknowledged. This action clears a local pending
checkpoint; it does not delete a Drive object.

Cold restoration does not depend on transfer journals: bounded catalog key
enumeration, stable locators, and independent downloads recover the neutral
catalog from the authorized archive folder. The original-byte reference closure
must verify before a restored claim passes. Permanent deletion targets one
registered object and verifies absence. No account-wide trash clearing, purge,
or unregistered-folder cleanup is used.
Rclone deletion is idempotent: after an interrupted delete, a successful exact
lookup proving absence completes recovery without issuing another delete.
Failed lookup, inaccessible credentials, and changed object identity still block.
