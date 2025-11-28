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
BUFFER_LOW_THRESHOLD = 10  # Increased threshold
STATUS_INTERVAL = 1800
FETCH_INTERVAL = 300  # 5 minutes between fetches

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nbyzjrrgmgfvgkhftydv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ieXpqcnJnbWdmdmdraGZ0eWR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5OTQwMTAsImV4cCI6MjA3OTU3MDAxMH0.BUs7AgjjBtq1vDNClvqAjUZRMLjbrfNOAGpA0UPtyWk")
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------- TELEGRAM BOT -------------------
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    try:
        result = supabase.table(TABLE_NAME).select("*") \
            .eq("chat_id", chat_id).eq("url", url).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"Database error in link_sent: {e}")
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
    except Exception as e:
        print(f"Database error in mark_sent: {e}")

# ------------------- RSS FEEDS -------------------
RSS_FEEDS_PRIORITY = {
    "AI News": [
        "https://venturebeat.com/category/ai/feed/",
        "https://techcrunch.com/tag/artificial-intelligence/feed/",
        "https://www.aifeed.tech/rss/",
        "https://blogs.microsoft.com/ai/feed/",
    ],
    "Tech News": [
        "https://www.techmeme.com/feed.xml",
        "https://www.theverge.com/tech/rss/index.xml",
        "https://gizmodo.com/rss"
    ]
}

# ------------------- BUFFER -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()  # Add lock for thread safety

# ------------------- TRACK DEAD FEEDS -------------------
dead_feeds = {}

