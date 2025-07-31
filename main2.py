import time
import json
import os
import csv
import datetime
import argparse
import smtplib
from email.mime.text import MIMEText
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from zoneinfo import ZoneInfo

# Configuration
MORNING_START = 9   # 09:00 PKT
MORNING_END = 16    # 16:00 PKT
EVENING_START = 17  # 17:00 PKT
EVENING_END = 22    # 22:00 PKT
TIMEZONE = ZoneInfo("Asia/Karachi")

# Interval between checks when inside allowed window (seconds)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", 900))  # default 15 minutes

# Email credentials via env vars
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

if not (EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER):
    print("⚠ WARNING: One or more email environment variables are missing. "
          "Ensure EMAIL_SENDER, EMAIL_PASSWORD, and EMAIL_RECEIVER are set.")

# URL of the filtered page for your shoe size
SHOES_URLS = [
    "https://www.khazanay.pk/collections/mens-running-shoes?page=1&rb_filter_option_6f6cb72d544962fa333e2e34ce64f719=EUR%2044.5%7CEUR%2045%7CEUR%2045.5&rb_vendor=Brooks%7CSaucony%7CHoka%20One%20One",
    # "https://www.khazanay.pk/collections/mens-running-shoes?page=1&rb_filter_option_6f6cb72d544962fa333e2e34ce64f719=EUR%2045%7CEUR%2045.5&rb_vendor=Hoka%20One%20One"
]

STORAGE_FILE = "shoes.json"
CSV_FILE = "shoes_log.csv"

def now_pk():
    return datetime.datetime.now(tz=ZoneInfo("UTC")).astimezone(TIMEZONE)

def is_allowed_time(dt: datetime.datetime = None, ignore_time=False) -> bool:
    if ignore_time:
        return True
    dt = dt or now_pk()
    h = dt.hour
    in_morning = MORNING_START <= h < MORNING_END
    in_evening = EVENING_START <= h < EVENING_END
    return in_morning or in_evening

def seconds_until_next_allowed(dt: datetime.datetime = None) -> float:
    dt = dt or now_pk()
    h = dt.hour
    today = dt.date()

    windows = [
        (datetime.datetime.combine(today, datetime.time(MORNING_START, 0), tzinfo=TIMEZONE),
         datetime.datetime.combine(today, datetime.time(MORNING_END, 0), tzinfo=TIMEZONE)),
        (datetime.datetime.combine(today, datetime.time(EVENING_START, 0), tzinfo=TIMEZONE),
         datetime.datetime.combine(today, datetime.time(EVENING_END, 0), tzinfo=TIMEZONE)),
    ]

    for start, end in windows:
        if dt < start:
            return (start - dt).total_seconds()
        if start <= dt < end:
            return 0  # already inside

    next_day = today + datetime.timedelta(days=1)
    next_start = datetime.datetime.combine(next_day, datetime.time(MORNING_START, 0), tzinfo=TIMEZONE)
    return (next_start - dt).total_seconds()

def send_email(subject, message):
    if not (EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER):
        print("⚠ Email credentials missing; skipping email send.")
        return
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("📧 Email sent successfully!")
    except Exception as e:
        print(f"⚠ Error sending email: {e}")

def init_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver

def fetch_shoes(url, max_retries=2, backoff=3):
    for attempt in range(1, max_retries + 2):
        driver = None
        try:
            driver = init_driver()
            driver.get(url)
            time.sleep(5)
            shoes = {}
            shoe_elements = driver.find_elements(By.CLASS_NAME, "snize-product")
            print(f"Found {len(shoe_elements)} shoes on the page: {url}")
            for shoe in shoe_elements:
                try:
                    name = shoe.find_element(By.XPATH, ".//span[contains(@class, 'snize-title')]").text.strip()
                    price = shoe.find_element(By.CLASS_NAME, "snize-price").text.strip()
                    try:
                        condition_raw = shoe.find_element(
                            By.XPATH, ".//span[contains(@class, 'snize-product-condition-list')]"
                        ).text
                        condition = condition_raw.replace("Condition: ", "").strip()
                    except Exception:
                        condition = "Unknown"
                    unique_key = f"{name} | {url}"
                    shoes[unique_key] = {"price": price, "condition": condition, "url": url}
                except Exception as e:
                    print(f"⚠ Error extracting details for one shoe: {e}")
            print(f"✔ Parsed {len(shoes)} shoes from {url}")
            return shoes
        except Exception as e:
            print(f"❌ Attempt {attempt} failed fetching {url}: {e}")
            if attempt <= max_retries:
                wait = backoff * attempt
                print(f"⏳ Retrying in {wait} seconds...")
                time.sleep(wait)
            else:
                print(f"❌ Giving up on {url} after {attempt} attempts.")
                return {}
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

