#!/usr/bin/env python3
"""
Retry failed URL extractions from all accounts.
Uses fresh browser for each URL to bypass Cloudflare.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium_stealth import stealth
from webdriver_manager.chrome import ChromeDriverManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration
FAILED_URLS_FILE = "failed_urls_all_accounts.txt"
OUTPUT_FILE = "retry_results.json"
MAX_RETRIES_PER_URL = 3
BATCH_SIZE = 10


def create_driver():
    """Create a Selenium browser instance with anti-detection."""
    chrome_bin = os.environ.get("CHROME_BIN")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    if chrome_bin and os.path.exists(chrome_bin):
        chrome_options.binary_location = chrome_bin
    
    # WebDriver Manager automatically downloads the correct driver for the platform
    driver_path = ChromeDriverManager(cache_valid_range=7).install()
    service = Service(executable_path=driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    stealth(driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="MacIntel",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    
    return driver


def extract_url_data(driver, url):
    """Extract data from a single URL."""
    try:
        driver.get(url)
        
        # Wait for main content
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".dictionary-items"))
        )
        
        time.sleep(2)
        
        # Extract h1
        h1 = ""
        try:
            h1_element = driver.find_element(By.CSS_SELECTOR, "h1.dictionary-title")
            h1 = h1_element.text.strip()
        except:
            pass
        
        # Extract h2
        h2 = ""
        try:
            h2_element = driver.find_element(By.CSS_SELECTOR, "h2")
            h2 = h2_element.text.strip()
        except:
            pass
        
        # Extract content
        content = ""
        try:
            content_element = driver.find_element(By.CSS_SELECTOR, ".dictionary-items")
            content = content_element.text.strip()
        except:
            pass
        
        return {
            "url": url,
            "h1": h1,
            "h2": h2,
            "content": content,
            "extracted_at": datetime.now().isoformat()
        }
    except Exception as e:
        logging.error(f"Error extracting {url}: {e}")
        return {
            "url": url,
            "h1": "",
            "h2": "",
            "content": "",
            "error": str(e),
            "extracted_at": datetime.now().isoformat()
        }


def load_failed_urls():
    """Load failed URLs from file."""
    if not os.path.exists(FAILED_URLS_FILE):
        logging.error(f"❌ {FAILED_URLS_FILE} not found!")
        return []
    
    with open(FAILED_URLS_FILE, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip()]
    
    logging.info(f"📂 Loaded {len(urls)} failed URLs")
    return urls


def load_existing_results():
    """Load existing retry results to avoid re-processing."""
    if not os.path.exists(OUTPUT_FILE):
        return set()
    
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {item['url'] for item in data}
    except:
        return set()


def save_results(results):
    """Save results to JSON file."""
    # Load existing results
    existing_results = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing_results = json.load(f)
        except:
            pass
    
    # Append new results
    existing_results.extend(results)
    
    # Save
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing_results, f, ensure_ascii=False, indent=2)
    
    logging.info(f"💾 Saved {len(results)} results to {OUTPUT_FILE}")


def main():
    logging.info("="*70)
    logging.info("🔄 RETRYING FAILED URL EXTRACTIONS")
    logging.info("="*70)
    
    # Load failed URLs
    failed_urls = load_failed_urls()
    if not failed_urls:
        return
    
    # Load already processed
    processed_urls = load_existing_results()
    remaining_urls = [url for url in failed_urls if url not in processed_urls]
    
    logging.info(f"📊 Total failed URLs: {len(failed_urls)}")
    logging.info(f"✅ Already processed: {len(processed_urls)}")
    logging.info(f"⏳ Remaining to process: {len(remaining_urls)}")
    
    if not remaining_urls:
        logging.info("✅ All URLs have been processed!")
        return
    
    # Process in batches
    successful = 0
    still_failed = 0
    batch = []
    
    for idx, url in enumerate(remaining_urls, 1):
        logging.info(f"[{idx}/{len(remaining_urls)}] Processing: {url}")
        
        # Create fresh browser for each URL
        driver = None
        try:
            driver = create_driver()
            
            # Try to extract
            data = extract_url_data(driver, url)
            
            # Check if successful
            if data.get("h1") or data.get("h2") or data.get("content"):
                batch.append(data)
                successful += 1
                logging.info(f"  ✅ Success!")
            else:
                still_failed += 1
                logging.warning(f"  ❌ Still empty")
                # Save even empty results to avoid re-processing
                batch.append(data)
            
            # Save batch incrementally
            if len(batch) >= BATCH_SIZE:
                save_results(batch)
                batch = []
            
        except Exception as e:
            logging.error(f"  ❌ Error: {e}")
            still_failed += 1
            batch.append({
                "url": url,
                "h1": "",
                "h2": "",
                "content": "",
                "error": str(e),
                "extracted_at": datetime.now().isoformat()
            })
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            
            time.sleep(2)  # Delay between requests
    
    # Save remaining batch
    if batch:
        save_results(batch)
    
    # Summary
    logging.info("="*70)
    logging.info("📊 RETRY SUMMARY")
    logging.info("="*70)
    logging.info(f"✅ Successful: {successful}")
    logging.info(f"❌ Still failed: {still_failed}")
    logging.info(f"📝 Total processed: {len(remaining_urls)}")
    logging.info("="*70)


if __name__ == "__main__":
    main()

