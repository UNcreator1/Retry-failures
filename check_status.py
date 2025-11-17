#!/usr/bin/env python3
"""
Quick status checker for retry progress.
Shows current progress, success rate, and remaining URLs.
"""

import json
import os
from typing import Dict, Tuple


def load_checkpoint() -> Dict:
    """Load checkpoint data."""
    checkpoint_file = "data/retry_checkpoint.json"
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'last_index': 0, 'processed_urls': []}


def load_results() -> list:
    """Load all results."""
    results_file = "data/retry_results.json"
    if os.path.exists(results_file):
        with open(results_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def count_success_failure(results: list) -> Tuple[int, int]:
    """Count successful and failed extractions.
    
    Args:
        results: List of result dictionaries.
        
    Returns:
        Tuple of (successful_count, failed_count).
    """
    successful = sum(
        1 for r in results 
        if r.get('h1') or r.get('h2') or r.get('content')
    )
    failed = len(results) - successful
    return successful, failed


def main() -> None:
    """Main status display."""
    print("=" * 80)
    print("📊 RETRY STATUS CHECKER")
    print("=" * 80)
    
    # Load failed URLs
    failed_urls_file = "failed_urls_all_accounts.txt"
    if not os.path.exists(failed_urls_file):
        print(f"❌ {failed_urls_file} not found!")
        return
    
    with open(failed_urls_file, 'r', encoding='utf-8') as f:
        total_urls = len([line for line in f if line.strip()])
    
    print(f"\n📁 Total Failed URLs: {total_urls}")
    
    # Load checkpoint
    checkpoint = load_checkpoint()
    last_index = checkpoint.get('last_index', 0)
    processed_count = len(checkpoint.get('processed_urls', []))
    timestamp = checkpoint.get('timestamp', 'N/A')
    
    print(f"\n🔖 Checkpoint Status:")
    print(f"  - Last Index: {last_index}")
    print(f"  - Processed URLs: {processed_count}")
    print(f"  - Last Updated: {timestamp}")
    print(f"  - Remaining: {total_urls - last_index}")
    
    # Calculate progress
    progress_pct = (last_index / total_urls * 100) if total_urls > 0 else 0
    print(f"  - Progress: {progress_pct:.1f}%")
    
    # Load results
    results = load_results()
    if results:
        print(f"\n📊 Results Summary:")
        print(f"  - Total Results: {len(results)}")
        
        successful, failed = count_success_failure(results)
        print(f"  - ✅ Successful: {successful}")
        print(f"  - ❌ Failed: {failed}")
        
        if len(results) > 0:
            success_rate = (successful / len(results) * 100)
            print(f"  - Success Rate: {success_rate:.1f}%")
    else:
        print(f"\n📊 Results Summary:")
        print(f"  - No results yet")
    
    # Estimate remaining work
    batch_size = 100
    remaining = total_urls - last_index
    batches_remaining = (remaining + batch_size - 1) // batch_size  # Ceiling division
    
    print(f"\n⏳ Remaining Work:")
    print(f"  - URLs to Process: {remaining}")
    print(f"  - Batches Remaining: {batches_remaining}")
    print(f"  - Estimated Time: {batches_remaining * 2.5:.1f} hours (~2.5h per batch)")
    
    # Next batch info
    if remaining > 0:
        next_start = last_index + 1
        next_end = min(last_index + batch_size, total_urls)
        print(f"\n🔄 Next Batch:")
        print(f"  - URLs {next_start} to {next_end}")
        print(f"  - Batch Size: {next_end - next_start + 1}")
    else:
        print(f"\n🎉 All URLs Processed!")
    
    print("=" * 80)


if __name__ == "__main__":
    main()

