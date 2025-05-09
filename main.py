import time
import json
import os
import csv
import datetime
import smtplib
from email.mime.text import MIMEText
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# Allowed time ranges (24-hour format)
MORNING_START = 9   # 07:00 AM
MORNING_END = 16    # 11:00 AM
EVENING_START = 17  # 05:00 PM
EVENING_END = 22    # 10:00 PM
UK_PK_OFFSET = 5    # UK is 5 hours behind Pakistan

# Email credentials via env vars
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# URL of the filtered page for your shoe size
SHOES_URLS = [
    "https://www.khazanay.pk/collections/mens-running-shoes?page=1&rb_filter_option_6f6cb72d544962fa333e2e34ce64f719=EUR%2044.5&rb_vendor=Brooks%7CSaucony%7CAsics",
    "https://www.khazanay.pk/collections/mens-running-shoes?page=1&rb_filter_option_6f6cb72d544962fa333e2e34ce64f719=EUR%2045%7CEUR%2045.5&rb_vendor=Hoka%20One%20One"
]

STORAGE_FILE = "shoes.json"
CSV_FILE = "shoes_log.csv"

def is_allowed_time():
    now = (datetime.datetime.now().hour + UK_PK_OFFSET) % 24
    return True or (MORNING_START <= now < MORNING_END) or (EVENING_START <= now < EVENING_END)

def send_email(subject, message):
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

def fetch_shoes(url):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.get(url)
    time.sleep(5)
    
    shoes = {}
    shoe_elements = driver.find_elements(By.CLASS_NAME, "snize-product")
    print(f"Found {len(shoe_elements)} shoes on the page.")
    for shoe in shoe_elements:
        try:
            name = name = shoe.find_element(By.XPATH, ".//span[contains(@class, 'snize-title')]").text.strip()
            price = shoe.find_element(By.CLASS_NAME, "snize-price").text.strip()
            condition = shoe.find_element(By.XPATH, ".//span[contains(@class, 'snize-product-condition-list')]").text.replace("Condition: ", "").strip()
            unique_key = f"{name} | {url}"
            shoes[unique_key] = {"price": price, "condition": condition, "url": url}
        except Exception as e:
            print(f"⚠ Error extracting shoe details: {e}")
    
    driver.quit()
    print(f"✔ Found {len(shoes)} shoes on the website.")
    return shoes

def load_stored_shoes():
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, "r") as file:
            stored_shoes = json.load(file)
            print(f"✔ Loaded {len(stored_shoes)} stored shoes from local storage.")
            return stored_shoes
    print("⚠ No stored shoes found. This might be the first run.")
    return {}

def save_shoes(shoes):
    with open(STORAGE_FILE, "w") as file:
        json.dump(shoes, file, indent=4)

def log_new_shoes(new_shoes):
    # adjust time to PK
    first_appearance = (datetime.datetime.now() + datetime.timedelta(hours=UK_PK_OFFSET))
    date_first_appeared = first_appearance.strftime("%Y-%m-%d")
    time_first_appeared = first_appearance.strftime("%H:%M:%S")
    with open(CSV_FILE, "a", newline="") as file:
        writer = csv.writer(file)
        for shoe, details in new_shoes.items():
            writer.writerow([shoe, details["condition"], details["price"], date_first_appeared, time_first_appeared])

def check_for_new_shoes():
    stored_shoes = load_stored_shoes()
    new_shoes = {}
    all_shoes = {}

    for url in SHOES_URLS:
        current_shoes = fetch_shoes(url)
        
        if not current_shoes:
            print("❌ No shoes found or error fetching data.")
            return
        for shoe, details in current_shoes.items():
            all_shoes[shoe] = details
            if shoe not in stored_shoes:
                new_shoes[shoe] = details
    
    if new_shoes:
        print(f"🚀 New shoes found: {len(new_shoes)}")
        message = "New Shoes Available:\n" + "\n".join([f"{s} - {d['condition']} - {d['price']}\n{d['url']}" for s, d in new_shoes.items()])
        # notification.notify(title="Shoe Availability Alert", message=message, timeout=10)
        send_email("Khazanay New Shoes", message)
        log_new_shoes(new_shoes)
        save_shoes(all_shoes)
    else:
        print("✅ No new shoes found.")

if __name__ == "__main__":
    print("🔍 Shoe availability checker running...\n")
    delay = 900
    if not os.path.exists(STORAGE_FILE):
        print("🆕 First run detected: Fetching and storing initial shoe list...")
        all_shoes = {}
        for url in SHOES_URLS:
            all_shoes.update(fetch_shoes(url))
        save_shoes(all_shoes)
    
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as file:
            csv.writer(file).writerow(["Shoe Name", "Condition", "Price", "Date First Appeared", "Time First Appeared"])
    
    if is_allowed_time():
        check_for_new_shoes()
        print(f"⏳ Waiting for next check in {delay / 3600.} hour(s)...\n")
    else:
        print("🌙 Outside allowed hours. Skipping check.")
