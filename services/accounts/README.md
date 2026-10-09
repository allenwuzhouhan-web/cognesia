# Public Cognesia accounts

Status on 2026-10-09: implemented and verified against local Firebase emulators.
**Not deployed.** No real verification email or SMS has been sent. The live
GitHub Pages site intentionally does not link to this portal until deployment
and real delivery checks pass.

The portal supports email/password signup with email-link verification and
phone signup/sign-in with a six-digit SMS code. Only a verified, enabled Firebase
user can enroll. Enrollment issues a personal Cognesia access key once. Subsequent
sign-ins show its status; users can replace or revoke it. Keys use 256-bit random
secrets, are stored only as SHA-256 verifiers, expire after 90 days and retain the
existing app's `cgnk_…` and `/v1/access` contracts. These are bearer access keys,
not Touch ID/WebAuthn credentials.

Each account has a separate stable local-workspace identity. This service grants
local app access; it does not expose the owner's Mac or provision hosted compute.
Existing local account/workspace bindings are preserved and cannot be reassigned
by signing in as another user.

## Implementation

- `web/`: signup, verification, sign-in, password-reset and key-management UI.
- `functions/`: trusted Firebase Admin identity checks, transactional key
  issuance/replacement, revocation and the app's HTTPS verifier.
- `firestore.rules`: browser access is denied; only the backend owns key records.
- `scripts/build.mjs`: bundles the browser SDK locally; production configuration
  comes from Firebase Hosting's reserved initialization endpoint.
- `test/integration.test.mjs`: actual Auth/Firestore emulator requests, database
  rules, transaction races, and a login through Python `AppAccess`.

Key mutations require a sign-in within ten minutes, same-origin JSON requests,
a 30-second replacement interval and a persistent five-keys-per-day limit.
Replacement revokes the old key in the same transaction. Disabled/deleted accounts,
revoked keys, expiry and provider token-revocation timestamps are checked by the
public verifier. Browser sessions are memory-only; keys are never written to
browser storage, URLs or analytics. Do not log request bodies or credentials.

## Local validation

Use Node 22, Java 21 and the project's Python 3.12 environment:

```sh
cd services/accounts
npm ci
npm --prefix functions ci
npm run build
npm test
npm run test:integration
npm run preview
```

The preview uses the `demo-cognesia-accounts` project and binds to loopback on
ports 15000 (website), 15001 (function), 18080 (database) and 19099 (identity).
The build creates an ignored local Firebase config and `.env.local` for this
emulator only. It never enables test verification in production. Emulator email
links and SMS codes are printed locally; no real messages are delivered.
Set `COGNESIA_PYTHON` if the Python interpreter is not at the workspace `.venv`.

## Production activation

1. Sign in to the Google account that should own the service and create/select a
   Firebase project. Owner sign-in is confirmed; project creation is awaiting
   acceptance of the Firebase terms. No production project exists yet.
2. Enable the Blaze billing plan only after the owner approves the billing setup.
   Configure the agreed SMS destination countries and quotas. Cloud Functions
   and production SMS require Blaze. Provider budgets send alerts; they are not
   guaranteed spending caps. `maxInstances: 1` also is not a spending cap.
3. Enable email/password authentication, enforce a minimum 12-character password
   policy, enable email-enumeration protection and verify the email templates.
   Enable phone authentication only after billing, destination-country policy,
   reCAPTCHA and delivery testing are ready. Keep it disabled otherwise.
4. Register a Firebase web app, create Firestore in locked production mode, and
   choose the desired data region (the prepared function uses Singapore,
   `asia-southeast1`). Authorize the actual Firebase Hosting domain for Auth.
5. Run `npx firebase login` in this directory. Keep the CLI credential in its
   provider-managed storage. Do not put a service-account private key in the
   repository, browser bundle, GitHub variables or website build.
6. Create an ignored `functions/.env.PROJECT_ID` from `.env.example`. Set
   `ACCOUNT_ORIGIN` to the exact HTTPS Hosting origin and leave
   `PHONE_SIGNUP_ENABLED=false` until real SMS verification is ready.
7. From this directory, run `npm run build` (without `--emulator`) and
   `npx firebase deploy --project PROJECT_ID --only firestore:rules,firestore:indexes,functions:accounts,hosting`.
   Replace `PROJECT_ID` with the actual selected project ID. The deployment uses
   this separate project, not any existing research-service project.
8. On the public address, verify email delivery, SMS delivery for approved
   countries, signup, repeat sign-in, key display once, replacement, revocation,
   wrong-key rejection and a real app login. Do not use fictional test identities
   as evidence of real message delivery.
9. After those checks pass, set the GitHub repository variable
   `COGNESIA_ACCOUNTS_URL` to the verified portal origin, then run `pages.yml`.
   The website builder accepts only an explicit HTTPS account-portal origin.
10. Ship the actual public `/v1/access` endpoint in
    `src/flybrain/public_access.json` as `{"access_url":"https://ACTUAL_HOST/v1/access"}`
    with the next source release. This optional release-owned default is used
    only when no explicit environment/private operator configuration exists.
    The file is deliberately absent until the verifier is live. Existing 0.0.2
    installations need the documented private access configuration or an update.

## Remaining live requirements

Firebase terms acceptance, selected project, billing approval, explicit country
restrictions and SMS limits, production email/SMS delivery, deployment and a release with
the real verifier endpoint remain outstanding. The public website stays usable
while this activation is pending. No billing has been enabled.

Email and phone are alternative accounts unless the owner later adds an explicit
verified account-linking flow; this implementation never merges identities by
unverified contact strings. Administrative account deletion is currently handled
through the provider console. Self-service deletion and broader usage/admin UI
are separate work.

Provider references:
[email authentication](https://firebase.google.com/docs/auth/web/password-auth),
[phone verification](https://firebase.google.com/docs/auth/web/phone-auth),
[quotas and SMS billing](https://firebase.google.com/docs/auth/limits),
[Cloud Functions deployment](https://firebase.google.com/docs/functions/get-started),
[ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens).
