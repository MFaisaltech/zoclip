# YouTube import and security release preparation — 2026-10-29

Updated 2026-10-30 for the final focused verification round.

Branches remain backend `perf/parallel-pipeline` and frontend `ui/responsive-pass`.
The Generation Studio redesign is preserved. No staging deployment, production
change, schema migration, pricing/payment change or historical balance mutation
has been performed. Test accounts and financial terms exist only in disposable
databases. Provider credentials are absent from runtime verification.

## Root causes and implementation

1. The running AI worker belongs only to internal `data` and `queue` networks.
   Docker's embedded resolver cannot forward public DNS in that configuration;
   `www.youtube.com` fails with `EAI_AGAIN`. The opt-in YouTube overlay adds an
   outbound network and explicit DNS resolvers to **only** that worker. Database,
   Redis, API and render-worker networking remain private. No ports are published
   by the worker or its relay. Outbound routing is not a DNS-only firewall rule.
2. `LINK_PROXY_URL` is empty in the actual worker; host loopback WARP is not
   container loopback. Two systemd Unix socket units forward to existing host
   `127.0.0.1:40000` and `127.0.0.1:4416`. Socket mode is `0600`, UID/GID 10001.
   A bounded relay joins the worker's network namespace, binds its TCP listeners
   to `127.0.0.1` only, and mounts only those Unix sockets read-only. It receives
   no database secrets or media volume. The original host services keep their
   loopback listeners. No host TCP proxy listener is added.
3. A host plugin installation is invisible in the worker image. Pin and lock
   `bgutil-ytdlp-pot-provider==2.0.2` inside the worker Python environment and
   assert importability during image construction. Use the recommended `mweb`
   client and HTTP token provider, rather than skipping webpage/visitor data.
4. Once networking and token discovery worked, actual extraction exposed a
   missing JavaScript runtime and challenge solver. Pin `yt-dlp==2026.10.26`,
   matching `yt-dlp-ejs==0.8.0`, and the Node 22.23.3 binary from a digest-pinned
   image. Pass `--js-runtimes node`; no solver download is enabled at runtime.
5. The local Whisper/local-selection configuration incorrectly required Gemini
   credentials. Configuration now requires credentials only for selected paid
   providers. `AI_ENABLED` remains mandatory, and private staging still forbids
   enabling AI. No private-staging or spending breaker is bypassed.
6. Real 26.735-second media exposed a fractional-duration bug: auto-render wrote
   a float into integer Settings bounds, causing `ai_processing_failed` before
   transcription. Clip bounds now use an integer floor of source duration,
   preserving the source ceiling. Fractional upload/link regressions were added.

URL canonicalization, exact HTTPS YouTube host/video-ID validation, rights,
authentication, CSRF, owner isolation, admitted byte caps, probing, duration and
capacity limits remain enforced. Direct-file import keeps its existing SSRF,
connected-IP and redirect checks. Production downloads with an empty proxy fail
before launching yt-dlp; they cannot silently fall back to direct egress.
Downloader stderr is no longer returned to customers, and unread subprocess
pipes cannot deadlock the download. Socket timeout/retry bounds and the existing
whole-download deadline remain in place.

