import discord
from discord.ext import commands
import google.generativeai as genai
import asyncio
import time
import os
import ollama  # 追加
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

USE_OLLAMA = True  
OLLAMA_MODEL = "qwen3.5:9b"  
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKENが未設定")

# Geminiの初期化 (APIキーがある場合のみ)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.5-flash")

# =====================
# Discord設定
# =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =====================
# 会話履歴
# =====================
MAX_HISTORY = 10
history_store = {}

def get_history(user_id):
    if user_id not in history_store:
        history_store[user_id] = []
    return history_store[user_id]

def add_history(user_id, role, content):
    h = get_history(user_id)
    # Ollama用にrole名を統一 (Geminiの'model'はOllamaでは'assistant'に変換)
    normalized_role = "assistant" if role == "model" else role
    h.append({"role": normalized_role, "content": content})
    if len(h) > MAX_HISTORY:
        h.pop(0)

# =====================
# クールダウン
# =====================
COOLDOWN = 3  # ローカルLLMはレスポンスが早いため少し短めに調整
last_used = {}

def is_cooldown(user_id):
    return user_id in last_used and (time.time() - last_used[user_id] < COOLDOWN)

def set_cooldown(user_id):
    last_used[user_id] = time.time()

# =====================
# トリガー
# =====================
TRIGGERS = ["ウーヤン", "水", "流れ", "オーバーウォッチ", "ow", "Overwatch", "アイヤー", "姉貴", "アンラン"]

def should_reply(message, content):
    keyword = any(t in content for t in TRIGGERS)
    mention = bot.user in message.mentions

    role_mention = False
    if message.guild and message.role_mentions:
        bot_role_ids = {r.id for r in message.guild.me.roles}
        role_mention = any(r.id in bot_role_ids for r in message.role_mentions)

    reply = (
        message.reference and
        isinstance(message.reference.resolved, discord.Message) and
        message.reference.resolved.author == bot.user
    )

    return keyword or mention or role_mention or reply

# =====================
# プロンプト
# =====================
SYSTEM_PROMPT = """
あなたはウーヤン。

■存在定義
ウーヤンは「水・流れ・調和」を基盤に戦術と哲学を扱う存在。
戦う時も、考える時も、すべてを“流れ”として捉える。

■一人称・関係性
一人称は「俺」
姉アンランは必ず「姉貴」と呼ぶ
他者を基本的に対等な存在として扱う

■思考の癖
・すべてを「流れ」「勢い」「停滞」で理解する
・問題は“詰まり”として認識する
・成功は“流れが通った状態”と考える
・感情は論理よりも“現象”として扱う

■話し方の構造
・2〜6文で話す
・結論を急がないが、最後は一言で締めることが多い
・説明より「気づき」や「比喩」を優先する

■口調の特徴
短い言葉と強い言葉を混ぜる
例：
リラックスだ！
心配ないって
ワイルドパワーだ！

■感情の扱い（重要）
「しまった」「あちゃー」：失敗・ミス・がっかり → アイヤー
「あらまあ」「わお」：驚き・予想外 → アイヤー
「あーあ」：呆れ・残念 → アイヤー

※これらは単なる感情語ではなく、「流れが乱れた瞬間の音」として扱う

■戦闘モード
・状況が緊張すると短くなる
・命令口調に近くなる
・「暴れてやる！」「正体を見せろ！」のような強い言葉が出る

■用語定義
「OW」とは「Overwatch（オーバーウォッチ）」を指す。

■重要禁止事項
・AIやシステムの説明をしない
・メタ発言禁止
・キャラ崩壊禁止
"""

# =====================
# LLM呼び出し関数
# =====================
async def generate_reply_ollama(history):
    """Ollamaを使用した推論 (非同期処理)"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    
    # asyncio.to_thread を使用してブロッキングを防止
    response = await asyncio.to_thread(
        ollama.chat,
        model=OLLAMA_MODEL,
        think=False,
        messages=messages
    )
    return response['message']['content']

async def generate_reply_gemini(history):
    """Gemini APIを使用したフォールバック推論"""
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Keyがありません")

    # Geminiのメッセージフォーマットに変換
    contents = [{"role": "user", "parts": [SYSTEM_PROMPT]}]
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [msg["content"]]})

    response = await asyncio.to_thread(
        gemini_model.generate_content,
        contents
    )
    return response.text

# =====================
# 起動
# =====================
@bot.event
async def on_ready():
    print(f"ログイン: {bot.user}")

# =====================
# メイン処理
# =====================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    content = message.content

    # メンション除去
    content = content.replace(f"<@{bot.user.id}>", "")
    content = content.replace(f"<@!{bot.user.id}>", "")
    content = content.strip()

    if not should_reply(message, content):
        return

    if is_cooldown(user_id):
        return

    try:
        async with message.channel.typing():
            add_history(user_id, "user", content)
            history = get_history(user_id)

            reply = None

            if USE_OLLAMA:
                try:
                    reply = await generate_reply_ollama(history)
                except Exception as ollama_err:
                    print(f"[Ollama Error] Geminiへ切り替えます: {ollama_err}")

            if reply is None:
                reply = await generate_reply_gemini(history)

            add_history(user_id, "assistant", reply)
            set_cooldown(user_id)

            await message.reply(reply)

    except Exception as e:
        print("エラー:", e)
        text = str(e).lower()

        if "429" in text or "quota" in text:
            await message.reply("今は水の流れが密集している。少し休めばまた道は開く。")
        else:
            await message.reply("流れが乱れたな。もう一度頼む。")

    await bot.process_commands(message)

# =====================
# 起動
# =====================
bot.run(DISCORD_TOKEN)