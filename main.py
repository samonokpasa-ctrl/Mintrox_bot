import time
import threading
from datetime import datetime, timezone
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8374495248:AAECvxzEgHxYRV3VhKC2LpH8rlNVBktRf6Q")
USER_CHAT_ID = int(os.environ.get("USER_CHAT_ID", "1168907278"))
BATCH_SIZE = 5
BATCH_SEND_INTERVAL = 600  # 10 minutes
PULSE_DELAY = 7
BUFFER_LOW_THRESHOLD = 10
STATUS_INTERVAL = 1800
FETCH_INTERVAL = 300  # 5 minutes

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nbyzjrrgmgfvgkhftydv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ieXpqcnJnbWdmdmdraGZ0eWR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5OTQwMTAsImV4cCI6MjA3OTU3MDAxMH0.BUs7AgjjBtq1vDNClvqAjUZRMLjbrfNOAGpA0UPtyWk")
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- RSS FEEDS -------------------
RSS_FEEDS_PRIORITY = {
    "AI News": [
        "https://techcrunch.com/tag/artificial-intelligence/feed/",
    ],
    "Tech News": [
        "https://www.techmeme.com/feed.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "https://feeds.bbci.co.uk/news/technology/rss.xml"
    ]
}

# ------------------- BUFFER -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    try:
        result = supabase.table(TABLE_NAME).select("*").eq("chat_id", chat_id).eq("url", url).execute()
        return len(result.data) > 0
    except Exception as e:
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
    except Exception as e:
        pass

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    all_posts = []
    
    for category, feeds in RSS_FEEDS_PRIORITY.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries[:10]:
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    published = entry.get("published_parsed", time.gmtime(0))
                    
                    if link and not link_sent(USER_CHAT_ID, link):
                        post = {
                            "title": title,
                            "link": link,
                            "published_parsed": published,
                            "category": category
                        }
                        all_posts.append(post)
                        
            except Exception:
                continue
    
    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    return all_posts

# ------------------- ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    while True:
        try:
            with buffer_lock:
                if len(semi_fetch_buffer) < BUFFER_LOW_THRESHOLD:
                    new_posts = fetch_rss_posts()
                    if new_posts:
                        semi_fetch_buffer.extend(new_posts)
        except Exception:
            pass
            
        time.sleep(FETCH_INTERVAL)

# ------------------- BATCH SENDER -------------------
def send_batch():
    while True:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    batch = semi_fetch_buffer[:BATCH_SIZE]
                    semi_fetch_buffer[:BATCH_SIZE] = []
                    
                    for post in batch:
                        msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                        try:
                            bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                            mark_sent(USER_CHAT_ID, post["link"])
                        except Exception:
                            pass
                        
                        time.sleep(PULSE_DELAY)
                    
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    time.sleep(60)
                    
        except Exception:
            time.sleep(60)

# ------------------- STATUS LOOP -------------------
def status_loop():
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            bot.send_message(USER_CHAT_ID, f"📘 THOT STATUS: {buffer_size} posts in buffer")
        except Exception:
            pass

# ------------------- FLASK APP -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = "https://mintrox-bot-jp7h.onrender.com"
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    return "THOT RSS Bot is running"

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK"

# ------------------- INITIALIZATION -------------------
def initialize_bot():
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
        
        bot.send_message(USER_CHAT_ID, "📘 THOT is online and monitoring RSS feeds")
        
        initial_posts = fetch_rss_posts()
        if initial_posts:
            with buffer_lock:
                semi_fetch_buffer.extend(initial_posts)
                
    except Exception:
        pass

# ------------------- MAIN -------------------
if __name__ == "__main__":
    initialize_bot()

    threading.Thread(target=adaptive_fetcher, daemon=True).start()
    threading.Thread(target=send_batch, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()
    
    app.run(host="0.0.0.0", port=PORT, debug=False)
