#!/usr/bin/env python3
"""
Retry failed URL extractions from all accounts.
Uses fresh browser for each URL to bypass Cloudflare.
"""

import os
import sys
import json
import time
import logging
import subprocess
import zipfile
import requests
import io
from pathlib import Path
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium_stealth import stealth

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


def get_chrome_version():
    """Detect installed Chrome version."""
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    
    if not os.path.exists(chrome_bin):
        chrome_bin = os.environ.get("CHROME_BIN", "")
    
    if not chrome_bin or not os.path.exists(chrome_bin):
        return None
    
    try:
        result = subprocess.run([chrome_bin, "--version"], capture_output=True, text=True)
        version_string = result.stdout.strip()
        version = version_string.split()[-1].split('.')[0]
        return version
    except Exception as e:
        logging.warning(f"Could not detect Chrome version: {e}")
        return None


def download_chromedriver_for_version(chrome_version):
    """Download matching ChromeDriver for Chrome version."""
    cache_dir = os.path.expanduser("~/.cache/selenium")
    os.makedirs(cache_dir, exist_ok=True)
    
    # Check if already downloaded
    for root, dirs, files in os.walk(cache_dir):
        for file in files:
            if file == "chromedriver" or file == "chromedriver.exe":
                chromedriver_path = os.path.join(root, file)
                if os.access(chromedriver_path, os.X_OK):
                    return chromedriver_path
    
    # Download new one
    try:
        api_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Find matching version
        for version_info in reversed(data['versions']):
            if version_info['version'].startswith(f"{chrome_version}."):
                downloads = version_info.get('downloads', {}).get('chromedriver', [])
                
                # Find macOS version
                for download in downloads:
                    if download['platform'] in ['mac-x64', 'mac-arm64']:
                        url = download['url']
                        
                        # Download and extract
                        zip_response = requests.get(url, timeout=60)
                        zip_response.raise_for_status()
                        
                        zip_file = zipfile.ZipFile(io.BytesIO(zip_response.content))
                        zip_file.extractall(cache_dir)
                        
                        # Find chromedriver
                        for root, dirs, files in os.walk(cache_dir):
                            for file in files:
                                if file == "chromedriver":
                                    chromedriver_path = os.path.join(root, file)
                                    os.chmod(chromedriver_path, 0o755)
                                    return chromedriver_path
        
        return None
    except Exception as e:
        logging.error(f"Failed to download ChromeDriver: {e}")
        return None


def create_driver():
    """Create a Selenium browser instance with anti-detection."""
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    
    if not os.path.exists(chrome_bin):
        chrome_bin = os.environ.get("CHROME_BIN", "")
    
    os.environ["CHROME_BIN"] = chrome_bin
    chrome_version = get_chrome_version()
    
    chromedriver_path = download_chromedriver_for_version(chrome_version)
    if not chromedriver_path:
        raise Exception("Failed to download ChromeDriver")
    
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
    
    service = Service(executable_path=chromedriver_path)
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

