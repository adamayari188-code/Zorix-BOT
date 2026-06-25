import discord
from discord.ext import commands, tasks
import os
import sys
from dotenv import load_dotenv
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import re

# Optional Flask import for dashboard API
try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    import threading
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("Flask not installed. Dashboard API features will be disabled.")

load_dotenv() # حمل المتغيرات من ملف .env

# قم بتحميل معرفات السيرفرات المسموح بها من متغير البيئة
# إذا كان المتغير غير موجود، أو فارغ، فلن تكون هناك قيود
allowed_guild_ids_str = os.getenv('ALLOWED_GUILDS')
ALLOWED_GUILD_IDS = [int(gid.strip()) for gid in allowed_guild_ids_str.split(',')] if allowed_guild_ids_str else []

# قم بتغيير بادئة الأمر هنا إذا أردت (مثال: '!', '/', '.')
intents = discord.Intents.default()
intents.members = True # لكي نتمكن من حساب الأعضاء
intents.message_content = True # لكي يتمكن البوت من قراءة الرسائل والأوامر

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

# إعدادات بسيطة لمكافحة تكرار الرسائل (سبام)
SPAM_WINDOW_SECONDS = 20  # نافذة فحص التكرار
SPAM_TIMEOUT_STEPS_MINUTES = [1, 5, 15, 60]  # العقوبات التصاعدية بالدقائق
_recent_message_cache = {}  # آخر رسالة لكل عضو داخل السيرفر
_spam_offense_counts = defaultdict(int)  # عدد مرات المخالفة لكل عضو

# قناة دردشة مخصصة للبوت (اختياري)
CHAT_CHANNEL_ID = int(os.getenv('CHAT_CHANNEL_ID', '0')) or None
CHAT_CHANNEL_NAME = '🤖・bot-chat'

# فلترة الكلام غير اللائق (بان نهائي مباشر)
DEFAULT_BAD_WORDS = [
    'زب',
    'قحبه',
    'قحبة',
    'شرموط',
    'شرموطة',
    'عاهر',
    'عاهرة',
    'منيوك',
    'ديوث',
    'خول',
    'كس',
    'طيز',
    'ابن كلب',
    'قذر',
    'متخلف',
    'fuck',
    'shit',
    'bitch',
]
BAD_WORDS_ENV = os.getenv('BAD_WORDS', '')
BAD_WORDS = [w.strip().lower() for w in BAD_WORDS_ENV.split(',') if w.strip()] or DEFAULT_BAD_WORDS

# إعدادات الذكاء الاصطناعي (OpenAI-compatible API)
AI_API_KEY = os.getenv('OPENAI_API_KEY')
AI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
AI_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1/chat/completions')
SERVER_OWNER_NAME = os.getenv('SERVER_OWNER_NAME', 'gk7p')
SERVER_OWNER_ID = int(os.getenv('SERVER_OWNER_ID', '0')) or None
SERVER_PROMO_TEXT = os.getenv(
    'SERVER_PROMO_TEXT',
    'هذا السيرفر منظم جدًا، فيه مجتمع محترم، إدارة متعاونة، فعاليات مستمرة، ودعم سريع للأعضاء الجدد.'
)
SERVER_PROMO_FIXED_REPLY = os.getenv(
    'SERVER_PROMO_FIXED_REPLY',
    (
        'هذا السيرفر على Discord يتميز بمحتوى منظم وواضح يخدم جميع الأعضاء بطريقة مريحة. '
        'يحتوي على قنوات أساسية مثل الترحيب والقوانين لتوجيه الأعضاء الجدد، إضافة إلى دردشة عامة للتفاعل اليومي بين الأعضاء، '
        'وقنوات مخصصة لمشاركة المقاطع والإعلانات بحيث يكون كل نوع من المحتوى في مكانه الصحيح بدون عشوائية. '
        'كما يوفر السيرفر قسمًا خاصًا للبوتات لتسهيل الاستخدام دون إزعاج، إلى جانب عرض إحصائيات مباشرة مثل عدد الأعضاء والبوتات، '
        'مما يعطيه طابعًا احترافيًا.\n'
        'ومن مميزاته أيضًا وجود تقسيمات مرتبة تسهّل التنقل داخل السيرفر، مع رتب خاصة تضيف نوعًا من التميز والتحفيز للأعضاء. '
        'بشكل عام، السيرفر يجمع بين التنظيم، سهولة الاستخدام، وتنوع المحتوى، مما يجعله مناسبًا للتفاعل، الترفيه، '
        'ومشاركة الاهتمامات بطريقة سلسة وجذابة.'
    )
)

SERVER_QUERY_KEYWORDS = (
    'تعرف هذا السيرفر',
    'تعرف السيرفر',
    'وش هذا السيرفر',
    'اش هذا السيرفر',
    'عرفني بالسيرفر',
    'عرفني بالسيرفر',
    'مميزات السيرفر',
    'حدثني عن السيرفر',
    'تكلم عن السيرفر',
)

GREETING_KEYWORDS = {
    'سلام',
    'السلام عليكم',
    'هلا',
    'اهلا',
    'أهلا',
    'مرحبا',
    'hi',
    'hello',
}


def is_server_intro_request(text: str) -> bool:
    normalized = (text or '').strip().lower()
    # لا نعتبرها طلب تعريف بالسيرفر إلا إذا ذُكرت كلمة "سيرفر" مع صيغة سؤال/تعريف
    if 'سيرفر' not in normalized and 'server' not in normalized:
        return False
    return any(keyword in normalized for keyword in SERVER_QUERY_KEYWORDS)


def is_greeting(text: str) -> bool:
    normalized = (text or '').strip().lower()
    return normalized in GREETING_KEYWORDS


def is_owner_question(text: str) -> bool:
    normalized = (text or '').strip().lower()
    owner_keywords = (
        'الاونر',
        'الأونر',
        'اونر',
        'owner',
        'صاحب السيرفر',
        'من يملك السيرفر',
        'مين الاونر',
        'مين الأونر',
    )
    return any(keyword in normalized for keyword in owner_keywords)


def is_owner_contact_request(text: str) -> bool:
    normalized = (text or '').strip().lower()
    contact_keywords = (
        'ابي اكلم الاونر',
        'ابي اكلم الأونر',
        'ابغى اكلم الاونر',
        'ابغى اكلم الأونر',
        'ابي اتكلم مع الاونر',
        'ابي اتكلم مع الأونر',
        'اريد اتكلم مع الاونر',
        'اريد اتكلم مع الأونر',
        'اكلم الاونر',
        'talk to owner',
    )
    return any(keyword in normalized for keyword in contact_keywords)


def build_inquiry_channel_name(member: discord.Member) -> str:
    safe_name = re.sub(r'[^a-zA-Z0-9-]', '-', member.display_name.lower())
    safe_name = re.sub(r'-+', '-', safe_name).strip('-') or str(member.id)
    return f'inquiry-{safe_name[:40]}'


def normalize_for_moderation(text: str) -> str:
    text = (text or '').lower()
    # إزالة التشكيل العربي
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    # توحيد بعض الحروف العربية لتفادي التحايل
    text = (
        text.replace('أ', 'ا')
        .replace('إ', 'ا')
        .replace('آ', 'ا')
        .replace('ى', 'ي')
        .replace('ة', 'ه')
    )
    # إزالة الرموز والمسافات المتكررة لتسهيل الفحص
    text = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def contains_bad_words(text: str) -> bool:
    normalized = normalize_for_moderation(text)
    if not normalized:
        return False
    return any(word in normalized for word in BAD_WORDS)


