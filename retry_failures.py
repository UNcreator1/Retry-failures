#!/usr/bin/env python3
"""
Retry failed URL extractions using the exact same Selenium/Cloudflare
handling as the main fmit-crawler pipeline.
"""

import glob
import io
import json
import logging
import os
import platform
import re
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

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

# Logging setup (same format as crawler.py)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FAILED_URLS_FILE = "failed_urls_all_accounts.txt"
OUTPUT_FILE = "retry_results.json"
BATCH_SIZE = 10

CLOUDFLARE_KEYWORDS = [
    "just a moment",
    "checking your browser",
    "please enable cookies",
    "attention required",
    "verify you are human",
    "enable javascript",
]


def get_chrome_version() -> str:
    """Detect Chrome version using same logic as crawler.py."""
    chrome_bin = os.getenv("CHROME_BIN")
    if not chrome_bin:
        chrome_bin = "google-chrome"
        if os.path.exists("/opt/hostedtoolcache/setup-chrome/chromium"):
            matches = glob.glob("/opt/hostedtoolcache/setup-chrome/chromium/*/x64/chrome")
            if matches:
                chrome_bin = matches[0]
    try:
        result = subprocess.run([chrome_bin, "--version"], capture_output=True, text=True, timeout=10)
        version_output = result.stdout.strip()
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", version_output)
        if match:
            return match.group(1).split(".")[0]
    except Exception as exc:
        logging.warning(f"Could not detect Chrome version: {exc}")
    return ""


def download_chromedriver_for_version(chrome_version: str) -> str:
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

        versions_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        data = requests.get(versions_url, timeout=30).json()

        target_version = None
        for version_info in reversed(data["versions"]):
            version_str = version_info["version"]
            if version_str.startswith(f"{chrome_version}."):
                target_version = version_str
                break
        if not target_version:
            return ""

        download_url = None
        for version_info in data["versions"]:
            if version_info["version"] == target_version:
                downloads = version_info.get("downloads", {}).get("chromedriver", [])
                for item in downloads:
                    if item["platform"] == platform_name:
                        download_url = item["url"]
                        break
                break
        if not download_url:
            return ""

        cache_dir = Path.home() / ".wdm" / "drivers" / "chromedriver" / platform_name / target_version
        cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = cache_dir / f"chromedriver-{platform_name}.zip"
        resp = requests.get(download_url, timeout=120)
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(resp.content)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(cache_dir)
        executable = "chromedriver.exe" if system == "windows" else "chromedriver"
        for root, _, files in os.walk(cache_dir):
            if executable in files:
                path = Path(root) / executable
                if system != "windows":
                    os.chmod(path, 0o755)
                return str(path)
    except Exception as exc:
        logging.warning(f"Failed to download ChromeDriver via Chrome for Testing API: {exc}")
    return ""


def wait_for_cloudflare_clear(driver: webdriver.Chrome, url: str, timeout: int = 45) -> bool:
    start_time = time.time()
    already_refreshed = False
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
            logging.warning(f"☁️  Cloudflare challenge detected on {url}. Waiting...")
            time.sleep(5)
            if not already_refreshed:
                try:
                    driver.refresh()
                    already_refreshed = True
                except Exception:
                    pass
            continue
        return True
    logging.error(f"❌ Cloudflare challenge did not clear for {url} within {timeout}s")
    return False


def create_driver() -> webdriver.Chrome:
    chrome_bin = os.getenv("CHROME_BIN")
    if not chrome_bin:
        if os.path.exists("/opt/hostedtoolcache/setup-chrome/chromium"):
            matches = glob.glob("/opt/hostedtoolcache/setup-chrome/chromium/*/x64/chrome")
            if matches:
                chrome_bin = matches[0]
        else:
            chrome_bin = "google-chrome"

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

    chromedriver_path = ""
    chrome_version = get_chrome_version()
    if chrome_version:
        chromedriver_path = download_chromedriver_for_version(chrome_version)
    if not chromedriver_path:
        chromedriver_path = ChromeDriverManager().install()

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


def extract_url_data(driver: webdriver.Chrome, url: str, max_retries: int = 5) -> Tuple[Dict[str, str], webdriver.Chrome]:
    for attempt in range(max_retries):
        try:
            driver.get(url)
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            if not wait_for_cloudflare_clear(driver, url):
                raise TimeoutException("Cloudflare challenge did not clear in time")
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            h1 = h2 = content = ""
            try:
                h1_el = WebDriverWait(driver, 20).until(
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
                content_el = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.dictionary-details"))
                )
                content = content_el.text.strip()
            except TimeoutException:
                pass
            return {"url": url, "h1": h1, "h2": h2, "content": content}, driver
        except Exception as exc:
            logging.warning(f"URL error {url} (attempt {attempt + 1}/{max_retries}): {exc}. Retry in 10s...")
            time.sleep(10)
    return {"url": url, "h1": "", "h2": "", "content": ""}, driver


def load_failed_urls() -> List[str]:
    if not os.path.exists(FAILED_URLS_FILE):
        logging.error(f"❌ {FAILED_URLS_FILE} not found!")
        return []
    with open(FAILED_URLS_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]
    logging.info(f"📂 Loaded {len(urls)} failed URLs")
    return urls


def load_existing_results() -> List[str]:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [item.get("url", "") for item in data if item.get("url")]
    except Exception:
        return []


def save_results(results: List[Dict[str, str]]) -> None:
    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.extend(results)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    logging.info(f"💾 Saved {len(results)} results (total: {len(existing)})")


def main():
    logging.info("=" * 70)
    logging.info("🔄 RETRYING FAILED URL EXTRACTIONS")
    logging.info("=" * 70)

    failed_urls = load_failed_urls()
    if not failed_urls:
        return

    processed = set(load_existing_results())
    remaining = [url for url in failed_urls if url not in processed]

    logging.info(f"📊 Total failed URLs: {len(failed_urls)}")
    logging.info(f"✅ Already processed: {len(processed)}")
    logging.info(f"⏳ Remaining to process: {len(remaining)}")

    if not remaining:
        logging.info("✅ All URLs already processed!")
        return

    batch: List[Dict[str, str]] = []
    successful = 0
    still_failed = 0

    for idx, url in enumerate(remaining, 1):
        logging.info(f"[{idx}/{len(remaining)}] Processing: {url}")
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
            data["extracted_at"] = datetime.utcnow().isoformat()
            batch.append(data)
            if len(batch) >= BATCH_SIZE:
                save_results(batch)
                batch = []
        except Exception as exc:
            still_failed += 1
            logging.error(f"  ❌ Error: {exc}")
            batch.append({
                "url": url,
                "h1": "",
                "h2": "",
                "content": "",
                "error": str(exc),
                "extracted_at": datetime.utcnow().isoformat(),
            })
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            time.sleep(2)

    if batch:
        save_results(batch)

    logging.info("=" * 70)
    logging.info("📊 RETRY SUMMARY")
    logging.info("=" * 70)
    logging.info(f"✅ Successful: {successful}")
    logging.info(f"❌ Still failed: {still_failed}")
    logging.info(f"📝 Total processed: {len(remaining)}")
    logging.info("=" * 70)


if __name__ == "__main__":
    main()
