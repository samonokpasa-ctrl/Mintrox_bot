import time
import threading
from datetime import datetime, timezone
import feedparser
import telebot
from supabase import create_client
from flask import Flask
import os

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = "8374495248:AAECvxzEgHxYRV3VhKC2LpH8rlNVBktRf6Q"
USER_CHAT_ID = 1168907278
BATCH_SIZE = 5
BATCH_SEND_INTERVAL = 600   # 10 minutes
PULSE_DELAY = 7             # delay between posts
BUFFER_LOW_THRESHOLD = 5    # trigger fetch when buffer is below this
STATUS_INTERVAL = 1800      # 30 minutes

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = "https://nbyzjrrgmgfvgkhftydv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ieXpqcnJnbWdmdmdraGZ0eWR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5OTQwMTAsImV4cCI6MjA3OTU3MDAxMH0.BUs7AgjjBtq1vDNClvqAjUZRMLjbrfNOAGpA0UPtyWk"
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------- TELEGRAM BOT -------------------
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    result = supabase.table(TABLE_NAME).select("*")\
        .eq("chat_id", str(chat_id)).eq("url", url).execute()
    return len(result.data) > 0

def mark_sent(chat_id, url):
    supabase.table(TABLE_NAME).insert({"chat_id": str(chat_id), "url": url}).execute()

# ------------------- RSS FEEDS -------------------
RSS_FEEDS = {
    "AI Core": [
        "https://openai.com/blog/rss/",
        "https://deepmind.com/blog/rss.xml",
        "https://www.anthropic.com/rss",
        "https://ai.facebook.com/blog/rss.xml",
        "https://blogs.microsoft.com/ai/feed/",
        "https://huggingface.co/blog/rss"
    ],
    "Tech News": [
        "https://techcrunch.com/tag/ai/feed/",
        "https://www.theverge.com/ai/rss/index.xml",
        "https://www.technologyreview.com/feed/"
    ],
    "Futurism + Future Tech": [
        "https://futurism.com/feed",
        "https://interestingengineering.com/feed/",
        "https://electrek.co/feed/"
    ],
    "WHO Updates": [
        "https://www.who.int/feeds/entity/mediacentre/news/en/rss.xml"
    ]
}

# ------------------- BUFFER -------------------
semi_fetch_buffer = []

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Fetching new posts...")
    posts = []
    for category, feeds in RSS_FEEDS.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    published = entry.get("published_parsed", time.gmtime(0))
                    if link and not link_sent(USER_CHAT_ID, link):
                        posts.append({"title": title, "link": link, "published_parsed": published})
            except Exception as e:
                print(f"Feed failed ({url}): {e}")
    posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    return posts

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
            bot.send_message(USER_CHAT_ID, "📘 THOT STATUS:\nScanning networks.\nProcessing signals.\nPipelines clean.")
        except:
            pass

# ------------------- AUTO-START MESSAGE -------------------
def send_start_message():
    bot.send_message(USER_CHAT_ID, "📘 THOT is online.\nCore systems calibrated.\nSignal flow initiated.")

# ------------------- FLASK FAKE WEB SERVER -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))  # Render sets PORT automatically

@app.route("/")
def home():
    return "Bot is alive!"

# ------------------- INITIAL SETUP -------------------
send_start_message()
initial_posts = fetch_rss_posts()
if initial_posts:
    semi_fetch_buffer.extend(initial_posts)

# ------------------- THREADS -------------------
threading.Thread(target=adaptive_fetcher, daemon=True).start()
threading.Thread(target=send_batch, daemon=True).start()
threading.Thread(target=status_loop, daemon=True).start()

# ------------------- MAIN -------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)  # keeps Render happy
    bot.infinity_polling()        "https://deepmind.com/blog/rss.xml",
        "https://www.anthropic.com/rss",
        "https://ai.facebook.com/blog/rss.xml",
        "https://blogs.microsoft.com/ai/feed/",
        "https://huggingface.co/blog/rss"
    ],
    "Tech News": [
        "https://techcrunch.com/tag/ai/feed/",
        "https://www.theverge.com/ai/rss/index.xml",
        "https://www.technologyreview.com/feed/"
    ],
    "Futurism + Future Tech": [
        "https://futurism.com/feed",
        "https://interestingengineering.com/feed",
        "https://electrek.co/feed/"
    ],
    "WHO Updates": [
        "https://www.who.int/feeds/entity/mediacentre/news/en/rss.xml"
    ]
}

# ------------------- BUFFERS -------------------
semi_fetch_buffer = []

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Fetching new posts...")
    posts = []
    for category, feeds in RSS_FEEDS.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    published = entry.get("published_parsed", time.gmtime(0))
                    if link and link not in sent_links:
                        posts.append({"title": title, "link": link, "published_parsed": published})
            except Exception as e:
                print(f"Feed failed ({url}): {e}")
    posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    return posts

def adaptive_fetcher():
    while True:
        if len(semi_fetch_buffer) < BUFFER_LOW_THRESHOLD:
            new_posts = fetch_rss_posts()
            if new_posts:
                semi_fetch_buffer.extend(new_posts)
        time.sleep(60)  # check every 60 seconds

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
                    append_sent_link(post["link"])
                except Exception as e:
                    print(f"Send failed: {e}")
                time.sleep(PULSE_DELAY)
            # After batch, send "New updates are coming!" message
            try:
                bot.send_message(USER_CHAT_ID, "📢 New updates are coming!")
            except Exception as e:
                print(f"Send failed: {e}")
            # Wait the batch interval
            time.sleep(BATCH_SEND_INTERVAL)
        else:
            time.sleep(10)  # buffer empty, check again soon

# ------------------- STATUS LOOP -------------------
def status_loop():
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            bot.send_message(
                USER_CHAT_ID,
                "📘 THOT STATUS:\nScanning networks.\nProcessing signals.\nPipelines clean."
            )
        except:
            pass

# ------------------- AUTO-START MESSAGE -------------------
def send_start_message():
    bot.send_message(
        USER_CHAT_ID,
        "📘 THOT is online.\nCore systems calibrated.\nSignal flow initiated."
    )

# ------------------- INITIAL SETUP -------------------
send_start_message()
initial_posts = fetch_rss_posts()
if initial_posts:
    semi_fetch_buffer.extend(initial_posts)

# ------------------- THREADS -------------------
threading.Thread(target=adaptive_fetcher, daemon=True).start()
threading.Thread(target=send_batch, daemon=True).start()
threading.Thread(target=status_loop, daemon=True).start()

# ------------------- MAIN LOOP -------------------
bot.infinity_polling()