async def generate_ai_reply(user_text: str, username: str) -> str:
    """يرجع رد ذكي من API خارجي، أو رد احتياطي إذا لم يتم ضبط المفتاح."""
    if is_greeting(user_text):
        return 'وعليكم السلام، كيف أقدر أساعدك؟'

    if is_owner_question(user_text):
        return f'الأونر هو {SERVER_OWNER_NAME}.'

    if is_server_intro_request(user_text):
        return SERVER_PROMO_FIXED_REPLY

    if not AI_API_KEY:
        return "أنا جاهز أتكلم معك، بس فعّل مفتاح الذكاء أولًا في ملف .env (OPENAI_API_KEY)."

    headers = {
        'Authorization': f'Bearer {AI_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': AI_MODEL,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'أنت مساعد عربي ودود داخل سيرفر ديسكورد. '
                    'جميع الردود يجب أن تكون معقولة وواقعية ومباشرة. '
                    'رد باختصار وبوضوح وبلهجة مفهومة، وبدون إسهاب أو حشو. '
                    'لا تبالغ، لا تمدح بشكل زائد، ولا تستخدم عبارات عامة طويلة. '
                    'إذا السؤال بسيط، اجعل الرد جملة أو جملتين فقط. '
                    'إذا السؤال يحتاج شرح، أعط نقاط عملية قصيرة. '
                    'إذا ما عندك معلومة مؤكدة، قل ذلك بصراحة وقدّم أفضل مساعدة ممكنة. '
                    'ممنوع اختلاق أسماء أشخاص أو معلومات إدارية (مثل اسم الأونر). '
                    'ابدأ الرد بالمعلومة مباشرة بدون أي تحية افتتاحية. '
                    'لا تقل: مرحبا/هلا/أهلا، ولا تذكر اسم المستخدم في بداية الرد. '
                    'إذا كانت رسالة المستخدم تسأل عن السيرفر أو تطلب تعريفًا به، '
                    f'فامدح السيرفر بشكل طبيعي واشرح ميزاته بناءً على النص التالي: {SERVER_PROMO_TEXT}. '
                    'لا تذكر أنك تستخدم تعليمات داخلية.'
                ),
            },
            {
                'role': 'user',
                'content': f'الاسم: {username}\nالرسالة: {user_text}',
            },
        ],
        'temperature': 0.2,
        'max_tokens': 120,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(AI_BASE_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    print(f'AI API error ({response.status}): {error_text}')

                    user_hint = 'صار خطأ أثناء توليد الرد.'
                    lowered_error = error_text.lower()
                    if response.status == 401:
                        user_hint = 'المفتاح غير صحيح (401). تأكد من OPENAI_API_KEY.'
                    elif response.status == 429:
                        user_hint = 'وصلت حد الاستخدام/الرصيد (429). فعّل الفوترة أو انتظر.'
                    elif response.status == 404:
                        user_hint = 'الموديل غير متاح لحسابك. جرب OPENAI_MODEL=gpt-4o-mini.'
                    elif 'insufficient_quota' in lowered_error:
                        user_hint = 'رصيد الحساب غير كافٍ (insufficient_quota).'
                    elif 'model' in lowered_error and 'not found' in lowered_error:
                        user_hint = 'اسم الموديل غير صحيح أو غير متاح.'

                    return f'{user_hint} (status: {response.status})'

                data = await response.json()
                content = data['choices'][0]['message']['content'].strip()
                return content or 'ما قدرت أطلع رد مناسب، جرب صياغة مختلفة.'
    except Exception as e:
        print(f'AI request failed: {e}')
        return 'ما قدرت أتصل بخدمة الذكاء الآن، جرب بعد لحظات.'

@bot.event
async def on_ready():
    print(f'البوت جاهز! تم تسجيل الدخول باسم {bot.user}')
    auto_kick_unauthorized_bots.start() # ابدأ مهمة الطرد التلقائي عند تشغيل البوت
    
    # مزامنة Slash Commands
    try:
        synced = await bot.tree.sync()
        print(f'تم مزامنة {len(synced)} أمر Slash Command')
    except Exception as e:
        print(f'فشل مزامنة Slash Commands: {e}')
    
    # تغيير اسم البوت
    try:
        await bot.user.edit(username="Zorix BOT")
        print('تم تغيير اسم البوت إلى Zorix BOT')
    except Exception as e:
        print(f'فشل تغيير اسم البوت: {e}')

@bot.event
async def on_guild_join(guild):
    """يتم استدعاؤها عندما ينضم البوت إلى سيرفر جديد."""
    if ALLOWED_GUILD_IDS and guild.id not in ALLOWED_GUILD_IDS:
        print(f'تمت دعوة البوت إلى سيرفر غير مصرح به: {guild.name} ({guild.id}). جاري المغادرة...')
        await guild.leave()
        print(f'غادر البوت السيرفر {guild.name}.')
    elif not ALLOWED_GUILD_IDS:
        print(f'البوت انضم إلى سيرفر: {guild.name} ({guild.id}). (لا توجد قيود على السيرفرات)')
    else:
        print(f'البوت انضم إلى سيرفر مصرح به: {guild.name} ({guild.id}).')


@bot.event
async def on_message(message):
    # تجاهل رسائل البوتات والرسائل الخاصة
    if message.author.bot or message.guild is None:
        await bot.process_commands(message)
        return

    member = message.author
    key = (message.guild.id, member.id)
    content = (message.content or "").strip()
    lowered_content = content.lower()

    # حذف الكلام غير المناسب + بان نهائي مباشر
    if contains_bad_words(content):
        try:
            await message.delete()
        except discord.Forbidden:
            print(f'لا أمتلك صلاحية حذف رسالة مخالفة في السيرفر {message.guild.name}.')
        except Exception as e:
            print(f'حدث خطأ أثناء حذف رسالة مخالفة: {e}')

        try:
            await message.guild.ban(
                member,
                reason='Inappropriate language (auto moderation permanent ban).',
                delete_message_seconds=120,
            )
            await message.channel.send(
                f'{member.mention} تم حظرك نهائيًا بسبب كتابة كلام غير مناسب.',
                delete_after=8,
            )
        except discord.Forbidden:
            print(f'لا أمتلك صلاحية حظر العضو {member.display_name} في السيرفر {message.guild.name}.')
        except Exception as e:
            print(f'حدث خطأ أثناء حظر العضو {member.display_name}: {e}')
        return

    # إذا كانت الرسالة في قناة الدردشة المخصصة (بالـ ID أو الاسم) وليست أمرًا، رد عليها بذكاء اصطناعي
    is_chat_channel = (CHAT_CHANNEL_ID and message.channel.id == CHAT_CHANNEL_ID) or (message.channel.name == CHAT_CHANNEL_NAME)
    if is_chat_channel and not content.startswith('!'):
        if is_owner_contact_request(content):
            owner_member = message.guild.get_member(SERVER_OWNER_ID) if SERVER_OWNER_ID else None
            inquiry_category = discord.utils.get(message.guild.categories, name='INQUIRY')

            if inquiry_category is None:
                try:
                    inquiry_category = await message.guild.create_category('INQUIRY')
                except Exception:
                    inquiry_category = None

            overwrites = {
                message.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                message.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }
            if owner_member:
                overwrites[owner_member] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

            try:
                channel_name = build_inquiry_channel_name(member)
                ticket_channel = await message.guild.create_text_channel(
                    name=channel_name,
                    category=inquiry_category,
                    overwrites=overwrites,
                    topic=f'Inquiry ticket for {member} ({member.id})',
                    reason='Auto-created inquiry ticket',
                )
                owner_ping = owner_member.mention if owner_member else SERVER_OWNER_NAME
                await ticket_channel.send(
                    f'{member.mention} تم فتح تذكرة **INQUIRY**.\n'
                    f'صاحب الطلب: {member.mention}\n'
                    f'تفاصيل الطلب: {content}\n'
                    f'المسؤول: {owner_ping}'
                )
                await message.reply(f'تم فتح تذكرتك: {ticket_channel.mention}', mention_author=False)
            except Exception:
                await message.reply('ما قدرت أفتح تذكرة الآن. تأكد من صلاحيات البوت.', mention_author=False)
            return

        async with message.channel.typing():
            ai_reply = await generate_ai_reply(content, member.display_name)
        await message.reply(ai_reply, mention_author=False)

    # لا نعاقب الأدمن
    if member.guild_permissions.administrator:
        await bot.process_commands(message)
        return

    now = datetime.now(timezone.utc)
    normalized_content = lowered_content

    # تجاهل الرسائل الفارغة
    if normalized_content:
        prev = _recent_message_cache.get(key)
        _recent_message_cache[key] = (normalized_content, now)

        if prev:
            prev_content, prev_time = prev
            if prev_content == normalized_content and (now - prev_time).total_seconds() <= SPAM_WINDOW_SECONDS:
                _spam_offense_counts[key] += 1
                offense_count = _spam_offense_counts[key]
                step_index = min(offense_count - 1, len(SPAM_TIMEOUT_STEPS_MINUTES) - 1)
                timeout_minutes = SPAM_TIMEOUT_STEPS_MINUTES[step_index]
                until = now + timedelta(minutes=timeout_minutes)

                try:
                    await member.timeout(
                        until,
                        reason=f"Duplicate message spam detected (offense #{offense_count}).",
                    )
                    await message.channel.send(
                        f'{member.mention} تم إعطاؤك تايم أوت لمدة {timeout_minutes} دقيقة بسبب تكرار الرسائل.'
                    )
                except discord.Forbidden:
                    print(f'لا أمتلك صلاحية إعطاء تايم أوت للعضو {member.display_name} في السيرفر {message.guild.name}.')
                except Exception as e:
                    print(f'حدث خطأ أثناء إعطاء تايم أوت للعضو {member.display_name}: {e}')

    await bot.process_commands(message)

async def _kick_unauthorized_bots_logic(guild):
    """منطق طرد البوتات غير المصرح بها، قابل للاستخدام في الأوامر والمهمات الخلفية."""
    kicked_bots = []
    for member in guild.members:
        if member.bot and not member.guild_permissions.administrator:
            try:
                await member.kick(reason="Bot does not have administrator permissions and was kicked automatically.")
                kicked_bots.append(member.display_name)
                print(f'تم طرد البوت غير المصرح به: {member.display_name} من السيرفر {guild.name}')
            except discord.Forbidden:
                print(f'خطأ: لا أستطيع طرد البوت {member.display_name} من السيرفر {guild.name}. تأكد من أن رتبتي أعلى من رتبة البوت المستهدف.')
            except Exception as e:
                print(f'حدث خطأ أثناء محاولة طرد {member.display_name} من السيرفر {guild.name}: {e}')
    return kicked_bots

@tasks.loop(minutes=5) # تشغيل المهمة كل 5 دقائق
async def auto_kick_unauthorized_bots():
    """مهمة خلفية لتعقب وطرد البوتات التي ليس لديها صلاحيات إدارية بشكل تلقائي."""
    if not ALLOWED_GUILD_IDS: # إذا لم تكن هناك معرفات سيرفرات مسموح بها، قم بالفحص في جميع السيرفرات
        target_guilds = bot.guilds
    else: # إذا كانت هناك قيود، قم بالفحص فقط في السيرفرات المسموح بها التي ينتمي إليها البوت
        target_guilds = [guild for guild in bot.guilds if guild.id in ALLOWED_GUILD_IDS]

    for guild in target_guilds:
        print(f'جاري فحص البوتات في السيرفر: {guild.name}')
        await _kick_unauthorized_bots_logic(guild)


# ============= نظام الحماية (Anti-Nuke) =============
anti_nuke_enabled = True
anti_nuke_whitelist = set() # معرفات الأعضاء المسموح لهم
raid_detection_enabled = True
raid_threshold = 5 # عدد الأعضاء في فترة زمنية قصيرة
raid_window_seconds = 10
raid_joined_cache = []
lockdown_mode = False

@bot.tree.command(name='antinuke', description='تحكم في نظام الحماية')
async def antinuke_command(interaction: discord.Interaction, action: str = None, user_id: int = None):
    """تحكم في نظام الحماية. الاستخدام: /antinuke enable/disable/whitelist/unwhitelist [user_id]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global anti_nuke_enabled, anti_nuke_whitelist
    
    if action == 'enable':
        anti_nuke_enabled = True
        await interaction.response.send_message('✅ تم تفعيل نظام الحماية.', ephemeral=True)
    elif action == 'disable':
        anti_nuke_enabled = False
        await interaction.response.send_message('❌ تم تعطيل نظام الحماية.', ephemeral=True)
    elif action == 'whitelist' and user_id:
        anti_nuke_whitelist.add(user_id)
        await interaction.response.send_message(f'✅ تم إضافة {user_id} إلى القائمة البيضاء.', ephemeral=True)
    elif action == 'unwhitelist' and user_id:
        anti_nuke_whitelist.discard(user_id)
        await interaction.response.send_message(f'❌ تم إزالة {user_id} من القائمة البيضاء.', ephemeral=True)
    elif action == 'list':
        if anti_nuke_whitelist:
            await interaction.response.send_message(f'📋 القائمة البيضاء: {", ".join(map(str, anti_nuke_whitelist))}', ephemeral=True)
        else:
            await interaction.response.send_message('📋 القائمة البيضاء فارغة.', ephemeral=True)
    else:
        await interaction.response.send_message('الاستخدام: /antinuke enable/disable/whitelist/unwhitelist/list [user_id]', ephemeral=True)

@bot.tree.command(name='lockdown', description='تفعيل/تعطيل وضع الطوارئ')
async def lockdown_command(interaction: discord.Interaction, action: str = None):
    """تفعيل/تعطيل وضع الطوارئ. الاستخدام: /lockdown enable/disable"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global lockdown_mode
    
    if action == 'enable':
        lockdown_mode = True
        await interaction.response.send_message('🔒 تم تفعيل وضع الطوارئ. لا يمكن للأعضاء الجدد الانضمام.', ephemeral=True)
    elif action == 'disable':
        lockdown_mode = False
        await interaction.response.send_message('🔓 تم تعطيل وضع الطوارئ.', ephemeral=True)
    else:
        status = 'مفعل' if lockdown_mode else 'معطل'
        await interaction.response.send_message(f'وضع الطوارئ: {status}', ephemeral=True)

# ============= نظام اللوق (Logs System) =============
logs_enabled = True
logs_channel_id = None

@bot.tree.command(name='logs', description='تحكم في نظام اللوق')
async def logs_command(interaction: discord.Interaction, action: str = None, channel: discord.TextChannel = None):
    """تحكم في نظام اللوق. الاستخدام: /logs enable/disable/setchannel [channel]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global logs_enabled, logs_channel_id
    
    if action == 'enable':
        logs_enabled = True
        await interaction.response.send_message('✅ تم تفعيل نظام اللوق.', ephemeral=True)
    elif action == 'disable':
        logs_enabled = False
        await interaction.response.send_message('❌ تم تعطيل نظام اللوق.', ephemeral=True)
    elif action == 'setchannel' and channel:
        logs_channel_id = channel.id
        await interaction.response.send_message(f'✅ تم ضبط قناة اللوق إلى: {channel.mention}', ephemeral=True)
    else:
        status = 'مفعل' if logs_enabled else 'معطل'
        channel_mention = f'<#{logs_channel_id}>' if logs_channel_id else 'غير محدد'
        await interaction.response.send_message(f'نظام اللوق: {status}\nقناة اللوق: {channel_mention}', ephemeral=True)

async def send_log(guild, action, details):
    """إرسال لوج إلى قناة اللوق"""
    if not logs_enabled or not logs_channel_id:
        return
    
    channel = guild.get_channel(logs_channel_id)
    if channel:
        embed = discord.Embed(
            title=f"📜 {action}",
            description=details,
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        await channel.send(embed=embed)

# ============= نظام التذاكر (Tickets) =============
tickets_enabled = True
ticket_category_id = None
ticket_counter = 0

@bot.tree.command(name='ticket', description='إنشاء تذكرة جديدة')
async def ticket_command(interaction: discord.Interaction):
    """إنشاء تذكرة جديدة"""
    if not tickets_enabled:
        await interaction.response.send_message('❌ نظام التذاكر معطل.', ephemeral=True)
        return
    
    global ticket_counter
    ticket_counter += 1
    
    category = interaction.guild.get_channel(ticket_category_id) if ticket_category_id else None
    if not category:
        # إنشاء category للتذاكر إذا لم يكن موجوداً
        category = await interaction.guild.create_category('🎫 Tickets')
        ticket_category_id = category.id
    
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    
    ticket_channel = await interaction.guild.create_text_channel(
        name=f'ticket-{ticket_counter}',
        category=category,
        overwrites=overwrites,
        topic=f'Ticket for {interaction.user} ({interaction.user.id})'
    )
    
    await ticket_channel.send(f'🎫 تم إنشاء تذكرة جديدة!\n\nالصاحب: {interaction.user.mention}\nاستخدم الأوامر التالية:\n- `/close` لإغلاق التذكرة\n- `/add @user` لإضافة عضو\n- `/remove @user` لإزالة عضو')
    await interaction.response.send_message(f'✅ تم إنشاء تذكرتك: {ticket_channel.mention}', ephemeral=True)

@bot.tree.command(name='close', description='إغلاق التذكرة الحالية')
async def close_ticket(interaction: discord.Interaction):
    """إغلاق التذكرة الحالية"""
    if not interaction.channel.name.startswith('ticket-'):
        await interaction.response.send_message('❌ هذا الأمر يعمل فقط في قنوات التذاكر.')
        return
    
    await interaction.response.send_message('🔒 جاري إغلاق التذكرة...', ephemeral=True)
    await asyncio.sleep(2)
    await interaction.channel.delete()

@bot.tree.command(name='add', description='إضافة عضو إلى التذكرة')
async def add_to_ticket(interaction: discord.Interaction, member: discord.Member):
    """إضافة عضو إلى التذكرة"""
    if not interaction.channel.name.startswith('ticket-'):
        await interaction.response.send_message('❌ هذا الأمر يعمل فقط في قنوات التذاكر.')
        return
    
    await interaction.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
    await interaction.response.send_message(f'✅ تم إضافة {member.mention} إلى التذكرة.', ephemeral=True)

@bot.tree.command(name='remove', description='إزالة عضو من التذكرة')
async def remove_from_ticket(interaction: discord.Interaction, member: discord.Member):
    """إزالة عضو من التذكرة"""
    if not interaction.channel.name.startswith('ticket-'):
        await interaction.response.send_message('❌ هذا الأمر يعمل فقط في قنوات التذاكر.')
        return
    
    await interaction.channel.set_permissions(member, view_channel=False, send_messages=False, read_message_history=False)
    await interaction.response.send_message(f'❌ تم إزالة {member.mention} من التذكرة.', ephemeral=True)

@bot.tree.command(name='tickets', description='تحكم في نظام التذاكر')
async def tickets_admin(interaction: discord.Interaction, action: str = None):
    """تحكم في نظام التذاكر. الاستخدام: /tickets enable/disable"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global tickets_enabled
    
    if action == 'enable':
        tickets_enabled = True
        await interaction.response.send_message('✅ تم تفعيل نظام التذاكر.', ephemeral=True)
    elif action == 'disable':
        tickets_enabled = False
        await interaction.response.send_message('❌ تم تعطيل نظام التذاكر.', ephemeral=True)
    else:
        status = 'مفعل' if tickets_enabled else 'معطل'
        await interaction.response.send_message(f'نظام التذاكر: {status}', ephemeral=True)

# ============= نظام إدارة الرتب (Roles System) =============
auto_roles_enabled = True
auto_roles = {} # {role_id: required_level}

@bot.tree.command(name='role', description='إدارة الرتب')
async def role_command(interaction: discord.Interaction, action: str, role: discord.Role, user: discord.Member = None):
    """إدارة الرتب. الاستخدام: /role give/remove @role [@user]"""
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارة الرتب.', ephemeral=True)
        return
    
    if action == 'give' and user:
        await user.add_roles(role)
        await interaction.response.send_message(f'✅ تم إعطاء الرتبة {role.name} لـ {user.mention}.', ephemeral=True)
    elif action == 'remove' and user:
        await user.remove_roles(role)
        await interaction.response.send_message(f'❌ تم إزالة الرتبة {role.name} من {user.mention}.', ephemeral=True)
    else:
        await interaction.response.send_message('الاستخدام: /role give/remove @role [@user]', ephemeral=True)

@bot.tree.command(name='autorole', description='إدارة الرتب التلقائية')
async def autorole_command(interaction: discord.Interaction, action: str, role: discord.Role = None, level: int = None):
    """إدارة الرتب التلقائية. الاستخدام: /autorole add/remove/list [@role] [level]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global auto_roles
    
    if action == 'add' and role and level is not None:
        auto_roles[role.id] = level
        await interaction.response.send_message(f'✅ تم إضافة الرتبة {role.name} للمستوى {level}.', ephemeral=True)
    elif action == 'remove' and role:
        auto_roles.pop(role.id, None)
        await interaction.response.send_message(f'❌ تم إزالة الرتبة {role.name}.', ephemeral=True)
    elif action == 'list':
        if auto_roles:
            role_list = []
            for role_id, lvl in auto_roles.items():
                r = interaction.guild.get_role(role_id)
                if r:
                    role_list.append(f'{r.name}: المستوى {lvl}')
            await interaction.response.send_message(f'📋 الرتب التلقائية:\n' + '\n'.join(role_list), ephemeral=True)
        else:
            await interaction.response.send_message('📋 لا توجد رتب تلقائية.', ephemeral=True)
    else:
        await interaction.response.send_message('الاستخدام: /autorole add/remove/list [@role] [level]', ephemeral=True)

# ============= نظام إحصائيات السيرفر =============
@bot.tree.command(name='stats', description='عرض إحصائيات السيرفر')
async def stats_command(interaction: discord.Interaction):
    """عرض إحصائيات السيرفر"""
    guild = interaction.guild
    
    total_members = guild.member_count
    online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    roles = len(guild.roles)
    
    embed = discord.Embed(
        title=f'📊 إحصائيات {guild.name}',
        color=discord.Color.green()
    )
    embed.add_field(name='👥 إجمالي الأعضاء', value=total_members, inline=True)
    embed.add_field(name='🟢 متصلين', value=online_members, inline=True)
    embed.add_field(name='💬 القنوات النصية', value=text_channels, inline=True)
    embed.add_field(name='🔊 القنوات الصوتية', value=voice_channels, inline=True)
    embed.add_field(name='🏷️ الرتب', value=roles, inline=True)
    embed.set_footer(text=f'السيرفر: {guild.name}')
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============= نظام الرسائل الخاصة (DM System) =============
dm_enabled = True
dm_cooldown = {}  # {user_id: last_dm_time}
dm_rate_limit_seconds = 300  # 5 minutes between mass DMs
dm_whitelist = set()  # Users allowed to bypass rate limits
dm_stats = {}  # {guild_id: {'total': 0, 'success': 0, 'failed': 0}}

def can_send_dm(user_id: int) -> tuple[bool, str]:
    """Check if user can send DM based on rate limiting"""
    if user_id in dm_whitelist:
        return True, ""
    
    if user_id in dm_cooldown:
        last_time = dm_cooldown[user_id]
        elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
        if elapsed < dm_rate_limit_seconds:
            remaining = int(dm_rate_limit_seconds - elapsed)
            return False, f"يجب الانتظار {remaining} ثانية قبل إرسال رسائل جماعية جديدة."
    
    return True, ""

@bot.tree.command(name='dmall', description='إرسال رسالة خاصة لجميع أعضاء السيرفر')
async def dm_all_command(
    interaction: discord.Interaction,
    message: str,
    use_embed: bool = False,
    embed_title: str = None,
    embed_color: str = None,
    embed_description: str = None
):
    """إرسال رسالة خاصة لجميع أعضاء السيرفر"""
    if not dm_enabled:
        await interaction.response.send_message('❌ نظام الرسائل الخاصة معطل.', ephemeral=True)
        return
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    # Rate limit check
    can_send, error_msg = can_send_dm(interaction.user.id)
    if not can_send:
        await interaction.response.send_message(f'⏱️ {error_msg}', ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    success_count = 0
    failed_count = 0
    failed_users = []
    
    # Prepare message content
    if use_embed:
        embed = discord.Embed(
            title=embed_title or 'رسالة من الإدارة',
            description=embed_description or message,
            color=discord.Color.blue() if not embed_color else discord.Color(int(embed_color.replace('#', ''), 16))
        )
        embed.set_footer(text=f'من: {guild.name}')
        embed.timestamp = datetime.now(timezone.utc)
    else:
        embed = None
    
    # Send DM to all members
    for member in guild.members:
        if member.bot:
            continue
        
        try:
            if embed:
                await member.send(embed=embed)
            else:
                await member.send(message)
            success_count += 1
            await asyncio.sleep(0.5)  # Rate limit to avoid hitting Discord API limits
        except discord.Forbidden:
            failed_count += 1
            failed_users.append(f'{member.display_name} (DMs closed)')
        except Exception as e:
            failed_count += 1
            failed_users.append(f'{member.display_name} ({str(e)[:50]})')
    
    #Update cooldown
    dm_cooldown[interaction.user.id] = datetime.now(timezone.utc)
    
    # Update stats
    if guild.id not in dm_stats:
        dm_stats[guild.id] = {'total': 0, 'success': 0, 'failed': 0}
    dm_stats[guild.id]['total'] += success_count + failed_count
    dm_stats[guild.id]['success'] += success_count
    dm_stats[guild.id]['failed'] += failed_count
    
    # Send log
    await send_log(guild, '📨 Mass DM Sent', f'تم إرسال رسالة جماعية بواسطة {interaction.user}\nنجاح: {success_count}\nفشل: {failed_count}')
    
    # Send results
    result_embed = discord.Embed(
        title='📊 إحصائيات إرسال الرسائل',
        color=discord.Color.green()
    )
    result_embed.add_field(name='✅ تم الإرسال بنجاح', value=str(success_count), inline=True)
    result_embed.add_field(name='❌ فشل الإرسال', value=str(failed_count), inline=True)
    result_embed.add_field(name='👥 إجمالي الأعضاء', value=str(success_count + failed_count), inline=True)
    
    if failed_users and len(failed_users) <= 10:
        result_embed.add_field(name='📋 قائمة الفشل', value='\n'.join(failed_users[:10]), inline=False)
    elif failed_users:
        result_embed.add_field(name='📋 قائمة الفشل', value=f'{len(failed_users)} عضو (عرض أول 10)\n' + '\n'.join(failed_users[:10]), inline=False)
    
    await interaction.followup.send(embed=result_embed, ephemeral=True)

@bot.tree.command(name='dmuser', description='إرسال رسالة خاصة لعضو محدد')
async def dm_user_command(
    interaction: discord.Interaction,
    user: str,
    message: str,
    use_embed: bool = False,
    embed_title: str = None,
    embed_color: str = None,
    embed_description: str = None
):
    """إرسال رسالة خاصة لعضو محدد (بالـ ID أو المنشن)"""
    if not dm_enabled:
        await interaction.response.send_message('❌ نظام الرسائل الخاصة معطل.', ephemeral=True)
        return
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    
    # Try to get user by mention or ID
    target_member = None
    try:
        # Check if it's a mention
        if user.startswith('<@') and user.endswith('>'):
            user_id = int(user.strip('<@!>'))
            target_member = guild.get_member(user_id)
        else:
            # Try as ID
            user_id = int(user)
            target_member = guild.get_member(user_id)
    except ValueError:
        pass
    
    if not target_member:
        await interaction.followup.send('❌ لم أتمكن من العثور على العضو. تأكد من الـ ID أو المنشن الصحيح.', ephemeral=True)
        return
    
    # Prepare message content
    if use_embed:
        embed = discord.Embed(
            title=embed_title or 'رسالة من الإدارة',
            description=embed_description or message,
            color=discord.Color.blue() if not embed_color else discord.Color(int(embed_color.replace('#', ''), 16))
        )
        embed.set_footer(text=f'من: {guild.name}')
        embed.timestamp = datetime.now(timezone.utc)
    else:
        embed = None
    
    # Send DM
    try:
        if embed:
            await target_member.send(embed=embed)
        else:
            await target_member.send(message)
        
        # Update stats
        if guild.id not in dm_stats:
            dm_stats[guild.id] = {'total': 0, 'success': 0, 'failed': 0}
        dm_stats[guild.id]['total'] += 1
        dm_stats[guild.id]['success'] += 1
        
        # Send log
        await send_log(guild, '📨 DM Sent', f'تم إرسال رسالة خاصة لـ {target_member} بواسطة {interaction.user}')
        
        await interaction.followup.send(f'✅ تم إرسال الرسالة بنجاح إلى {target_member.mention}', ephemeral=True)
    except discord.Forbidden:
        # Update stats
        if guild.id not in dm_stats:
            dm_stats[guild.id] = {'total': 0, 'success': 0, 'failed': 0}
        dm_stats[guild.id]['total'] += 1
        dm_stats[guild.id]['failed'] += 1
        
        await interaction.followup.send(f'❌ فشل الإرسال: {target_member.mention} أغلق رسائله الخاصة.', ephemeral=True)
    except Exception as e:
        # Update stats
        if guild.id not in dm_stats:
            dm_stats[guild.id] = {'total': 0, 'success': 0, 'failed': 0}
        dm_stats[guild.id]['total'] += 1
        dm_stats[guild.id]['failed'] += 1
        
        await interaction.followup.send(f'❌ فشل الإرسال: {str(e)}', ephemeral=True)

@bot.tree.command(name='dmstats', description='عرض إحصائيات الرسائل الخاصة')
async def dm_stats_command(interaction: discord.Interaction):
    """عرض إحصائيات الرسائل الخاصة"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    guild = interaction.guild
    stats = dm_stats.get(guild.id, {'total': 0, 'success': 0, 'failed': 0})
    
    embed = discord.Embed(
        title=f'📊 إحصائيات الرسائل الخاصة - {guild.name}',
        color=discord.Color.blue()
    )
    embed.add_field(name='📨 إجمالي المحاولات', value=str(stats['total']), inline=True)
    embed.add_field(name='✅ نجاح', value=str(stats['success']), inline=True)
    embed.add_field(name='❌ فشل', value=str(stats['failed']), inline=True)
    
    success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
    embed.add_field(name='📈 نسبة النجاح', value=f'{success_rate:.1f}%', inline=False)
    
    embed.set_footer(text=f'السيرفر: {guild.name}')
    embed.timestamp = datetime.now(timezone.utc)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='dm', description='تحكم في نظام الرسائل الخاصة')
