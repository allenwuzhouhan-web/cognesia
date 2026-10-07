# Publishing Cognesia v0.0.1

The source folder is prepared locally. Preparation does not create a GitHub
repository, deploy GitHub Pages, publish a release or get indexed by Google.

## Upload the clean source snapshot

From the working repository, run:

```sh
python3.12 scripts/prepare_public_release.py --check
python3.12 scripts/prepare_public_release.py --export
```

The exporter writes `release/Cognesia-v0.0.1/`, a matching ZIP and an external
SHA-256 manifest. It includes current tracked and unignored source files, so
uncommitted implementation work is included. It excludes the original `.git`
history, local environments, downloaded datasets, recordings and caches. It
refuses to overwrite an existing export. The scan checks common credential
patterns, machine paths, forbidden filenames, symlinks and large files; it is
not an exhaustive secret audit.

Use this clean folder for the first public repository. The working repository's
old commits contain local-machine metadata and paths; changing current files
and `.gitignore` does not remove those historical values. Do not upload the
whole working folder through Finder or push its old history by accident.

Create an **empty public repository named `Cognesia`** on GitHub. Do not initialize
it with a generated README or license. With GitHub Desktop, add the clean folder
as a new repository and publish it as public. Alternatively, in a terminal:

```sh
cd release/Cognesia-v0.0.1
git init -b main
# Set your preferred public name and GitHub-provided noreply email before committing.
git add .
git commit -m "Prepare Cognesia v0.0.1"
git remote add origin https://github.com/YOUR-USERNAME/Cognesia.git
git push -u origin main
```

Replace `YOUR-USERNAME` with the real account. These commands publish the files;
they are instructions, not actions already performed. For the first release,
create tag `v0.0.1` and use `CHANGELOG.md` as the release-note basis.

## Repository About settings

- **Name:** `Cognesia`
- **Description:** `Cognesia is an experimental Drosophila connectome and neural simulation workbench with 3D anatomy, visual stimuli and neuromodulation.`
- **Topics:** `cognesia`, `drosophila`, `neuroscience`, `computational-neuroscience`, `connectomics`, `neural-simulation`, `flywire`, `banc`, `neuromodulation`, `python`
- **Website:** the real URL returned by the successful GitHub Pages deployment.

Topics help discovery within GitHub; they do not guarantee a Google ranking.
See [GitHub's topic documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics).

## Enable the public project page

1. In **Settings → Pages → Build and deployment**, select **GitHub Actions**.
2. Under **Actions**, run **Publish Cognesia project page** from `main`.
3. Wait for deployment success and open the returned HTTPS URL.
4. Add that URL to the repository's **About → Website** field.

The workflow builds only `site/` into `_site/`; it does not expose the local
simulation server or datasets. It reads the actual repository and Pages URL to
set the canonical URL, GitHub links, structured data and `sitemap.xml`. Later
changes to site files or package metadata on `main` redeploy it. If the first
push ran before Pages was enabled, rerun the workflow after step 1. If using a
branch other than `main`, update the workflow's push branch accordingly.

For a local preview, supply your intended public URL:

```sh
python3.12 scripts/build_public_site.py --repository YOUR-USERNAME/Cognesia --site-url https://YOUR-USERNAME.github.io/Cognesia/
python3.12 -m http.server 8080 --directory _site --bind 127.0.0.1
```

Visit `http://127.0.0.1:8080`. The template in `site/index.html` should be built
before publication; do not upload it as an unprocessed Pages document.
See [GitHub Pages workflow setup](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Help Google find Cognesia

After deployment, add the Pages URL as a URL-prefix property in
[Google Search Console](https://search.google.com/search-console). Verify ownership
with Google's supplied verification meta tag: add the exact tag to the `<head>`
of `site/index.html` and redeploy.
Do not invent a verification token. Submit the deployed `sitemap.xml` and use
URL Inspection to request indexing of the homepage. Link the project page from
relevant public research profiles or project pages you control.

The page uses Cognesia in its title, main heading, visible text and description.
It supplies a canonical URL and useful static HTML without requiring JavaScript.
A project site under `/Cognesia/` does not control the host's root `robots.txt`;
there is no need to add a misleading subdirectory robots file.

Google says crawling may take days to weeks, and requesting indexing does not
guarantee inclusion or ranking. Check the actual URL in Search Console before
claiming indexing. See [Google's indexing guidance](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl).

## License and research evidence

**All rights reserved** is the selected license status for original Cognesia
code and documentation. Keep the root `LICENSE` notice in the repository.
Public availability does not grant an open-source reuse license.
Third-party asset licenses and attribution are retained in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

Historical `REPORT.md` entries point to some locally retained evidence excluded
from the source package. Do not describe those artifacts as bundled or describe
old test counts as a new release verification. v0.0.1 labels the public source
release and does not change the scientific validation status.
