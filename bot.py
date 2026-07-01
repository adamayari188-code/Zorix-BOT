import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import sys
import threading
from dotenv import load_dotenv
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from settings_manager import get_settings, update_settings
from db import add_audit_log, get_audit_logs

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
SPAM_TIMEOUT_STEPS_MINUTES = [10, 20, 40, 80, 160, 320, 640, 1280]  # العقوبات التصاعدية بالدقائق (تبدأ من 10 وتتضاعف)
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
                
                # التحقق إذا كان العضو لديه رتبة من قائمة الحظر التلقائي
                member_role_ids = {role.id for role in member.roles}
                has_spam_ban_role = bool(member_role_ids & spam_ban_roles)
                
                if has_spam_ban_role:
                    # حظر العضو نهائيًا
                    try:
                        await member.ban(reason=f"Automatic ban for spam in restricted role (offense #{offense_count}).")
                        await message.channel.send(
                            f'{member.mention} تم حظرك نهائيًا بسبب السبام في رتبة محدودة.'
                        )
                    except discord.Forbidden:
                        print(f'لا أمتلك صلاحية حظر العضو {member.display_name} في السيرفر {message.guild.name}.')
                    except Exception as e:
                        print(f'حدث خطأ أثناء حظر العضو {member.display_name}: {e}')
                else:
                    # السلوك العادي: تايم أوت
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

# ============= نظام الحظر التلقائي للسبام في رتب محددة =============
spam_ban_roles = set() # معرفات الرتب التي يتم فيها الحظر تلقائيًا عند السبام

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

@bot.tree.command(name='spamban', description='تحكم في رتب الحظر التلقائي للسبام')
@app_commands.describe(action='الإجراء: add/remove/list', role='الرتبة المراد إضافتها/إزالتها')
async def spamban_command(interaction: discord.Interaction, action: str, role: discord.Role = None):
    """تحكم في رتب الحظر التلقائي للسبام. الاستخدام: /spamban add/remove/list [@role]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global spam_ban_roles
    
    if action == 'add' and role:
        spam_ban_roles.add(role.id)
        await interaction.response.send_message(f'✅ تم إضافة الرتبة {role.name} لقائمة الحظر التلقائي للسبام.', ephemeral=True)
    elif action == 'remove' and role:
        spam_ban_roles.discard(role.id)
        await interaction.response.send_message(f'❌ تم إزالة الرتبة {role.name} من قائمة الحظر التلقائي للسبام.', ephemeral=True)
    elif action == 'list':
        if spam_ban_roles:
            role_names = []
            for role_id in spam_ban_roles:
                r = interaction.guild.get_role(role_id)
                if r:
                    role_names.append(r.name)
            await interaction.response.send_message(f'📋 رتب الحظر التلقائي للسبام:\n' + '\n'.join(role_names), ephemeral=True)
        else:
            await interaction.response.send_message('📋 لا توجد رتب في قائمة الحظر التلقائي للسبام.', ephemeral=True)
    else:
        await interaction.response.send_message('الاستخدام: /spamban add/remove/list [@role]', ephemeral=True)

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

# ============= نظام الترحيب (Welcome System) =============
welcome_enabled = True
welcome_channel_id = None
welcome_message = 'أهلاً وسهلاً {member.mention} في السيرفر! نتمنى لك وقتاً ممتعاً معنا 🎉'

@bot.tree.command(name='welcome', description='تحكم في نظام الترحيب')
async def welcome_command(interaction: discord.Interaction, action: str = None, channel: discord.TextChannel = None, message: str = None):
    """تحكم في نظام الترحيب. الاستخدام: /welcome enable/disable/setchannel/setmessage [channel] [message]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global welcome_enabled, welcome_channel_id, welcome_message
    
    if action == 'enable':
        welcome_enabled = True
        await interaction.response.send_message('✅ تم تفعيل نظام الترحيب.', ephemeral=True)
    elif action == 'disable':
        welcome_enabled = False
        await interaction.response.send_message('❌ تم تعطيل نظام الترحيب.', ephemeral=True)
    elif action == 'setchannel' and channel:
        welcome_channel_id = channel.id
        await interaction.response.send_message(f'✅ تم ضبط قناة الترحيب إلى: {channel.mention}', ephemeral=True)
    elif action == 'setmessage' and message:
        welcome_message = message
        await interaction.response.send_message('✅ تم تحديث رسالة الترحيب.', ephemeral=True)
    else:
        status = 'مفعل' if welcome_enabled else 'معطل'
        channel_mention = f'<#{welcome_channel_id}>' if welcome_channel_id else 'غير محدد'
        await interaction.response.send_message(
            f'نظام الترحيب: {status}\nقناة الترحيب: {channel_mention}\nالرسالة: {welcome_message}',
            ephemeral=True
        )

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