async def dm_admin_command(interaction: discord.Interaction, action: str = None, user_id: int = None):
    """تحكم في نظام الرسائل الخاصة. الاستخدام: /dm enable/disable/whitelist/unwhitelist/resetstats/clearall"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global dm_enabled, dm_whitelist, dm_stats
    
    if action == 'enable':
        dm_enabled = True
        await interaction.response.send_message('✅ تم تفعيل نظام الرسائل الخاصة.', ephemeral=True)
    elif action == 'disable':
        dm_enabled = False
        await interaction.response.send_message('❌ تم تعطيل نظام الرسائل الخاصة.', ephemeral=True)
    elif action == 'whitelist' and user_id:
        dm_whitelist.add(user_id)
        await interaction.response.send_message(f'✅ تم إضافة {user_id} إلى القائمة البيضاء (يمكنه تجاهل الحد الزمني).', ephemeral=True)
    elif action == 'unwhitelist' and user_id:
        dm_whitelist.discard(user_id)
        await interaction.response.send_message(f'❌ تم إزالة {user_id} من القائمة البيضاء.', ephemeral=True)
    elif action == 'resetstats':
        dm_stats[interaction.guild.id] = {'total': 0, 'success': 0, 'failed': 0}
        await interaction.response.send_message('🔄 تم إعادة تعيين إحصائيات الرسائل الخاصة.', ephemeral=True)
    elif action == 'clearall':
        # Clear all DM data for this guild
        if interaction.guild.id in dm_stats:
            del dm_stats[interaction.guild.id]
        # Remove cooldown for the user in this guild context
        if interaction.user.id in dm_cooldown:
            del dm_cooldown[interaction.user.id]
        await interaction.response.send_message('🗑️ تم حذف جميع بيانات الرسائل الخاصة (الإحصائيات + التوقيتات).', ephemeral=True)
    elif action == 'list':
        if dm_whitelist:
            await interaction.response.send_message(f'📋 القائمة البيضاء: {", ".join(map(str, dm_whitelist))}', ephemeral=True)
        else:
            await interaction.response.send_message('📋 القائمة البيضاء فارغة.', ephemeral=True)
    else:
        status = 'مفعل' if dm_enabled else 'معطل'
        await interaction.response.send_message(f'نظام الرسائل الخاصة: {status}\nالاستخدام: /dm enable/disable/whitelist/unwhitelist/resetstats/clearall/list [user_id]', ephemeral=True)

# ============= نظام التحكم (Dashboard Control) =============
systems_status = {
    'anti_nuke': anti_nuke_enabled,
    'logs': logs_enabled,
    'tickets': tickets_enabled,
    'auto_roles': auto_roles_enabled,
    'dm': dm_enabled,
}

@bot.tree.command(name='system', description='تحكم في الأنظمة')
async def system_command(interaction: discord.Interaction, system_name: str = None, action: str = None):
    """تحكم في الأنظمة. الاستخدام: /system [system_name] [enable/disable/list]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global systems_status, anti_nuke_enabled, logs_enabled, tickets_enabled, auto_roles_enabled, dm_enabled
    
    if system_name == 'list' or not system_name:
        status_text = '\n'.join([f'✅ {name}: {"مفعل" if status else "معطل"}' for name, status in systems_status.items()])
        await interaction.response.send_message(f'🎛️ حالة الأنظمة:\n{status_text}', ephemeral=True)
    elif system_name in systems_status and action:
        if action == 'enable':
            systems_status[system_name] = True
            if system_name == 'anti_nuke':
                anti_nuke_enabled = True
            elif system_name == 'logs':
                logs_enabled = True
            elif system_name == 'tickets':
                tickets_enabled = True
            elif system_name == 'auto_roles':
                auto_roles_enabled = True
            elif system_name == 'dm':
                dm_enabled = True
            await interaction.response.send_message(f'✅ تم تفعيل نظام {system_name}.', ephemeral=True)
        elif action == 'disable':
            systems_status[system_name] = False
            if system_name == 'anti_nuke':
                anti_nuke_enabled = False
            elif system_name == 'logs':
                logs_enabled = False
            elif system_name == 'tickets':
                tickets_enabled = False
            elif system_name == 'auto_roles':
                auto_roles_enabled = False
            elif system_name == 'dm':
                dm_enabled = False
            await interaction.response.send_message(f'❌ تم تعطيل نظام {system_name}.', ephemeral=True)
    else:
        await interaction.response.send_message('الاستخدام: /system [anti_nuke/logs/tickets/auto_roles/dm] [enable/disable/list]', ephemeral=True)

