import time
import threading
from datetime import datetime, timezone
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = "8374495248:AAECvxzEgHxYRV3VhKC2LpH8rlNVBktRf6Q"
USER_CHAT_ID = 1168907278
BATCH_SIZE = 5
BATCH_SEND_INTERVAL = 600  # 10 minutes
PULSE_DELAY = 7
BUFFER_LOW_THRESHOLD = 5
STATUS_INTERVAL = 1800

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = "https://nbyzjrrgmgfvgkhftydv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ieXpqcnJnbWdmdmdraGZ0eWR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5OTQwMTAsImV4cCI6MjA3OTU3MDAxMH0.BUs7AgjjBtq1vDNClvqAjUZRMLjbrfNOAGpA0UPtyWk"
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------- TELEGRAM BOT -------------------
bot = telebot.TeleBot(TELEGRAM_TOKEN)  # Webhook only

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    result = supabase.table(TABLE_NAME).select("*") \
        .eq("chat_id", chat_id).eq("url", url).execute()
    return len(result.data) > 0

def mark_sent(chat_id, url):
    supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()

# ------------------- RSS FEEDS -------------------
RSS_FEEDS_PRIORITY = {
    "AI News": [
        "https://venturebeat.com/category/ai/feed/",         # High
        "https://techcrunch.com/tag/artificial-intelligence/feed/", # High
        "https://www.aifeed.tech/rss/",                     # Medium
        "https://blogs.microsoft.com/ai/feed/",            # Medium
        "https://raw.githubusercontent.com/foorilla/allainews_sources/main/feeds.txt"  # Low / list
    ],
    "Tech News": [
        "https://www.techmeme.com/feed.xml",               # High
        "https://www.theverge.com/tech/rss/index.xml",     # Medium
        "https://gizmodo.com/rss"                          # Medium
    ]
}

# ------------------- BUFFER -------------------
semi_fetch_buffer = []

# ------------------- TRACK DEAD FEEDS -------------------
dead_feeds = {}

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Fetching new posts...")
    posts = []

    for category, feeds in RSS_FEEDS_PRIORITY.items():
        for url in feeds:
            # Skip temporarily dead feeds
            if url in dead_feeds and time.time() - dead_feeds[url] < 3600:
                continue
            try:
                feed = feedparser.parse(url)
                if not feed.entries:
                    raise ValueError("No entries")
                for entry in feed.entries:
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    published = entry.get("published_parsed", time.gmtime(0))
                    if link and not link_sent(USER_CHAT_ID, link):
                        posts.append({
                            "title": title,
                            "link": link,
                            "published_parsed": published
                        })
            except Exception as e:
                print(f"Feed failed ({url}): {e}")
                dead_feeds[url] = time.time()  # mark dead temporarily

            # Stop if buffer will be filled enough
            if len(semi_fetch_buffer) + len(posts) >= BUFFER_LOW_THRESHOLD:
                semi_fetch_buffer.extend(posts)
                return semi_fetch_buffer

    posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    return posts

# ------------------- ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    while True:
        if len(semi_fetch_buffer) < BUFFER_LOW_THRESHOLD:
            new_posts = fetch_rss_posts()
            if new_posts:
                semi_fetch_buffer.extend(new_posts)
        time.sleep(60)

# ------------------- BATCH SENDER -------------------
def send_batch():
    while True:
        if semi_fetch_buffer:
            batch = semi_fetch_buffer[:BATCH_SIZE]
            del semi_fetch_buffer[:BATCH_SIZE]

            for post in batch:
                msg = f"📘 **THOT SIGNAL**\n**{post['title']}**\n{post['link']}"
                try:
                    bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                    mark_sent(USER_CHAT_ID, post["link"])
                except Exception as e:
                    print(f"Send failed: {e}")

                time.sleep(PULSE_DELAY)

            try:
                bot.send_message(USER_CHAT_ID, "📢 New updates are coming!")
            except Exception as e:
                print(f"Send failed: {e}")

            time.sleep(BATCH_SEND_INTERVAL)
        else:
            time.sleep(10)

# ------------------- STATUS LOOP -------------------
def status_loop():
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            bot.send_message(USER_CHAT_ID,
                "📘 THOT STATUS:\nScanning networks.\nProcessing signals.\nPipelines clean.")
        except:
            pass

# ------------------- AUTO START -------------------
def send_start_message():
    bot.send_message(USER_CHAT_ID,
        "📘 THOT is online.\nCore systems calibrated.\nSignal flow initiated.")

# ------------------- FLASK SERVER -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = "https://mintrox-bot-jp7h.onrender.com"
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    return "Bot is alive!"

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK"

# ------------------- INITIAL SETUP -------------------
send_start_message()
initial_posts = fetch_rss_posts()
if initial_posts:
    semi_fetch_buffer.extend(initial_posts)

# ------------------- MAIN -------------------
if __name__ == "__main__":
    # Remove old webhook and set the new one
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)

    # Start background threads
    threading.Thread(target=adaptive_fetcher, daemon=True).start()
    threading.Thread(target=send_batch, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()

    # Run Flask server (handle webhook POSTs)
    app.run(host="0.0.0.0", port=PORT)
