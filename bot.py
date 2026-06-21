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

load_dotenv() # حمل المتغيرات من ملف .env

# قم بتحميل معرفات السيرفرات المسموح بها من متغير البيئة
# إذا كان المتغير غير موجود، أو فارغ، فلن تكون هناك قيود
allowed_guild_ids_str = os.getenv('ALLOWED_GUILDS')
ALLOWED_GUILD_IDS = [int(gid.strip()) for gid in allowed_guild_ids_str.split(',')] if allowed_guild_ids_str else []

# قم بتغيير بادئة الأمر هنا إذا أردت (مثال: '!', '/', '.')
intents = discord.Intents.default()
intents.members = True # لكي نتمكن من حساب الأعضاء
intents.message_content = True # لكي يتمكن البوت من قراءة الرسائل والأوامر

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

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

@bot.command(name='antinuke')
@commands.has_permissions(administrator=True)
async def antinuke_command(ctx, action: str = None, user_id: int = None):
    """تحكم في نظام الحماية. الاستخدام: !antinuke enable/disable/whitelist/unwhitelist [user_id]"""
    global anti_nuke_enabled, anti_nuke_whitelist
    
    if action == 'enable':
        anti_nuke_enabled = True
        await ctx.send('✅ تم تفعيل نظام الحماية.')
    elif action == 'disable':
        anti_nuke_enabled = False
        await ctx.send('❌ تم تعطيل نظام الحماية.')
    elif action == 'whitelist' and user_id:
        anti_nuke_whitelist.add(user_id)
        await ctx.send(f'✅ تم إضافة {user_id} إلى القائمة البيضاء.')
    elif action == 'unwhitelist' and user_id:
        anti_nuke_whitelist.discard(user_id)
        await ctx.send(f'❌ تم إزالة {user_id} من القائمة البيضاء.')
    elif action == 'list':
        if anti_nuke_whitelist:
            await ctx.send(f'📋 القائمة البيضاء: {", ".join(map(str, anti_nuke_whitelist))}')
        else:
            await ctx.send('📋 القائمة البيضاء فارغة.')
    else:
        await ctx.send('الاستخدام: !antinuke enable/disable/whitelist/unwhitelist/list [user_id]')

@bot.command(name='lockdown')
@commands.has_permissions(administrator=True)
async def lockdown_command(ctx, action: str = None):
    """تفعيل/تعطيل وضع الطوارئ. الاستخدام: !lockdown enable/disable"""
    global lockdown_mode
    
    if action == 'enable':
        lockdown_mode = True
        await ctx.send('🔒 تم تفعيل وضع الطوارئ. لا يمكن للأعضاء الجدد الانضمام.')
    elif action == 'disable':
        lockdown_mode = False
        await ctx.send('🔓 تم تعطيل وضع الطوارئ.')
    else:
        status = 'مفعل' if lockdown_mode else 'معطل'
        await ctx.send(f'وضع الطوارئ: {status}')

# ============= نظام اللوق (Logs System) =============
logs_enabled = True
logs_channel_id = None

@bot.command(name='logs')
@commands.has_permissions(administrator=True)
async def logs_command(ctx, action: str = None, channel: discord.TextChannel = None):
    """تحكم في نظام اللوق. الاستخدام: !logs enable/disable/setchannel [channel]"""
    global logs_enabled, logs_channel_id
    
    if action == 'enable':
        logs_enabled = True
        await ctx.send('✅ تم تفعيل نظام اللوق.')
    elif action == 'disable':
        logs_enabled = False
        await ctx.send('❌ تم تعطيل نظام اللوق.')
    elif action == 'setchannel' and channel:
        logs_channel_id = channel.id
        await ctx.send(f'✅ تم ضبط قناة اللوق إلى: {channel.mention}')
    else:
        status = 'مفعل' if logs_enabled else 'معطل'
        channel_mention = f'<#{logs_channel_id}>' if logs_channel_id else 'غير محدد'
        await ctx.send(f'نظام اللوق: {status}\nقناة اللوق: {channel_mention}')

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

@bot.command(name='ticket')
async def ticket_command(ctx):
    """إنشاء تذكرة جديدة"""
    if not tickets_enabled:
        await ctx.send('❌ نظام التذاكر معطل.')
        return
    
    global ticket_counter
    ticket_counter += 1
    
    category = ctx.guild.get_channel(ticket_category_id) if ticket_category_id else None
    if not category:
        # إنشاء category للتذاكر إذا لم يكن موجوداً
        category = await ctx.guild.create_category('🎫 Tickets')
        ticket_category_id = category.id
    
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    
    ticket_channel = await ctx.guild.create_text_channel(
        name=f'ticket-{ticket_counter}',
        category=category,
        overwrites=overwrites,
        topic=f'Ticket for {ctx.author} ({ctx.author.id})'
    )
    
    await ticket_channel.send(f'🎫 تم إنشاء تذكرة جديدة!\n\nالصاحب: {ctx.author.mention}\nاستخدم الأوامر التالية:\n- `!close` لإغلاق التذكرة\n- `!add @user` لإضافة عضو\n- `!remove @user` لإزالة عضو')
    await ctx.send(f'✅ تم إنشاء تذكرتك: {ticket_channel.mention}')

