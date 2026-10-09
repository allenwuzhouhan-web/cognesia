# Customer website and API keys

The site in `site/` presents the workbench, model anatomy, chemical messengers,
experiment controls and local research agent. Its illustrative workbench is
explicitly a demo. Its API console connects to a real same-origin gateway.
There is no payment requirement. The public overview is now hosted at
[Cognesia on GitHub Pages](https://allenwuzhouhan-web.github.io/cognesia/).
That static deployment offers documentation and source downloads; the same-origin
API console described below still requires a separate application host.
Public accounts, hosted compute and a custom domain remain pending.
See the [hosting decision and launch boundary](public-hosting.md).

## Customer journey

1. Visit the public site and explore the capability tabs and scientific status.
2. Obtain an individual API access key from the workspace administrator.
3. Enter it in the API console. Access verification returns that customer's
   workspace, permissions and expiration date.
4. Discover tools and make a read-only request. The console displays the real
   response. Scripts can use the same key for the permitted API tools.
5. Disconnect to remove the key from browser memory. Disconnecting does not
   revoke the credential; the administrator can revoke or rotate it separately.

The site has no unauthenticated key-issuance route or open compute signup. Issuing
a key is an explicit administrative action after provisioning the workspace.
The browser never persists keys in cookies, localStorage, sessionStorage or URLs.
Keys are bearer credentials, not biometric/WebAuthn passkeys or user passwords.

## Provision a customer

Run each customer's viewer under its own OS account and workspace root. The
`deploy/cognesia-worker@.service` template uses the instance's port as its identity;
for example, worker `18800` has root `/srv/cognesia/workspaces/18800`.
Prepare its configuration and model inputs using the normal installation guide.
Do not share mutable runs, sessions, checkpoints, boundaries or build directories.
Read-only dataset access must be restricted by the operating system.

From the installed Cognesia directory, as the private gateway's service account:

```sh
.venv/bin/python -m flybrain.public_api \
  --registry /var/lib/cognesia-api/customer-keys.sqlite3 \
  key-issue --customer lab-a --name "Lab A" \
  --workspace lab-a --backend http://127.0.0.1:18800 \
  --workspace-root /srv/cognesia/workspaces/18800 \
  --scopes read --expires-days 90 \
  --output /var/lib/cognesia-api/lab-a-once.json
```

The output file is private (0600), created exclusively and never overwritten.
Its `api_key` value is the customer's credential; the CLI never prints it. Deliver
it to that customer through a private, authenticated channel, then move the
one-time file to a suitable secret store. The service registry stores only a
SHA-256 verifier of the high-entropy token, plus administrative metadata.

Each key has a random identifier and a 32-byte cryptographic random secret.
The random secret alone has 256 bits of entropy; brute-force guessing is
infeasible with current resources, not mathematically impossible. This strength
does not prevent phishing, a stolen device, exposed logs or a compromised server.

`read` is the default permission. Use `--scopes read,run` only for customers who
should start, control and stop experiments in their own workspaces. Customer keys
never expose operator-only model preparation or cache-maintenance tools.

Worker ports, workspace identities and roots are reserved to their original
customer, even after revocation. The registry rejects shared ports, overlapping
roots and escaping mutable-directory symlinks. Before dispatch, the gateway
checks the worker's workspace fingerprint against its assigned root. These are
application checks; separate OS accounts and filesystem permissions remain
necessary for public hosting.

## List, revoke or rotate keys

```sh
.venv/bin/python -m flybrain.public_api \
  --registry /var/lib/cognesia-api/customer-keys.sqlite3 key-list

.venv/bin/python -m flybrain.public_api \
  --registry /var/lib/cognesia-api/customer-keys.sqlite3 key-revoke KEY_ID

.venv/bin/python -m flybrain.public_api \
  --registry /var/lib/cognesia-api/customer-keys.sqlite3 \
  key-rotate KEY_ID --expires-days 90 \
  --output /var/lib/cognesia-api/lab-a-replacement.json
```

Use the nonsecret `key_id` returned by key-list, not the full bearer token.
Revocation/expiry are checked on subsequent authenticated requests. Rotation
issues a fresh key and revokes the old one. A previously dispatched operation
can still finish; inspect or stop the experiment separately if needed.

## Build and preview locally

```sh
.venv/bin/python scripts/build_public_site.py \
  --repository allenwuzhouhan-web/cognesia \
  --site-url https://cognesia.example.com/ --output build/customer-site
```

The example domain is a placeholder, not an active website. Replace it with the
real domain before deployment. The builder emits explicit static assets, a
sitemap and `security-headers.conf` with a hash of the generated JSON-LD metadata.
Keep this header include with its exact matching build.

For a local customer-key gateway and same-origin site preview, in separate shells:

```sh
.venv/bin/python -m flybrain.public_api \
  --registry build/private/customer-keys.sqlite3 \
  --state-file build/private/customer-gateway.sqlite3 \
  serve --auth-mode customer --port 8798 \
  --public-origin http://127.0.0.1:8800

.venv/bin/python -m flybrain.customer_site \
  --site-dir build/customer-site --gateway http://127.0.0.1:8798 --port 8800
```

Issue a key into the local registry first, pointing to a provisioned local
workspace and matching worker port. The preview server is loopback-only and is
not the production server. It forwards only `/health`, `/v1/access`, `/v1/tools`
and `/v1/tools/call`; it never exposes raw viewer routes or the source tree.
The existing owner API on port 8796 can continue independently.

## Public HTTPS deployment

1. Provision a domain, TLS certificate and a dedicated host with security updates.
2. Provision distinct OS users, roots and worker ports for customers. Restrict
   network exposure to HTTPS/HTTP redirect and authorized administration. All
   gateway and worker listeners remain bound to loopback.
3. Install the built website in `/var/www/cognesia`; keep credentials and gateway
   state outside that directory with private permissions and encrypted backups.
4. Configure `deploy/.env.example`, `cognesia-api.service` and `nginx.conf.example`.
   Use the actual HTTPS origin for both site and gateway. Production mode refuses
   the shared owner password. Nginx serves only allowlisted website assets and
   forwards only the documented API routes.
5. Run `nginx -t`, check service startup, certificate renewal, TLS and firewall
   configuration. Exercise invalid/expired/revoked keys, read/run permissions,
   cross-customer access, tool calls, retries and workspace fingerprint mismatch.
6. Share the public URL only after those live checks pass. GitHub Pages can serve
   the introduction, but does not host this Python API or customer workers.

## Security design and remaining responsibilities

- Authorization is checked for every authenticated endpoint and every tool.
  Replay state and experiment leases are scoped to the customer workspace.
- Keys travel in the Authorization header, never query strings. JSON responses
  use no-store, nosniff and no-referrer. API responses contain no private backend
  address or workspace filesystem path in access metadata.
- The website uses a restrictive CSP, no third-party scripts/fonts/trackers,
  no framing, no cross-origin credential requests, no inline executable scripts
  and text-only rendering of API responses. HSTS is configured for HTTPS.
- Both proxy and gateway apply request limits. Tool executions, response sizes,
  cached results, idempotency records and experiment durations remain bounded.
- Key administration is offline; the public site has no administrator credential
  or endpoint. Secrets are excluded from the website build and repository export.

This is a tested set of controls, not a claim of perfect security or an external
penetration test. Operational TLS, account isolation, recovery, patching, abuse
monitoring and incident response must be validated on the eventual public host.
Model simulation success also does not establish biological validity; consult
`REPORT.md` and the model provenance before interpreting experimental results.

Design references: [OWASP REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html),
[TLS](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html),
and [HTML5 browser security](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html).
