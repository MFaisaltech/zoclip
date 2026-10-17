# Transactional email operations

The API issues hashed, expiring, single-use verification/reset tokens and commits
an encrypted PostgreSQL mail outbox in the same transaction. SMTP happens in the
maintenance worker, after commit. Each message has a unique operation key, AES-256-GCM
nonce and authenticated row/user/purpose binding. Recipients and raw tokens never
appear in queue metadata, operational logs or HTTP responses.

Delivery is at least once: an SMTP acknowledgement lost during a crash can repeat
the same email. There are at most three persisted attempts, with 60/300-second
delays, a three-minute reclaim lease, and a row lock through transport IO.
Transport uses certificate-verified implicit TLS on 465 or mandatory STARTTLS on
587, ten-second socket timeouts in the worker, and no plaintext fallback.
Sent, terminally failed, expired and erased-account payloads are wiped. Redacted
rows are removed seven days after their delivery/token expiry. Superseded queued
links are expired; consumed or expired tokens and disabled accounts cannot send.
Queue failures and stalls appear in the existing operational monitor. Existing
auth rate limits remain enforced; outstanding mail is bounded per user.

The receipt observer reads at most ten recent, settled PAID orders per cycle,
requires the recorded credit grant, and queues one receipt per order. It cannot
accept payment, mutate an order or grant credits. It is inactive with email disabled.
No payment architecture or financial terms changed.

## Configuration needed for actual delivery

No authorized SMTP account is configured in private staging. Required inputs:
SMTP hostname; 465/implicit TLS or 587/STARTTLS; username; password installed via a
private secret file; verified From address; sender domain; provider DKIM selector
and TXT/CNAME records. Do not put passwords, queue keys or tokens in Git or chat.

For a later separately approved production deployment, review
`deploy/compose.smtp.example.yaml`. It mounts `smtp_password` and `email_queue_key`
using the existing `/run/secrets` loader. Generate a random 32-byte key with a
cryptographic RNG, base64-encode it, and install the private file readable by UID
10001. Do not rotate the key while deliverable ciphertext remains: drain/expire
the queue first. Retain the key in the encrypted recovery secret store while
restorable backups contain pending messages. Wrong keys fail closed.

The example adds outbound mail networking only to maintenance, with no published
ports. A later operator must restrict host egress to the authorized SMTP service.
It deliberately does not override PRIVATE_STAGING, registration, AI or payment
restrictions. Combining it with private staging fails configuration validation.

Before enabling delivery: publish the provider's SPF record without creating a
second SPF record; publish its DKIM selector; configure an aligned From domain and
DMARC at `_dmarc.<sender-domain>` (review aggregate reporting destination/retention
with the owner). Verify public DNS and domain verification in that provider's
account, then send one owner-authorized verification and reset email and inspect
Authentication-Results for SPF/DKIM/DMARC alignment. Exact DNS values cannot be
invented before a provider and sender domain are supplied.

Private staging remains email/registration disabled. This release sends no real
mail. Delivery, inbox placement and DNS authentication are BLOCKED, not live verified.
