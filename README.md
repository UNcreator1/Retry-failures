# Retry Failures - FMIT Crawler

This repository retries failed URL extractions from the main crawler.

## 📊 Status

- **Total Failed URLs:** 1,163
- **Breakdown:**
  - Account 2: 392 URLs
  - Account 3: 449 URLs
  - Account 4: 188 URLs
  - Account 5: 134 URLs

## 🚀 How to Run

### Manual GitHub Actions Trigger

1. Go to **Actions** tab
2. Click **Retry Failed Extractions** workflow
3. Click **Run workflow** button
4. Select **main** branch
5. Click **Run workflow**

The workflow will:
- ✅ Process failed URLs in batches
- ✅ Use fresh browser for each URL (bypass Cloudflare)
- ✅ Save results to `retry_results.json`
- ✅ Auto-commit and push results

### Local Run

```bash
pip install -r requirements.txt
python retry_failures.py
```

## 📁 Files

- `failed_urls_all_accounts.txt` - List of failed URLs to retry
- `retry_failures.py` - Main retry script
- `retry_results.json` - Output file with results (created after first run)
- `.github/workflows/retry.yml` - GitHub Actions workflow

## 🔄 How It Works

1. **Load Failed URLs** from `failed_urls_all_accounts.txt`
2. **Create Fresh Browser** for each URL (anti-detection)
3. **Extract Data** (h1, h2, content)
4. **Save in Batches** to avoid data loss
5. **Auto-commit** results to GitHub

## 📝 Notes

- The script uses **headless Chrome** with **selenium-stealth**
- Processes **10 URLs per batch**
- **2-second delay** between requests
- Results are saved **incrementally** (no data loss)
- Already-processed URLs are **skipped automatically**