Primary references: [PO-token guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide),
[bgutil installation](https://github.com/Brainicism/bgutil-ytdlp-pot-provider),
[yt-dlp EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

## Recorded verification

- An isolated, unprivileged, read-only candidate worker and relay on the existing
  VPS passed DNS, plugin discovery, token-service ping, and WARP `warp=on` checks.
  `download_youtube` downloaded the authorized Blender sample
  `aqz-KE-bpKQ`: **155,343,407 bytes; 634.624 seconds**, verified with ffprobe.
  No staging DB, Redis or retained-media volume was attached. Disposable socket
  activation processes, containers and network were removed afterward.
- Frontend **86 unit tests**, lint, TypeScript and all three API contract checks
  passed. Next.js **16.4.1** production webpack build passed on the existing VPS.
  Five Generation Studio desktop/mobile browser tests passed, including both
  input methods, exact confirmation, balance rejection, preview and download.
  Those five tests intercept API requests; screenshots show synthetic fixtures.
- Full Linux backend run: **744 passed, 19 failed, 37 errors, 14 skipped**.
  Follow-up: **306 passed, 1 failed**, with all earlier failures/errors/skips
  addressed by explicitly configured historical fixtures and isolated mock DBs.
  The remaining failure identified the fractional-duration defect described
  above. The final **80-case focused run passed**, including actual local Whisper
  inference, automatic rendering, single settlement, fractional upload/link cases,
  URL/ownership protections, and private deployment fences. All earlier backend
  failures are resolved through the focused reruns; the original whole-suite run
  is not described as green. It was not repeated.
- Historical single-use executor tests now use their original migration and
  explicitly test rejection of a newer schema. Existing execution fences remain
  unchanged. The legacy cap fixture pins its historical chunk budget.
- Ruff, formatting, mypy (87 application sources), and `uv lock --check` pass.
- Connected browser acceptance: **seven distinct cases pass across focused runs**:
  the earlier invalid-token case, five cases in the connected rerun, and the final
  registration/recovery/cross-tab case. Both generation inputs use actual local
  Whisper and FFmpeg, exact quote consent, authenticated preview/download and
  single settlement. Lost generation acknowledgment reuses one idempotency key,
  creates one job, and charges once. Mobile upload has no horizontal overflow.
  Authentication covers CSRF/origin denial, unavailable/malformed identity retry,
  duplicate submission protection, registration/verification, password recovery,
  cookie privacy, reload and cross-tab logout. The old status-text selector was
  replaced with the existing account identity display; the second tab is explicitly
  focused. Its final bounded browser run passed with a 2-GiB test-container ceiling.
  No application auth guard was relaxed. Successful cases were not rerun wholesale.
- Render/credit suites use real PostgreSQL, Redis and FFmpeg. The full suite and
  follow-up run in loopback-only container namespaces without Internet routes.
  The separate connected browser harness uses actual local Whisper and FFmpeg;
  its YouTube transport supplies the authorized local fixture. It does not claim
  that this fixture transport is a live YouTube download.

## Staging activation boundary

The running staging worker still has `PRIVATE_STAGING=true`, `AI_ENABLED=false`,
Whisper selected, payments disabled and absent paid-provider keys. The frontend's
private-preview mode intentionally refuses generation confirmation. This release
does not silently remove those controls. A paused-profile import/security rollout
alone **will not enable the requested live link-to-clips workflow**.

Full protected-staging generation requires a separately reviewed local-only
runtime/frontend activation configuration and existing spending-policy gates.
Do not change catalog prices, historical wallets, payment settings or bypass the
breaker to make an acceptance test pass. Do not deploy either scope without the
owner's explicit approval. A clean disposable workflow is not live acceptance.

## Safe rollout and rollback plan — not executed

1. Resolve the activation boundary above and approve the exact scope, branch
   commits, immutable image digest, protected frontend build and maintenance
   window. Preserve the existing VPN-only API, loopback HTTPS/admin publication
   and Vercel protection. No merge into main and no production alias change.
2. Record current Compose files, environment/approval metadata, old app image and
   protected frontend deployment. The old running app image is present locally.
   No migration is added by this release, so rollback requires no schema downgrade.
3. After approval, quiesce through the current release's controller and make a
   **fresh** encrypted DB/media backup. Verify ciphertext hashes, copy off-server,
   authenticate decryption locally and restore only into an isolated empty target.
   Keep the age identity off the VPS. Existing backup
   `20261027T200811-fc57a78b.json` passes both ciphertext checksums; that does not
   certify a new backup or a new off-server restore for this release. Existing
   backup/restore guard tests and historical restore evidence remain available.
4. For import connectivity, install the four reviewed `zoclip-link-*` units,
   validate with `systemd-analyze verify`, and enable only the two socket units.
   Check socket ownership/modes and both host services. No public TCP forwarding,
   host networking, Docker socket mount or host-service rebinding is required.
5. Use reviewed Compose files in order: `compose.yaml`,
   `compose.private-staging.yaml`, `compose.youtube-import.yaml`. The controller's
   `--private-staging --youtube-import` plan has been validated with synthetic
   metadata. It rejects other application egress and unreviewed relay mounts,
   secrets, publication and proxy/DNS settings. Set the reviewed immutable
   `APP_IMAGE` through the existing artifact procedure, verify the exact digest,
   and require the matching backup-approved rollout marker before `up`.
6. Recreate the worker and relay together; their network namespaces are shared.
   Verify relay health before accepting imports, all seven original service health
   checks, VPN access, unauthenticated API denial and zero public proxy ports.
   Run the authorized worker smoke. Publish only the approved protected staging
   frontend build, then perform the approved acceptance scope with test accounts.
7. Roll back on any critical failure: stop candidate workloads and remove only the
   candidate relay, stop its socket/service units, restore the captured old release
   configuration and image, and restore the previous protected frontend deployment.
   Use the **old** Compose profile, without the new YouTube overlay, for the old
   image: it has no relay module. Preserve all volumes, DB history and backups.
   Never use `down -v`, an automatic downgrade, or Deepgram as a paid fallback.
   Restore a backup to live data only under a separate, explicit recovery approval.

No rollout, service restart, new socket unit installation or backup quiescence
has been performed on staging. All seven staging services remained healthy.

## Final focused checkpoint — 2026-10-30

Critical code verification passes. Backend: 80 targeted passes; the earlier
306-case follow-up resolved historical fixtures. Frontend: 86 unit passes, five
isolated generation browser passes, seven connected browser cases across focused
runs, TypeScript/lint/contracts and the 16.4.1 production build. No full suite or
long-video benchmark was repeated in the final round. The candidate runtime OCI
manifest from the final application build is
`sha256:f571a1bac43ebfdecff8bd2dd06f75dedb0e897356d4b0d46d11ca025cc3a55c`.

The import/security fixes can proceed to owner review for protected staging.
Full **live generation activation remains gated** by the deliberately closed
staging configuration described above. A fixes-only deployment preserves that
pause. Do not claim the running staging site generates clips before an approved
activation configuration and post-deployment acceptance.
