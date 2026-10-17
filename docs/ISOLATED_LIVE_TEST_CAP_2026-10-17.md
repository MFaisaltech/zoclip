# Isolated live-test cap preparation - 2026-10-17

**Update:** The owner subsequently authorized installation. The reviewed package
and additive migration are now installed with an unapproved entitlement after
fresh encrypted backup verification. See the
[installation result and remaining evidence blockers](ISOLATED_LIVE_TEST_INSTALL_2026-10-17.md).
The installation-blocked text below records the earlier preparation state.

Implementation and offline verification are complete. **Live test READY FOR
APPROVAL: NO.** Automatic approval review rejected the staging installation.
The new entitlement/cap have **not** been installed there. Verified credential
and account-rate evidence is also absent. No paid execution is authorized.

The rejection concerned uploading code and changing the shared server/database
without explicit authorization for that deployment. No remote mutation occurred.
The subsequent local-only four-file package has not been uploaded or executed.
Installation approval would not authorize paid processing.

## Exact source

Fresh read-only SSH verification against the existing private API container:

| Field | Verified value |
|---|---|
| Video ID | `9cced2b6-cf08-410c-b653-318eef1dc5fe` |
| SHA-256 | `4e07da5b61752632ccc5027a9a0156e10b7efe4c6fdb70647796c745995deb80` |
| Bytes | 114,549,007 |
| Exact duration | 25,170 ms; admission rounds up to 26 seconds |
| Streams | 2160 x 3840 H.264 video, AAC audio |
| Stored/probed duration | Exact match |
| Database durability | fsync and synchronous_commit enabled |
| Current staging migration | `8c42ab719e30`, unchanged |
| Current controls | AI disabled, breaker open, payments disabled, provider keys empty |

Historical acceptance bindings, approvals and financial policies are untouched.
The exact source ID/hash are pinned in the new preparer. No source upload or
historical entitlement reuse is needed.

## Implemented safeguards

`src/zoclip/ops/isolated_live_test.py` is operator-only: no HTTP route, RQ job,
scheduler hook or credit bypass in the public pipeline. The sponsored job lives
only in its own entitlement table. Preparation creates no customer credits,
normal quotes/reservations, paid entitlements, billing orders, public processing
jobs or provider requests. Existing staff audit contracts record operator actions.

Forward migration `c910a2e31f40` adds two tables and protective triggers. It does
not change existing customer rows or open the normal circuit breaker. The
entitlement table permits one row, bound immutably to one job, source, owner and
configuration. Its numeric USD cap is constrained to **0.10**. The call table
permits one globally unique slot per component. The public `zoclip_runtime`
database role has no access to these tables.

| Component | Maximum | Permanent maximum-cost hold USD |
|---|---|---:|
| Deepgram Nova-3, en, version 2025-07-31.0 | 1 POST; <=27 seconds mono PCM; one minute reserved | 0.004300 |
| Gemini 3.1 Flash-Lite, text only | 1 POST; <=36,000 input tokens; <=2,048 output including thinking | 0.012072 |
| Local extraction/render/storage allocation | 1 generated clip; no re-export | 0.083628 |
| Aggregate | 1 isolated job; **zero paid retries** | **0.100000** |

Both application admission and a PostgreSQL BEFORE INSERT trigger check the
aggregate. Row locks serialize concurrent contenders. Permanent maximum-cost
holds commit before side effects; only the committing process may dispatch.
Replays cannot reconstruct permission. Holds never reset or decrease on failure,
date rollover or restart. Triggers reject deletion/truncation, source/policy/cap
changes and resetting final outcomes. Downgrade refuses to erase a prepared test.

Serialized Gemini UTF-8 request bytes plus 1,024 safety units must fit the input
bound. Exact generation configuration permits one candidate, no tools, grounding,
caching or model fallback. Chunking cannot cause a second paid request. The
existing HTTPS adapter enforces fixed destinations, TLS, no redirects/environment
proxies or implicit retries. Deepgram WAV format/duration is checked before IO.

Every admission rechecks source ownership/state/expiry, bytes, SHA-256 and actual
ffprobe duration, closed public controls, PostgreSQL durability, approval,
credential fingerprints and configuration. Unknown usage blocks further work.
429, timeout, non-200, malformed/missing usage and overruns stop the whole test.
Unknown/in-flight calls keep their full hold. Process death leaves a consumed
HELD slot; no retry/reset path exists. Rendering also consumes a durable slot.

Approval is separately audited, single-use and expires after one hour. It requires
explicit owner authorization for the exact job/source/policy, source consent,
verified account credentials, matching applicable rates and a verification
reference. Key presence is insufficient. These real external facts have not been
established for this new test. The prepare/inspect CLI cannot approve or execute.

The provider subtotal is 0.016372 USD at the pinned published rates, checked
against [Google standard pricing](https://ai.google.dev/gemini-api/docs/pricing)
and [Deepgram prerecorded pricing](https://deepgram.com/pricing). The remainder
is an operator accounting allocation, not a measured invoice. Applicable account
rates/options remain a gate. Application admission cannot override provider
billing errors or establish unknown taxes/FX fees. No external provider-project
hard cap or provider invoice guarantee was verified.

## Verification and installation boundary

Final fresh PostgreSQL 17 run: **157 passed**, zero skipped/failed, 77.71 seconds.
Files: `test_isolated_live_test.py`, `test_provider_amendment.py`,
`test_config.py`, `test_private_staging.py`, `test_credits.py`.

The 37 new cases cover concurrent dispatch, database enforcement independent of
application admission, actual child-process death after committed admission,
restart/re-entry, uncertain spend, both providers' failure/overrun behavior,
request limits, changed source/job/config/keys, expired approval, non-durable DB
settings, denied runtime-role access, one real FFmpeg clip with mocked providers,
and failed render without retry. The small synthetic financial fixture uses
synthetic 26-second metadata; it is distinct from the real staged source verified
above. FFmpeg extraction/rendering uses the small real media fixture.

Tests initialized a separate loopback PostgreSQL instance and stopped it afterward.
Existing databases were not modified. Actual HTTP transport is blocked in guard
tests; provider replies use MockTransport. Two existing Authlib/Starlette
deprecation warnings remain. Ruff check/format and mypy (80 source files) pass.
Migration upgrade, empty-target downgrade/re-upgrade and metadata comparison pass.
Restart evidence is from real separate test processes, not a staging restart.

Local evidence and concrete review package:

- `var/release-regression-63d93e91/results.xml`
- `var/isolated-live-test-20261017/manifest.json`
- `var/isolated-live-test-20261017/operator-cap.tar.gz`
- `var/install-live-cap.py` (prepared installer; remote execution was blocked)

The package contains the two operator modules, additive migration and prepare CLI.
The proposed installation uses the existing immutable image in a temporary
restricted container on the internal data network with read-only media. It
checks unchanged customer/job/financial counts and prepares one unapproved
entitlement. Public images/services, keys and controls stay unchanged. It
does not enable egress, approve a test or dispatch providers. **Not executed.**

After installation approval, cold inspection must confirm the durable job/source
binding, 0.10 cap, zero dispatches and closed public controls. Valid private
credential/account evidence is still required before paid-test readiness can be
reassessed. No spending authorization is requested at this stage.
