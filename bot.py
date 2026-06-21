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

@bot.command(name='count_members')
async def count_members(ctx):
    """يحسب عدد الأعضاء في الخادم."""
    await ctx.send(f'عدد الأعضاء في هذا السيرفر هو: {ctx.guild.member_count}')

@bot.command(name='send_dm')
@commands.has_permissions(administrator=True) # يتطلب صلاحيات إدارية
async def send_dm(ctx, member: discord.Member, *, message):
    """يرسل رسالة خاصة لعضو محدد."""
    try:
        await member.send(message)
        await ctx.send(f'تم إرسال الرسالة إلى {member.display_name}.')
    except discord.Forbidden:
        await ctx.send(f'لا يمكن إرسال رسالة خاصة إلى {member.display_name}. قد يكون لديهم الرسائل الخاصة معطلة.')

@bot.command(name='kick_unauthorized_bots_now')
@commands.has_permissions(administrator=True)
async def kick_unauthorized_bots_now(ctx):
    """يطرد جميع البوتات التي ليس لديها رتبة إدارية فورًا (بناءً على طلب)."""
    await ctx.send('جاري البحث عن البوتات التي ليس لديها صلاحيات إدارية وطردها...')
    kicked_bots = await _kick_unauthorized_bots_logic(ctx.guild)

    if kicked_bots:
        await ctx.send(f'تم طرد البوتات التالية التي لا تملك صلاحيات إدارية: {", ".join(kicked_bots)}')
    else:
        await ctx.send('لم يتم العثور على بوتات بدون صلاحيات إدارية لطردها.')

@bot.command(name='broadcast_message')
@commands.has_permissions(administrator=True) # يتطلب صلاحيات إدارية
async def broadcast_message(ctx, channel: discord.TextChannel, *, message):
    """يرسل رسالة إلى قناة نصية محددة. يمكنك استخدام @everyone أو @here في الرسالة.
    الاستخدام: !broadcast_message <معرف_القناة> <رسالتك هنا>"""
    try:
        await channel.send(message)
        await ctx.send(f'تم إرسال الرسالة إلى القناة {channel.mention}.')
    except discord.Forbidden:
        await ctx.send(f'لا أستطيع إرسال الرسالة إلى {channel.mention}. تأكد من أن لدي صلاحيات الكتابة في هذه القناة.')
    except Exception as e:
        await ctx.send(f'حدث خطأ أثناء إرسال الرسالة: {e}')

@bot.command(name='mass_dm')
@commands.has_permissions(administrator=True) # يتطلب صلاحيات إدارية
async def mass_dm(ctx, *, message):
    """يرسل رسالة خاصة إلى جميع أعضاء السيرفر.
    الاستخدام: !mass_dm <رسالتك هنا>"""
    await ctx.send('جاري إرسال رسالة خاصة إلى جميع أعضاء السيرفر. قد يستغرق هذا بعض الوقت...')
    
    success_count = 0
    failed_count = 0
    failed_members = []

    for member in ctx.guild.members:
        if member.bot: # لا ترسل رسائل خاصة للبوتات
            continue
        try:
            await member.send(message)
            success_count += 1
            # يمكنك إضافة تأخير بسيط هنا لتجنب تجاوز حدود ديسكورد إذا كان السيرفر كبيرًا جدًا
            # await asyncio.sleep(0.5) # مثال: تأخير 0.5 ثانية لكل رسالة
        except discord.Forbidden: # العضو عطل الرسائل الخاصة
            failed_count += 1
            failed_members.append(member.display_name)
        except Exception as e:
            failed_count += 1
            failed_members.append(f'{member.display_name} (خطأ: {e})')

    result_message = f'تم إرسال رسائل خاصة إلى {success_count} عضو بنجاح.'
    if failed_count > 0:
        result_message += f' فشل إرسال الرسائل إلى {failed_count} عضو. القائمة: {", ".join(failed_members[:10])}...' if len(failed_members) > 10 else f' فشل إرسال الرسائل إلى {failed_count} عضو. القائمة: {", ".join(failed_members)}'
    
    await ctx.send(result_message)

