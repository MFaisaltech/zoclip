# Focused provider compatibility update — 2026-10-14

Proposal only; no application code, private configuration, financial controls,
provider requests or AI enablement changed. Uses the existing approval sheet and
acceptance handoff. The approved sheet remains byte-for-byte unchanged because
the provisioning command pins its hash. This addendum proposes the required
replacement; it does not authorize implementation, rate installation or live work.

## Gemini replacement proposal

User confirms 2.5 Flash-Lite is absent and 3.1/3.5 Flash-Lite are visible in AI
Studio. Recommend **gemini-3.1-flash-lite** for the smallest acceptance change.
Both are stable text-output models with structured-output support; 3.1 has the
lower published price. Account UI visibility is useful access evidence, but does
not prove the project's API key restrictions, quota or successful inference.
Sources: [3.1 model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite),
[3.5 model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).

| Proposed model | Standard text input USD/token | Output incl. thinking USD/token | Accounting envelope USD |
|---|---:|---:|---:|
| gemini-3.1-flash-lite (recommended) | "0.00000025" | "0.0000015" | 0.022572 |
| gemini-3.5-flash-lite (alternative) | "0.0000003" | "0.0000025" | 0.026420 |

Verified [Google standard pricing](https://ai.google.dev/gemini-api/docs/pricing):
3.1 text input/output USD 0.25/1.50 per million tokens; 3.5 USD 0.30/2.50.
No batch/cache/free-tier discount assumed. Each envelope uses the existing
36000 input/2048 output units, USD 0.0043 for one rounded Deepgram minute and
USD 0.0062 approved local render/storage assumptions. 3.1 provider portion is
USD 0.016372; its initial 27000-input-unit quote estimate totals USD 0.020322.
Decimal calculations checked locally. Both fit the unchanged proposed USD 0.05
application budgets; neither is a guaranteed provider invoice ceiling. Confirm
the account's applicable tier/rates before installation.

Compatibility finding: **existing generateContent architecture is supported;
current acceptance configuration is not ready for a model-name-only switch.**

- Keep fixed v1beta `models/<model>:generateContent`, x-goog-api-key, one text
  request/candidate and 2048 output limit. Keep responseMimeType=application/json
  and Moments responseJsonSchema: the [GenerateContent structured-output guide](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)
  documents that format and lists both models. No Interactions API migration is
  necessary for this test; schema semantics remain locally validated.
- Proposed request delta: replace thinkingConfig={thinkingBudget:0} with
  thinkingConfig={thinkingLevel:"minimal"}; remove the explicit temperature=0.2
  to use default 1.0. The [Gemini 3 migration guide](https://ai.google.dev/gemini-api/docs/generate-content/gemini-3)
  still documents legacy thinking-budget compatibility, so do not infer that
  every such request is rejected. However the [thinking guide](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
  says Flash-Lite cannot fully disable thinking; minimal is supported/default and
  is not a zero-thinking guarantee. Do not send both thinking fields. The migration
  guide recommends default temperature to avoid degraded behavior/loops.
- Existing response parsing (candidates/content/parts, finishReason=STOP,
  Pydantic JSON) and usage accounting for prompt plus all residual output/thinking
  tokens fit the documented GenerateContent shape. This is a code/docs comparison,
  not a live validation. Preserve no-retry/unknown-spend behavior and the existing
  output ceiling; fail closed on unexpected usage or incomplete output.
- After approval, update acceptance_once.models_ready and financial_payloads,
  currently pinned to 2.5, together with reviewed model/rate bindings and the
  approved-sheet hash/manifest workflow. Preserve the historical bootstrap
  manifest's original approval hash; do not rewrite audit evidence. Record a new
  amendment for the model/rate change. Add offline body/binding/usage guard tests
  before installing rates. Current private GEMINI_MODEL remains unchanged.

## Deepgram version discovery

Availability of Nova-3 English batch is now user-confirmed; its fixed version is
still unknown. `nova-3` is a model name, not a version. Never use example version
strings or a model UUID as DEEPGRAM_VERSION.

The [model metadata guide](https://developers.deepgram.com/guides/fundamentals/model-metadata)
explicitly documents public `GET https://api.deepgram.com/v1/models` without an
API key. It returns latest public metadata, including a concrete version string.
Therefore authenticated discovery is **not necessarily required** for standard
Nova-3. Start, after approval, with **one unauthenticated GET /v1/models**, no
request body, audio, Authorization header, retries or redirects. If it yields
one unambiguous Nova-3 English batch entry, preserve its version/model/UUID and
timestamp as evidence; confirm its binding to model=nova-3. Stop on ambiguity,
401/403/429, timeout or missing batch metadata. This lookup has not been made.

Authenticated alternative, separately approved only if needed:

```text
GET https://api.deepgram.com/v1/projects/{existing_project_id}/models
Authorization: Token <existing private local key>
No body; one request; no retries/redirects; no audio or inference endpoint.
```

The [project-model reference](https://developers.deepgram.com/reference/manage/projects/models/list)
documents this authenticated listing and an optional include_outdated flag for
older versions. Default latest metadata is enough to discover a fixed returned
version; no need to enumerate old models initially. Only read model metadata for
the existing project; do not list/create keys, modify project settings, increase
permissions or submit audio. A permission error is a stop, not authorization to
elevate the key. Project ID can come from the console/private local config;
credentials must never be shared in chat.

Validate actual returned STT identity/architecture, English language support,
batch=true and a concrete version; batch means prerecorded here. A streaming-only
entry is invalid. Documentation's example payloads are not live availability
evidence. [Version documentation](https://developers.deepgram.com/docs/version)
uses version=VERSION_NUMBER for standard-model pins; the returned UUID identifies
a model entry and is a different field. Leave DEEPGRAM_VERSION unset until the
returned record establishes the required pin; no latest/beta/guessed fallback.

Billing assessment: these are metadata-management GETs, not audio processing;
expected inference cost is **USD 0**. This is an inference from the endpoint
contract and [usage-based product pricing](https://deepgram.com/pricing), not an
explicit documentation guarantee that every management request is free under
every contract. No separate metadata-call price was found. If a contractual
zero-charge guarantee is required, obtain Deepgram support confirmation before
an authenticated call. No authenticated or unauthenticated provider API was called.

## Minimum remaining action

Approve the documented 3.1 model/request/rate amendment and **one public Deepgram
metadata GET**. That is the smallest discovery step and needs no credentials.
If public metadata is insufficient, separately approve the one scoped project
metadata GET above or obtain the same version evidence from Deepgram support.

Then implement/test the approved small Gemini amendment, save only the verified
Deepgram pin, confirm applicable account rates, and install the five rates plus
breaker=true USD 0.05 policy through the existing audited admin routes. Existing
admin/one-credit setup is already complete. Finally, explicit breaker-opening
and one-shot live-execution approval is still required. No new general audit or
rebuild is necessary. AI remains disabled and the breaker remains open.