def load_stored_shoes():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r") as file:
                stored_shoes = json.load(file)
                print(f"✔ Loaded {len(stored_shoes)} stored shoes from local storage.")
                return stored_shoes
        except Exception as e:
            print(f"⚠ Failed to load storage file, starting fresh: {e}")
    else:
        print("⚠ No stored shoes found. This might be the first run.")
    return {}

def save_shoes(shoes):
    try:
        with open(STORAGE_FILE, "w") as file:
            json.dump(shoes, file, indent=2)
        print(f"✔ Saved {len(shoes)} shoes to storage.")
    except Exception as e:
        print(f"⚠ Failed to save shoes: {e}")

def log_new_shoes(new_shoes):
    first_appearance = now_pk()
    date_first_appeared = first_appearance.strftime("%Y-%m-%d")
    time_first_appeared = first_appearance.strftime("%H:%M:%S")
    try:
        with open(CSV_FILE, "a", newline="") as file:
            writer = csv.writer(file)
            for shoe, details in new_shoes.items():
                writer.writerow([shoe, details["condition"], details["price"], date_first_appeared, time_first_appeared])
        print(f"✔ Logged {len(new_shoes)} new shoes to CSV.")
    except Exception as e:
        print(f"⚠ Failed to log new shoes: {e}")

def check_for_new_shoes():
    stored_shoes = load_stored_shoes()
    new_shoes = {}
    all_shoes = {}

    for url in SHOES_URLS:
        current_shoes = fetch_shoes(url)
        if not current_shoes:
            print(f"❌ No shoes returned for {url}; skipping this URL.")
            continue
        for shoe, details in current_shoes.items():
            all_shoes[shoe] = details
            if shoe not in stored_shoes:
                new_shoes[shoe] = details

    if new_shoes:
        print(f"🚀 New shoes found: {len(new_shoes)}")
        message_lines = []
        for s, d in new_shoes.items():
            message_lines.append(f"{s} - {d['condition']} - {d['price']}\n{d['url']}")
        message = "New Shoes Available:\n" + "\n\n".join(message_lines)
        send_email("Khazanay New Shoes", message)
        log_new_shoes(new_shoes)
        save_shoes(all_shoes)
    else:
        print(f"✅ No new shoes at {now_pk().strftime('%Y-%m-%d %H:%M:%S %Z')}.")

def ensure_csv_header():
    if not os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, "w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["Shoe Name", "Condition", "Price", "Date First Appeared", "Time First Appeared"])
            print("✔ Created CSV log with header.")
        except Exception as e:
            print(f"⚠ Failed to create CSV file: {e}")

def main_loop(ignore_time=False):
    print("🔍 Shoe availability checker started...")
    ensure_csv_header()

    if not os.path.exists(STORAGE_FILE):
        print("🆕 First run detected: seeding initial shoe list...")
        all_shoes = {}
        for url in SHOES_URLS:
            all_shoes.update(fetch_shoes(url))
        save_shoes(all_shoes)

    while True:
        now = now_pk()
        if is_allowed_time(now, ignore_time=ignore_time):
            print(f"⏱ {now.strftime('%Y-%m-%d %H:%M:%S %Z')} inside allowed window (or ignored). Checking...")
            try:
                check_for_new_shoes()
            except Exception as e:
                print(f"⚠ Unexpected error during check: {e}")
            print(f"⏳ Sleeping for {CHECK_INTERVAL} seconds before next check.\n")
            time.sleep(CHECK_INTERVAL)
        else:
            wait_secs = seconds_until_next_allowed(now)
            human = str(datetime.timedelta(seconds=int(wait_secs)))
            print(f"🌙 {now.strftime('%Y-%m-%d %H:%M:%S %Z')} outside allowed hours. "
                  f"Waiting {human} until next allowed window.\n")
            time.sleep(wait_secs + 1)  # small buffer

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Khazanay shoe availability watcher")
    parser.add_argument("--ignore-time", action="store_true", help="Bypass time window restrictions and check continuously.")
    args = parser.parse_args()
    main_loop(ignore_time=args.ignore_time)
