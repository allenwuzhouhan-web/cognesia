# Personal access keys for the Cognesia app

Cognesia 0.0.2 protects the official viewer, its APIs and downloads, live
WebSocket connections, and the local research console. A personal access key is
a bearer credential issued by an operator. It is not a Touch ID or WebAuthn
passkey. The app requires a configured customer-key verification service; a
fresh checkout does not include a credential or a public account service.

Website signup, self-service key issuance, and the usage administration panel
are planned in [the website additions plan](website-accounts-plan.md). They are
not live features of this release. Until that service is deployed, an operator
issues keys with the existing command below.

## Before starting

Install Python 3.12 and the package from the repository root as described in the
[README](../README.md#installation). Model preparation is separate from access
setup: the interactive viewer still needs its initial FlyWire assets. Authentication
does not supply model data or satisfy scientific validation gates.

The viewer listens on loopback. The instructions below use viewer port `18794`
and gateway port `18796`; choose unused ports and keep the registered backend
and launch arguments consistent. Do not replace another person's running
workspace. Each account needs a dedicated, non-overlapping workspace directory
and backend port.

## Operator-managed local development setup

This is an explicit loopback development configuration. It provides a real
registry and key-verification gateway on your machine, without claiming a public
signup service or production HTTPS deployment.

From the prepared repository root, issue a key once:

```sh
.venv/bin/flybrain api --registry build/private/customer-keys.sqlite3 \
  key-issue --customer local-researcher --name "Local Researcher" \
  --workspace local-research --backend http://127.0.0.1:18794 \
  --workspace-root "$PWD" --scopes read,run --expires-days 90 \
  --output build/private/local-personal-key.json
```

The output file contains the `api_key` to enter in the login form. It is created
once with private permissions; the command prints metadata, not the key. The
registry stores a SHA-256 verifier for a randomly generated 256-bit secret. Keep
both files under private operator control and out of source exports. Reusing a
customer identifier requires its original name, workspace, root, and backend.

In one terminal, start the gateway:

```sh
.venv/bin/flybrain api --registry build/private/customer-keys.sqlite3 \
  --state-file build/private/tool-gateway.sqlite3 \
  serve --auth-mode customer --port 18796
```

In a second terminal, start the viewer with the development exception explicitly
enabled:

```sh
COGNESIA_ACCESS_URL=http://127.0.0.1:18796/v1/access \
COGNESIA_ACCESS_ALLOW_LOOPBACK_HTTP=1 \
  .venv/bin/flybrain view --port 18794 --no-watch --open
```

Open the private key file locally and paste only its `api_key` value into the
Cognesia login form. The local owner-password gateway mode does not satisfy the
app's personal-key verification contract; use `--auth-mode customer` here.

The gateway can authorize a login before model preparation finishes. Its tool
calls additionally verify the registered worker's workspace fingerprint and use
a private filesystem capability to access that worker. That capability is an
operator credential, not a second browser sign-in method.

## Trusted HTTPS verification

For an operator-deployed service, configure its actual HTTPS `/v1/access`
endpoint before launching the viewer:

```sh
COGNESIA_ACCESS_URL=https://your-service.example/v1/access \
  .venv/bin/flybrain view --open
```

Replace the example with a service you operate or trust. It must implement the
customer-key response in [the API guide](public-api.md), including customer and
workspace identities, `read`/`run` scopes, and key expiry. An arbitrary URL or
owner-password response will not unlock the app. Redirects are refused. Public
plaintext HTTP is refused; the HTTP exception is limited to loopback development.

Missing configuration, invalid/expired/revoked keys, and an unavailable verifier
fail closed. Existing sessions retain the bounded revalidation behavior below.
For a gateway deployed publicly, follow the dedicated-workspace, reverse-proxy,
TLS, and `--production` setup in [the customer deployment guide](customer-website.md).

## Persistent settings and the native macOS window

Apps started from Finder may not inherit terminal environment variables. The
viewer also reads a private configuration file at
`build/private/app-access/config.json`. For the local development example,
create it once from the repository root:

```sh
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

folder = Path('build/private/app-access')
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(folder / 'config.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as handle:
    json.dump({'access_url': 'http://127.0.0.1:18796/v1/access',
               'allow_loopback_http': True}, handle)
PY
```

For HTTPS, use the actual endpoint and set `allow_loopback_http` to `false`.
This command intentionally refuses to overwrite an existing configuration.
Review and edit your existing private file if setup was already completed.
`COGNESIA_ACCESS_URL`, when set, takes precedence over the file.

With Apple's Command Line Tools installed, build the native window locally:

```sh
.venv/bin/python macos/build_app.py --port 18794 --install
```

The build is saved at `build/macos/Cognesia.app` and installs into Applications
when possible, or the user's Applications directory. Keep the gateway running;
the native launcher starts or reconnects to the viewer and research services,
but does not provision the key gateway. Sign in to the simulation viewer before
using the research window. The bundle depends on this checkout, its `.venv`,
and prepared data; it is not a portable, notarized standalone distribution.
See [the native guide](../macos/README.md) for launch and build details.

## Permissions, sessions, and revocation

| Control | Release behavior |
| --- | --- |
| `read` | Inspect permitted model data, saved results, and read-only queries. |
| `read,run` | Also authorize simulation and workspace mutations. |
| Workspace binding | First successful login binds the local workspace to a customer/workspace pair. A different pair needs a separate workspace; logout does not erase that binding. |
| Session lifetime | At most 30 minutes, capped by the key expiry; restarting the viewer loses sessions. |
| Revalidation | Keys are checked again after 30 seconds. The viewer's monitor checks sessions every 2 seconds, and requests also enforce expiry/revalidation. |
| Revocation | The gateway rejects the revoked key immediately on new protected requests. A cached viewer session may remain valid until its next revalidation; verification failure removes that session and requests stopping active work. |
| Logout | Removes the session. Logging out a session with `run` permission requests stopping workspace jobs. |
| Browser storage | The browser receives an opaque HTTPOnly, SameSite=Strict session cookie. The app does not save the personal key in localStorage or URLs. |
| Key memory | The viewer retains the key in process memory for the session so it can revalidate it. The original operator-issued key file remains private on disk until its owner removes it. |

Sessions and CSRF checks protect browser mutations; Host/Origin checks apply to
the viewer and research console. The research console verifies the viewer
session and keeps its history bound to the same account/workspace pair.

List key identities without exposing their secrets:

```sh
.venv/bin/flybrain api --registry build/private/customer-keys.sqlite3 key-list
```

Use the returned `key_id` when revoking or rotating a key:

```sh
.venv/bin/flybrain api --registry build/private/customer-keys.sqlite3 \
  key-revoke KEY_ID_FROM_LIST
.venv/bin/flybrain api --registry build/private/customer-keys.sqlite3 \
  key-rotate ANOTHER_ACTIVE_KEY_ID --expires-days 90 \
  --output build/private/replacement-personal-key.json
```

Rotation creates a new secret and revokes its active predecessor. It does not
reassign the customer's workspace. The replacement output file must not exist.

## Usage accounting and release boundaries

The existing gateway records its tool calls and replay state. The planned
administrator panel will report defined, server-observed usage per account.
This release does not present those records as a complete billing or usage
dashboard. Local experiments started directly in a user's viewer are not
automatically measured by a central service; they require the planned telemetry
or hosted execution design. Changes made to locally available source cannot be
treated as a trusted enforcement or metering boundary.

The public repository remains **all rights reserved** for original Cognesia code
and documentation. Source availability does not grant an open-source license.
Third-party data and components retain their own terms.

The isolated release acceptance report is generated locally at
`build/validation_app_access_release.json`. It exercises real registry issuance,
gateway transport, viewer login and protected access, logout, and revocation
after the actual revalidation interval. It contains no credentials or local
paths. It does not verify a public HTTPS deployment, a hosted signup flow, or
biological model accuracy.

The release source includes the [sanitized acceptance report](evidence/app-access-0.0.2.json).
