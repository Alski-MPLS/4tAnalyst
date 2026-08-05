# Changelog

All notable changes to this project are documented here.

---

## [Unreleased] — 2026-08-05 (3)

### Fixed

#### Policy package cache + startup warm-up to prevent cold-cache MCP transport drops (`fortimanager_mcp/query.py`, `planner/fetch.py`, `fwanalyst_server/__main__.py`)

`plan_change` on a cold cache fetches thousands of address/service objects **and** iterates every policy package in the ADOM before evaluating anything — typically 2–3 minutes total on a large ADOM. The MCP SSE stream has no data to write during that window; the client-side SSE reader (or a network TCP-idle timer) drops the connection with `ClosedResourceError` in `standalone_sse_writer`, surfacing as "MCP transport dropped" on the Claude Code workstation.

**`fortimanager_mcp/query.py` — `build_policy_snapshot()`** (new function)
- Fetches and caches all policy packages and their policies for an ADOM using a 6-parallel `ThreadPoolExecutor` (one fetch per package).
- Cache TTL: 300 seconds (5 minutes) — shorter than the address/service catalog TTL because policies change more often than address objects.
- A `None` value for a package in the returned dict means the fetch failed (so callers degrade correctly); `[]` means the package was successfully fetched but is empty. Never conflates the two.

**`planner/fetch.py` — `fetch_device_snapshot()`**
- Now calls `build_policy_snapshot()` instead of fetching packages and policies inline. Per-package `None` entries (failed fetches) are propagated as `failures` so the snapshot is marked `degraded`.

**`fwanalyst_server/__main__.py` — `_start_catalog_warmup()`**
- Extended to also call `build_policy_snapshot()` for each ADOM alongside `build_catalogs()`. After a service restart, both the address/service catalog cache and the policy cache are populated before any engineer request arrives — so the first `plan_change` call hits warm caches and completes in seconds.
- Warm-up runs in a daemon thread so it never blocks server startup.
- Per-ADOM failures are logged as warnings and do not abort other ADOMs or the server.
- Skipped in `stdio` mode and when no `fortimanager.hosts` are configured.

---

## [Unreleased] — 2026-08-05 (2)

### Fixed

#### Existing Rules section: ICMP noise, disabled rules, and blocked recommendation (`fortimanager_mcp/matching.py`, `planner/engine.py`)

Three issues made the Existing Rules section misleading and the recommendation unhelpful when zone policy blocks a flow.

**`fortimanager_mcp/matching.py` — `ServiceCatalog._ranges_for_object()`**
- Fixed: FortiManager service objects with `protocol=IP` and a `protocol-number` field (e.g. `icmp-proto` with `protocol-number: 1`) were incorrectly resolved to the `WILDCARD_RANGE` (`PortRange("ip", 0, 65535)`) — making them appear to cover every TCP/UDP port. Only objects with `protocol=IP` and **no** `protocol-number` are the true ALL wildcard. Objects with a known `protocol-number` (currently ICMP=1) are now resolved to their actual protocol type; objects with an unknown protocol-number return `None` (unresolvable) rather than a false wildcard.
- Fixed: `exact_match_name()` would raise `TypeError` when `_ranges_for_object()` returned `None`. Added a `None` guard.

**`planner/engine.py` — `_plan_firewall()` partial_matches filter**
- Fixed: Disabled rules were appearing in partial matches. Rules with `status=disable` now skip the `partial_matches` list entirely — a disabled rule has no effect on traffic and should not appear in analysis.
- Fixed: Rules whose service dimension has no overlap with the requested service (e.g. an ICMP rule when tcp/22 was requested) were appearing as partial matches. Partial matches are now filtered to only include rules where `matcher.svc_side()` returns `matched=True`, eliminating service-irrelevant noise.

**`planner/engine.py` — `_recommendation()`**
- Fixed: When zone policy blocks a flow, the recommendation now names the specific blocking policy (e.g. `Blocked by: "NSS OT and CIP-H To and From Internet and IT".`), making it immediately clear to the engineer which policy governs the exception path.

**`tests/conftest.py`** (new)
- Added `autouse` fixture that clears the `fortimanager_mcp.query._catalog_cache` before and after each test. The cache is keyed on `id(client)` for non-real clients; CPython recycles object ids after GC, causing fake-client instances in one test to hit stale catalogs from prior tests in the same session.

**Tests added** (`tests/test_matching.py`, `tests/test_engine.py`)
- `test_catalog_icmp_protocol_resolves_to_icmp_range` — ICMP-typed service resolves to `PortRange("icmp", …)`
- `test_catalog_ip_protocol_no_number_is_wildcard` — bare IP-typed service is the ALL wildcard
- `test_catalog_ip_protocol_with_icmp_number_resolves_to_icmp` — `icmp-proto` resolves to ICMP range, not wildcard
- `test_catalog_ip_protocol_with_unknown_number_is_unresolvable` — unknown protocol-number returns None
- `test_icmp_proto_service_does_not_match_tcp22` — end-to-end: icmp-proto does not match a tcp/22 request
- `test_disabled_rule_not_in_partial_matches` — disabled rules absent from both covering_rules and partial_matches
- `test_non_overlapping_service_rule_not_in_partial_matches` — rules with no service overlap excluded from partial_matches
- `test_blocked_recommendation_names_governing_policy` — blocking policy name present in recommendation text

---

## [Unreleased] — 2026-08-05