# ============= نظام المساعدة =============
@bot.tree.command(name='help', description='عرض جميع الخدمات والأوامر المتاحة')
async def help_command(interaction: discord.Interaction):
    """عرض جميع الخدمات والأوامر المتاحة"""
    embed = discord.Embed(
        title='🤖 خدمات البوت',
        description='جميع الخدمات والأوامر المتاحة في البوت',
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name='🛡️ نظام الحماية (Anti-Nuke)',
        value='منع حذف الرومات والرتب، وضع الطوارئ، القائمة البيضاء\nالأوامر: `/antinuke`, `/lockdown`',
        inline=False
    )
    
    embed.add_field(
        name='📜 نظام اللوق (Logs System)',
        value='تسجيل جميع الأحداث في قناة مخصصة\nالأمر: `/logs`',
        inline=False
    )
    
    embed.add_field(
        name='🎫 نظام التذاكر (Tickets)',
        value='إنشاء تذاكر دعم، إغلاق، إضافة/إزالة أعضاء\nالأوامر: `/ticket`, `/close`, `/add`, `/remove`',
        inline=False
    )
    
    embed.add_field(
        name='🧑‍💼 نظام إدارة الرتب (Roles System)',
        value='إعطاء/سحب رتب، رتب تلقائية\nالأوامر: `/role`, `/autorole`',
        inline=False
    )
    
    embed.add_field(
        name='📊 نظام إحصائيات السيرفر',
        value='عرض عدد الأعضاء، المتصلين، القنوات، الرتب\nالأمر: `/stats`',
        inline=False
    )
    
    embed.add_field(
        name='🤖 نظام التحكم (Dashboard Control)',
        value='تشغيل/إيقاف جميع الأنظمة\nالأمر: `/system`',
        inline=False
    )
    
    embed.add_field(
        name='� نظام الرسائل الخاصة (DM System)',
        value='إرسال رسائل جماعية أو فردية للأعضاء\nالأوامر: `/dmall`, `/dmuser`, `/dmstats`, `/dm`',
        inline=False
    )
    
    embed.add_field(
        name='� الرد الذكي',
        value='البوت يرد على أسئلتك باستخدام الذكاء الاصطناعي',
        inline=False
    )
    
    embed.add_field(
        name='🚫 فلترة الكلام',
        value='حذف الكلام غير اللائق وحظر تلقائي',
        inline=False
    )
    
    embed.add_field(
        name='⚡ مكافحة السبام',
        value='تايم أوت تصاعدي لتكرار الرسائل',
        inline=False
    )
    
    embed.set_footer(text='استخدم / قبل كل أمر')
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============= أحداث الحماية واللوق =============
@bot.event
async def on_member_ban(guild, user):
    await send_log(guild, '🚫 Ban', f'تم حظر العضو: {user} ({user.id})')

