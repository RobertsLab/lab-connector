# Deploy to GitHub + GitHub Pages

Target: **github.com/RobertsLab/lab-connector**
Live site (after setup): **https://robertslab.github.io/lab-connector/**

The repo already contains everything Pages needs:
- `index.html` at the root redirects visitors to the map in `app/`.
- `app/index.html` + `app/graph-data.js` are self-contained (D3 from CDN).
- `.nojekyll` stops Pages from stripping any files.

No build step is required — Pages serves the committed files directly.

---

## 1. Push the project to GitHub

From this folder (`Lab Connector/`):

```bash
git init
git add .
git commit -m "Lab Connector: notebook⇄repo network map"
git branch -M main
```

Then create the repo under the RobertsLab org and push. Easiest with the GitHub CLI:

```bash
gh repo create RobertsLab/lab-connector --public --source=. --remote=origin --push
```

Or, if you created the empty repo on github.com first:

```bash
git remote add origin https://github.com/RobertsLab/lab-connector.git
git push -u origin main
```

(You need permission to create repositories in the RobertsLab org. If you'd
rather test under your own account first, replace `RobertsLab` with `sr320`; the
site becomes `https://sr320.github.io/lab-connector/`.)

## 2. Turn on GitHub Pages

On github.com: **repo → Settings → Pages → Build and deployment**
- **Source:** *Deploy from a branch*
- **Branch:** `main`  •  **Folder:** `/ (root)`
- **Save**

Wait ~1 minute. Your site goes live at
**https://robertslab.github.io/lab-connector/** — the root redirect opens the
network map automatically.

## 3. Updating the live graph later

Re-run the pipeline and push:

```bash
python run_all.py                 # live crawl (set GITHUB_TOKEN for higher limits)
# or: python run_all.py --offline # rebuild from the bundled snapshots
git add data outputs app/graph-data.js
git commit -m "refresh graph"
git push
```

Pages redeploys automatically on push.

---

## Optional: automated weekly refresh

`.github/workflows/refresh-graph.yml` can re-crawl weekly and rebuild the graph
in CI. To use it instead of manual updates, in **Settings → Pages** set the
source to **GitHub Actions**. The workflow already has the needed permissions;
the scheduled job commits refreshed data and (via the `deploy-pages` job)
publishes `app/` as the site root.

> Tip: keep the simple branch deploy above as your default. Switch to Actions
> only if you want hands-off weekly refreshes.
