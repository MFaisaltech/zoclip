# Protected staging account gate

Rollouts remain paused: `STAGING_GENERATION_ENABLED=false` and
`STAGING_GENERATION_USER_ID=` (empty). `AI_ENABLED=false` always remains in place.
The rollout controller refuses enabled generation. No migration is needed.

After explicit owner approval, a separate controlled activation must configure
the API, AI worker and render worker identically:

```dotenv
APP_ENV=production
DEPLOYMENT_TIER=protected_staging
PRIVATE_STAGING=true
AI_ENABLED=false
STAGING_GENERATION_ENABLED=true
STAGING_GENERATION_USER_ID=<one authenticated test account UUID>
TRANSCRIPTION_PROVIDER=whisper
ANALYSIS_PROVIDER=local
DEEPGRAM_API_KEY=
GEMINI_API_KEY=
PAYMENT_PROVIDER=disabled
ENABLE_LIVE_PAYMENTS=false
ENABLE_TRIAL_CREDITS=false
REGISTRATION_ENABLED=false
```

`APP_ENV=production` retains secure runtime validation; `DEPLOYMENT_TIER`
distinguishes protected staging from actual production. Production's default tier
rejects any configured allowlist. The private staging profile is also required;
production must never use that profile or the protected staging tier.

The UUID is a single database identity, never an email, list or browser-supplied
claim. Authentication and ownership checks remain mandatory. Other accounts are
rejected before ledger mutations; queued blocked jobs fail and release holds once.
Direct execution and render entry points enforce the same restriction.

Rebuild the protected staging frontend with `NEXT_PUBLIC_PRIVATE_STAGING=true`,
`NEXT_PUBLIC_STAGING_GENERATION_ENABLED=true` and
`NEXT_PUBLIC_STAGING_GENERATION_USER_ID=<same UUID>` only after approval. These
public values control presentation; they grant no API permission. Keep both new
frontend values absent/false while paused.

The existing approved price version, available credits, expense policy and
spending breaker remain authoritative. An open breaker still blocks reservation.
Paused private staging requires breaker=true at startup. Approved activation can
start with either breaker state but never changes it automatically. Financial
controls must be reviewed separately before a real generation test; this change
does not change prices, policies, balances, trials or payments. Provider credentials
and non-local processing are rejected even for the allowed account.

To pause again, disable the backend flag on all three services first, then rebuild
the frontend with its flag false. Existing job execution is gated at each claim;
an inference already running must be stopped gracefully during the pause.
