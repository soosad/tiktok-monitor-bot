import os
import time
import random
import json
import asyncio
from datetime import datetime, timezone, timedelta
import yt_dlp
from telegram import Bot
from telegram.error import TelegramError

# 從 GitHub Secrets 讀取密鑰與群組 ID
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "-1004401703362"))
GENERAL_THREAD_ID = 1  # General 話題 ID

ACCOUNTS_FILE = 'accounts (2).txt'
HISTORY_FILE = 'sent_history.txt'
TOPICS_FILE = 'topics_map.json'

topics_map = {}
sent_video_ids = set()

def load_topics_map():
    global topics_map
    if os.path.exists(TOPICS_FILE):
        try:
            with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
                topics_map = json.load(f)
        except:
            topics_map = {}

def save_topics_map():
    with open(TOPICS_FILE, 'w', encoding='utf-8') as f:
        json.dump(topics_map, f, ensure_ascii=False, indent=2)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    sent_video_ids.add(v_id)

def save_history_id(v_id):
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{v_id}\n")

def load_accounts(filename):
    accounts = []
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                username = line.strip()
                if username and not username.startswith('#'):
                    # 統一格式儲存乾淨的主播名稱
                    clean_name = username.replace('@', '')
                    accounts.append(clean_name)
    return accounts

async def ensure_topic_exists(bot: Bot, streamer_name: str) -> int:
    """確保該主播專屬話題已建立，並以主播名字命名話題"""
    if streamer_name in topics_map:
        return topics_map[streamer_name]
    
    topic_name = f"{streamer_name}"  # 直接以主播名字為話題名稱
    for _ in range(3):
        try:
            topic = await bot.create_forum_topic(chat_id=TELEGRAM_CHAT_ID, name=topic_name)
            thread_id = topic.message_thread_id
            topics_map[streamer_name] = thread_id
            save_topics_map()
            print(f"✨ 成功建立主播專屬話題：{topic_name} (ID: {thread_id})")
            await asyncio.sleep(4.0)
            return thread_id
        except TelegramError as e:
            if "Flood control exceeded" in str(e):
                await asyncio.sleep(20)
            else:
                print(f"⚠️ 建立話題失敗 [{streamer_name}]: {e}")
                break
    return None

def get_tiktok_videos(streamer_name, limit=5):
    """取得主播最新影片清單，包含發布時間戳記"""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.tiktok.com/'
        }
    }
    url = f"https://www.tiktok.com/@{streamer_name}"
    
    for attempt in range(2):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                time.sleep(random.uniform(1.5, 2.5))
                result = ydl.extract_info(url, download=False)
                if result and 'entries' in result:
                    videos = []
                    for entry in result['entries'][:limit]:
                        if entry:
                            v_id = entry.get('id')
                            if v_id:
                                title = entry.get('title') or entry.get('description') or '無標題影片'
                                v_url = entry.get('url') or f"https://www.tiktok.com/@{streamer_name}/video/{v_id}"
                                timestamp = entry.get('timestamp')
                                videos.append({'id': v_id, 'url': v_url, 'title': title, 'timestamp': timestamp})
                    return videos
            except:
                time.sleep(2)
    return []

async def download_and_send_video(bot: Bot, thread_id: int, video_url: str, title: str, streamer_name: str, upload_time_str: str):
    file_path = f"temp_{int(time.time() * 1000)}.mp4"
    ydl_opts = {
        'outtmpl': file_path,
        'format': 'best',
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.tiktok.com/'
        }
    }
    
    success = False
    try:
        # 1. 在 General 話題 (ID: 1) 發送提示通知
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                message_thread_id=GENERAL_THREAD_ID,
                text=f"🚨 **新影片通知**\n👤 主播：{streamer_name}\n⏰ 上傳時間：{upload_time_str}\n📌 標題：{title}"
            )
        except Exception as e:
            print(f"⚠️ 發送 General 提示失敗: {e}")

        # 2. 下載影片並傳送到該主播專屬話題
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([video_url]))
        
        if os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > 48:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    message_thread_id=thread_id,
                    text=f"📌 標題：{title}\n🔗 連結：{video_url} (檔案超過 50MB)"
                )
                success = True
            else:
                caption_text = f"📌 {title}"
                if len(caption_text) > 1024:
                    caption_text = caption_text[:1021] + "..."
                
                with open(file_path, 'rb') as video_file:
                    await bot.send_video(
                        chat_id=TELEGRAM_CHAT_ID,
                        message_thread_id=thread_id,
                        video=video_file,
                        caption=caption_text,
                        supports_streaming=True
                    )
                success = True
    except Exception as e:
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                message_thread_id=thread_id,
                text=f"📌 標題：{title}\n🔗 連結：{video_url}"
            )
            success = True
        except:
            pass
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            
    if success:
        await asyncio.sleep(random.uniform(3.0, 5.0))
        
    return success

async def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ 找不到 Telegram Bot Token")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    load_history()
    load_topics_map()
    accounts = load_accounts(ACCOUNTS_FILE)
    
    if not accounts:
        print("❌ 沒有載入任何帳號")
        return

    print(f"🎯 開始檢查 {len(accounts)} 個主播的最新影片...")
    
    # 程式啟動時，先確保所有名單中的主播都有對應的話題並記錄下來
    for streamer_name in accounts:
        await ensure_topic_exists(bot, streamer_name)

    # 計算過去 11 分鐘的時間閾值
    now_utc = datetime.now(timezone.utc)
    eleven_minutes_ago = now_utc - timedelta(minutes=11)
    
    for streamer_name in accounts:
        thread_id = topics_map.get(streamer_name)
        if not thread_id:
            continue
            
        videos = get_tiktok_videos(streamer_name, limit=5)
        for video in reversed(videos):
            v_id = video['id']
            v_timestamp = video['timestamp']
            
            if v_id not in sent_video_ids:
                upload_time_str = "剛剛"
                
                if v_timestamp:
                    upload_dt = datetime.fromtimestamp(v_timestamp, tz=timezone.utc)
                    upload_time_str = upload_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')
                    if upload_dt < eleven_minutes_ago:
                        # 超過 11 分鐘的舊影片，略過發送並加入歷史紀錄
                        sent_video_ids.add(v_id)
                        save_history_id(v_id)
                        continue

                print(f"📥 發現符合條件的新影片 [{streamer_name}]: {video['title']}")
                sent_ok = await download_and_send_video(bot, thread_id, video['url'], video['title'], streamer_name, upload_time_str)
                if sent_ok:
                    sent_video_ids.add(v_id)
                    save_history_id(v_id)
                await asyncio.sleep(4.0)

if __name__ == "__main__":
    asyncio.run(main())