# ============= نظام التحكم (Dashboard Control) =============
systems_status = {
    'anti_nuke': anti_nuke_enabled,
    'logs': logs_enabled,
    'tickets': tickets_enabled,
    'auto_roles': auto_roles_enabled,
}

@bot.tree.command(name='system', description='تحكم في الأنظمة')
async def system_command(interaction: discord.Interaction, system_name: str = None, action: str = None):
    """تحكم في الأنظمة. الاستخدام: /system [system_name] [enable/disable/list]"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارية.', ephemeral=True)
        return
    
    global systems_status, anti_nuke_enabled, logs_enabled, tickets_enabled, auto_roles_enabled
    
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
            await interaction.response.send_message(f'❌ تم تعطيل نظام {system_name}.', ephemeral=True)
    else:
        await interaction.response.send_message('الاستخدام: /system [anti_nuke/logs/tickets/auto_roles] [enable/disable/list]', ephemeral=True)

# ============= نظام إرسال الرسائل =============
@bot.tree.command(name='send', description='إرسال رسالة إلى قناة محددة')
@app_commands.describe(channel='القناة المطلوب إرسال الرسالة إليها', message='الرسالة المطلوب إرسالها')
async def send_message_command(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    """إرسال رسالة إلى قناة محددة"""
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ ليس لديك صلاحيات إدارة الرسائل.', ephemeral=True)
        return
    
    try:
        await channel.send(message)
        await interaction.response.send_message(f'✅ تم إرسال الرسالة إلى {channel.mention}', ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message('❌ لا أمتلك صلاحية الإرسال في هذه القناة.', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f'❌ حدث خطأ: {e}', ephemeral=True)

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
        name='� نظام الحظر التلقائي للسبام (Spam Ban)',
        value='حظر تلقائي للأعضاء الذين يسبام في رتب محددة\nالأمر: `/spamban`',
        inline=False
    )
    
    embed.add_field(
        name='�📜 نظام اللوق (Logs System)',
        value='تسجيل جميع الأحداث في قناة مخصصة\nالأمر: `/logs`',
        inline=False
    )
    
    embed.add_field(
        name='🎫 نظام التذاكر (Tickets)',
        value='إنشاء تذاكر دعم، إغلاق، إضافة/إزالة أعضاء\nالأوامر: `/ticket`, `/close`, `/add`, `/remove`',
        inline=False
    )
    
    embed.add_field(
        name='👋 نظام الترحيب (Welcome System)',
        value='رسالة ترحيب تلقائية للأعضاء الجدد\nالأمر: `/welcome`',
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
        name='� إرسال الرسائل',
        value='إرسال رسالة إلى قناة محددة\nالأمر: `/send`',
        inline=False
    )
    
    embed.add_field(
        name='�💬 الرد الذكي',
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
    
    # إرسال رسالة الترحيب
    if welcome_enabled and welcome_channel_id:
        welcome_channel = member.guild.get_channel(welcome_channel_id)
        if welcome_channel:
            try:
                formatted_message = welcome_message.format(member=member, guild=member.guild)
                await welcome_channel.send(formatted_message)
            except Exception as e:
                print(f'حدث خطأ أثناء إرسال رسالة الترحيب: {e}')
    
    # إعطاء الرتب التلقائية
    if auto_roles_enabled and auto_roles:
        for role_id, level in auto_roles.items():
            if level == 0: # الرتبة للمستوى 0 تعطى للجميع
                role = member.guild.get_role(role_id)
                if role:
                    await member.add_roles(role)


# ============= Flask API Server for Dashboard Integration =============
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
    
    gid = int(guild_id)
    cfg = get_settings(gid)

    settings = {
        'prefix': '/',
        'language': 'ar',
        'security_enabled': cfg.get('anti_nuke_enabled', anti_nuke_enabled),
        'logging_enabled': cfg.get('logs_enabled', logs_enabled),
        'log_channel_id': str(cfg['logs_channel_id']) if cfg.get('logs_channel_id') else None,
        'message_logs': cfg.get('logs_enabled', logs_enabled),
        'member_logs': cfg.get('logs_enabled', logs_enabled),
        'ticketing_enabled': cfg.get('tickets_enabled', tickets_enabled),
        'ticket_category_id': str(cfg['ticket_category_id']) if cfg.get('ticket_category_id') else None,
        'welcome_enabled': cfg.get('welcome_enabled', welcome_enabled),
        'welcome_channel_id': str(cfg['welcome_channel_id']) if cfg.get('welcome_channel_id') else None,
        'welcome_message': cfg.get('welcome_message', welcome_message),
        'leave_message': None,
        'leveling_enabled': cfg.get('auto_roles_enabled', auto_roles_enabled),
        'xp_per_message': 15,
        'level_roles': [{'role_id': str(rid), 'level': lvl} for rid, lvl in (cfg.get('auto_roles') or {}).items()],
        'ai_moderation_enabled': True,
        'ai_filters': cfg.get('bad_words') or BAD_WORDS,
        'ai_auto_delete': True,
        'anti_spam': True,
        'anti_raid': cfg.get('raid_detection_enabled', raid_detection_enabled),
        'anti_raid_threshold': cfg.get('raid_threshold', raid_threshold),
        'auto_mod': True,
        'max_mentions': cfg.get('max_mentions', 5),
        'analytics_enabled': True,
        'total_messages': 0,
        'total_members': guild.member_count
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
    
    gid = int(guild_id)
    data = request.json or {}
    updates = {}
    global anti_nuke_enabled, logs_enabled, logs_channel_id
    global tickets_enabled, ticket_category_id
    global auto_roles_enabled, auto_roles
    global raid_detection_enabled, raid_threshold
    global welcome_enabled, welcome_channel_id, welcome_message, BAD_WORDS

    if 'security_enabled' in data:
        updates['anti_nuke_enabled'] = data['security_enabled']
        anti_nuke_enabled = data['security_enabled']
    if 'anti_raid' in data:
        updates['raid_detection_enabled'] = data['anti_raid']
        raid_detection_enabled = data['anti_raid']
    if 'anti_raid_threshold' in data:
        updates['raid_threshold'] = data['anti_raid_threshold']
        raid_threshold = data['anti_raid_threshold']
    if 'logging_enabled' in data:
        updates['logs_enabled'] = data['logging_enabled']
        logs_enabled = data['logging_enabled']
    if 'log_channel_id' in data:
        val = int(data['log_channel_id']) if data['log_channel_id'] else None
        updates['logs_channel_id'] = val
        logs_channel_id = val
    if 'ticketing_enabled' in data:
        updates['tickets_enabled'] = data['ticketing_enabled']
        tickets_enabled = data['ticketing_enabled']
    if 'ticket_category_id' in data:
        val = int(data['ticket_category_id']) if data['ticket_category_id'] else None
        updates['ticket_category_id'] = val
        ticket_category_id = val
    if 'leveling_enabled' in data:
        updates['auto_roles_enabled'] = data['leveling_enabled']
        auto_roles_enabled = data['leveling_enabled']
    if 'level_roles' in data:
        mapped = {int(lr['role_id']): lr['level'] for lr in data['level_roles']}
        updates['auto_roles'] = mapped
        auto_roles = mapped
    if 'welcome_enabled' in data:
        updates['welcome_enabled'] = data['welcome_enabled']
        welcome_enabled = data['welcome_enabled']
    if 'welcome_channel_id' in data:
        val = int(data['welcome_channel_id']) if data['welcome_channel_id'] else None
        updates['welcome_channel_id'] = val
        welcome_channel_id = val
    if 'welcome_message' in data:
        updates['welcome_message'] = data['welcome_message']
        welcome_message = data['welcome_message']
    if 'ai_filters' in data:
        updates['bad_words'] = data['ai_filters']
        BAD_WORDS = data['ai_filters']

    if updates:
        update_settings(gid, **updates)
        add_audit_log(gid, 'settings_update', f'Dashboard updated: {", ".join(updates.keys())}')

    return jsonify({'success': True})

@app.route('/api/guild/<guild_id>/activity', methods=['GET'])
def get_guild_activity(guild_id):
    """Get recent activity logs for a guild"""
    if not bot_instance.is_ready():
        return jsonify({'error': 'Bot not ready'}), 503

    gid = int(guild_id)
    activity = get_audit_logs(gid, limit=50)
    return jsonify([
        {
            'id': str(i),
            'event_type': log.get('action', 'event'),
            'description': log.get('details', ''),
            'user_name': log.get('user_name'),
            'created_at': log.get('created_at').isoformat() if log.get('created_at') else None,
        }
        for i, log in enumerate(activity)
    ])

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

def run_flask():
    """Run Flask server in separate thread"""
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# Start Flask server in background thread
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# تشغيل البوت باستخدام التوكن الخاص بك
TOKEN = os.getenv('DISCORD_TOKEN')
bot.run(TOKEN)