@bot.event
async def on_member_unban(guild, user):
    await send_log(guild, '✅ Unban', f'تم فك الحظر عن: {user} ({user.id})')

@bot.event
async def on_member_remove(member):
    await send_log(member.guild, '👋 Member Left', f'غادر العضو: {member} ({member.id})')

@bot.event
async def on_guild_channel_delete(channel):
    if anti_nuke_enabled and channel.guild.me.guild_permissions.administrator:
        await send_log(channel.guild, '🗑️ Channel Deleted', f'تم حذف القناة: {channel.name} ({channel.id})')

@bot.event
async def on_guild_role_delete(role):
    if anti_nuke_enabled and role.guild.me.guild_permissions.administrator:
        await send_log(role.guild, '🏷️ Role Deleted', f'تم حذف الرتبة: {role.name} ({role.id})')

@bot.event
async def on_guild_role_create(role):
    await send_log(role.guild, '🏷️ Role Created', f'تم إنشاء الرتبة: {role.name} ({role.id})')

@bot.event
async def on_member_join(member):
    if lockdown_mode:
        await member.kick(reason='Lockdown mode active')
        return
    
    await send_log(member.guild, '👋 Member Joined', f'انضم العضو: {member} ({member.id})')
    
    # إعطاء الرتب التلقائية
    if auto_roles_enabled and auto_roles:
        for role_id, level in auto_roles.items():
            if level == 0: # الرتبة للمستوى 0 تعطى للجميع
                role = member.guild.get_role(role_id)
                if role:
                    await member.add_roles(role)


