# Search Log: job-search dashboard with weekly Gmail refresh

- `index.html`: the dashboard (static, saves to your browser's localStorage, has Import/Export CSV, dedupes on import)
- `scripts/sync_gmail.py`: reads recent Gmail, detects applications/interviews/offers/rejections, updates `data/applications.json`, emails you a weekly summary
- `.github/workflows/weekly-refresh.yml`: runs the script every Monday (and on demand), commits the updated JSON
- `data/applications.json`: pipeline output; the dashboard merges it in on load

## Privacy: read this first
`data/applications.json` contains your job-search history. **Keep the repo private.**
GitHub Pages on private repos needs a paid plan, so on the free plan either:
run the dashboard locally (`python3 -m http.server`, then open http://localhost:8000; `git pull` after each weekly run), or
skip Pages and just use the weekly summary email plus Export CSV.

## One-time setup (about 15 minutes)
1. **Google Cloud**: create a project at console.cloud.google.com, enable the **Gmail API**.
2. **OAuth consent screen**: user type External, add yourself as a test user, add scopes `gmail.readonly` and `gmail.send`.
   **Important:** while the app is in "Testing", refresh tokens expire after 7 days. Click **Publish app** (it stays "unverified", which is fine for personal use) so the token lasts.
3. **Credentials**: create an OAuth client ID of type **Desktop app**, download `client_secret.json`.
4. **Get a refresh token** (on your computer):
   ```
   pip install -r scripts/requirements.txt
   python scripts/get_refresh_token.py client_secret.json
   ```
   Sign in, approve the scopes, and copy the three printed values.
5. **GitHub secrets**: repo, Settings, Secrets and variables, Actions, add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`.
6. **First run**: Actions tab, "Weekly job-search refresh", Run workflow. Set `LOOKBACK_DAYS` higher (e.g. 90) in the workflow for this first run to backfill, then set it back to 14.

After that it runs every Monday at 13:00 UTC (edit the cron line to change it).

## How it works and its limits
- Classification is keyword-based (confirmation, screen, round 1/2/3, final, offer, rejection). It is a good first pass, not perfect. Spot-check new rows.
- Source: LinkedIn emails are tagged `linkedin`; a human interview email with no prior application is tagged `recruiter`; everything else is `ats`. **Networking can't be detected from email**, so change those manually.
- A rejection never overwrites a reached interview stage, so interview rounds stay counted.
- Company and role are parsed from subjects and sender names; odd formats can come out wrong or as "Unknown role".
- LinkedIn is only seen through its Gmail notifications, not its site.
- Rows you first imported from CSV may duplicate pipeline rows if the applied dates differ slightly.
- Your Gmail credentials live only in GitHub Actions secrets.
