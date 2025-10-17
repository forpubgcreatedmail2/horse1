import os
import csv
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from telegram import InputFile, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import mimetypes  # ✅ Python 3.13 me imghdr hata gaya — ye safe hai

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8093787434:AAHOhybQgLcPAghmZd0MgsrraYBcVRZBymU")
ALLOWED_USER_ID = None
VENUES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
DAYS_AHEAD = 5
OUTPUT_DIR = "racecards"
PORT = int(os.environ.get("PORT", 8443))
HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "localhost")

# ----------------------------
# HELPERS / SCRAPER
# ----------------------------
def safe_filename(s: str) -> str:
    s = re.sub(r"[<>:\"/\\|?*]", "", s)
    return s.strip().replace(" ", "_")

def capitalize_words(text: str) -> str:
    return " ".join(w.capitalize() for w in text.strip().split()) if text else ""

def scrape_one_racecard(url: str, date_label: str):
    print(f"🔍 Fetching: {url}")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ Request error for {url}: {e}")
        return None

    text = resp.text
    if re.search(r"No\s+Races|No races scheduled|No Race Card", text, re.I):
        print("⚠️ Page indicates no races.")
        return None

    soup = BeautifulSoup(text, "html.parser")

    header = soup.select_one(".home.headline_home h3.border_bottom")
    race_location, race_date = "Unknown", date_label
    if header:
        header_text = header.get_text(strip=True)
        m = re.search(r"Race Card\s*-\s*(.+?)\s*-\s*(\d{2}\s\w+\s\d{4})", header_text, re.I)
        if m:
            race_location, race_date = m.group(1).strip(), m.group(2).strip()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"{safe_filename(race_location)}_RaceCard_{safe_filename(race_date)}.csv")
    races = soup.select(".race-card-new")
    if not races:
        print("⚠️ No .race-card-new elements found.")
        return None

    country_el, ground_el = soup.select_one(".race-country"), soup.select_one(".race-ground")
    country_text = country_el.get_text(strip=True) if country_el else ""
    ground_text = ground_el.get_text(strip=True) if ground_el else ""

    rows_out = [["Race", "Country", "Ground", "Time", "Horse Number", "Horse Name",
                 "HR NAME", "Horse Jockey", "Horse Trainer", "Horse Age", "Horse Draw"]]

    for i, race in enumerate(races, start=1):
        race_no = i
        time_el = soup.select_one(f"#race-{i} h4:nth-child(2)")
        race_time = time_el.get_text(strip=True) if time_el else ""
        first_row = True

        for hr in race.select("tr.dividend_tr, tr"):
            cols = hr.find_all("td")
            if len(cols) < 3:
                continue
            no_text = cols[0].get_text(strip=True)
            horse_number = re.sub(r"\(\d+\)", "", no_text).strip()
            draw = re.search(r"\((\d+)\)", no_text)
            draw = draw.group(1) if draw else ""

            horse_el = cols[2].select_one("h5 a") if cols[2] else None
            horse_name = capitalize_words(horse_el.get_text(strip=True)) if horse_el else capitalize_words(cols[2].get_text(strip=True))

            age_m = re.search(r"\d+", cols[3].get_text(strip=True)) if len(cols) >= 4 else None
            age = age_m.group(0) if age_m else ""
            trainer = cols[5].get_text(strip=True) if len(cols) >= 6 else ""
            jockey = cols[6].get_text(strip=True) if len(cols) >= 7 else ""

            rows_out.append([
                race_no, country_text, ground_text, race_time if first_row else "",
                horse_number, horse_name, "", jockey, trainer, age, draw
            ])
            first_row = False

        rows_out.append([""] * 11)

    try:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows_out)
        print(f"✅ Saved: {filepath}")
        return filepath
    except Exception as e:
        print(f"❌ Could not write CSV: {e}")
        return None

def scrape_race_cards_for_venues(venues, days_ahead=DAYS_AHEAD):
    base = "https://www.indiarace.com/Home/racingCenterEvent?venueId={venue}&event_date={date}&race_type=RACECARD"
    saved_files = []
    for delta in range(days_ahead):
        d = datetime.now().date() + timedelta(days=delta)
        date_label, date_param = d.strftime("%d %b %Y"), d.strftime("%Y-%m-%d")
        for v in venues:
            url = base.format(venue=v, date=date_param)
            saved = scrape_one_racecard(url, date_label)
            if saved:
                saved_files.append(saved)
    return saved_files

# ----------------------------
# TELEGRAM HANDLERS
# ----------------------------
def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Welcome to Horse Race Bot!\nUse /fetch to get race cards.")

def fetch(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        update.message.reply_text("⛔ Unauthorized access.")
        return

    update.message.reply_text("🏇 Fetching race cards... please wait ⏳")
    files = scrape_race_cards_for_venues(VENUES, DAYS_AHEAD)
    if not files:
        update.message.reply_text("❌ No race cards found.")
        return

    for fpath in sorted(files, key=os.path.getmtime):
        fname = os.path.basename(fpath)
        update.message.reply_text(f"📤 Sending: {fname}")
        with open(fpath, "rb") as fh:
            context.bot.send_document(chat_id=update.effective_chat.id, document=fh, filename=fname)
    update.message.reply_text("✅ All files sent.")

# ----------------------------
# MAIN (WEBHOOK MODE)
# ----------------------------
def main():
    print("🚀 Starting Telegram bot on Render (Webhook mode)...")
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("fetch", fetch))

    webhook_url = f"https://{HOSTNAME}/{BOT_TOKEN}"
    print(f"🌐 Setting webhook to: {webhook_url}")

    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url,
    )

    print("🤖 Bot is live and listening via Webhook!")
    updater.idle()

if __name__ == "__main__":
    main()

