from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_user_main_keyboard(is_owner=False):
    """Returns the main Reply Keyboard for users."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📊 إحصائياتي"),
        KeyboardButton("🔗 رابط الإحالة")
    )
    markup.add(
        KeyboardButton("🏆 أفضل المستخدمين"),
        KeyboardButton("ℹ️ معلومات البوت")
    )
    if is_owner:
        markup.add(KeyboardButton("⚙️ لوحة التحكم"))
    return markup

def get_user_inline_menu(is_owner=False):
    """Returns the main Inline Keyboard for user actions."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 إحصائياتي", callback_data="user_stats"),
        InlineKeyboardButton("🔗 رابط الإحالة", callback_data="user_ref_link")
    )
    markup.add(
        InlineKeyboardButton("🏆 أفضل المستخدمين", callback_data="user_leaderboard"),
        InlineKeyboardButton("ℹ️ معلومات البوت", callback_data="user_info")
    )
    if is_owner:
        markup.add(InlineKeyboardButton("⚙️ لوحة التحكم (المالك)", callback_data="admin_panel"))
    return markup

def get_admin_panel_keyboard():
    """Returns the Admin Control Panel Inline Keyboard."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👤 عرض قائمة المستخدمين", callback_data="admin_list_users:0"),
        InlineKeyboardButton("🔍 البحث عن مستخدم", callback_data="admin_search_user")
    )
    markup.add(
        InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_action_ban"),
        InlineKeyboardButton("🎯 إضافة نقاط", callback_data="admin_action_add_pts")
    )
    markup.add(
        InlineKeyboardButton("❌ حذف نقاط", callback_data="admin_action_sub_pts"),
        InlineKeyboardButton("🔄 إعادة تعيين مستخدم", callback_data="admin_action_reset")
    )
    markup.add(
        InlineKeyboardButton("📊 إحصائيات عامة للبوت", callback_data="admin_general_stats")
    )
    markup.add(
        InlineKeyboardButton("🗑️ تصفير قاعدة البيانات", callback_data="admin_reset_db_confirm")
    )
    markup.add(
        InlineKeyboardButton("❌ إغلاق لوحة التحكم", callback_data="admin_close")
    )
    return markup

def get_users_list_keyboard(users, page, total_pages):
    """Returns an inline keyboard with list of users and pagination controls."""
    markup = InlineKeyboardMarkup(row_width=2)
    
    for u in users:
        # Create a button for each user
        name = u['first_name'] or "مستخدم"
        username_str = f" (@{u['username']})" if u['username'] else ""
        btn_text = f"{name}{username_str} [{u['user_id']}]"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"admin_view_user:{u['user_id']}:{page}"))
        
    # Pagination row
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_list_users:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"صفحة {page+1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_list_users:{page+1}"))
        
    markup.row(*nav_buttons)
    markup.add(InlineKeyboardButton("⬅️ العودة للوحة التحكم", callback_data="admin_panel_back"))
    return markup

def get_user_manage_keyboard(user_id, is_banned, return_page=0):
    """Returns options for managing a specific user."""
    markup = InlineKeyboardMarkup(row_width=2)
    
    ban_btn_text = "🔓 إلغاء الحظر" if is_banned else "🚫 حظر المستخدم"
    ban_btn_callback = f"admin_unban_confirm:{user_id}:{return_page}" if is_banned else f"admin_ban_confirm:{user_id}:{return_page}"
    
    markup.add(
        InlineKeyboardButton("🎯 إضافة نقاط", callback_data=f"admin_add_pts_state:{user_id}:{return_page}"),
        InlineKeyboardButton("❌ حذف نقاط", callback_data=f"admin_sub_pts_state:{user_id}:{return_page}")
    )
    markup.add(
        InlineKeyboardButton(ban_btn_text, callback_data=ban_btn_callback),
        InlineKeyboardButton("🔄 إعادة تعيين البيانات", callback_data=f"admin_reset_confirm:{user_id}:{return_page}")
    )
    markup.add(InlineKeyboardButton("⬅️ العودة لقائمة المستخدمين", callback_data=f"admin_list_users:{return_page}"))
    return markup

def get_confirm_keyboard(action, target_user_id, return_page=0):
    """General confirmation keyboard."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ تأكيد", callback_data=f"admin_execute_{action}:{target_user_id}:{return_page}"),
        InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_view_user:{target_user_id}:{return_page}")
    )
    return markup

def get_cancel_keyboard(callback_data="admin_panel_back"):
    """Returns a simple keyboard with a Cancel button."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ إلغاء العملية", callback_data=callback_data))
    return markup
