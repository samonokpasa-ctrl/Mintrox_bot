import time
import threading
from datetime import datetime, timezone
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
USER_CHAT_ID = int(os.environ.get("USER_CHAT_ID"))
BATCH_SIZE = 5
BATCH_SEND_INTERVAL = 600  # 10 minutes
PULSE_DELAY = 7
BUFFER_LOW_THRESHOLD = 10
STATUS_INTERVAL = 1800
FETCH_INTERVAL = 300  # 5 minutes

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- VERIFIED WORKING FEEDS -------------------
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
        print(f"Database error: {e}")
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
    except Exception as e:
        print(f"Mark sent error: {e}")

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching posts...")
    all_posts = []
    
    for category, feeds in RSS_FEEDS_PRIORITY.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:15]:  # Recent 15 entries
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
                        print(f"✅ New: {title[:60]}...")
                        
            except Exception as e:
                print(f"❌ Feed error {url}: {e}")
    
    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    print(f"📥 Found {len(all_posts)} new posts")
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
                        print(f"📦 Buffer: {len(semi_fetch_buffer)} posts")
        except Exception as e:
            print(f"Fetcher error: {e}")
        time.sleep(FETCH_INTERVAL)

# ------------------- BATCH SENDER -------------------
def send_batch():
    while True:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    batch = semi_fetch_buffer[:BATCH_SIZE]
                    semi_fetch_buffer[:BATCH_SIZE] = []
                    
                    print(f"🚀 Sending batch of {len(batch)} posts")
                    
                    for i, post in enumerate(batch):
                        msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                        try:
                            bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                            mark_sent(USER_CHAT_ID, post["link"])
                            print(f"✅ Sent {i+1}/{len(batch)}")
                            
                            if i < len(batch) - 1:
                                time.sleep(PULSE_DELAY)
                                
                        except Exception as e:
                            print(f"❌ Send failed: {e}")
                            semi_fetch_buffer.append(post)  # Re-add failed post
                    
                    if batch:
                        bot.send_message(USER_CHAT_ID, f"📢 Batch complete. {len(batch)} signals processed.")
                    
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    time.sleep(60)
                    
        except Exception as e:
            print(f"Batch error: {e}")
            time.sleep(60)

# ------------------- STATUS LOOP -------------------
def status_loop():
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            bot.send_message(USER_CHAT_ID, f"📘 STATUS: {buffer_size} posts in buffer")
        except Exception as e:
            print(f"Status error: {e}")

# ------------------- FLASK APP -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    return {"status": "online", "buffer": buffer_size}

# ------------------- MAIN -------------------
if __name__ == "__main__":
    # Send startup message
    bot.send_message(USER_CHAT_ID, "📘 THOT is online. Monitoring verified feeds.")
    
    # Initial fetch
    initial_posts = fetch_rss_posts()
    with buffer_lock:
        semi_fetch_buffer.extend(initial_posts)
    
    # Start threads
    threading.Thread(target=adaptive_fetcher, daemon=True).start()
    threading.Thread(target=send_batch, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()
    
    print("🎉 Production bot running with verified feeds!")
    app.run(host="0.0.0.0", port=PORT, debug=False)