@bot.command(name='clear_channel', help='يحذف جميع الرسائل (التي لا يزيد عمرها عن 14 يومًا) من القناة المحددة أو القناة الحالية. يتطلب صلاحيات إدارية.')
@commands.has_permissions(administrator=True) # يتطلب صلاحيات إدارية
async def clear_channel(ctx, channel: discord.TextChannel = None):
    if channel is None:
        channel = ctx.channel

    deleted_count = 0
    try:
        deleted = await channel.purge(limit=None) # limit=None يعني حذف كل ما يمكن حذفه
        deleted_count = len(deleted)
        await ctx.send(f'تم حذف {deleted_count} رسالة بنجاح من القناة {channel.mention}. (الرسائل الأقدم من 14 يومًا لا يمكن حذفها بشكل جماعي).' , delete_after=10)
    except discord.Forbidden:
        await ctx.send(f'لا أمتلك صلاحيات `Manage Messages` لحذف الرسائل في القناة {channel.mention}.')
    except Exception as e:
        await ctx.send(f'حدث خطأ أثناء حذف الرسائل من القناة {channel.mention}: {e}')


@bot.command(name='delete_thread', help='يحذف الثريد المحدد. إذا لم تحدد ثريدًا وكان الأمر داخل ثريد، سيتم حذف الثريد الحالي. يتطلب صلاحيات إدارية.')
@commands.has_permissions(administrator=True)
async def delete_thread(ctx, thread: discord.Thread = None):
    target_thread = thread

    if target_thread is None and isinstance(ctx.channel, discord.Thread):
        target_thread = ctx.channel

    if target_thread is None:
        await ctx.send('يرجى تحديد ثريد للحذف، أو استخدام الأمر من داخل الثريد نفسه.')
        return

    try:
        thread_name = target_thread.name
        await target_thread.delete()
        await ctx.send(f'تم حذف الثريد: **{thread_name}**.')
    except discord.Forbidden:
        await ctx.send('لا أمتلك صلاحية حذف هذا الثريد. تأكد من صلاحياتي وترتيبي.')
    except Exception as e:
        await ctx.send(f'حدث خطأ أثناء حذف الثريد: {e}')


@bot.command(name='delete_channel', help='يحذف القناة المحددة أو القناة الحالية. يتطلب صلاحيات إدارية.')
@commands.has_permissions(administrator=True)
async def delete_channel(ctx, channel: discord.TextChannel = None):
    target_channel = channel or ctx.channel

    try:
        channel_name = target_channel.name
        await ctx.send(f'جاري حذف القناة: **{channel_name}**...')
        await target_channel.delete(reason=f'Deleted by {ctx.author} using bot command.')
    except discord.Forbidden:
        await ctx.send('لا أمتلك صلاحية حذف هذه القناة. تأكد من صلاحياتي وترتيبي.')
    except Exception as e:
        await ctx.send(f'حدث خطأ أثناء حذف القناة: {e}')


@bot.command(name='restart', help='يعيد تشغيل البوت. يتطلب صلاحيات إدارية.')
@commands.has_permissions(administrator=True)
async def restart_bot(ctx):
    await ctx.send('جاري إعادة تشغيل البوت...')
    await bot.close()
    os.execv(sys.executable, [sys.executable] + sys.argv)


@bot.command(name='set_chat_channel', help='يضبط قناة مخصصة يتكلم فيها البوت مع الأعضاء. إذا لم تحدد قناة، يستخدم القناة الحالية. يتطلب صلاحيات إدارية.')
@commands.has_permissions(administrator=True)
async def set_chat_channel(ctx, channel: discord.TextChannel = None):
    global CHAT_CHANNEL_ID
    target_channel = channel or ctx.channel
    CHAT_CHANNEL_ID = target_channel.id
    await ctx.send(f'تم ضبط قناة الدردشة المخصصة إلى: {target_channel.mention}')


@bot.command(name='disable_chat_channel', help='يعطل قناة الدردشة المخصصة للبوت. يتطلب صلاحيات إدارية.')
@commands.has_permissions(administrator=True)
async def disable_chat_channel(ctx):
    global CHAT_CHANNEL_ID
    CHAT_CHANNEL_ID = None
    await ctx.send('تم تعطيل قناة الدردشة المخصصة.')


@bot.command(name='help')
async def help_command(ctx):
    """يعرض قائمة بجميع الأوامر المتاحة ووصفها."""
    help_text = "**الأوامر المتاحة:**\n"
    for command in bot.commands:
        help_text += f'-   **!{command.name}**: {command.help or "لا يوجد وصف."}\n'
    await ctx.send(help_text)

# تشغيل البوت باستخدام التوكن الخاص بك
TOKEN = os.getenv('DISCORD_TOKEN')
bot.run(TOKEN)