@bot.command(name='close')
async def close_ticket(ctx):
    """إغلاق التذكرة الحالية"""
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.send('❌ هذا الأمر يعمل فقط في قنوات التذاكر.')
        return
    
    await ctx.send('🔒 جاري إغلاق التذكرة...')
    await asyncio.sleep(2)
    await ctx.channel.delete()

@bot.command(name='add')
async def add_to_ticket(ctx, member: discord.Member):
    """إضافة عضو إلى التذكرة"""
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.send('❌ هذا الأمر يعمل فقط في قنوات التذاكر.')
        return
    
    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
    await ctx.send(f'✅ تم إضافة {member.mention} إلى التذكرة.')

@bot.command(name='remove')
async def remove_from_ticket(ctx, member: discord.Member):
    """إزالة عضو من التذكرة"""
    if not ctx.channel.name.startswith('ticket-'):
        await ctx.send('❌ هذا الأمر يعمل فقط في قنوات التذاكر.')
        return
    
    await ctx.channel.set_permissions(member, view_channel=False, send_messages=False, read_message_history=False)
    await ctx.send(f'❌ تم إزالة {member.mention} من التذكرة.')

@bot.command(name='tickets')
@commands.has_permissions(administrator=True)
async def tickets_admin(ctx, action: str = None):
    """تحكم في نظام التذاكر. الاستخدام: !tickets enable/disable"""
    global tickets_enabled
    
    if action == 'enable':
        tickets_enabled = True
        await ctx.send('✅ تم تفعيل نظام التذاكر.')
    elif action == 'disable':
        tickets_enabled = False
        await ctx.send('❌ تم تعطيل نظام التذاكر.')
    else:
        status = 'مفعل' if tickets_enabled else 'معطل'
        await ctx.send(f'نظام التذاكر: {status}')

# ============= نظام إدارة الرتب (Roles System) =============
auto_roles_enabled = True
auto_roles = {} # {role_id: required_level}

@bot.command(name='role')
@commands.has_permissions(manage_roles=True)
async def role_command(ctx, action: str, role: discord.Role, user: discord.Member = None):
    """إدارة الرتب. الاستخدام: !role give/remove @role [@user]"""
    if action == 'give' and user:
        await user.add_roles(role)
        await ctx.send(f'✅ تم إعطاء الرتبة {role.name} لـ {user.mention}.')
    elif action == 'remove' and user:
        await user.remove_roles(role)
        await ctx.send(f'❌ تم إزالة الرتبة {role.name} من {user.mention}.')
    else:
        await ctx.send('الاستخدام: !role give/remove @role [@user]')

@bot.command(name='autorole')
@commands.has_permissions(administrator=True)
async def autorole_command(ctx, action: str, role: discord.Role = None, level: int = None):
    """إدارة الرتب التلقائية. الاستخدام: !autorole add/remove/list [@role] [level]"""
    global auto_roles
    
    if action == 'add' and role and level is not None:
        auto_roles[role.id] = level
        await ctx.send(f'✅ تم إضافة الرتبة {role.name} للمستوى {level}.')
    elif action == 'remove' and role:
        auto_roles.pop(role.id, None)
        await ctx.send(f'❌ تم إزالة الرتبة {role.name}.')
    elif action == 'list':
        if auto_roles:
            role_list = []
            for role_id, lvl in auto_roles.items():
                r = ctx.guild.get_role(role_id)
                if r:
                    role_list.append(f'{r.name}: المستوى {lvl}')
            await ctx.send(f'📋 الرتب التلقائية:\n' + '\n'.join(role_list))
        else:
            await ctx.send('📋 لا توجد رتب تلقائية.')
    else:
        await ctx.send('الاستخدام: !autorole add/remove/list [@role] [level]')

# ============= نظام إحصائيات السيرفر =============
@bot.command(name='stats')
async def stats_command(ctx):
    """عرض إحصائيات السيرفر"""
    guild = ctx.guild
    
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
    
    await ctx.send(embed=embed)

# ============= نظام التحكم (Dashboard Control) =============
systems_status = {
    'anti_nuke': anti_nuke_enabled,
    'logs': logs_enabled,
    'tickets': tickets_enabled,
    'auto_roles': auto_roles_enabled,
}

@bot.command(name='system')
@commands.has_permissions(administrator=True)
async def system_command(ctx, system_name: str = None, action: str = None):
    """تحكم في الأنظمة. الاستخدام: !system [system_name] [enable/disable/list]"""
    global systems_status, anti_nuke_enabled, logs_enabled, tickets_enabled, auto_roles_enabled
    
    if system_name == 'list' or not system_name:
        status_text = '\n'.join([f'✅ {name}: {"مفعل" if status else "معطل"}' for name, status in systems_status.items()])
        await ctx.send(f'🎛️ حالة الأنظمة:\n{status_text}')
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
            await ctx.send(f'✅ تم تفعيل نظام {system_name}.')
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
            await ctx.send(f'❌ تم تعطيل نظام {system_name}.')
    else:
        await ctx.send('الاستخدام: !system [anti_nuke/logs/tickets/auto_roles] [enable/disable/list]')

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


# تشغيل البوت باستخدام التوكن الخاص بك
TOKEN = os.getenv('DISCORD_TOKEN')
bot.run(TOKEN)