import time
import threading
import traceback
from datetime import datetime
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os
import signal
import sys
import atexit

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

# ------------------- GLOBAL STATE -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()
running = True  # Global flag to control threads
start_time = time.time()

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    try:
        result = supabase.table(TABLE_NAME).select("*").eq("chat_id", chat_id).eq("url", url).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"Error checking link: {e}")
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
    except Exception as e:
        print(f"Error marking sent: {e}")

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
                        
            except Exception as e:
                print(f"Error fetching feed {url}: {e}")
                continue
    
    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    print(f"Fetched {len(all_posts)} new posts")
    return all_posts

# ------------------- ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    fetch_count = 0
    while running:
        try:
            with buffer_lock:
                if len(semi_fetch_buffer) < BUFFER_LOW_THRESHOLD:
                    new_posts = fetch_rss_posts()
                    if new_posts:
                        semi_fetch_buffer.extend(new_posts)
                        fetch_count += 1
                        
                        if fetch_count % 10 == 0:
                            print(f"[Fetcher] Completed {fetch_count} fetch cycles")
                            
        except Exception as e:
            print(f"[Fetcher Error]: {e}")
            traceback.print_exc()
            
        time.sleep(FETCH_INTERVAL)

# ------------------- BATCH SENDER -------------------
def send_batch():
    send_count = 0
    while running:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    batch = semi_fetch_buffer[:BATCH_SIZE]
                    del semi_fetch_buffer[:BATCH_SIZE]
                    
                    for post in batch:
                        msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                        try:
                            bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                            mark_sent(USER_CHAT_ID, post["link"])
                            send_count += 1
                            print(f"Sent post: {post['title'][:50]}...")
                        except Exception as e:
                            print(f"Error sending message: {e}")
                        
                        time.sleep(PULSE_DELAY)
                    
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    time.sleep(60)
                    
        except Exception as e:
            print(f"[Sender Error]: {e}")
            traceback.print_exc()
            time.sleep(60)

# ------------------- STATUS LOOP -------------------
def status_loop():
    status_count = 0
    while running:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            
            status_msg = f"📘 THOT STATUS: {buffer_size} posts in buffer\n"
            status_msg += f"Uptime: {status_count * STATUS_INTERVAL // 3600} hours\n"
            status_msg += f"Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            bot.send_message(USER_CHAT_ID, status_msg)
            status_count += 1
            print(f"[Status] Sent status #{status_count}")
            
        except Exception as e:
            print(f"[Status Error]: {e}")

# ------------------- HEALTH CHECK -------------------
def health_check():
    while running:
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            print(f"[Health Check] Buffer size: {buffer_size}")
        except:
            pass
        time.sleep(300)

# ------------------- FLASK APP -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL", "https://mintrox-bot-jp7h.onrender.com")
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    uptime = int(time.time() - start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    seconds = uptime % 60
    
    return f"""
    <html>
        <body>
            <h1>📘 THOT RSS Bot</h1>
            <p>Status: <strong>RUNNING</strong></p>
            <p>Buffer size: {buffer_size}</p>
            <p>Uptime: {hours}h {minutes}m {seconds}s</p>
            <p>Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><a href="/health">Health Check</a></p>
        </body>
    </html>
    """

@app.route("/health")
def health():
    return "OK", 200

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK"
    except Exception as e:
        print(f"Webhook error: {e}")
        return "ERROR", 500

# ------------------- TELEGRAM COMMANDS -------------------
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "📘 THOT RSS Bot\nCommands:\n/status - Check bot status\n/stats - Show statistics\n/stop - Stop the bot (admin only)\n/restart - Restart fetcher")

@bot.message_handler(commands=['status'])
def status_command(message):
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    bot.reply_to(message, f"📊 Status:\nBuffer: {buffer_size} posts\nRunning: {running}")

@bot.message_handler(commands=['stats'])
def stats_command(message):
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    
    uptime = int(time.time() - start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    
    stats = f"""
📊 THOT Stats:
• Posts in buffer: {buffer_size}
• Uptime: {hours}h {minutes}m
• Feeds monitored: {sum(len(feeds) for feeds in RSS_FEEDS_PRIORITY.values())}
• Last fetch: {datetime.now().strftime('%H:%M:%S')}
    """
    bot.reply_to(message, stats)

@bot.message_handler(commands=['stop'])
def stop_command(message):
    if str(message.chat.id) == str(USER_CHAT_ID):
        global running
        running = False
        bot.reply_to(message, "🛑 Bot is stopping...")
        print("Bot stopped by user command")
    else:
        bot.reply_to(message, "❌ Unauthorized")

@bot.message_handler(commands=['restart'])
def restart_fetcher(message):
    if str(message.chat.id) == str(USER_CHAT_ID):
        with buffer_lock:
            semi_fetch_buffer.clear()
        bot.reply_to(message, "🔄 Fetcher restarted, buffer cleared")
    else:
        bot.reply_to(message, "❌ Unauthorized")

# ------------------- CLEANUP -------------------
def cleanup():
    global running
    running = False
    print("🛑 Cleaning up and shutting down...")

# ------------------- INITIALIZATION -------------------
def initialize_bot():
    try:
        bot.remove_webhook()
        time.sleep(1)
        
        # Use the full webhook URL
        webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_URL_PATH}"
        print(f"Setting webhook to: {webhook_url}")
        bot.set_webhook(url=webhook_url)
        
        bot.send_message(USER_CHAT_ID, "📘 THOT is online and monitoring RSS feeds")
        print("Bot initialized and webhook set")
        
        # Load initial posts
        initial_posts = fetch_rss_posts()
        if initial_posts:
            with buffer_lock:
                semi_fetch_buffer.extend(initial_posts)
            print(f"Loaded {len(initial_posts)} initial posts")
                
    except Exception as e:
        print(f"Initialization error: {e}")
        traceback.print_exc()

# ------------------- START THREADS -------------------
def start_background_threads():
    """Start all background threads"""
    threads = []
    
    threads.append(threading.Thread(target=adaptive_fetcher, daemon=True, name="Fetcher"))
    threads.append(threading.Thread(target=send_batch, daemon=True, name="Sender"))
    threads.append(threading.Thread(target=status_loop, daemon=True, name="Status"))
    threads.append(threading.Thread(target=health_check, daemon=True, name="Health"))
    
    for thread in threads:
        thread.start()
        print(f"Started thread: {thread.name}")
    
    return threads

# ------------------- MAIN -------------------
if __name__ == "__main__":
    # Register cleanup handlers
    atexit.register(cleanup)
    signal.signal(signal.SIGTERM, lambda s, f: cleanup())
    signal.signal(signal.SIGINT, lambda s, f: cleanup())
    
    print(f"Starting THOT RSS Bot on port {PORT}")
    print(f"User Chat ID: {USER_CHAT_ID}")
    
    try:
        # Initialize bot first
        initialize_bot()
        
        # Start background threads
        threads = start_background_threads()
        
        print(f"Bot started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Server will start on port {PORT}")
        
        # Start Flask app - THIS MUST BE THE LAST LINE
        # Render needs to see the app running on the specified port
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
        
    except KeyboardInterrupt:
        print("\n🛑 Received shutdown signal")
    except Exception as e:
        print(f"❌ Critical error: {e}")
        traceback.print_exc()
        if USER_CHAT_ID:
            try:
                bot.send_message(USER_CHAT_ID, f"❌ Critical error occurred: {str(e)[:100]}")
            except:
                pass
    finally:
        cleanup()