# ------------------- IMPROVED FETCHER -------------------
def fetch_rss_posts():
    """Fetch posts from all feeds without early termination"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Fetching new posts from all feeds...")
    all_posts = []

    for category, feeds in RSS_FEEDS_PRIORITY.items():
        print(f"Processing category: {category} with {len(feeds)} feeds")
        
        for url in feeds:
            # Skip temporarily dead feeds
            if url in dead_feeds and time.time() - dead_feeds[url] < 3600:
                print(f"Skipping dead feed: {url}")
                continue
                
            try:
                print(f"Fetching from: {url}")
                feed = feedparser.parse(url)
                
                if not feed.entries:
                    print(f"No entries in feed: {url}")
                    continue
                    
                print(f"Found {len(feed.entries)} entries in {url}")
                
                for entry in feed.entries[:10]:  # Process only recent 10 entries
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    published = entry.get("published_parsed", time.gmtime(0))
                    
                    if link and not link_sent(USER_CHAT_ID, link):
                        post = {
                            "title": title,
                            "link": link,
                            "published_parsed": published,
                            "category": category,
                            "feed_url": url
                        }
                        all_posts.append(post)
                        print(f"New post found: {title[:50]}...")
                        
            except Exception as e:
                print(f"Feed failed ({url}): {e}")
                dead_feeds[url] = time.time()

    # Sort all posts by date
    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    print(f"Total new posts fetched: {len(all_posts)}")
    return all_posts

# ------------------- FIXED ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    """Continuous fetcher that runs on a fixed interval"""
    while True:
        try:
            with buffer_lock:
                current_buffer_size = len(semi_fetch_buffer)
            
            print(f"Buffer size: {current_buffer_size}, Threshold: {BUFFER_LOW_THRESHOLD}")
            
            if current_buffer_size < BUFFER_LOW_THRESHOLD:
                print("Buffer low, fetching new posts...")
                new_posts = fetch_rss_posts()
                
                if new_posts:
                    with buffer_lock:
                        semi_fetch_buffer.extend(new_posts)
                    print(f"Added {len(new_posts)} posts to buffer. Total: {len(semi_fetch_buffer)}")
                else:
                    print("No new posts found in this fetch cycle")
            else:
                print(f"Buffer sufficient ({current_buffer_size}), skipping fetch")
                
        except Exception as e:
            print(f"Error in adaptive_fetcher: {e}")
            
        time.sleep(FETCH_INTERVAL)  # Wait before next fetch cycle

# ------------------- IMPROVED BATCH SENDER -------------------
def send_batch():
    """Send posts in batches with better error handling"""
    while True:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    batch_size = min(BATCH_SIZE, len(semi_fetch_buffer))
                    batch = semi_fetch_buffer[:batch_size]
                    semi_fetch_buffer[:batch_size] = []  # More efficient deletion
                    
                    print(f"Sending batch of {len(batch)} posts")
                    
                    for i, post in enumerate(batch):
                        try:
                            msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                            bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                            mark_sent(USER_CHAT_ID, post["link"])
                            print(f"Sent post {i+1}/{len(batch)}: {post['title'][:30]}...")
                            
                            if i < len(batch) - 1:  # Don't sleep after last post
                                time.sleep(PULSE_DELAY)
                                
                        except Exception as e:
                            print(f"Failed to send post: {e}")
                            # Put failed post back to buffer?
                            with buffer_lock:
                                semi_fetch_buffer.append(post)
                    
                    # Send batch completion message
                    if batch:
                        try:
                            bot.send_message(USER_CHAT_ID, f"📢 Batch complete. {len(batch)} signals processed. Next update in {BATCH_SEND_INTERVAL//60} minutes.")
                        except Exception as e:
                            print(f"Failed to send completion message: {e}")
                    
                    print(f"Batch sent. Waiting {BATCH_SEND_INTERVAL} seconds for next batch")
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    print("Buffer empty, waiting for posts...")
                    time.sleep(60)  # Wait longer when buffer is empty
                    
        except Exception as e:
            print(f"Error in send_batch: {e}")
            time.sleep(60)

# ------------------- STATUS LOOP -------------------
def status_loop():
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            
            status_msg = f"📘 THOT STATUS:\nBuffer: {buffer_size} posts\nLast check: {datetime.now().strftime('%H:%M:%S')}\nSystem: Operational"
            bot.send_message(USER_CHAT_ID, status_msg)
            print("Status update sent")
        except Exception as e:
            print(f"Status update failed: {e}")

# ------------------- AUTO START -------------------
def send_start_message():
    try:
        bot.send_message(USER_CHAT_ID, 
            "📘 THOT is online.\nCore systems calibrated.\nSignal flow initiated.\nContinuous monitoring enabled.")
        print("Start message sent")
    except Exception as e:
        print(f"Failed to send start message: {e}")

# ------------------- FLASK SERVER -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = "https://mintrox-bot-jp7h.onrender.com"
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    return f"Bot is alive! Buffer: {buffer_size} posts"

@app.route("/debug")
def debug():
    with buffer_lock:
        buffer_info = {
            "buffer_size": len(semi_fetch_buffer),
            "buffer_titles": [post["title"][:50] + "..." for post in semi_fetch_buffer[:5]],
            "dead_feeds": len(dead_feeds)
        }
    return buffer_info

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK"

# ------------------- INITIAL SETUP -------------------
def initialize_bot():
    """Initialize bot with error handling"""
    try:
        print("Initializing bot...")
        send_start_message()
        
        # Initial fetch
        print("Performing initial fetch...")
        initial_posts = fetch_rss_posts()
        if initial_posts:
            with buffer_lock:
                semi_fetch_buffer.extend(initial_posts)
            print(f"Initial fetch added {len(initial_posts)} posts to buffer")
        else:
            print("No posts in initial fetch")
            
    except Exception as e:
        print(f"Initialization error: {e}")

# ------------------- MAIN -------------------
if __name__ == "__main__":
    # Remove old webhook and set the new one
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
        print("Webhook set successfully")
    except Exception as e:
        print(f"Webhook setup error: {e}")

    # Initialize bot
    initialize_bot()

    # Start background threads
    print("Starting background threads...")
    threading.Thread(target=adaptive_fetcher, daemon=True).start()
    threading.Thread(target=send_batch, daemon=True).start() 
    threading.Thread(target=status_loop, daemon=True).start()
    
    print("All threads started. Bot is running...")
    
    # Run Flask server
    app.run(host="0.0.0.0", port=PORT, debug=False)
