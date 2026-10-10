# Google Drive evidence transport

Local users need only Python 3.12+. Selecting Drive requires explicit account and
folder authorization, an external credential configuration, and the evidence
manager's successful synthetic upload, independent original-byte retrieval, hash
verification, and cold restoration probe. A successful connector response, browser
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

A host may inject a Python callable `adapter(request) -> response`, or provide an
external `bridge_command` argument array to `JsonCommandAdapter`. The latter starts
one process per request, writes one UTF-8 JSON object on stdin, and expects one
bounded JSON object on stdout. No shell, scheduler, or credential storage is
provided. The host owns the authenticated tool calls; this repository provides
the transport and protocol, not a universal connector runtime.

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
Every `lookup` must enumerate all exact matches, including duplicate IDs across
pages; every `list` must reach the final page. Never set `next_page_token:null`
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

## Interrupted uploads and recovery

Before upload, the transport durably records the deterministic key, hash, size,
and pending state under external `state_dir`. On success it records the stable
locator. After an interruption or unknown response, bounded exact lookup attempts
recover an uploaded object and independently compare its bytes. Retrying with
the same key does not blindly upload again. A missing object retains its pending
checkpoint and blocks with an unknown-outcome error, including after restart.

Resume at the verified pack boundary. If the account holder has inspected the
selected destination and confirmed the upload never created an object,
`transport.acknowledge_missing_upload(key)` explicitly clears that one pending
checkpoint; a following `put` may try again. Existing objects cannot be abandoned
through this action. Duplicate remote names require reconciliation and are never
automatically deduplicated or deleted. This favors recoverable failure over
duplicate payloads when a remote listing is delayed.

Cold restoration does not depend on transfer journals: bounded catalog key
enumeration, stable locators, and independent downloads recover the neutral
catalog from the authorized archive folder. The original-byte reference closure
must verify before a restored claim passes. Permanent deletion targets one
registered object and verifies absence. No account-wide trash clearing, purge,
or unregistered-folder cleanup is used.
Rclone deletion is idempotent: after an interrupted delete, a successful exact
lookup proving absence completes recovery without issuing another delete.
Failed lookup, inaccessible credentials, and changed object identity still block.