### Changed

#### Existing Rules section in `report.html` now shows rule detail tables (`scripts/render_report.py`, `planner/engine.py`)

Engineers can now verify "already covered" claims directly in the report instead of having to query FortiManager separately. The Existing Rules section previously showed only `#ID "name"` per rule — insufficient to confirm whether the found rule actually covered the requested source, destination, and service.

**`planner/engine.py` — `to_report_payload()`**
- The `existing_rules[fw]` payload dict now emits two additional keys alongside the existing merged `"rules"` list:
  - `"covering_rules"` — rules where every requested flow pair is fully covered (enabled, unconditional, no unknown refs)
  - `"partial_matches"` — rules that overlap the request but do not fully cover it (e.g. an ICMP rule found when SSH/SNMP were requested, or a rule covering a sub-range of the requested CIDR)

**`scripts/render_report.py` — `render_html()`**
- Each rule is now rendered as a detail table showing: Policy ID, name, package, enabled/disabled status, source address objects, destination address objects, and service objects
- Covering rules (green badge) and partial/overlapping matches (amber badge, separate section) are visually distinct
- Partial matches include a note: "This rule overlaps the request but does not fully cover it — it is not sufficient on its own"
- Optional rows surface `covered_pairs` (when only some src×dst pairs are covered) and `unknown_refs` (when address/service objects could not be resolved)
- `status` field handles both string (`"enable"`/`"disable"`) and integer (`1`/`0`) values from FortiManager
- **Backward compatible:** payloads with only the legacy `"rules"` key are split on `full_cover` at render time — no re-generation required for existing saved payloads

---

## [Unreleased] — 2026-07-27

### Added

#### Per-engineer ADOM access control (`fwanalyst_server`, `fortimanager_mcp`)

Engineers now connect with individual bearer tokens, each scoped to one or more ADOMs. This replaces the previous single-shared-token model where every caller had unrestricted access to all ADOMs on FortiManager.

**New module — `fwanalyst_server/context.py`**
Thin shared module exporting a single `ContextVar[set[str]]` (`allowed_adoms_var`). Lives outside both `fwanalyst_server` and `fortimanager_mcp` to avoid a circular import between the two packages.

**`fwanalyst_server/auth.py`**
- Added `_resolve_allowed_adoms(token, creds)` — resolves a named token from `server.tokens` to its allowed ADOM set. The legacy `auth_token` is intentionally excluded here (handled by the primary `hmac.compare_digest` check) to prevent the YAML credential from acting as a backdoor after `FW_ANALYST_TOKEN` env-var rotation.
- `require_bearer` now accepts an optional `creds` dict; when provided, it injects the resolved ADOM set into `allowed_adoms_var` for the duration of each request (reset via `try/finally`).
- Named tokens from `server.tokens` are accepted in addition to the primary admin token.

**`fortimanager_mcp/server.py`**
- Added `_require_adom(adom)` helper — returns an error dict if the caller's token does not include the requested ADOM, or `None` if permitted. Defaults to full access in stdio/dev mode (no ContextVar set).
- Every tool that accepts an `adom` parameter now calls `_require_adom` as its first line (hard error on deny): `get_devices`, `search_devices`, `search_policies`, `get_address_object`, `search_address_objects`, `get_service_object`, `get_policy`, `get_interface_map`, `get_routing_table`, `list_device_vdoms`.
- `get_adoms()` silently filters the returned list to the caller's allowed ADOM set.

**`credentials.yaml.example`**
- Added `server.adom_restriction` toggle (`true`/`false`).
- Added `server.tokens` list schema with `token`, `label`, and `adoms` fields.
- `adoms: ["*"]` grants full access; `adoms: ["OT-ADOM", "GAS-ADOM"]` restricts to those ADOMs.
- Setting `adom_restriction: false` lifts ADOM filtering for all recognized tokens; unrecognized tokens still receive 401.

**New tests**
- `tests/test_fwanalyst_auth.py` — 6 new cases: `_resolve_allowed_adoms` with restriction disabled, restricted named token, wildcard token, legacy auth_token exclusion, unknown token, ContextVar injection, and named-token-differs-from-primary acceptance.
- `tests/test_fortimanager_adom_guard.py` (new file) — 6 cases: `_require_adom` permitted/denied/wildcard, `get_adoms` filtering/wildcard, and stdio dev-mode full-access default.

#### Engineer token provisioning documentation

- **`SECURITY.md`** — new "Issuing engineer tokens" section: `openssl rand -hex 32` generation, `credentials.yaml` schema, server restart procedure, secure token delivery guidance, revocation steps, and notes on disabling ADOM filtering for single-team deployments.
- **`docs/workstation-onboarding.md`** — new Step 3 "Request your bearer token from the admin" — tells engineers what to ask for, how to treat the token as a credential, and where to find the admin-side procedure.
- **`docs/engineer-workflow.md`** — troubleshooting note updated to distinguish `401 Unauthorized` (bad/revoked token) from the new `ADOM not in your allowed list` error; links to `SECURITY.md` provisioning guide for each case.

### Security

- Fixed: `_resolve_allowed_adoms` no longer resolves the YAML `auth_token` as a named token. Previously, if `FW_ANALYST_TOKEN` env var overrode the admin token, the old YAML value would still match as a named token and receive `{"*"}` access — bypassing token rotation. Now only `server.tokens` entries are resolved here.
