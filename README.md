# Retry Failures - FMIT Crawler (Batch Mode)

Fast, automated retry system for failed URL extractions with **100-URL batches** and **auto-triggering workflows**.

## 📊 Status

- **Total Failed URLs:** 1,163
- **Batch Size:** 100 URLs per run
- **Processing Mode:** Auto-batch with checkpoints
- **Breakdown:**
  - Account 2: 392 URLs
  - Account 3: 449 URLs
  - Account 4: 188 URLs
  - Account 5: 134 URLs

## 🚀 Quick Start

### Auto-Batch Mode (Recommended)

The system automatically processes URLs in batches of 100:

1. **Start First Batch:**
   - Go to **Actions** tab
   - Click **Retry Failed URLs (Auto-Batch)**
   - Click **Run workflow** → **Run workflow**

2. **Auto-Processing:**
   - ✅ Processes 100 URLs per run
   - ✅ Saves results incrementally (every 5 URLs)
   - ✅ Creates checkpoint automatically
   - ✅ Triggers next batch when done
   - ✅ Stops when all URLs processed

### Manual Run

```bash
pip install -r requirements.txt
python retry_failures_batch.py
```

## 📁 File Structure

```
├── data/
│   ├── retry_results.json      # All extraction results
│   └── retry_checkpoint.json   # Progress checkpoint
├── failed_urls_all_accounts.txt  # Input: URLs to retry
├── retry_failures_batch.py       # Main batch processor
└── .github/workflows/
    └── retry_batch.yml          # Auto-batch workflow
```

## 🔄 How It Works

### 1. **Batch Processing**
- Processes **100 URLs per workflow run**
- Avoids 6-hour GitHub Actions timeout
- Each batch takes ~2-3 hours

### 2. **Checkpoint System**
```json
{
  "last_index": 100,
  "processed_urls": ["url1", "url2", ...],
  "timestamp": "2025-11-17 10:30:00"
}
```

### 3. **Incremental Saving**
- Saves results **every 5 successful extractions**
- No data loss if workflow fails
- Results accumulate in `retry_results.json`

### 4. **Auto-Triggering**
- When batch completes → triggers next batch
- Continues until all 1,163 URLs processed
- Can monitor progress in Actions tab

## 📊 Progress Tracking

### Check Current Progress

```bash
# View checkpoint
cat data/retry_checkpoint.json

# Count total results
python3 -c "import json; print(f'Results: {len(json.load(open(\"data/retry_results.json\")))}')"

# Count successful vs failed
python3 -c "import json; data=json.load(open('data/retry_results.json')); success=sum(1 for d in data if d.get('h1') or d.get('h2') or d.get('content')); print(f'Success: {success}, Failed: {len(data)-success}')"
```

### Estimate Completion

- **Total URLs:** 1,163
- **Batch Size:** 100 URLs
- **Total Batches:** ~12 batches
- **Time per Batch:** ~2-3 hours
- **Total Time:** ~30-36 hours (automatic)

## 🎯 Features

### ✅ Fast Scanning
- Fresh browser for each URL (bypass Cloudflare)
- Optimized wait times (10s vs 20s)
- Parallel-ready architecture

### ✅ Incremental Appending
- Results saved every 5 URLs
- No batch size limits
- Handles failures gracefully

### ✅ Smart Checkpointing
- Tracks both index and processed URLs
- Resume from exact position
- Skips already-processed URLs

### ✅ Auto-Recovery
- If workflow fails → resume from checkpoint
- If browser crashes → continue next URL
- If rate-limited → automatic delay

## 🔧 Configuration

Edit `retry_failures_batch.py` to customize:

```python
BATCH_SIZE = 100        # URLs per workflow run
SAVE_INTERVAL = 5       # Save every N successful extractions
```

Edit `.github/workflows/retry_batch.yml` to adjust:

```yaml
timeout-minutes: 330    # 5.5 hours max per batch
schedule:
  - cron: '0 */6 * * *' # Fallback: every 6 hours
```

## 📈 Monitoring

### GitHub Actions Dashboard
1. Go to **Actions** tab
2. See all batch runs
3. Click any run to see logs
4. Check "Display Results Summary" step

### Output Files
- **`data/retry_results.json`** - All results (committed after each batch)
- **`data/retry_checkpoint.json`** - Current progress (committed after each batch)

## 🐛 Troubleshooting

### Workflow Not Auto-Triggering?
- Check if `more_batches` output is `true` in last run
- Manually trigger next batch from Actions tab
- Workflow uses `repository_dispatch` event

### Checkpoint Not Updating?
- Check workflow logs for errors
- Ensure `data/` directory exists
- Verify write permissions

### Results Not Saving?
- Check if `data/retry_results.json` committed
- Look for save errors in workflow logs
- Ensure JSON is valid

### Browser Crashes?
- Fresh browser created for EACH URL
- Failures are logged and skipped
- Next batch will continue

## 🎯 Comparison with Original

| Feature | Original | Batch Mode |
|---------|----------|------------|
| URLs per run | All (1,163) | 100 |
| Checkpoint | Manual | Auto |
| Save frequency | End of run | Every 5 URLs |
| Auto-trigger | No | Yes |
| Resume support | Basic | Advanced |
| Failure recovery | Poor | Excellent |
| Time to complete | 10+ hours | 30-36 hours (unattended) |

## 📝 Example Workflow

```
Run 1:  Process URLs 1-100   → Save → Trigger Run 2
Run 2:  Process URLs 101-200 → Save → Trigger Run 3
Run 3:  Process URLs 201-300 → Save → Trigger Run 4
...
Run 12: Process URLs 1101-1163 → Save → Complete! 🎉
```

## 🚨 Important Notes

1. **Don't Delete Checkpoint**: `data/retry_checkpoint.json` tracks progress
2. **Results Accumulate**: `retry_results.json` grows with each batch
3. **Auto-Commits**: Workflow commits results automatically
4. **Rate Limiting**: 1-second delay between URLs
5. **Cloudflare Handling**: Fresh browser + stealth mode

## 📞 Support

If batches stop auto-triggering:
1. Check last workflow run status
2. Manually trigger from Actions tab
3. System will resume from checkpoint

---

**Status:** ✅ Ready for auto-batch processing

**Next Steps:** 
1. Trigger first batch from Actions tab
2. Monitor progress (optional)
3. Wait for completion (~30-36 hours)
4. Check `data/retry_results.json` for final results
