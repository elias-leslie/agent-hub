# Web retrieval and retained extraction

`web-research` (the Agent Hub owner executable behind `st web`) keeps the existing
`auto` policy: direct HTTP extraction, the configured CDP browser for sparse
HTML, then the public Jina reader. `direct` remains deterministic HTTP-only
retrieval. The default returned content limit is 12,000 characters; the existing
maximum is 50,000. The full extracted content is retained before focusing or
truncation. No new packages are required.

## Local artifacts and batch reuse

Successful fetches return `artifact_id`, `artifact_path`, and
`full_content_chars`. Records contain the full extracted text, citation metadata,
coverage and stage evidence. They live in
`${XDG_CACHE_HOME:-~/.cache}/agent-hub/web`; an explicit
`AGENT_HUB_WEB_CACHE_DIR` chooses another owner-managed cache. New records have
mode 0600 and are never overwritten. Storage is durable until owner cleanup;
there is no automatic expiration or size eviction. Cache write failures preserve
readable output and report `artifact_error` and `full_extraction_retained=false`.
Large failure `raw_receipt`, `stderr`, and `detail` strings are saved in full
before diagnostic previews are limited to the requested `max_chars`. The
response lists `diagnostic_truncated` paths and its artifact reference holds
the full evidence. This bounds content and diagnostic fields, rather than
claiming a maximum size for the entire JSON object or batch.

```bash
st web fetch https://example.com/article --backend direct --max-chars 1000
st web refocus <artifact_id> --focus-query 'trial eligibility' --max-chars 2000
st web batch https://example.com/one https://example.com/two --backend direct
```

Refocus accepts an id or an absolute path directly within the owner cache and
rejects symlinks and paths outside it. It performs no network access and keeps
citation metadata and original coverage. It cannot upgrade a source's
completeness assertion. A raw response retained after extraction failure is
evidence, not a refocusable article. Batch runs serially in one process and
reuses one HTTP client, including public-reader fallbacks. It retains every
result and exits nonzero if any fetch fails; there are no added retries or
arbitrary batch caps.

## Opt-in Lightpanda DOM retrieval

```bash
st web doctor
st web fetch https://example.com/article --backend lightpanda \
  --selector article --wait-script 'document.querySelector("article")?.innerText.includes("Conclusion")' \
  --timeout 20
```

Choose a predicate tied to expected readable content within the target article
or `#report`. `document.body.textContent` and broad containers can include inline
scripts and styles containing the expected words before the readable report is
ready. Prefer scoped `innerText`, then verify that the returned extraction
contains the requested facts. A passing predicate establishes only the condition
you supplied; it does not establish full source coverage.

Lightpanda uses the reviewed binary at
`${XDG_DATA_HOME:-~/.local/share}/agent-hub/web/lightpanda/e24d135bb5c4c0905cea9ee9a1cd87eff407755af24bd99b659fa64ec907f18d/lightpanda`.
The exact version is `1.1.0-nightly.10071+3be033135`; the directory name is the
SHA256 pin. `doctor` checks the full digest and exact version locally. An override
requires all three environment variables together:
`AGENT_HUB_WEB_LIGHTPANDA_BINARY` (absolute executable path),
`AGENT_HUB_WEB_LIGHTPANDA_SHA256`, and `AGENT_HUB_WEB_LIGHTPANDA_VERSION`.
An ordinary fetch verifies once in process; batch reuses the verification only
while path, pins, device, inode, size, mtime and ctime remain unchanged. This
avoids hashing the large binary and spawning a version process per batch item.
Doctor always performs full verification. The service/CLI owner must have the
binary available in its own filesystem; host provisioning alone does not make
it available inside a container.

The backend invokes an argv subprocess with no shell, sets
`LIGHTPANDA_DISABLE_TELEMETRY=1`, and enforces both the CLI termination deadline
and a parent-process deadline. A timeout kills and reaps the child and retains
partial stdout/stderr evidence. `--selector` selects the first matching CSS
scope; `--wait-script` is an explicit JavaScript readiness expression. They are
rejected for other backends. Fetch uses DOMContentLoaded before readiness and
never combines a readiness expression with `--wait-ms`, which supersedes other
Lightpanda waits. HTTP failures, CLI errors, malformed receipts, empty extraction
and failed readiness remain failures with retained artifacts and nonzero CLI
status. Explicit Lightpanda failures suggest recovery routes; no automatic
fallback claims those routes satisfied the requested predicate.

This is text/DOM retrieval. It does not provide visual layout, screenshots or
managed browser interaction. Images, external stylesheets, workers and iframes
are not loaded by this route. `coverage` describes scope, readiness and omitted
resources. Successful readiness does not prove that every relevant fact was
loaded, so Lightpanda reports `content_complete=false` with
`source_completeness_unverified`. Direct output's historical `content_complete`
field describes the returned extraction view; `coverage.source_completeness`
remains unverified. Character limits and focused selections report their own
omissions. Stage durations, total fetch duration, pin metadata and fallback
errors support troubleshooting; they are not visual or complete-article proof.

HTML comments are excluded from structured rendering. A failure in that optional
renderer keeps prior trafilatura extraction. Unsupported MIME and supported-MIME
extraction failures have different errors. The latter retain the raw response
artifact even when `auto` continues to the public reader.
