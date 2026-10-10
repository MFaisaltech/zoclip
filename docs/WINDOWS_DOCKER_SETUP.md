# Windows Docker Desktop / WSL2 setup - historical Phase 1 instructions

The pending statements below describe the original setup handoff. Local Docker
Phases 1 through 3 verification is recorded in IMPLEMENTATION_STATUS.md; current ingestion
and disk requirements are in INGESTION_HANDOFF.md. Contabo remains untouched.

Prepared 2026-10-10. These installation and Docker commands have **not** been run.
The user will install Docker locally first. Contabo access and changes are outside
the authorized scope. Phase 2 remains unstarted.

## 1. Check the Windows support prerequisite

Read-only local checks found Windows 10 Pro 22H2 build 19045.6466, approximately
8 GB RAM, Intel i7-4785T with virtualization/SLAT enabled, no active hypervisor,
and LanmanServer running with Automatic startup. Docker is absent. The present
inbox `wsl.exe` did not provide modern status/version information; WSL2 is unverified.

Microsoft ended normal Windows 10 Home/Pro support on October 14, 2025.
See [Microsoft lifecycle](https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro).
Docker lists build 19045 but also requires a Windows release within Microsoft's
servicing timeline. A matching build alone is not proof of current support. Resolve
OS servicing eligibility before relying on Docker Desktop; ESU/Docker eligibility
has not been verified for this PC. Do not bypass Windows hardware requirements.
See [Docker's current prerequisites](https://docs.docker.com/desktop/setup/install/windows-install/).

The following steps assume a supported Windows installation. They change only
your Windows PC and may require administrator elevation and a restart.

## 2. Install/update WSL2

Save your work. Open **PowerShell as Administrator** and run:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart Windows when requested. Launch Ubuntu-24.04 from Start and create its local
Linux username/password. Keep those credentials private. Then in Administrator
PowerShell run:

```powershell
wsl --update
wsl --set-default-version 2
wsl --list --verbose
```

If Ubuntu-24.04 is listed as version 1, convert it:

```powershell
wsl --set-version Ubuntu-24.04 2
```

Verify:

```powershell
wsl --version
wsl --status
wsl --list --verbose
wsl -d Ubuntu-24.04 uname -r
```

Ubuntu must report version **2**. Docker requires WSL 2.1.5 or newer; use current
stable WSL. If the old inbox command displays help or lacks update/install support,
install the latest stable x64 WSL MSI from [Microsoft's WSL releases](https://github.com/microsoft/WSL/releases),
restart, then repeat. If a distro name is rejected, use `wsl --list --online` to
confirm it. For a download stuck at 0%, Microsoft documents:

```powershell
wsl --install --web-download -d Ubuntu-24.04
```

For virtualization/feature errors, follow [Microsoft's troubleshooting](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting).
Do not disable security features as a workaround. See [Microsoft's WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install).

## 3. Install Docker Desktop

1. Download the x86_64 Windows installer from [Docker's official installation page](https://docs.docker.com/desktop/setup/install/windows-install/).
2. Run it interactively. Choose per-user installation when available and the WSL2
   backend. Review the license terms yourself. Restart if requested.
3. Start Docker Desktop from Start and wait for its engine to be running.
4. In Settings > General, enable the WSL2 engine if the option is shown. In
   Resources > WSL Integration, enable Ubuntu-24.04 and apply the changes.
5. Use **Linux containers**. Do not install a second Docker Engine inside Ubuntu.

See [Docker's WSL2 configuration guide](https://docs.docker.com/desktop/features/wsl/).
Your 8 GB PC meets the stated RAM minimum; this is not a render/load capacity result.
Keep image/volume growth in mind and close unnecessary memory-heavy applications.

## 4. Verify the local engine

Open a new ordinary PowerShell window so PATH is refreshed:

```powershell
docker context ls
```

Choose Docker Desktop's **local** Linux context (usually `desktop-linux`), not an
SSH/TCP context. If that context is listed:

```powershell
docker context use desktop-linux
docker version
docker compose version
docker info --format '{{.OSType}}'
docker run --rm hello-world
```

Both client and server must appear, Compose must be available, and OSType must be
`linux`. If the local context is absent or the server cannot be reached, start/fix
Docker Desktop before continuing. Nothing here configures a remote Docker host.

## 5. Run the pending ZoClip container checks

Only after the preceding checks pass, use the isolated local project below.
`.env.example` contains development-only placeholders and no live credentials.
It is intentionally used for this disposable test; no private `.env` is needed.
Port 8000 must be free. Commands below must use the local Desktop context.

```powershell
Set-Location D:\zoclip
docker compose --project-name zoclip-phase1-check --env-file .env.example config --quiet
docker compose --project-name zoclip-phase1-check --env-file .env.example build
docker compose --project-name zoclip-phase1-check --env-file .env.example up --detach --wait --wait-timeout 180
docker compose --project-name zoclip-phase1-check --env-file .env.example ps --all
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
docker compose --project-name zoclip-phase1-check --env-file .env.example exec -T api alembic current
docker compose --project-name zoclip-phase1-check --env-file .env.example exec -T api alembic check
docker compose --project-name zoclip-phase1-check --env-file .env.example exec -T api python scripts/container_smoke.py
```

`container_smoke.py` checks actual API readiness, PostgreSQL connectivity/migration
head and Redis PING, then submits a harmless addition job to **each** `ai`/`render`
queue. The already-running Linux workers must return 42 within a bounded deadline.
It does not call AI, email, OAuth, payments or grant credits. Failed assertions exit
nonzero. Its PASS output is expected behavior, **not an observed result yet**.

Accept only: successful image build; migrate exited 0 at revision 39bc6d102a49;
db/redis/api healthy; both worker services running; no schema drift; both actual
worker job results verified. YAML parsing alone does not satisfy these checks.

If startup fails, inspect local logs privately:

```powershell
docker compose --project-name zoclip-phase1-check --env-file .env.example logs --tail 100 migrate api worker-ai worker-render
```

Do not publish unredacted logs or environment output. Stop this isolated project:

```powershell
docker compose --project-name zoclip-phase1-check --env-file .env.example down
```

This preserves its volumes. Never use a volume-removal option on data you need.
The CI workflow contains the same container startup/smoke gate, but has not run here.

## Remaining gates

Docker build/start and official Linux Redis/RQ verification remain **PENDING** until
these commands actually succeed. A separate Windows Redis port check is recorded
in IMPLEMENTATION_STATUS.md; it does not close the Linux/Compose gate. Real Google,
live email, Contabo deployment/load and production backup/restore remain untested.
Return the local results before moving to Phase 2.
