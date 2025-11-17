# ⚡ Quick Start Guide - Batch Mode

Get started with the auto-batch retry system in 3 steps!

## 🚀 Step 1: Commit and Push

```bash
cd /Users/apple/fmit-crawler/Retry-failures

# Add all new files
git add .

# Commit
git commit -m "✨ Add batch mode with auto-triggering (100 URLs per batch)"

# Push to GitHub
git push
```

## 🎯 Step 2: Start First Batch

1. Go to your GitHub repository
2. Click **Actions** tab at the top
3. Click **Retry Failed URLs (Auto-Batch)** in the left sidebar
4. Click **Run workflow** (green button on the right)
5. Keep **Branch: main** selected
6. Click **Run workflow** button

That's it! The system will now:
- ✅ Process 100 URLs
- ✅ Save results every 5 URLs
- ✅ Create checkpoint
- ✅ Automatically trigger next batch
- ✅ Repeat until all 1,163 URLs are done

## 📊 Step 3: Monitor Progress (Optional)

### From GitHub
1. Go to **Actions** tab
2. See all batch runs
3. Click any run to view logs
4. Check "Display Results Summary" step

### From Local Machine
```bash
# Quick status check
python check_status.py

# Output:
# - Current progress (%)
# - URLs processed
# - Success/failure count
# - Batches remaining
# - Estimated time
```

## ⏱️ Timeline

```
Start:    Trigger first batch manually
+2.5h:    Batch 1 complete → Auto-trigger Batch 2
+5h:      Batch 2 complete → Auto-trigger Batch 3
+7.5h:    Batch 3 complete → Auto-trigger Batch 4
...
+30-36h:  All 12 batches complete! 🎉
```

## 📁 Output Files

Check these files after each batch:

```bash
data/
├── retry_results.json      # All extracted data
└── retry_checkpoint.json   # Current progress
```

### View Results
```bash
# Count total results
python3 -c "import json; print(len(json.load(open('data/retry_results.json'))))"

# Count successful extractions
python3 -c "import json; data=json.load(open('data/retry_results.json')); print(sum(1 for d in data if d.get('h1') or d.get('h2') or d.get('content')))"

# Or use the status checker
python check_status.py
```

## 🔧 Troubleshooting

### ❓ Workflow didn't auto-trigger next batch?
**Solution:** Manually trigger from Actions tab (system will resume from checkpoint)

### ❓ Want to check progress?
**Solution:** Run `python check_status.py` or check Actions tab

### ❓ Need to stop processing?
**Solution:** Cancel workflow in Actions tab. Resume anytime - checkpoint saves progress!

### ❓ Want to restart from beginning?
**Solution:** Delete `data/retry_checkpoint.json` and `data/retry_results.json`

## 🎯 What Happens Next

### Automatic Process (No Intervention Needed)
```
1. Batch 1 starts  ──→  Processes 100 URLs  ──→  Saves results
                                               ──→  Triggers Batch 2
                                               
2. Batch 2 starts  ──→  Processes 100 URLs  ──→  Saves results
                                               ──→  Triggers Batch 3
                                               
3. Batch 3 starts  ──→  ...continues automatically...

...12 batches later...

12. Batch 12 done  ──→  All URLs processed!  ──→  Complete 🎉
```

## 📊 Expected Results

After all batches complete, you'll have:

```
data/retry_results.json
├── Total entries: ~1,163
├── Successful: ~800-900 (estimated 70-80%)
└── Failed: ~200-300 (may need manual review)
```

## 🎉 Success Indicators

You'll know it's working when you see:
- ✅ Actions tab shows workflow runs
- ✅ Commits appear automatically ("Batch X results")
- ✅ `data/retry_results.json` grows
- ✅ `data/retry_checkpoint.json` updates
- ✅ New batches trigger automatically

## 💡 Pro Tips

### 1. Don't Wait Around
- System runs automatically
- Check back in 30-36 hours
- Or monitor via email notifications (GitHub settings)

### 2. Pull Latest Results
```bash
# After batches complete
git pull

# View final results
python check_status.py
```

### 3. Resume Anytime
If workflow stops for any reason:
- Just trigger manually from Actions tab
- System resumes from last checkpoint
- No data loss!

## 🔥 Common Scenarios

### Scenario 1: Everything Working
```
✅ Batch completes
✅ Results committed
✅ Next batch triggered automatically
→ Do nothing, let it run!
```

### Scenario 2: Manual Restart Needed
```
⚠️  Batch fails or stops
⚠️  Next batch doesn't auto-trigger
→ Go to Actions → Run workflow manually
→ System resumes from checkpoint
```

### Scenario 3: Check Progress
```
📊 Want to see progress
→ Run: python check_status.py
→ Or check Actions tab on GitHub
```

## 🎯 Final Checklist

Before starting:
- [ ] All files committed and pushed
- [ ] Workflow file exists: `.github/workflows/retry_batch.yml`
- [ ] Input file exists: `failed_urls_all_accounts.txt`
- [ ] Data directory exists: `data/`

Ready to run:
- [ ] Go to GitHub Actions tab
- [ ] Click "Retry Failed URLs (Auto-Batch)"
- [ ] Click "Run workflow"
- [ ] Sit back and relax! ☕

## 🎊 That's It!

The system will automatically:
1. Process all 1,163 URLs in batches
2. Save progress incrementally
3. Handle failures gracefully
4. Complete in 30-36 hours
5. Commit results automatically

**No babysitting required!** 🎉

---

**Questions?** Check `README.md` for detailed documentation or `COMPARISON.md` for feature comparisons.

**Need help?** Run `python check_status.py` to see current state.

