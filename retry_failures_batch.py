#!/usr/bin/env python3
"""
Retry failed URLs in batches of 100 with auto-checkpoint and incremental saving.
Optimized for fast scanning and immediate result appending.
"""

import glob
import json
import logging
import os
import platform
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth
from webdriver_manager.chrome import ChromeDriverManager

# Configuration
DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)

FAILED_URLS_FILE = "failed_urls_all_accounts.txt"
OUTPUT_FILE = os.path.join(DATA_DIR, "retry_results.json")
CHECKPOINT_FILE = os.path.join(DATA_DIR, "retry_checkpoint.json")
BATCH_SIZE = 100  # Process 100 URLs per workflow run
SAVE_INTERVAL = 5  # Save every 5 successful extractions

CLOUDFLARE_KEYWORDS = [
    "just a moment",
    "checking your browser",
    "please enable cookies",
    "attention required",
    "verify you are human",
    "enable javascript",
]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_chrome_version() -> Optional[str]:
    """Get Chrome version from binary.
    
    Returns:
        Major version number or None if detection fails.
    """
    chrome_bin = os.getenv("CHROME_BIN")
    if not chrome_bin:
        chrome_bin = "google-chrome"
        if os.path.exists("/opt/hostedtoolcache/setup-chrome/chromium"):
            chrome_bin_pattern = "/opt/hostedtoolcache/setup-chrome/chromium/*/x64/chrome"
            matches = glob.glob(chrome_bin_pattern)
            if matches:
                chrome_bin = matches[0]
    
    try:
        result = subprocess.run(
            [chrome_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        version_output = result.stdout.strip()
        match = re.search(r'(\d+\.\d+\.\d+\.\d+)', version_output)
        if match:
            full_version = match.group(1)
            major_version = full_version.split('.')[0]
            logging.info(f"Detected Chrome version: {major_version}")
            return major_version
        return None
    except Exception as e:
        logging.warning(f"Could not detect Chrome version: {e}")
        return None


def download_chromedriver_for_version(chrome_version: str) -> str:
    """Download ChromeDriver for specific Chrome version.
    
    Args:
        chrome_version: Major version number of Chrome.
        
    Returns:
        Path to ChromeDriver executable.
        
    Raises:
        Exception: If download fails or no matching version found.
    """
    try:
        system = platform.system().lower()
        if system == "darwin":
            platform_name = "mac-arm64" if platform.machine().lower() in ["arm64", "aarch64"] else "mac-x64"
        elif system == "linux":
            platform_name = "linux64"
        elif system == "windows":
            platform_name = "win64"
        else:
            platform_name = "linux64"
        
        logging.info(f"Detected platform: {platform_name}")
        
        # Get available ChromeDriver versions
        versions_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        response = requests.get(versions_url, timeout=30)
        response.raise_for_status()
        versions_data = response.json()
        
        # Find matching version
        target_version = None
        for version_info in reversed(versions_data["versions"]):
            version_str = version_info["version"]
            if version_str.startswith(f"{chrome_version}."):
                target_version = version_str
                break
        
        if not target_version:
            for version_info in reversed(versions_data["versions"]):
                version_str = version_info["version"]
                if version_str.split('.')[0] == chrome_version:
                    target_version = version_str
                    break
        
        if not target_version:
            raise Exception(f"No ChromeDriver found for Chrome version {chrome_version}")
        
        logging.info(f"Found ChromeDriver version: {target_version}")
        
        # Get download URL
        download_url = None
        for version_info in versions_data["versions"]:
            if version_info["version"] == target_version:
                downloads = version_info.get("downloads", {})
                chromedriver = downloads.get("chromedriver", [])
                for item in chromedriver:
                    if item["platform"] == platform_name:
                        download_url = item["url"]
                        break
                break
        
        if not download_url:
            raise Exception(f"No {platform_name} ChromeDriver download found")
        
        # Download and extract
        logging.info(f"Downloading ChromeDriver from {download_url}")
        cache_dir = Path.home() / ".wdm" / "drivers" / "chromedriver" / platform_name / target_version
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        zip_filename = {
            "linux64": "chromedriver-linux64.zip",
            "mac-x64": "chromedriver-mac-x64.zip",
            "mac-arm64": "chromedriver-mac-arm64.zip",
            "win64": "chromedriver-win64.zip"
        }.get(platform_name, "chromedriver.zip")
        
        zip_path = cache_dir / zip_filename
        response = requests.get(download_url, timeout=120)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(response.content)
        
        # Extract
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(cache_dir)
        
        # Find chromedriver executable
        chromedriver_path = None
        executable_name = "chromedriver.exe" if system == "windows" else "chromedriver"
        for root, dirs, files in os.walk(cache_dir):
            if executable_name in files:
                chromedriver_path = Path(root) / executable_name
                break
        
        if not chromedriver_path or not chromedriver_path.exists():
            raise Exception(f"ChromeDriver executable not found in {cache_dir}")
        
        # Make executable
        if system != "windows":
            os.chmod(chromedriver_path, 0o755)
        
        logging.info(f"ChromeDriver installed at: {chromedriver_path}")
        return str(chromedriver_path)
        
    except Exception as e:
        logging.error(f"Failed to download ChromeDriver: {e}")
        raise


def create_driver() -> webdriver.Chrome:
    """Create a fresh Chrome WebDriver instance with stealth mode.
    
    Returns:
        Configured Chrome WebDriver instance.
        
    Raises:
        FileNotFoundError: If Chrome binary not found.
        PermissionError: If Chrome binary not executable.
        Exception: If driver creation fails.
    """
    chrome_bin = os.getenv("CHROME_BIN")
    if not chrome_bin:
        if os.path.exists("/opt/hostedtoolcache/setup-chrome/chromium"):
            chrome_bin_pattern = "/opt/hostedtoolcache/setup-chrome/chromium/*/x64/chrome"
            matches = glob.glob(chrome_bin_pattern)
            if matches:
                chrome_bin = matches[0]
        else:
            chrome_bin = "google-chrome"
    
    if not os.path.exists(chrome_bin):
        raise FileNotFoundError(f"Chrome binary not found at: {chrome_bin}")
    
    if not os.access(chrome_bin, os.X_OK):
        raise PermissionError(f"Chrome binary is not executable: {chrome_bin}")
    
    chrome_options = Options()
    chrome_options.binary_location = chrome_bin
    
    # Headless and stealth options
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")
    
    # Get ChromeDriver
    chromedriver_path = None
    try:
        original_chrome_bin = os.getenv("CHROME_BIN")
        os.environ["CHROME_BIN"] = chrome_bin
        
        chrome_version = get_chrome_version()
        if chrome_version:
            chromedriver_path = download_chromedriver_for_version(chrome_version)
        
        if original_chrome_bin:
            os.environ["CHROME_BIN"] = original_chrome_bin
        elif "CHROME_BIN" in os.environ:
            del os.environ["CHROME_BIN"]
    except Exception:
        pass
    
    if not chromedriver_path:
        try:
            chromedriver_path = ChromeDriverManager().install()
        except Exception as e:
            logging.error(f"Failed to install ChromeDriver: {e}")
            raise
    
    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Apply stealth mode
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Linux",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
    )
    
    return driver


def wait_for_cloudflare_clear(driver: webdriver.Chrome, url: str, timeout: int = 30) -> bool:
    """Wait for Cloudflare challenge to clear.
    
    Args:
        driver: Chrome WebDriver instance.
        url: URL being accessed.
        timeout: Maximum wait time in seconds.
        
    Returns:
        True if cleared, False if timeout.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            title = (driver.title or "").lower()
        except Exception:
            title = ""
        try:
            page_source = driver.page_source.lower() if driver.page_source else ""
        except Exception:
            page_source = ""
        
        if any(keyword in title or keyword in page_source for keyword in CLOUDFLARE_KEYWORDS):
            logging.debug(f"Cloudflare detected on {url}, waiting...")
            time.sleep(3)
            continue
        return True
    
    logging.warning(f"Cloudflare timeout on {url}")
    return False


def extract_url_data(driver: webdriver.Chrome, url: str) -> Tuple[Dict[str, str], webdriver.Chrome]:
    """Extract data from a single URL.
    
    Args:
        driver: Chrome WebDriver instance.
        url: URL to extract data from.
        
    Returns:
        Tuple of (extracted data dict, driver instance).
    """
    try:
        driver.get(url)
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        if not wait_for_cloudflare_clear(driver, url):
            return {"url": url, "h1": "", "h2": "", "content": "", "error": "Cloudflare timeout"}, driver
        
        h1 = h2 = content = ""
        try:
            h1_el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1.dictionary-detail-title"))
            )
            h1 = h1_el.text.strip()
        except TimeoutException:
            pass
        
        try:
            h2_el = driver.find_element(By.CSS_SELECTOR, "h2.dictionary-detail-title")
            h2 = h2_el.text.strip()
        except NoSuchElementException:
            pass
        
        try:
            content_el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.dictionary-details"))
            )
            content = content_el.text.strip()
        except TimeoutException:
            pass
        
        return {"url": url, "h1": h1, "h2": h2, "content": content}, driver
    except Exception as e:
        logging.error(f"Error extracting {url}: {e}")
        return {"url": url, "h1": "", "h2": "", "content": "", "error": str(e)}, driver


def load_checkpoint() -> Dict:
    """Load checkpoint data.
    
    Returns:
        Dict with 'last_index' and 'processed_urls'.
    """
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    'last_index': data.get('last_index', 0),
                    'processed_urls': set(data.get('processed_urls', []))
                }
        except Exception as e:
            logging.warning(f"Could not load checkpoint: {e}")
    
    return {'last_index': 0, 'processed_urls': set()}


def save_checkpoint(last_index: int, processed_urls: set) -> None:
    """Save checkpoint data.
    
    Args:
        last_index: Last processed index.
        processed_urls: Set of successfully processed URLs.
    """
    try:
        data = {
            'last_index': last_index,
            'processed_urls': list(processed_urls),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"✅ Checkpoint saved: index={last_index}, processed={len(processed_urls)}")
    except Exception as e:
        logging.error(f"Failed to save checkpoint: {e}")


def append_results(results: List[Dict[str, str]]) -> None:
    """Append results to output file.
    
    Args:
        results: List of result dictionaries to append.
    """
    if not results:
        return
    
    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception as e:
            logging.warning(f"Could not read output file: {e}")
    
    # Merge results
    existing.extend(results)
    
    # Save
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        logging.info(f"💾 Saved {len(results)} result(s) to {OUTPUT_FILE}")
    except Exception as e:
        logging.error(f"Failed to save results: {e}")


def main() -> None:
    """Main execution function."""
    logging.info("=" * 80)
    logging.info("🔄 RETRY FAILED URL EXTRACTIONS - BATCH MODE")
    logging.info("=" * 80)

    # Load failed URLs
    if not os.path.exists(FAILED_URLS_FILE):
        logging.error(f"❌ {FAILED_URLS_FILE} not found!")
        return
    
    with open(FAILED_URLS_FILE, "r", encoding="utf-8") as f:
        all_urls = [line.strip() for line in f if line.strip()]
    
    # Load checkpoint
    checkpoint = load_checkpoint()
    start_index = checkpoint['last_index']
    processed_urls = checkpoint['processed_urls']
    
    total_urls = len(all_urls)
    remaining = total_urls - start_index
    
    logging.info(f"📊 Total failed URLs: {total_urls}")
    logging.info(f"✅ Already processed: {start_index}")
    logging.info(f"⏳ Remaining to process: {remaining}")
    logging.info(f"📦 Batch size: {BATCH_SIZE} URLs")
    logging.info(f"💾 Save interval: every {SAVE_INTERVAL} successful extractions")
    
    if start_index >= total_urls:
        logging.info("🎉 All URLs already processed!")
        return
    
    # Process batch
    end_index = min(start_index + BATCH_SIZE, total_urls)
    batch_urls = all_urls[start_index:end_index]
    
    logging.info(f"🚀 Processing batch: URLs {start_index + 1} to {end_index}")
    logging.info("=" * 80)
    
    successful = 0
    failed = 0
    buffer = []  # Buffer for incremental saving
    
    for idx, url in enumerate(batch_urls, start=1):
        global_idx = start_index + idx
        
        # Skip if already processed
        if url in processed_urls:
            logging.info(f"[{global_idx}/{total_urls}] ⏩ Skipping (already processed): {url}")
            continue
        
        logging.info(f"[{global_idx}/{total_urls}] 🌐 Processing: {url}")
        
        driver = None
        try:
            # Create fresh browser for each URL (anti-detection)
            driver = create_driver()
            data, driver = extract_url_data(driver, url)
            
            # Check if extraction was successful
            if data.get("h1") or data.get("h2") or data.get("content"):
                successful += 1
                logging.info(f"[{global_idx}/{total_urls}] ✅ Success: {url[:80]}...")
            else:
                failed += 1
                logging.warning(f"[{global_idx}/{total_urls}] ⚠️  Empty content: {url[:80]}...")
            
            # Add to buffer
            buffer.append(data)
            processed_urls.add(url)
            
            # Save buffer when it reaches save interval
            if len(buffer) >= SAVE_INTERVAL:
                append_results(buffer)
                save_checkpoint(start_index + idx, processed_urls)
                buffer = []
            
        except Exception as exc:
            failed += 1
            logging.error(f"[{global_idx}/{total_urls}] ❌ Error: {exc}")
            error_data = {
                "url": url,
                "h1": "",
                "h2": "",
                "content": "",
                "error": str(exc)
            }
            buffer.append(error_data)
            processed_urls.add(url)
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            time.sleep(1)  # Small delay between requests
    
    # Save remaining buffer
    if buffer:
        append_results(buffer)
    
    # Save final checkpoint
    save_checkpoint(end_index, processed_urls)
    
    # Summary
    logging.info("=" * 80)
    logging.info("📊 BATCH SUMMARY")
    logging.info("=" * 80)
    logging.info(f"✅ Successful extractions: {successful}")
    logging.info(f"❌ Failed extractions: {failed}")
    logging.info(f"📝 Total processed in batch: {len(batch_urls)}")
    logging.info(f"📍 Next start index: {end_index}")
    logging.info(f"⏳ Remaining URLs: {total_urls - end_index}")
    
    if end_index < total_urls:
        logging.info(f"🔄 Next batch will process URLs {end_index + 1} to {min(end_index + BATCH_SIZE, total_urls)}")
    else:
        logging.info("🎉 All URLs have been processed!")
    
    logging.info("=" * 80)


if __name__ == "__main__":
    main()

