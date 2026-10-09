# Cognesia public hosting

Decision date: 2026-10-09. The first launch uses the existing public GitHub
repository and GitHub Pages. No new account or paid plan is needed.

Public address: https://allenwuzhouhan-web.github.io/cognesia/

Launch verified: [deployment 37910033473](https://github.com/allenwuzhouhan-web/cognesia/actions/runs/37910033473)
succeeded for commit `c9b35f2afd0ed44b8e4d793c7adfdd4020b436c3`.
Unauthenticated HTTPS requests returned the exact built HTML, JavaScript, CSS,
icon and sitemap. HTTP redirects to HTTPS; HTTPS enforcement is enabled.
Local account assets and nginx configuration return 404. Browser inspection
confirmed the page and interactive capability tabs with no console errors.
Ten focused public-build/customer-site tests passed in both source checkouts.

## Options and decision

| Option | What it can host | Fit for Cognesia |
| --- | --- | --- |
| GitHub Pages | Static HTML, CSS and JavaScript; HTTPS; a project address or custom domain | Selected for the public overview, documentation and source-download links. The account and manual workflow already exist. |
| An application host with persistent storage | Account service, key verification and Python gateway | Next stage for public accounts. Use a paid persistent service or an external durable database; an ephemeral SQLite file is not suitable. Hosted simulations need separately sized and isolated workers. |
| Cloudflare Tunnel to an existing server | Routes a public hostname to a private origin | Useful for a controlled pilot. Uptime still depends on the origin computer and its network. A tunnel does not supply compute, customer isolation or account recovery. |

[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
is available for public repositories on GitHub Free and serves static files.
[HTTPS](https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https)
is supported on its default domain.
[Render's free service](https://render.com/docs/free) sleeps after idle periods,
loses filesystem changes on restart and cannot attach persistent disks; its free
Postgres databases expire after 30 days. This is unsuitable for Cognesia's current
SQLite-backed production account registry without a storage redesign.
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
connects Cloudflare to an origin through an outbound connector.

## Launch boundary

The public site offers the interactive capability illustration, scientific status,
documentation and source preview. It does not run simulations, host GPT-OSS,
create accounts or verify personal keys. The static build replaces the API form
with installation/access instructions, excludes local account assets and nginx
configuration, and prevents page-initiated API connections with a static CSP.
Existing local account and simulation services remain independent.

The source download is a preview that requires local installation and dataset
preparation. It is not a portable macOS installer. Personal app access still
requires a configured local account service or administrator-issued key.

## Publish an update

Use the clean public repository, not the private research checkout's Git history.
Review and push only the intended public files. Validate with:

```sh
python -m pytest -q tests/test_public_release.py tests/test_customer_site.py
node --check site/app.js
python scripts/build_public_site.py --repository allenwuzhouhan-web/cognesia \
  --site-url https://allenwuzhouhan-web.github.io/cognesia/ --mode static
```

Pages must use the GitHub Actions build source. Run the existing manual workflow:

```sh
gh workflow run pages.yml --repo allenwuzhouhan-web/cognesia --ref main
```

Confirm that the deployment workflow succeeded, HTTPS is enforced, and an
unauthenticated request returns the expected page and assets. Check the rendered
site, capability tabs, documentation links and absence of credential forms.
Do not describe signup or hosted compute as live until those services are
implemented and verified separately.

## Next hosting stage

Public account signup can be hosted independently of heavy simulations while the
native app continues to compute locally. It needs durable account/key storage,
recovery, appropriate abuse limits and the account/admin work described in
[the accounts plan](website-accounts-plan.md). The current local signup service
is limited to one owner and must not be exposed as public multi-user enrollment.

If hosted simulations are desired, provision separate workers and storage with
measured memory/thread requirements and quotas. A custom domain can be attached
to the public website later without replacing it; domain registration and paid
service commitments require a specific domain choice and spending limit.
