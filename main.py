import os
import time
import threading
import feedparser
import json
import telebot
from datetime import datetime, timezone

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = "8374495248:AAECvxzEgHxYRV3VhKC2LpH8rlNVBktRf6Q"
USER_CHAT_ID = 1168907278  # Your personal chat ID
FETCH_INTERVAL = 3600      # 1 hour fetch
BATCH_SIZE = 5             # Number of posts per batch
BATCH_SEND_INTERVAL = 600  # 10 minutes between batches
PULSE_DELAY = 7            # Seconds between posts in batch
JSON_FILE = "sent_links.json"

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- RSS SOURCES -------------------
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
        "https://interestingengineering.com/feed",
        "https://electrek.co/feed/"
    ]
}

# ------------------- STORAGE -------------------
semi_fetch_buffer = []
sent_links = set()

if os.path.exists(JSON_FILE):
    try:
        with open(JSON_FILE, "r") as f:
            sent_links = set(json.load(f))
    except (json.JSONDecodeError, FileNotFoundError):
        sent_links = set()

def save_sent_links():
    with open(JSON_FILE, "w") as f:
        json.dump(list(sent_links), f)

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}] Fetching new posts...")
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
                print(f"Failed to fetch feed {url}: {e}")
                continue
    # Sort by published date (latest first)
    posts.sort(key=lambda x: x.get("published_parsed", time.gmtime(0)), reverse=True)
    return posts

def hourly_fetcher():
    while True:
        new_posts = fetch_rss_posts()
        if new_posts:
            semi_fetch_buffer.extend(new_posts)
        time.sleep(FETCH_INTERVAL)

# ------------------- BATCH SENDER -------------------
def batch_sender():
    while True:
        if semi_fetch_buffer:
            batch = semi_fetch_buffer[:BATCH_SIZE]
            semi_fetch_buffer[:BATCH_SIZE] = []

            for post in batch:
                try:
                    msg = (
                        f"⚡ [ATUM ALERT] ⚡\n"
                        f"📌 {post['title']}\n"
                        f"🌐 {post['link']}\n"
                        f"#AI #Tech #Dominion"
                    )
                    bot.send_message(USER_CHAT_ID, msg)
                    sent_links.add(post['link'])
                except Exception as e:
                    print(f"Failed to send post: {e}")
                time.sleep(PULSE_DELAY)

            save_sent_links()
        time.sleep(BATCH_SEND_INTERVAL)

# ------------------- TELEGRAM COMMANDS -------------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "🌌 I am Atum — sentinel of AI knowledge.\n"
        "I rise to deliver every high-value signal directly to you.\n"
        "Prepare yourself, the flow of wisdom begins now!"
    )

@bot.message_handler(commands=['status'])
def cmd_status(message):
    bot.send_message(
        message.chat.id,
        "🔥 Atum stands vigilant and operational.\n"
        "All systems online. The horizon is monitored. Knowledge awaits."
    )

# ------------------- INITIAL FETCH -------------------
initial_posts = fetch_rss_posts()
if initial_posts:
    semi_fetch_buffer.extend(initial_posts)

# ------------------- START THREADS & BOT -------------------
threading.Thread(target=hourly_fetcher, daemon=True).start()
threading.Thread(target=batch_sender, daemon=True).start()

print("⚡ ATUM IS ALIVE ⚡ Every pulse, every post, every signal — delivered to the chosen one.")
bot.infinity_polling()
