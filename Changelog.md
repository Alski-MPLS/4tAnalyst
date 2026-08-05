# Changelog

All notable changes to this project are documented here.

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
