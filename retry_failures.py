#!/usr/bin/env python3
"""
Retry failed URL extractions with checkpoint system for resume capability.
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
from typing import Dict, Tuple

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

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration
FAILED_URLS_FILE = "failed_urls_all_accounts.txt"
OUTPUT_FILE = "retry_results.json"
CHECKPOINT_FILE = "retry_checkpoint.txt"
BATCH_SIZE = 5  # Save every 5 URLs

CLOUDFLARE_KEYWORDS = [
    "just a moment",
    "checking your browser",
    "please enable cookies",
    "attention required",
    "verify you are human",
    "enable javascript",
]


def get_chrome_version() -> str:
    """Get Chrome version from binary."""
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
            return major_version
        return None
    except Exception as e:
        logging.warning(f"Could not detect Chrome version: {e}")
        return None


def download_chromedriver_for_version(chrome_version: str) -> str:
    """Download ChromeDriver for a specific Chrome version from Chrome for Testing."""
    try:
        system = platform.system().lower()
        if system == "darwin":
            if platform.machine().lower() in ["arm64", "aarch64"]:
                platform_name = "mac-arm64"
            else:
                platform_name = "mac-x64"
        elif system == "linux":
            platform_name = "linux64"
        elif system == "windows":
            platform_name = "win64"
        else:
            platform_name = "linux64"
        
        versions_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        response = requests.get(versions_url, timeout=30)
        response.raise_for_status()
        versions_data = response.json()
        
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
            raise Exception(f"No {platform_name} ChromeDriver download found for version {target_version}")
        
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
        
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(cache_dir)
        
        chromedriver_path = None
        executable_name = "chromedriver.exe" if system == "windows" else "chromedriver"
        for root, dirs, files in os.walk(cache_dir):
            if executable_name in files:
                chromedriver_path = Path(root) / executable_name
                break
        
        if not chromedriver_path or not chromedriver_path.exists():
            raise Exception(f"ChromeDriver executable not found after extraction in {cache_dir}")
        
        if system != "windows":
            os.chmod(chromedriver_path, 0o755)
        
        return str(chromedriver_path)
        
    except Exception as e:
        logging.error(f"Failed to download ChromeDriver for version {chrome_version}: {e}")
        raise


def create_driver() -> webdriver.Chrome:
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
    
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")
    
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
    """Detect and wait for Cloudflare challenge pages to clear."""
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
            time.sleep(3)
            continue
        return True
    return False


def extract_url_data(driver: webdriver.Chrome, url: str) -> Tuple[Dict[str, str], webdriver.Chrome]:
    """Extract data from URL - single attempt only."""
    try:
        driver.get(url)
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        if not wait_for_cloudflare_clear(driver, url):
            return {"url": url, "h1": "", "h2": "", "content": "", "error": "Cloudflare timeout"}, driver
        
        h1 = h2 = content = ""
        try:
            h1_el = WebDriverWait(driver, 15).until(
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
            content_el = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.dictionary-details"))
            )
            content = content_el.text.strip()
        except TimeoutException:
            pass
        return {"url": url, "h1": h1, "h2": h2, "content": content}, driver
    except Exception as e:
        return {"url": url, "h1": "", "h2": "", "content": "", "error": str(e)}, driver


def load_checkpoint() -> int:
    """Load last processed index."""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r') as f:
                return int(f.read().strip())
        except:
            pass
    return 0


def save_checkpoint(index: int):
    """Save current progress."""
    with open(CHECKPOINT_FILE, 'w') as f:
        f.write(str(index))


def save_result(result: Dict[str, str]):
    """Append single result to JSON file."""
    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except:
            pass
    
    existing.append(result)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def main():
    logging.info("=" * 70)
    logging.info("🔄 RETRYING FAILED URL EXTRACTIONS")
    logging.info("=" * 70)

    # Load all failed URLs
    if not os.path.exists(FAILED_URLS_FILE):
        logging.error(f"❌ {FAILED_URLS_FILE} not found!")
        return
    
    with open(FAILED_URLS_FILE, "r", encoding="utf-8") as f:
        all_urls = [line.strip() for line in f if line.strip()]
    
    # Load checkpoint
    start_index = load_checkpoint()
    
    logging.info(f"📊 Total failed URLs: {len(all_urls)}")
    logging.info(f"✅ Already processed: {start_index}")
    logging.info(f"⏳ Remaining to process: {len(all_urls) - start_index}")

    if start_index >= len(all_urls):
        logging.info("✅ All URLs already processed!")
        return

    successful = 0
    still_failed = 0

    # Process from checkpoint
    for idx in range(start_index, len(all_urls)):
        url = all_urls[idx]
        logging.info(f"[{idx + 1}/{len(all_urls)}] Processing: {url}")
        
        driver = None
        try:
            driver = create_driver()
            data, driver = extract_url_data(driver, url)
            
            if data.get("h1") or data.get("h2") or data.get("content"):
                successful += 1
                logging.info("  ✅ Success!")
            else:
                still_failed += 1
                logging.warning("  ❌ Still empty")
            
            # Save result immediately
            save_result(data)
            
            # Save checkpoint after each URL
            save_checkpoint(idx + 1)
            
        except Exception as exc:
            still_failed += 1
            logging.error(f"  ❌ Error: {exc}")
            save_result({
                "url": url,
                "h1": "",
                "h2": "",
                "content": "",
                "error": str(exc)
            })
            save_checkpoint(idx + 1)
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            time.sleep(1)  # Shorter delay

    logging.info("=" * 70)
    logging.info("📊 RETRY SUMMARY")
    logging.info("=" * 70)
    logging.info(f"✅ Successful: {successful}")
    logging.info(f"❌ Still failed: {still_failed}")
    logging.info(f"📝 Total processed in this run: {successful + still_failed}")
    logging.info("=" * 70)


if __name__ == "__main__":
    main()
