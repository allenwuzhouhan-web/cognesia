# Public Cognesia accounts

The launch backend uses **Netlify Free** with **Firebase Authentication and
Firestore on Spark**. Billing remains disabled. Email/password signup with email
verification and Google sign-in are supported. Phone signup is disabled because
Firebase's production SMS verification requires billing.

Status on 2026-10-09: local production build, five unit checks and eleven emulator
integration checks pass. The Netlify function bundles successfully. The existing
Netlify team is Free, with 300 monthly credits and no saved payment method.
Public deployment and real signup verification remain pending CLI authorization.
The GitHub Pages overview is already public; its signup link remains gated until
the account service is verified live.

## Accounts and access

Only a verified, enabled Firebase user can enroll. Enrollment issues one personal
Cognesia access key. Subsequent sign-ins show its status; users can replace or
revoke it. Keys have 256-bit random secrets, SHA-256 verifier-only storage and a
90-day expiry. They retain the existing app's `cgnk_…` and `/v1/access` contracts.
These are bearer access keys, not Touch ID/WebAuthn credentials.

Each account has a separate stable local-workspace identity. This grants local
app access; it does not expose the owner's Mac or provision hosted compute.
Existing local account/workspace bindings cannot be reassigned by another login.

The confirmed location policy blocks mainland China, Cuba, Laos, North Korea and
Vietnam (`CN,CU,LA,KP,VN`). Every account API and native-key verification request
is checked using Netlify's trusted `context.geo.country.code`; unknown locations
are denied. Client-supplied country headers are ignored. This controls Cognesia
access, not the Firebase identity provider's public endpoints. Connection
geolocation is approximate and can reflect a VPN or proxy exit location.

## Provisioned resources

- Firebase project `cognesia-accounts`, number `1008135294118`; billing disabled.
- Web app `1:1008135294118:web:7b26982fe59c9b870a3867`. The reserved Firebase
  Hosting site exists but has no release; Netlify will host the account portal.
- Email/password and Google Auth enabled. Password minimum: 12 characters.
  Email-enumeration protection enabled; phone and anonymous providers disabled.
  This uses Firebase Authentication without an Identity Platform upgrade.
- Standard Firestore `(default)` in `asia-southeast1`, free tier, deletion
  protection enabled. Deny-all browser rules and empty indexes are deployed;
  a live unauthenticated read returned 403.
- Dedicated service account `netlify-accounts@cognesia-accounts.iam.gserviceaccount.com`
  has only Firebase user lookup plus Firestore entity read/create/update and
  transaction permissions. No private credential has been created yet.
- Existing Netlify team `allenwuzhouhan-web`, display name Cognesia Limited Co. Ltd,
  on Free. The free credit limit can pause the service when exhausted; it does
  not make this an unlimited-availability service.

## Implementation and security

- `web/`: signup, verified sign-in, reset and key-management UI.
- `functions/app.js`, `service.js`: provider identity checks and transactional
  key enrollment, replacement, revocation and native-app verification.
- `netlify/`: modern Request/Context adapter, trusted location/IP checks,
  bounded request bodies and server-only Firebase credentials.
- `firestore.rules`: all browser database access denied.
- `scripts/build.mjs`: locally bundled browser SDK and whitelisted public Firebase
  configuration. An emulator build cannot pass the production guard.
- `test/`: real Auth/Firestore emulator requests, transaction races, denial rules,
  Netlify adapter requests and Python `AppAccess` login.

Key mutations require a sign-in within ten minutes, same-origin JSON requests,
a 30-second replacement interval and a persistent five-keys-per-day limit.
Replacement revokes the old key atomically. Disabled/deleted users, revocation,
expiry and provider token-revocation timestamps are checked on access. Sessions
are memory-only; keys never enter browser storage, URLs or analytics. Do not log
request bodies or credentials.

## Local validation

Use Node 24.12 or newer, npm 11.11, Java 21 and the project's Python 3.12 environment:

```sh
cd services/accounts
npm ci
npm --prefix functions ci
npm run build
npm test
npm run test:integration
npm run preview
```

The preview uses `demo-cognesia-accounts` on loopback ports 15000 (web), 15001
(function), 18080 (database) and 19099 (Auth). Local email links and SMS codes are
emulated, not delivered. `COGNESIA_PYTHON` can override the workspace `.venv`.
The Firebase Functions entry remains for emulator use; do not deploy it on Spark.

## Free production deployment

1. Reuse the existing Netlify Free team. Do not add a payment method, enable
   recharge, upgrade Firebase or enable phone authentication.
2. Put only the Firebase **public web SDK config** in ignored
   `firebase-config.json`, or the build environment variable
   `COGNESIA_FIREBASE_WEB_CONFIG`. The build accepts only expected public fields.
3. Give a dedicated service account only the required Firebase-user lookup and
   Firestore entity/transaction permissions in `cognesia-accounts`. Never deploy
   the owner's CLI OAuth token. Store its private credential in the Netlify
   function environment, never the public directory, repository or client build.
4. Configure the production function environment: `ACCOUNT_ORIGIN` is the exact
   HTTPS Netlify origin; `BLOCKED_COUNTRIES=CN,CU,LA,KP,VN`;
   `COGNESIA_FIREBASE_SERVICE_ACCOUNT` contains the dedicated credential JSON.
   Authorize the exact Netlify hostname in Firebase Auth.
5. Run `npm run build:netlify`, then deploy `public/` and `netlify/functions/`
   using `netlify.toml`. Local deployment avoids connecting unrelated research
   files or owner data to a remote build. Do not upload an entire research checkout.
6. Check public HTTPS, provider sign-in, key issuance, native verification,
   replacement/revocation, invalid-key denial and location enforcement. Real
   delivery and emulated verification are distinct evidence.
7. After live verification, set repository variable `COGNESIA_ACCOUNTS_URL` to
   the portal origin and run the manual Pages workflow. Ship
   `src/flybrain/public_access.json` as `{"access_url":"https://ACTUAL_HOST/v1/access"}`
   in the next app source release. Existing installations need that update or
   the documented private endpoint configuration; explicit operator settings win.

Administrative deletion is handled through the provider console. Self-service
account deletion, hosted workers, usage accounting and an admin dashboard remain
separate work. Free provider quotas can make signup temporarily unavailable.

References: [Netlify Free limits](https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/),
[Netlify function context](https://docs.netlify.com/build/functions/api/),
[email authentication](https://firebase.google.com/docs/auth/web/password-auth),
[Google sign-in](https://firebase.google.com/docs/auth/web/google-signin),
[Firebase quotas and SMS billing](https://firebase.google.com/docs/auth/limits),
[ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens).