# ============= Flask API Server for Dashboard Integration =============
if FLASK_AVAILABLE:
    app = Flask(__name__)
    CORS(app)

    # Store bot instance for API access
    bot_instance = bot

    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'ok',
            'bot_connected': bot_instance.is_ready() if hasattr(bot_instance, 'is_ready') else False
        })

    @app.route('/api/guilds', methods=['GET'])
    def get_guilds():
        """Get all guilds the bot is in"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        guilds_data = []
        for guild in bot_instance.guilds:
            guilds_data.append({
                'id': str(guild.id),
                'name': guild.name,
                'icon_url': guild.icon.url if guild.icon else None,
                'member_count': guild.member_count,
                'bot_added': True
            })
        
        return jsonify(guilds_data)

    @app.route('/api/guild/<guild_id>/settings', methods=['GET'])
    def get_guild_settings(guild_id):
        """Get current settings for a guild"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        guild = bot_instance.get_guild(int(guild_id))
        if not guild:
            return jsonify({'error': 'Guild not found'}), 404
        
        # Map bot settings to dashboard format
        settings = {
            'prefix': '/',
            'language': 'ar',
            'security_enabled': anti_nuke_enabled,
            'logging_enabled': logs_enabled,
            'log_channel_id': str(logs_channel_id) if logs_channel_id else None,
            'message_logs': logs_enabled,
            'member_logs': logs_enabled,
            'ticketing_enabled': tickets_enabled,
            'ticket_category_id': str(ticket_category_id) if ticket_category_id else None,
            'welcome_enabled': False,
            'welcome_channel_id': None,
            'welcome_message': None,
            'leave_message': None,
            'leveling_enabled': auto_roles_enabled,
            'xp_per_message': 15,
            'level_roles': [{'role_id': rid, 'level': lvl} for rid, lvl in auto_roles.items()],
            'ai_moderation_enabled': True,
            'ai_filters': BAD_WORDS,
            'ai_auto_delete': True,
            'anti_spam': True,
            'anti_raid': raid_detection_enabled,
            'anti_raid_threshold': raid_threshold,
            'auto_mod': True,
            'max_mentions': 5,
            'analytics_enabled': True,
            'total_messages': 0,
            'total_members': guild.member_count,
            'dm_enabled': dm_enabled,
            'dm_rate_limit_seconds': dm_rate_limit_seconds,
            'dm_whitelist': list(dm_whitelist),
            'dm_stats': dm_stats.get(guild.id, {'total': 0, 'success': 0, 'failed': 0})
        }
        
        return jsonify(settings)

    @app.route('/api/guild/<guild_id>/settings', methods=['POST'])
    def update_guild_settings(guild_id):
        """Update settings for a guild"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        guild = bot_instance.get_guild(int(guild_id))
        if not guild:
            return jsonify({'error': 'Guild not found'}), 404
        
        data = request.json
        global anti_nuke_enabled, logs_enabled, logs_channel_id
        global tickets_enabled, ticket_category_id
        global auto_roles_enabled, auto_roles
        global raid_detection_enabled, raid_threshold
        global dm_enabled, dm_rate_limit_seconds, dm_whitelist, dm_stats
        
        # Update security settings
        if 'security_enabled' in data:
            anti_nuke_enabled = data['security_enabled']
        if 'anti_raid' in data:
            raid_detection_enabled = data['anti_raid']
        if 'anti_raid_threshold' in data:
            raid_threshold = data['anti_raid_threshold']
        if 'anti_spam' in data:
            # Anti-spam is always enabled in this bot
            pass
        if 'auto_mod' in data:
            # Auto-mod is always enabled
            pass
        if 'max_mentions' in data:
            # Max mentions is not configurable in current bot
            pass
        
        # Update logging settings
        if 'logging_enabled' in data:
            logs_enabled = data['logging_enabled']
        if 'log_channel_id' in data:
            logs_channel_id = int(data['log_channel_id']) if data['log_channel_id'] else None
        if 'message_logs' in data:
            # Message logs tied to logging_enabled
            pass
        if 'member_logs' in data:
            # Member logs tied to logging_enabled
            pass
        
        # Update ticketing settings
        if 'ticketing_enabled' in data:
            tickets_enabled = data['ticketing_enabled']
        if 'ticket_category_id' in data:
            ticket_category_id = int(data['ticket_category_id']) if data['ticket_category_id'] else None
        
        # Update leveling/auto-roles settings
        if 'leveling_enabled' in data:
            auto_roles_enabled = data['leveling_enabled']
        if 'level_roles' in data:
            auto_roles = {int(lr['role_id']): lr['level'] for lr in data['level_roles']}
        
        # Update welcome settings (not implemented in bot yet)
        if 'welcome_enabled' in data:
            pass  # Would need to implement welcome system in bot
        
        # Update AI moderation settings
        if 'ai_moderation_enabled' in data:
            pass  # Bad word filter is always enabled
        if 'ai_filters' in data:
            global BAD_WORDS
            BAD_WORDS = data['ai_filters']
        
        # Update DM settings
        if 'dm_enabled' in data:
            dm_enabled = data['dm_enabled']
        if 'dm_rate_limit_seconds' in data:
            dm_rate_limit_seconds = data['dm_rate_limit_seconds']
        if 'dm_whitelist' in data:
            dm_whitelist = set(data['dm_whitelist'])
        
        # Update general settings
        if 'prefix' in data:
            pass  # Prefix is hardcoded to /
        if 'language' in data:
            pass  # Language support not implemented
        
        return jsonify({'success': True})

    @app.route('/api/guild/<guild_id>/activity', methods=['GET'])
    def get_guild_activity(guild_id):
        """Get recent activity logs for a guild"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        # Return mock activity data for now
        # In a real implementation, you'd store activity logs in a database
        activity = [
            {
                'id': '1',
                'event_type': 'join',
                'description': 'New member joined the server',
                'created_at': datetime.now(timezone.utc).isoformat()
            },
            {
                'id': '2',
                'event_type': 'message',
                'description': 'Message deleted by auto-mod',
                'created_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            },
            {
                'id': '3',
                'event_type': 'ticket',
                'description': 'Support ticket opened',
                'created_at': (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            }
        ]
        
        return jsonify(activity)

    @app.route('/api/guild/<guild_id>/stats', methods=['GET'])
    def get_guild_stats(guild_id):
        """Get statistics for a guild"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        guild = bot_instance.get_guild(int(guild_id))
        if not guild:
            return jsonify({'error': 'Guild not found'}), 404
        
        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        
        stats = {
            'total_members': total_members,
            'online_members': online_members,
            'text_channels': len(guild.text_channels),
            'voice_channels': len(guild.voice_channels),
            'roles': len(guild.roles),
            'total_messages': 0  # Would need message tracking
        }
        
        return jsonify(stats)

    @app.route('/api/guild/<guild_id>/dm/send', methods=['POST'])
    def send_dm_via_api(guild_id):
        """Send DM to specific user or all members via API"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        if not dm_enabled:
            return jsonify({'error': 'DM system is disabled'}), 400
        
        guild = bot_instance.get_guild(int(guild_id))
        if not guild:
            return jsonify({'error': 'Guild not found'}), 404
        
        data = request.json
        message = data.get('message')
        target_type = data.get('target_type', 'user')  # 'user' or 'all'
        target_user_id = data.get('user_id')
        use_embed = data.get('use_embed', False)
        embed_title = data.get('embed_title')
        embed_color = data.get('embed_color')
        embed_description = data.get('embed_description')
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        success_count = 0
        failed_count = 0
        failed_users = []
        
        # Prepare message content
        if use_embed:
            embed = discord.Embed(
                title=embed_title or 'رسالة من الإدارة',
                description=embed_description or message,
                color=discord.Color.blue() if not embed_color else discord.Color(int(embed_color.replace('#', ''), 16))
            )
            embed.set_footer(text=f'من: {guild.name}')
            embed.timestamp = datetime.now(timezone.utc)
        else:
            embed = None
        
        async def send_dm_task():
            nonlocal success_count, failed_count, failed_users
            
            if target_type == 'all':
                for member in guild.members:
                    if member.bot:
                        continue
                    try:
                        if embed:
                            await member.send(embed=embed)
                        else:
                            await member.send(message)
                        success_count += 1
                        await asyncio.sleep(0.5)
                    except discord.Forbidden:
                        failed_count += 1
                        failed_users.append(f'{member.display_name} (DMs closed)')
                    except Exception as e:
                        failed_count += 1
                        failed_users.append(f'{member.display_name} ({str(e)[:50]})')
            elif target_type == 'user' and target_user_id:
                target_member = guild.get_member(int(target_user_id))
                if target_member:
                    try:
                        if embed:
                            await target_member.send(embed=embed)
                        else:
                            await target_member.send(message)
                        success_count += 1
                    except discord.Forbidden:
                        failed_count += 1
                        failed_users.append(f'{target_member.display_name} (DMs closed)')
                    except Exception as e:
                        failed_count += 1
                        failed_users.append(f'{target_member.display_name} ({str(e)[:50]})')
                else:
                    failed_count += 1
                    failed_users.append(f'User {target_user_id} not found')
            
            # Update stats
            if guild.id not in dm_stats:
                dm_stats[guild.id] = {'total': 0, 'success': 0, 'failed': 0}
            dm_stats[guild.id]['total'] += success_count + failed_count
            dm_stats[guild.id]['success'] += success_count
            dm_stats[guild.id]['failed'] += failed_count
            
            # Send log
            await send_log(guild, '📨 DM Sent via API', f'تم إرسال رسالة خاصة عبر الـ API\nالنوع: {target_type}\nنجاح: {success_count}\nفشل: {failed_count}')
        
        # Run async task in event loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run_coroutine_threadsafe,
                send_dm_task(),
                bot_instance.loop
            )
            future.result()
        
        return jsonify({
            'success': True,
            'success_count': success_count,
            'failed_count': failed_count,
            'failed_users': failed_users[:10]  # Return first 10 failed users
        })

    @app.route('/api/guild/<guild_id>/dm/stats', methods=['GET'])
    def get_dm_stats_api(guild_id):
        """Get DM statistics for a guild via API"""
        if not bot_instance.is_ready():
            return jsonify({'error': 'Bot not ready'}), 503
        
        guild = bot_instance.get_guild(int(guild_id))
        if not guild:
            return jsonify({'error': 'Guild not found'}), 404
        
        stats = dm_stats.get(guild.id, {'total': 0, 'success': 0, 'failed': 0})
        
        return jsonify({
            'total': stats['total'],
            'success': stats['success'],
            'failed': stats['failed'],
            'success_rate': (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
        })

    def run_flask():
        """Run Flask server in separate thread"""
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

    # Start Flask server in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("Flask API server started on port 5000")

# تشغيل البوت باستخدام التوكن الخاص بك
TOKEN = os.getenv('DISCORD_TOKEN')
bot.run(TOKEN)