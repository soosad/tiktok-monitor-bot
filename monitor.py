import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import random
import subprocess
import time
from telegram import Bot
from telegram.error import TelegramError
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
import yt_dlp

# === 讀取環境變數 ===
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GENERAL_THREAD_ID = 1  # General 話題 ID

ACCOUNTS_FILE = "accounts (2).txt"
HISTORY_FILE = "sent_history.txt"
TOPICS_FILE = "topics_map.json"

topics_map = {}
sent_video_ids = set()

def load_topics_map():
    global topics_map
    if os.path.exists(TOPICS_FILE):
        try:
            with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                topics_map = json.load(f)
                print(f"📂 已成功載入本機 topics_map.json，共 {len(topics_map)} 筆對應。")
        except Exception as e:
            print(f"⚠️ 載入 topics_map.json 失敗: {e}")
            topics_map = {}

def save_topics_map():
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics_map, f, ensure_ascii=False, indent=2)

def save_and_push_topic_immediately(streamer_name, thread_id):
    """當下即時儲存對應並推送到 GitHub 倉庫"""
    save_topics_map()
    print(f"💾 【即時儲存】已將 【{streamer_name}】 (ID: {thread_id}) 寫入 topics_map.json")
    
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.io"], check=True)
        subprocess.run(["git", "add", "topics_map.json"], check=True)
        subprocess.run(["git", "commit", "-m", f"🤖 Auto-update topic map for {streamer_name}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"🚀 【即時推送】已成功將 topics_map.json 推回 GitHub 倉庫！")
    except Exception as e:
        print(f"⚠️ 【即時推送失敗】（可能是本地無變動或權限問題，不影響主程式）: {e}")

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    sent_video_ids.add(v_id)
        print(f"📂 已載入歷史發送紀錄，共 {len(sent_video_ids)} 筆。")

def save_history_id(v_id):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{v_id}\n")

def load_accounts(filename):
    accounts = []
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                username = line.strip()
                if username and not username.startswith("#"):
                    clean_name = username.replace("@", "")
                    accounts.append(clean_name)
    print(f"📋 從 {filename} 載入了以下主播名單: {accounts}")
    return accounts

async def clean_and_sync_topics(accounts):
    """使用 Telethon 掃描群組所有話題，並印出詳細偵錯訊息"""
    print("\n🔍 【Debug 1】準備透過 Telethon 連線並掃描群組話题...")
    
    if not API_ID or not API_HASH or not SESSION_STRING:
        print("❌ 【Debug 錯誤】缺少 API_ID, API_HASH 或 SESSION_STRING，無法啟動 Telethon！")
        return

    try:
        client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            print("❌ 【Debug 錯誤】SESSION_STRING 已經失效或未授權！")
            await client.disconnect()
            return

        me = await client.get_me()
        print(f"👤 【Debug 成功】Telethon 已成功登入帳號: {me.first_name} (ID: {me.id})")

        chat_id_int = int(TELEGRAM_CHAT_ID)
        print(f"💬 【Debug】正在取得聊天室實體，目標 Chat ID: {chat_id_int}")
        entity = await client.get_entity(chat_id_int)
        print(f"🏢 【Debug】成功取得群組名稱: {getattr(entity, 'title', '未知群組')}")

        raw_topics = {}
        try:
            from telethon.tl.functions.messages import GetForumTopicsRequest
            result = await client(GetForumTopicsRequest(
                peer=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
            ))
            for topic in result.topics:
                raw_topics[topic.id] = topic.title
        except Exception as e1:
            print(f"⚠️ 【Debug 提示】messages.GetForumTopics 失敗 ({e1})，嘗試 channels 版本...")
            try:
                from telethon.tl.functions.channels import GetForumTopicsRequest
                result = await client(GetForumTopicsRequest(
                    channel=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
                ))
                for topic in result.topics:
                    raw_topics[topic.id] = topic.title
            except Exception as e2:
                print(f"❌ 【Debug 錯誤】無法取得話題清單: {e2}")
                await client.disconnect()
                return

        print(f"📋 【Debug】群組內現有的所有話題清單: {raw_topics}")

        title_to_ids = {}
        for tid, title in raw_topics.items():
            if title not in title_to_ids:
                title_to_ids[title] = []
            title_to_ids[title].append(tid)

        for streamer_name in accounts:
            topic_name = streamer_name
            if topic_name in title_to_ids:
                tids = sorted(title_to_ids[topic_name])
                earliest_tid = tids[0]
                topics_map[streamer_name] = earliest_tid
                print(f"🔗 【配對成功】主播 【{streamer_name}】 對應到現有話題 ID: {earliest_tid}")

                if len(tids) > 1:
                    print(f"🧹 發現主播 【{streamer_name}】 有 {len(tids)} 個重複話題，保留最早的 ID [{earliest_tid}]，正在刪除多餘話題...")
                    for dup_tid in tids[1:]:
                        try:
                            await client(functions.channels.DeleteTopicRequest(
                                channel=entity,
                                topic_id=dup_tid
                            ))
                            print(f"  🗑️ 已刪除重複話題 ID: {dup_tid}")
                            await asyncio.sleep(1.0)
                        except Exception as del_err:
                            print(f"  ⚠️ 刪除話題失敗 (ID: {dup_tid}): {del_err}")
            else:
                print(f"📌 【未找到】群組內找不到名為 【{streamer_name}】 的話題，後續將由 Bot 建立。")

        save_topics_map()
        print("✅ 【Debug】話題掃描流程結束。\n")
        await client.disconnect()

    except Exception as e:
        print(f"❌ 【Debug 嚴重錯誤】Telethon 執行時發生例外: {e}")

async def ensure_topic_exists(bot: Bot, streamer_name: str) -> int:
    topic_name = f"{streamer_name}"
    if streamer_name in topics_map:
        return topics_map[streamer_name]

    for _ in range(3):
        try:
            topic = await bot.create_forum_topic(chat_id=int(TELEGRAM_CHAT_ID), name=topic_name)
            thread_id = topic.message_thread_id
            topics_map[streamer_name] = thread_id
            
            # 建立成功當下立刻儲存並推送到 GitHub
            save_and_push_topic_immediately(streamer_name, thread_id)
            
            print(f"✨ 成功在群組中建立新話題：{topic_name} (ID: {thread_id})")
            await asyncio.sleep(4.0)
            return thread_id
        except TelegramError as e:
            if "Flood control exceeded" in str(e):
                await asyncio.sleep(20)
            else:
                print(f"⚠️ 建立話題失敗 [{streamer_name}]: {e}")
                break
    return None

def get_tiktok_videos(streamer_name, limit=3):
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Referer': 'https://www.tiktok.com/',
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
                                title = entry.get('title') or entry.get('description') or "無標題影片"
                                v_url = entry.get('url') or f"https://www.tiktok.com/@{streamer_name}/video/{v_id}"
                                timestamp = entry.get('timestamp')
                                videos.append({
                                    'id': v_id,
                                    'url': v_url,
                                    'title': title,
                                    'timestamp': timestamp
                                })
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
            'Referer': 'https://www.tiktok.com/',
        }
    }

    success = False
    try:
        try:
            await bot.send_message(
                chat_id=int(TELEGRAM_CHAT_ID),
                message_thread_id=GENERAL_THREAD_ID,
                text=f"🚨 **新影片通知**\n👤 主播：{streamer_name}\n⏰ 上傳時間：{upload_time_str}\n📌 標題：{title}"
            )
        except Exception as e:
            print(f"⚠️ 發送 General 提示失敗: {e}")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([video_url]))

        if os.path.exists(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > 48:
                await bot.send_message(
                    chat_id=int(TELEGRAM_CHAT_ID),
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
                        chat_id=int(TELEGRAM_CHAT_ID),
                        message_thread_id=thread_id,
                        video=video_file,
                        caption=caption_text,
                        supports_streaming=True
                    )
                success = True
    except Exception as e:
        try:
            await bot.send_message(
                chat_id=int(TELEGRAM_CHAT_ID),
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

    # 1. 執行 Telethon 掃描與話題整併清理
    await clean_and_sync_topics(accounts)

    print(f"🎯 開始檢查 {len(accounts)} 個主播的最新影片...")

    for streamer_name in accounts:
        await ensure_topic_exists(bot, streamer_name)

    now_utc = datetime.now(timezone.utc)
    four_hours_ago = now_utc - timedelta(hours=4)  # 改為往回推 4 小時

    for streamer_name in accounts:
        thread_id = topics_map.get(streamer_name)
        if not thread_id:
            continue

        videos = get_tiktok_videos(streamer_name, limit=3)
        for video in reversed(videos):
            v_id = video["id"]
            v_timestamp = video["timestamp"]

            if v_id not in sent_video_ids:
                upload_time_str = "剛剛"

                if v_timestamp:
                    upload_dt = datetime.fromtimestamp(v_timestamp, tz=timezone.utc)
                    upload_time_str = upload_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')
                    if upload_dt < four_hours_ago:  # 超過 4 小時前的舊影片略過
                        sent_video_ids.add(v_id)
                        save_history_id(v_id)
                        continue

                print(f"📥 發現符合條件的新影片 [{streamer_name}]: {video['title']}")
                sent_ok = await download_and_send_video(
                    bot, thread_id, video["url"], video["title"], streamer_name, upload_time_str
                )
                if sent_ok:
                    sent_video_ids.add(v_id)
                    save_history_id(v_id)
                await asyncio.sleep(4.0)

if __name__ == "__main__":
    asyncio.run(main())
