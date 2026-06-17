import logging
import math
import time
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler

import config
import database
import keyboards

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Bot and Dispatcher
bot = Bot(token=config.BOT_TOKEN, parse_mode=types.ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- States ---
class AdminStates(StatesGroup):
    waiting_search_query = State()       # When admin is searching a user
    waiting_add_points_amount = State()  # When admin enters points to add
    waiting_sub_points_amount = State()  # When admin enters points to subtract
    waiting_ban_reason = State()         # When admin enters a ban reason

# --- Middlewares ---
class BanMiddleware(BaseMiddleware):
    """Prevents banned users from interacting with the bot."""
    async def on_pre_process_message(self, message: types.Message, data: dict):
        if message.from_user.is_bot:
            raise CancelHandler()
        
        if database.is_user_banned(message.from_user.id):
            # Reply only in private chats to prevent group spam
            if message.chat.type == types.ChatType.PRIVATE:
                await message.reply("⚠️ <b>عذراً، لقد تم حظر حسابك من استخدام البوت.</b>")
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        if callback_query.from_user.is_bot:
            raise CancelHandler()
            
        if database.is_user_banned(callback_query.from_user.id):
            await callback_query.answer("⚠️ عذراً، لقد تم حظرك من استخدام البوت.", show_alert=True)
            raise CancelHandler()

dp.middleware.setup(BanMiddleware())

# --- Group Join Checking ---
async def is_user_member_of_group(user_id: int) -> bool:
    """Checks if the user is a member of the configured target group."""
    if config.GROUP_ID is None:
        return True
    try:
        member = await bot.get_chat_member(chat_id=config.GROUP_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member', 'restricted']:
            return True
        # Status is 'left' or 'kicked' — user is definitely not a member
        return False
    except Exception as e:
        error_msg = str(e).lower()
        logging.warning(f"Error checking group membership for user {user_id}: {e}")
        # If the error indicates the user is simply not found in the group, return False
        if 'user not found' in error_msg or 'chat not found' in error_msg:
            return False
        # For permission errors or other API issues, fall back to DB check:
        # If user has group_messages recorded, they were once a verified member
        user_stats = database.get_user_stats(user_id)
        if user_stats and user_stats.get('group_messages', 0) > 0:
            logging.info(f"Fallback DB check: user {user_id} has {user_stats['group_messages']} group messages — treating as member.")
            return True
        # Cannot confirm membership, require them to join
        return False

async def is_user_member_of_channel(user_id: int) -> bool:
    """Checks if the user is a member of the configured target channel."""
    if config.CHANNEL_ID is None:
        return True
    try:
        member = await bot.get_chat_member(chat_id=config.CHANNEL_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member', 'restricted']:
            return True
        return False
    except Exception as e:
        error_msg = str(e).lower()
        logging.warning(f"Error checking channel membership for user {user_id}: {e}")
        if 'user not found' in error_msg or 'chat not found' in error_msg:
            return False
        return False

class JoinCheckMiddleware(BaseMiddleware):
    """Enforces that users join the target group and channel before they can use private chat features."""
    async def on_pre_process_message(self, message: types.Message, data: dict):
        if message.from_user.is_bot:
            raise CancelHandler()
        
        # Bypass for owner
        if message.from_user.id == config.OWNER_ID:
            return
            
        # Only check private chats
        if message.chat.type != types.ChatType.PRIVATE:
            return
            
        # Allow /start command to pass through so referral logic registers first
        if message.text and message.text.startswith('/start'):
            return
            
        is_group_member = await is_user_member_of_group(message.from_user.id)
        is_channel_member = await is_user_member_of_channel(message.from_user.id)
        
        if not is_group_member or not is_channel_member:
            markup = types.InlineKeyboardMarkup(row_width=1)
            if not is_group_member:
                markup.add(types.InlineKeyboardButton("📢 انضم للقروب", url=config.GROUP_LINK))
            if not is_channel_member:
                markup.add(types.InlineKeyboardButton("📢 انضم للقناة", url=config.CHANNEL_LINK))
            markup.add(types.InlineKeyboardButton("🔄 تحقق من الانضمام", callback_data="check_join"))
            
            if not is_group_member and not is_channel_member:
                text = "🚫 <b>يجب الانضمام للقروب والقناة أولاً لاستخدام البوت!</b>"
            elif not is_group_member:
                text = "🚫 <b>يجب الانضمام للقروب أولاً لاستخدام البوت!</b>"
            else:
                text = "🚫 <b>يجب الانضمام للقناة أولاً لاستخدام البوت!</b>"
                
            await message.reply(
                text,
                reply_markup=markup
            )
            raise CancelHandler()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        if callback_query.from_user.is_bot:
            raise CancelHandler()
            
        # Bypass for owner
        if callback_query.from_user.id == config.OWNER_ID:
            return
            
        # Do not cancel the check_join callback itself
        if callback_query.data == "check_join":
            return
            
        is_group_member = await is_user_member_of_group(callback_query.from_user.id)
        is_channel_member = await is_user_member_of_channel(callback_query.from_user.id)
        
        if not is_group_member or not is_channel_member:
            if not is_group_member and not is_channel_member:
                alert_text = "🚫 يجب الانضمام للقروب والقناة أولاً!"
                text = "🚫 <b>يجب الانضمام للقروب والقناة أولاً لاستخدام البوت!</b>"
            elif not is_group_member:
                alert_text = "🚫 يجب الانضمام للقروب أولاً!"
                text = "🚫 <b>يجب الانضمام للقروب أولاً لاستخدام البوت!</b>"
            else:
                alert_text = "🚫 يجب الانضمام للقناة أولاً!"
                text = "🚫 <b>يجب الانضمام للقناة أولاً لاستخدام البوت!</b>"
                
            await callback_query.answer(alert_text, show_alert=True)
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            if not is_group_member:
                markup.add(types.InlineKeyboardButton("📢 انضم للقروب", url=config.GROUP_LINK))
            if not is_channel_member:
                markup.add(types.InlineKeyboardButton("📢 انضم للقناة", url=config.CHANNEL_LINK))
            markup.add(types.InlineKeyboardButton("🔄 تحقق من الانضمام", callback_data="check_join"))
            
            try:
                await callback_query.message.edit_text(
                    text,
                    reply_markup=markup
                )
            except Exception:
                pass
                
            raise CancelHandler()

dp.middleware.setup(JoinCheckMiddleware())

# --- Helper Text Generators ---
def get_stats_message_text(user_id):
    stats = database.get_user_stats(user_id)
    if not stats:
        return "❌ لم يتم العثور على بياناتك في قاعدة البيانات. أرسل /start أولاً لتسجيل حسابك."
        
    username_str = f"@{stats['username']}" if stats['username'] else "لا يوجد"
    return (
        f"📊 <b>إحصائياتك الشخصية:</b>\n\n"
        f"👤 <b>الاسم:</b> {stats['first_name']}\n"
        f"🆔 <b>معرف الحساب:</b> <code>{user_id}</code>\n"
        f"🏷️ <b>اسم المستخدم:</b> {username_str}\n\n"
        f"💬 <b>رسائل المجموعة:</b> {stats['group_messages']} رسالة\n"
        f"👥 <b>الإحالات قيد الانتظار:</b> {stats['pending_referrals']}\n"
        f"✅ <b>الإحالات المفعّلة:</b> {stats['active_referrals']}\n\n"
        f"🪙 <b>تفاصيل النقاط:</b>\n"
        f"  ├─ نقاط الإحالات: +{stats['referral_points']}\n"
        f"  ├─ نقاط المكافأة: +{stats['bonus_points']}\n"
        f"  ├─ نقاط التفاعل: +{stats['interaction_points']}\n"
        f"  └─ تعديل الإدارة: {stats['admin_adjusted_points']}\n\n"
        f"🏆 <b>إجمالي النقاط:</b> <code>{stats['total_points']}</code> نقطة."
    )

async def get_ref_link_message_text(user_id):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user_id}"
    return (
        f"🔗 <b>رابط الإحالة الخاص بك:</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"قم بنسخ هذا الرابط ومشاركته مع أصدقائك لدعوتهم.\n\n"
        f"⚠️ <b>شروط الاحتساب:</b>\n"
        f"لن يتم تفعيل الإحالة إلا بعد أن يرسل الشخص المدعو <b>{config.REFERRAL_REQUIRED_MESSAGES} رسالة</b> على الأقل داخل المجموعة.\n\n"
        f"➕ <b>1 نقطة</b> لكل إحالة مفعّلة.\n"
        f"🎁 <b>5 نقاط إضافية</b> لكل 10 إحالات مفعّلة."
    )

def get_leaderboard_message_text():
    leaders = database.get_leaderboard(10)
    if not leaders:
        return "🏆 <b>قائمة المتصدرين:</b>\n\nلا يوجد مستخدمون في لوحة الصدارة حالياً."
        
    text = "🏆 <b>أفضل 10 مستخدمين في البوت:</b>\n\n"
    for i, lead in enumerate(leaders, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        name = lead['first_name'] or "مستخدم"
        username_str = f" (@{lead['username']})" if lead['username'] else ""
        text += f"{medal} <b>{name}{username_str}</b>\n"
        text += f"   └─ النقاط: <b>{lead['total_points']}</b> | الإحالات: <b>{lead['active_referrals']}</b> | الرسائل: <b>{lead['group_messages']}</b>\n\n"
        
    return text

def get_info_message_text():
    return (
        f"ℹ️ <b>معلومات حول نظام البوت:</b>\n\n"
        f"هذا نظام إحالات وتفاعل متطور لحساب النقاط وترتيب الأعضاء داخل القروب.\n\n"
        f"💡 <b>كيف تجمع النقاط؟</b>\n"
        f"• <b>نظام الإحالة:</b> شارك رابطك مع أصدقائك. عند دخول عضو جديد عبر رابطك وكتابته <b>{config.REFERRAL_REQUIRED_MESSAGES} رسالة</b> في المجموعة، يتم تفعيل إحالتك وتحصل على <b>+1 نقطة</b>.\n"
        f"• <b>مكافأة الإحالة المتكررة:</b> لكل 10 إحالات مفعّلة، ستحصل تلقائياً على <b>+5 نقاط إضافية</b>.\n"
        f"• <b>نقاط التفاعل:</b> كل {config.INTERACTION_THRESHOLD} رسالة ترسلها في المجموعة تمنحك تلقائياً <b>+1 نقطة تفاعل</b>.\n\n"
        f"⚠️ <b>مكافحة الغش:</b>\n"
        f"• الحسابات الوهمية أو البوتات يتم استبعادها تلقائياً.\n"
        f"• محاولة إحالة نفسك أو تكرار الدخول لن يتم احتسابها.\n"
        f"• يحتفظ مالك البوت بحق حظر أي مستخدم يتلاعب بالرسائل أو النقاط."
    )

def get_streak_message_text(user_id):
    streak = database.get_or_update_user_streak(user_id)
    if not streak:
        return "❌ لم يتم العثور على بياناتك في قاعدة البيانات. أرسل /start أولاً لتسجيل حسابك."
        
    current_streak = streak['current_streak']
    best_streak = streak['best_streak']
    daily_messages = streak['daily_messages']
    
    # Calculate daily progress percentage
    progress_percentage = min(100, int((daily_messages / config.INTERACTION_THRESHOLD) * 100))
    
    return (
        f"🔥 <b>سلسلة النشاط</b>\n\n"
        f"📅 <b>السلسلة الحالية:</b> {current_streak} يوم\n"
        f"🏆 <b>أعلى سلسلة:</b> {best_streak} يوم\n"
        f"💬 <b>رسائل اليوم:</b> {daily_messages}/{config.INTERACTION_THRESHOLD}\n"
        f"📈 <b>نسبة الإنجاز اليوم:</b> {progress_percentage}%"
    )

def get_streak_leaderboard_message_text():
    leaders = database.get_streak_leaderboard(10)
    if not leaders:
        return (
            f"🏆 <b>أفضل سلاسل النشاط</b>\n\n"
            f"لا توجد سلاسل نشاط مسجلة حالياً."
        )
        
    text = "🏆 <b>أفضل سلاسل النشاط</b>\n\n"
    for i, lead in enumerate(leaders, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"<b>{i}.</b>"
        name = lead['first_name'] or "مستخدم"
        username_str = f" (@{lead['username']})" if lead['username'] else ""
        text += f"{medal} {name}{username_str} — {lead['best_streak']} يوم\n"
        
    return text

# Cache to prevent spam and duplicate messages in groups
# Format: {user_id: {'time': float, 'text': str}}
user_msg_cache = {}

# --- Group Message Tracking ---
@dp.message_handler(chat_type=[types.ChatType.GROUP, types.ChatType.SUPERGROUP])
async def handle_group_message(message: types.Message):
    """Tracks message counts in the group chat and checks for referral completions."""
    if message.from_user.is_bot:
        return
        
    # Check if target group is configured
    if config.GROUP_ID is not None and message.chat.id != config.GROUP_ID:
        return

    # Spam & Duplicate filtering
    user_id = message.from_user.id
    now = time.time()
    text = message.text.strip() if message.text else (message.caption.strip() if message.caption else "")

    if user_id in user_msg_cache:
        last_time = user_msg_cache[user_id]['time']
        last_text = user_msg_cache[user_id]['text']
        
        # 1. Spam protection: consecutive messages within less than 2 seconds
        if now - last_time < 2:
            return
            
        # 2. Duplicate protection: exact same content as the last message
        if text and text == last_text:
            return

    # Update cache
    user_msg_cache[user_id] = {
        'time': now,
        'text': text
    }

    # Add user to database if not exists
    database.add_user(user_id, message.from_user.username, message.from_user.first_name)
    
    # Update activity streak first to ensure stats are updated on message arrival
    streak_res = database.update_streak_on_message(user_id)
    
    if streak_res['streak_broken']:
        try:
            await bot.send_message(
                user_id,
                f"💔 <b>انقطعت سلسلة نشاطك</b>\n\n"
                f"📅 السلسلة السابقة: {streak_res['previous_streak']} يوم\n"
                f"🏆 أعلى سلسلة: {streak_res['best_streak']} يوم"
            )
        except Exception:
            pass
            
    if streak_res['streak_achieved']:
        curr = streak_res['current_streak']
        milestones = {
            3: "🔥 3 أيام متتالية!",
            7: "🔥 7 أيام متتالية!",
            14: "🔥 14 يومًا متتاليًا!",
            30: "🔥 30 يومًا متتاليًا!",
            100: "🔥 100 يوم متتالي!"
        }
        streak_text = milestones.get(curr, f"🔥 <b>تم الحفاظ على سلسلة نشاطك!</b>\n📅 السلسلة الحالية: {curr} يوم")
        try:
            await bot.send_message(user_id, streak_text)
        except Exception:
            pass

    # Increment count
    result = database.increment_message_count(user_id)
    
    # Notify referrer if referral became active
    if result['referral_activated'] and result['referrer_id']:
        referrer_id = result['referrer_id']
        try:
            ref_name = message.from_user.first_name
            ref_username = f" (@{message.from_user.username})" if message.from_user.username else ""
            
            ref_stats = database.get_user_stats(referrer_id)
            total_pts = ref_stats['total_points'] if ref_stats else 0
            
            await bot.send_message(
                referrer_id,
                f"🎉 <b>تهانينا! إحالة نشطة جديدة!</b>\n\n"
                f"أكمل العضو المدعو <b>{ref_name}{ref_username}</b> شرط التفاعل ({config.REFERRAL_REQUIRED_MESSAGES} رسالة في المجموعة).\n"
                f"تم احتساب الإحالة بنجاح وحصلت على <b>+1 نقطة</b>!\n"
                f"إجمالي نقاطك الآن: <b>{total_pts}</b> نقطة."
            )
        except Exception:
            pass  # User might have blocked the bot, ignore
            
    # Notify user if they earned an interaction point
    if result['interaction_point_earned']:
        try:
            user_stats = database.get_user_stats(user_id)
            total_pts = user_stats['total_points'] if user_stats else 0
            await bot.send_message(
                user_id,
                f"💬 <b>تفاعل رائع!</b>\n\n"
                f"لقد أرسلت <b>{result['group_messages']} رسالة</b> في المجموعة.\n"
                f"حصلت على <b>+1 نقطة تفاعل</b>!\n"
                f"إجمالي نقاطك الآن: <b>{total_pts}</b> نقطة."
            )
        except Exception:
            pass  # User might not have started private chat with bot, ignore

# --- Private Chat User Handlers ---

@dp.message_handler(commands=['start'], chat_type=types.ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Parse payload (referral link start parameter)
    args = message.get_args()
    referrer_id = None
    if args and args.isdigit():
        referrer_id = int(args)
        
    # Attempt to register referral first (verifies if user is new)
    ref_registered = False
    if referrer_id:
        ref_registered = database.add_referral(referrer_id, user_id)
        
    # Attempt to register user in users table
    is_new = database.add_user(user_id, username, first_name, has_started=1)
        
    # Check if they are in the group and channel (except owner)
    if user_id != config.OWNER_ID:
        is_group_member = await is_user_member_of_group(user_id)
        is_channel_member = await is_user_member_of_channel(user_id)
        
        if not is_group_member or not is_channel_member:
            markup = types.InlineKeyboardMarkup(row_width=1)
            if not is_group_member:
                markup.add(types.InlineKeyboardButton("📢 انضم للقروب", url=config.GROUP_LINK))
            if not is_channel_member:
                markup.add(types.InlineKeyboardButton("📢 انضم للقناة", url=config.CHANNEL_LINK))
            markup.add(types.InlineKeyboardButton("🔄 تحقق من الانضمام", callback_data="check_join"))
            
            if not is_group_member and not is_channel_member:
                text = "🚫 <b>يجب الانضمام للقروب والقناة أولاً لاستخدام البوت!</b>"
            elif not is_group_member:
                text = "🚫 <b>يجب الانضمام للقروب أولاً لاستخدام البوت!</b>"
            else:
                text = "🚫 <b>يجب الانضمام للقناة أولاً لاستخدام البوت!</b>"
                
            await message.reply(text, reply_markup=markup)
            return
        
    welcome_text = (
        f"👋 <b>أهلاً بك {first_name} في بوت الإحالات والتفاعل!</b>\n\n"
        f"هذا البوت يتيح لك كسب النقاط من خلال:\n"
        f"1️⃣ دعوة أصدقائك للانضمام للمجموعة عبر رابط الإحالة الخاص بك.\n"
        f"2️⃣ التفاعل وإرسال الرسائل داخل المجموعة.\n\n"
        f"📝 <b>شروط احتساب الإحالة:</b>\n"
        f"يجب على الشخص المدعو إرسال ما لا يقل عن <b>{config.REFERRAL_REQUIRED_MESSAGES} رسالة</b> في المجموعة ليتم تفعيل إحالتك بنجاح.\n\n"
        f"استخدم الأزرار أدناه لتصفح خيارات البوت."
    )
    
    if ref_registered:
        welcome_text += f"\n\n🔗 لقد سجلت في البوت عبر رابط دعوة من المستخدم (ID: <code>{referrer_id}</code>)."
        # Inform referrer that someone registered
        try:
            await bot.send_message(
                referrer_id,
                f"🔔 <b>عضو جديد انضم عبر رابطك!</b>\n\n"
                f"قام <b>{first_name}</b> بالدخول للبوت عبر رابط الدعوة الخاص بك.\n"
                f"ستحصل على النقطة بمجرد أن يرسل <b>{config.REFERRAL_REQUIRED_MESSAGES} رسالة</b> في المجموعة."
            )
        except Exception:
            pass
            
    is_owner = (user_id == config.OWNER_ID)
    await message.reply(
        welcome_text,
        reply_markup=keyboards.get_user_main_keyboard(is_owner)
    )

# Reply Keyboard Handlers
@dp.message_handler(lambda message: message.text == "📊 إحصائياتي", chat_type=types.ChatType.PRIVATE)
async def menu_stats_msg(message: types.Message):
    await message.reply(get_stats_message_text(message.from_user.id))

@dp.message_handler(lambda message: message.text == "🔗 رابط الإحالة", chat_type=types.ChatType.PRIVATE)
async def menu_ref_link_msg(message: types.Message):
    text = await get_ref_link_message_text(message.from_user.id)
    await message.reply(text)

@dp.message_handler(lambda message: message.text == "🏆 أفضل المستخدمين", chat_type=types.ChatType.PRIVATE)
async def menu_leaderboard_msg(message: types.Message):
    await message.reply(get_leaderboard_message_text())

@dp.message_handler(lambda message: message.text == "ℹ️ معلومات البوت", chat_type=types.ChatType.PRIVATE)
async def menu_info_msg(message: types.Message):
    await message.reply(get_info_message_text())

@dp.message_handler(lambda message: message.text == "⚙️ لوحة التحكم", chat_type=types.ChatType.PRIVATE)
async def menu_admin_panel_msg(message: types.Message):
    if message.from_user.id != config.OWNER_ID:
        return
    await message.reply("⚙️ <b>أهلاً بك يا مالك البوت في لوحة التحكم:</b>", reply_markup=keyboards.get_admin_panel_keyboard())

# --- Streak Handlers ---
@dp.message_handler(commands=['streak'], chat_type=types.ChatType.PRIVATE)
@dp.message_handler(lambda message: message.text == "🔥 سلسلة النشاط", chat_type=types.ChatType.PRIVATE)
async def cmd_streak(message: types.Message):
    user_id = message.from_user.id
    
    # Check if user's streak broke and notify them in private chat
    streak_data = database.get_or_update_user_streak(user_id)
    if streak_data and streak_data.get('streak_broken'):
        try:
            await bot.send_message(
                user_id,
                f"💔 <b>انقطعت سلسلة نشاطك</b>\n\n"
                f"📅 السلسلة السابقة: {streak_data['previous_streak']} يوم\n"
                f"🏆 أعلى سلسلة: {streak_data['best_streak']} يوم"
            )
        except Exception:
            pass
            
    await message.reply(get_streak_message_text(user_id))

@dp.message_handler(commands=['streaktop'], chat_type=types.ChatType.PRIVATE)
@dp.message_handler(lambda message: message.text == "🏆 ترتيب الستريك", chat_type=types.ChatType.PRIVATE)
async def cmd_streaktop(message: types.Message):
    await message.reply(get_streak_leaderboard_message_text())

@dp.callback_query_handler(lambda call: call.data == "user_streak", state="*")
async def user_streak_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    # Check if user's streak broke
    streak_data = database.get_or_update_user_streak(user_id)
    if streak_data and streak_data.get('streak_broken'):
        try:
            await bot.send_message(
                user_id,
                f"💔 <b>انقطعت سلسلة نشاطك</b>\n\n"
                f"📅 السلسلة السابقة: {streak_data['previous_streak']} يوم\n"
                f"🏆 أعلى سلسلة: {streak_data['best_streak']} يوم"
            )
        except Exception:
            pass
            
    await call.message.reply(get_streak_message_text(user_id))
    await call.answer()

@dp.callback_query_handler(lambda call: call.data == "user_streak_leaderboard", state="*")
async def user_streak_leaderboard_callback(call: types.CallbackQuery):
    await call.message.reply(get_streak_leaderboard_message_text())
    await call.answer()

@dp.callback_query_handler(lambda call: call.data == "check_join", state="*")
async def check_join_callback(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    
    # Register user in DB if not already (handles old members who never used /start)
    database.add_user(user_id, call.from_user.username, call.from_user.first_name)
    
    is_group_member = await is_user_member_of_group(user_id)
    is_channel_member = await is_user_member_of_channel(user_id)
    
    if is_group_member and is_channel_member:
        # Mark user as having started the bot
        database.add_user(user_id, call.from_user.username, call.from_user.first_name, has_started=1)
        
        await call.answer("✅ تم التحقق! أنت عضو في المجموعة والقناة.", show_alert=True)
        await state.finish()
        
        is_owner = (user_id == config.OWNER_ID)
        try:
            await call.message.edit_text(
                f"👋 <b>مرحباً بك {call.from_user.first_name}!</b>\n"
                f"✅ تم التحقق من عضويتك في المجموعة والقناة بنجاح.\n"
                f"يمكنك الآن استخدام البوت بشكل طبيعي.",
                reply_markup=None
            )
        except Exception:
            pass
            
        await bot.send_message(
            user_id,
            "🎮 تم تفعيل لوحة أزرار البوت بنجاح:",
            reply_markup=keyboards.get_user_main_keyboard(is_owner)
        )
    else:
        if not is_group_member and not is_channel_member:
            alert_text = "❌ لم يتم التحقق من انضمامك بعد!\nتأكد أنك انضممت للمجموعة والقناة ثم حاول مجدداً."
            text = "🚫 <b>يجب الانضمام للقروب والقناة أولاً لاستخدام البوت!</b>"
        elif not is_group_member:
            alert_text = "❌ لم يتم التحقق من انضمامك للمجموعة!\nتأكد أنك انضممت للمجموعة ثم حاول مجدداً."
            text = "🚫 <b>يجب الانضمام للقروب أولاً لاستخدام البوت!</b>"
        else:
            alert_text = "❌ لم يتم التحقق من انضمامك للقناة!\nتأكد أنك انضممت للقناة ثم حاول مجدداً."
            text = "🚫 <b>يجب الانضمام للقناة أولاً لاستخدام البوت!</b>"
            
        await call.answer(alert_text, show_alert=True)
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        if not is_group_member:
            markup.add(types.InlineKeyboardButton("📢 انضم للقروب", url=config.GROUP_LINK))
        if not is_channel_member:
            markup.add(types.InlineKeyboardButton("📢 انضم للقناة", url=config.CHANNEL_LINK))
        markup.add(types.InlineKeyboardButton("🔄 تحقق من الانضمام", callback_data="check_join"))
        
        try:
            await call.message.edit_text(
                text,
                reply_markup=markup
            )
        except Exception:
            pass

# --- Owner / Admin Control Panel Handlers ---

@dp.message_handler(commands=['admin'], chat_type=types.ChatType.PRIVATE)
async def cmd_admin(message: types.Message):
    if message.from_user.id != config.OWNER_ID:
        await message.reply("⚠️ عذراً، هذا الأمر مخصص لمالك البوت فقط.")
        return
    await message.reply("⚙️ <b>لوحة تحكم مالك البوت:</b>", reply_markup=keyboards.get_admin_panel_keyboard())

@dp.callback_query_handler(lambda call: call.data in ["admin_panel", "admin_panel_back"], state="*")
async def admin_panel_callback(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        await call.answer("❌ غير مصرح لك.", show_alert=True)
        return
    await state.finish()
    await call.message.edit_text("⚙️ <b>لوحة تحكم مالك البوت:</b>", reply_markup=keyboards.get_admin_panel_keyboard())
    await call.answer()

@dp.callback_query_handler(lambda call: call.data == "admin_close", state="*")
async def admin_close_callback(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        return
    await state.finish()
    await call.message.delete()
    await call.answer("تم إغلاق لوحة التحكم.")

@dp.callback_query_handler(lambda call: call.data == "admin_general_stats")
async def admin_general_stats_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    stats = database.get_general_stats()
    text = (
        f"📊 <b>إحصائيات عامة للبوت:</b>\n\n"
        f"👥 <b>إجمالي الأعضاء المسجلين:</b> {stats['total_users']}\n"
        f"💬 <b>إجمالي رسائل المجموعة المقتفية:</b> {stats['total_messages']}\n\n"
        f"🔗 <b>تفاصيل الإحالات:</b>\n"
        f"  ├─ إجمالي الإحالات: {stats['total_referrals']}\n"
        f"  ├─ الإحالات المفعّلة: {stats['active_referrals']}\n"
        f"  └─ الإحالات قيد الانتظار: {stats['pending_referrals']}\n\n"
        f"🚫 <b>الأعضاء المحظورين:</b> {stats['banned_users']}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ العودة للوحة التحكم", callback_data="admin_panel_back"))
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()

@dp.callback_query_handler(lambda call: call.data.startswith("admin_list_users:"))
async def admin_list_users_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    page = int(call.data.split(':')[1])
    users_per_page = 5
    offset = page * users_per_page
    
    total_users = database.get_users_count()
    if total_users == 0:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ العودة للوحة التحكم", callback_data="admin_panel_back"))
        await call.message.edit_text("👤 لا يوجد مستخدمين مسجلين في البوت حالياً.", reply_markup=markup)
        await call.answer()
        return
        
    total_pages = math.ceil(total_users / users_per_page)
    if page >= total_pages:
        page = total_pages - 1
        offset = page * users_per_page
        
    users = database.get_all_users(limit=users_per_page, offset=offset)
    markup = keyboards.get_users_list_keyboard(users, page, total_pages)
    await call.message.edit_text("👤 <b>قائمة المستخدمين المسجلين في البوت:</b>\nاختر مستخدم لإدارته:", reply_markup=markup)
    await call.answer()

@dp.callback_query_handler(lambda call: call.data.startswith("admin_view_user:"), state="*")
async def admin_view_user_callback(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        return
    await state.finish()  # Clear state if any
    
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    stats = database.get_user_stats(user_id)
    if not stats:
        await call.answer("❌ لم يتم العثور على هذا المستخدم.", show_alert=True)
        return
        
    status_str = "🚫 محظور" if stats['is_banned'] else "✅ نشط"
    username_str = f"@{stats['username']}" if stats['username'] else "لا يوجد"
    
    text = (
        f"👤 <b>تفاصيل المستخدم:</b> {stats['first_name']}\n\n"
        f"🆔 <b>معرف الحساب:</b> <code>{user_id}</code>\n"
        f"🏷️ <b>اسم المستخدم:</b> {username_str}\n"
        f"📅 <b>تاريخ الانضمام:</b> {stats['joined_at']}\n"
        f"⚡ <b>حالة الحساب:</b> {status_str}\n\n"
        f"💬 <b>رسائل المجموعة:</b> {stats['group_messages']}\n"
        f"👥 <b>الإحالات (مفعّلة/الكل):</b> {stats['active_referrals']} / {stats['active_referrals'] + stats['pending_referrals']}\n\n"
        f"🪙 <b>تفاصيل النقاط:</b>\n"
        f"  ├─ نقاط الإحالات: +{stats['referral_points']}\n"
        f"  ├─ نقاط المكافأة: +{stats['bonus_points']}\n"
        f"  ├─ نقاط التفاعل: +{stats['interaction_points']}\n"
        f"  ├─ تعديل الإدارة: {stats['admin_adjusted_points']}\n"
        f"  └─ إجمالي النقاط: <b>{stats['total_points']}</b>"
    )
    
    if stats['referred_by']:
        text += f"\n\n🔗 <b>تمت دعوته بواسطة:</b> <code>{stats['referred_by']}</code>\n"
        text += f"   └─ حالة الإحالة: {stats['referred_by_status']} (رسائله: {stats['referred_by_messages']}/{config.REFERRAL_REQUIRED_MESSAGES})"
        
    markup = keyboards.get_user_manage_keyboard(user_id, stats['is_banned'], page)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()

# Search flow
@dp.callback_query_handler(lambda call: call.data in [
    "admin_search_user", "admin_action_ban", "admin_action_add_pts", "admin_action_sub_pts", "admin_action_reset"
])
async def admin_search_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        return
    await call.message.edit_text(
        "🔎 <b>أرسل معرف المستخدم (ID) أو اسم المستخدم للبحث عنه وإدارته:</b>",
        reply_markup=keyboards.get_cancel_keyboard()
    )
    await AdminStates.waiting_search_query.set()
    await call.answer()

@dp.message_handler(state=AdminStates.waiting_search_query, chat_type=types.ChatType.PRIVATE)
async def admin_search_process(message: types.Message, state: FSMContext):
    if message.from_user.id != config.OWNER_ID:
        return
    query = message.text.strip()
    
    if query.startswith('@'):
        query = query[1:]
        
    users = database.search_users(query)
    
    if not users:
        await message.reply(
            "❌ <b>لم يتم العثور على أي مستخدم يطابق هذا البحث.</b>\n\nأرسل اسماً آخر أو معرفاً جديداً، أو اضغط إلغاء:",
            reply_markup=keyboards.get_cancel_keyboard()
        )
        return
        
    await state.finish()
    
    if len(users) == 1:
        user_id = users[0]['user_id']
        stats = database.get_user_stats(user_id)
        status_str = "🚫 محظور" if stats['is_banned'] else "✅ نشط"
        username_str = f"@{stats['username']}" if stats['username'] else "لا يوجد"
        
        text = (
            f"👤 <b>تفاصيل المستخدم المكتشف:</b> {stats['first_name']}\n\n"
            f"🆔 <b>معرف الحساب:</b> <code>{user_id}</code>\n"
            f"🏷️ <b>اسم المستخدم:</b> {username_str}\n"
            f"📅 <b>تاريخ الانضمام:</b> {stats['joined_at']}\n"
            f"⚡ <b>حالة الحساب:</b> {status_str}\n\n"
            f"💬 <b>رسائل المجموعة:</b> {stats['group_messages']}\n"
            f"👥 <b>الإحالات (مفعّلة/الكل):</b> {stats['active_referrals']} / {stats['active_referrals'] + stats['pending_referrals']}\n\n"
            f"🪙 <b>إجمالي النقاط:</b> <b>{stats['total_points']}</b>"
        )
        markup = keyboards.get_user_manage_keyboard(user_id, stats['is_banned'], return_page=0)
        await message.reply(text, reply_markup=markup)
    else:
        markup = types.InlineKeyboardMarkup(row_width=1)
        for u in users:
            name = u['first_name'] or "مستخدم"
            username_str = f" (@{u['username']})" if u['username'] else ""
            btn_text = f"{name}{username_str} [{u['user_id']}]"
            markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_view_user:{u['user_id']}:0"))
        markup.add(types.InlineKeyboardButton("⬅️ العودة للوحة التحكم", callback_data="admin_panel_back"))
        
        await message.reply("🔎 <b>نتائج البحث (اختر المستخدم المطلوب):</b>", reply_markup=markup)

# Points Addition flow
@dp.callback_query_handler(lambda call: call.data.startswith("admin_add_pts_state:"))
async def admin_add_pts_state_callback(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        return
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    await state.update_data(target_user_id=user_id, return_page=page)
    await AdminStates.waiting_add_points_amount.set()
    
    user_info = database.get_user(user_id)
    name = user_info['first_name'] if user_info else "المستخدم"
    
    await call.message.edit_text(
        f"🎯 <b>إضافة نقاط للمستخدم: {name} [ID: {user_id}]</b>\n\n"
        f"الرجاء إرسال عدد النقاط التي تريد إضافتها (رقم صحيح موجب):",
        reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}")
    )
    await call.answer()

@dp.message_handler(state=AdminStates.waiting_add_points_amount, chat_type=types.ChatType.PRIVATE)
async def admin_add_pts_process(message: types.Message, state: FSMContext):
    if message.from_user.id != config.OWNER_ID:
        return
        
    state_data = await state.get_data()
    user_id = state_data['target_user_id']
    page = state_data.get('return_page', 0)
    
    amount_str = message.text.strip()
    if not amount_str.isdigit():
        await message.reply(
            "❌ <b>القيمة غير صالحة.</b> الرجاء إرسال رقم صحيح موجب فقط:",
            reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}")
        )
        return
        
    amount = int(amount_str)
    success = database.adjust_user_points(user_id, amount)
    await state.finish()
    
    if success:
        try:
            await bot.send_message(
                user_id,
                f"🎁 <b>تعديل نقاط من الإدارة!</b>\n\n"
                f"لقد قام مالك البوت بإضافة <b>+{amount} نقطة</b> لحسابك."
            )
        except Exception:
            pass
            
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 عرض حساب المستخدم", callback_data=f"admin_view_user:{user_id}:{page}"))
        await message.reply(f"✅ تم إضافة <b>+{amount} نقطة</b> للمستخدم بنجاح.", reply_markup=markup)
    else:
        await message.reply("❌ حدث خطأ أثناء تعديل النقاط.", reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}"))

# Points Subtraction flow
@dp.callback_query_handler(lambda call: call.data.startswith("admin_sub_pts_state:"))
async def admin_sub_pts_state_callback(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        return
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    await state.update_data(target_user_id=user_id, return_page=page)
    await AdminStates.waiting_sub_points_amount.set()
    
    user_info = database.get_user(user_id)
    name = user_info['first_name'] if user_info else "المستخدم"
    
    await call.message.edit_text(
        f"❌ <b>خصم نقاط من المستخدم: {name} [ID: {user_id}]</b>\n\n"
        f"الرجاء إرسال عدد النقاط التي تريد خصمها (رقم صحيح موجب):",
        reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}")
    )
    await call.answer()

@dp.message_handler(state=AdminStates.waiting_sub_points_amount, chat_type=types.ChatType.PRIVATE)
async def admin_sub_pts_process(message: types.Message, state: FSMContext):
    if message.from_user.id != config.OWNER_ID:
        return
        
    state_data = await state.get_data()
    user_id = state_data['target_user_id']
    page = state_data.get('return_page', 0)
    
    amount_str = message.text.strip()
    if not amount_str.isdigit():
        await message.reply(
            "❌ <b>القيمة غير صالحة.</b> الرجاء إرسال رقم صحيح موجب فقط:",
            reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}")
        )
        return
        
    amount = int(amount_str)
    # Deduct means negative adjustment
    success = database.adjust_user_points(user_id, -amount)
    await state.finish()
    
    if success:
        try:
            await bot.send_message(
                user_id,
                f"⚠️ <b>تعديل نقاط من الإدارة!</b>\n\n"
                f"لقد قام مالك البوت بخصم <b>-{amount} نقطة</b> من حسابك."
            )
        except Exception:
            pass
            
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 عرض حساب المستخدم", callback_data=f"admin_view_user:{user_id}:{page}"))
        await message.reply(f"✅ تم خصم <b>-{amount} نقطة</b> من المستخدم بنجاح.", reply_markup=markup)
    else:
        await message.reply("❌ حدث خطأ أثناء تعديل النقاط.", reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}"))

# Ban flow
@dp.callback_query_handler(lambda call: call.data.startswith("admin_ban_confirm:"))
async def admin_ban_confirm_callback(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != config.OWNER_ID:
        return
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    await state.update_data(target_user_id=user_id, return_page=page)
    await AdminStates.waiting_ban_reason.set()
    
    user_info = database.get_user(user_id)
    name = user_info['first_name'] if user_info else "المستخدم"
    
    await call.message.edit_text(
        f"🚫 <b>حظر المستخدم: {name} [ID: {user_id}]</b>\n\n"
        f"الرجاء إرسال سبب الحظر (أو اكتب 'بدون سبب'):",
        reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}")
    )
    await call.answer()

@dp.message_handler(state=AdminStates.waiting_ban_reason, chat_type=types.ChatType.PRIVATE)
async def admin_ban_process(message: types.Message, state: FSMContext):
    if message.from_user.id != config.OWNER_ID:
        return
    state_data = await state.get_data()
    user_id = state_data['target_user_id']
    page = state_data.get('return_page', 0)
    reason = message.text.strip()
    
    success = database.ban_user(user_id, reason)
    await state.finish()
    
    if success:
        try:
            await bot.send_message(
                user_id,
                f"🚫 <b>تم حظر حسابك من استخدام البوت!</b>\n\n"
                f"📝 <b>السبب:</b> {reason}"
            )
        except Exception:
            pass
            
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 عرض حساب المستخدم", callback_data=f"admin_view_user:{user_id}:{page}"))
        await message.reply("✅ تم حظر المستخدم بنجاح.", reply_markup=markup)
    else:
        await message.reply("❌ حدث خطأ أثناء محاولة حظر المستخدم.", reply_markup=keyboards.get_cancel_keyboard(f"admin_view_user:{user_id}:{page}"))

# Unban flow
@dp.callback_query_handler(lambda call: call.data.startswith("admin_unban_confirm:"))
async def admin_unban_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    success = database.unban_user(user_id)
    if success:
        try:
            await bot.send_message(user_id, "🔓 <b>تم إلغاء حظر حسابك! يمكنك استخدام البوت الآن.</b>")
        except Exception:
            pass
        await call.answer("✅ تم إلغاء الحظر بنجاح.", show_alert=True)
        
        stats = database.get_user_stats(user_id)
        status_str = "✅ نشط"
        username_str = f"@{stats['username']}" if stats['username'] else "لا يوجد"
        text = (
            f"👤 <b>تفاصيل المستخدم:</b> {stats['first_name']}\n\n"
            f"🆔 <b>معرف الحساب:</b> <code>{user_id}</code>\n"
            f"🏷️ <b>اسم المستخدم:</b> {username_str}\n"
            f"📅 <b>تاريخ الانضمام:</b> {stats['joined_at']}\n"
            f"⚡ <b>حالة الحساب:</b> {status_str}\n\n"
            f"💬 <b>رسائل المجموعة:</b> {stats['group_messages']}\n"
            f"👥 <b>الإحالات (مفعّلة/الكل):</b> {stats['active_referrals']} / {stats['active_referrals'] + stats['pending_referrals']}\n\n"
            f"🪙 <b>إجمالي النقاط:</b> <b>{stats['total_points']}</b>"
        )
        markup = keyboards.get_user_manage_keyboard(user_id, False, page)
        await call.message.edit_text(text, reply_markup=markup)
    else:
        await call.answer("❌ حدث خطأ أثناء إلغاء الحظر.", show_alert=True)

# Reset flow
@dp.callback_query_handler(lambda call: call.data.startswith("admin_reset_confirm:"))
async def admin_reset_confirm_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    user_info = database.get_user(user_id)
    name = user_info['first_name'] if user_info else "المستخدم"
    
    text = (
        f"⚠️ <b>تحذير هام!</b>\n\n"
        f"هل أنت متأكد من رغبتك في إعادة تعيين جميع بيانات المستخدم <b>{name} [ID: {user_id}]</b>؟\n\n"
        f"هذا الإجراء سيقوم بـ:\n"
        f"• تصفير رسائل العضو في القروب.\n"
        f"• حذف كافة الإحالات التي جلبها.\n"
        f"• تصفير نقاطه بالكامل.\n"
        f"• <b>لا يمكن التراجع عن هذا الإجراء!</b>"
    )
    markup = keyboards.get_confirm_keyboard("reset", user_id, page)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()

@dp.callback_query_handler(lambda call: call.data.startswith("admin_execute_reset:"))
async def admin_execute_reset_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    _, user_id_str, page_str = call.data.split(':')
    user_id = int(user_id_str)
    page = int(page_str)
    
    success = database.reset_user_data(user_id)
    if success:
        try:
            await bot.send_message(
                user_id,
                "🔄 <b>تم إعادة تعيين بيانات حسابك ونقاطك من قبل الإدارة!</b>"
            )
        except Exception:
            pass
        await call.answer("✅ تم إعادة تعيين البيانات بنجاح.", show_alert=True)
        
        stats = database.get_user_stats(user_id)
        status_str = "🚫 محظور" if stats['is_banned'] else "✅ نشط"
        username_str = f"@{stats['username']}" if stats['username'] else "لا يوجد"
        text = (
            f"👤 <b>تفاصيل المستخدم:</b> {stats['first_name']}\n\n"
            f"🆔 <b>معرف الحساب:</b> <code>{user_id}</code>\n"
            f"🏷️ <b>اسم المستخدم:</b> {username_str}\n"
            f"📅 <b>تاريخ الانضمام:</b> {stats['joined_at']}\n"
            f"⚡ <b>حالة الحساب:</b> {status_str}\n\n"
            f"💬 <b>رسائل المجموعة:</b> {stats['group_messages']}\n"
            f"👥 <b>الإحالات (مفعّلة/الكل):</b> {stats['active_referrals']} / {stats['active_referrals'] + stats['pending_referrals']}\n\n"
            f"🪙 <b>إجمالي النقاط:</b> <b>{stats['total_points']}</b>"
        )
        markup = keyboards.get_user_manage_keyboard(user_id, stats['is_banned'], page)
        await call.message.edit_text(text, reply_markup=markup)
    else:
        await call.answer("❌ حدث خطأ أثناء محاولة تصفير البيانات.", show_alert=True)

# Reset all database flow
@dp.callback_query_handler(lambda call: call.data == "admin_reset_db_confirm")
async def admin_reset_db_confirm_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    
    text = (
        "⚠️ <b>تحذير هام جداً!</b>\n\n"
        "هل أنت متأكد من رغبتك في <b>تصفير قاعدة البيانات بالكامل</b>؟\n\n"
        "هذا الإجراء سيقوم بحذف:\n"
        "• كافة المستخدمين المسجلين.\n"
        "• كافة الإحالات (المعلقة والنشطة).\n"
        "• كافة رسائل المجموعة المسجلة.\n"
        "• كافة النقاط وجميع التعديلات.\n\n"
        "🚨 <b>لا يمكن التراجع عن هذا الإجراء نهائياً!</b>"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🗑️ نعم، صفر قاعدة البيانات", callback_data="admin_reset_db_execute"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel_back")
    )
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()

@dp.callback_query_handler(lambda call: call.data == "admin_reset_db_execute")
async def admin_reset_db_execute_callback(call: types.CallbackQuery):
    if call.from_user.id != config.OWNER_ID:
        return
    
    success = database.reset_all_database()
    if success:
        await call.answer("✅ تم تصفير قاعدة البيانات بالكامل بنجاح!", show_alert=True)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ العودة للوحة التحكم", callback_data="admin_panel_back"))
        await call.message.edit_text("✅ <b>تم تصفير قاعدة البيانات بالكامل بنجاح!</b>\n\nتم حذف كافة البيانات والبدء من جديد.", reply_markup=markup)
    else:
        await call.answer("❌ حدث خطأ غير متوقع أثناء تصفير قاعدة البيانات.", show_alert=True)

# --- Startup / Shutdown ---
async def on_startup(dispatcher):
    print("Initializing Database...")
    database.init_db()
    print("Database Initialized successfully.")

if __name__ == '__main__':
    # Warn user if they have not set up the token
    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("WARNING: Please replace 'YOUR_BOT_TOKEN_HERE' in config.py or set the BOT_TOKEN environment variable.")
    
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
