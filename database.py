import sqlite3
import os
from datetime import datetime
import config

def get_db_connection():
    conn = sqlite3.connect(config.DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_banned INTEGER DEFAULT 0,
        has_started INTEGER DEFAULT 0
    )
    """)
    
    # Check if has_started column exists in users
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'has_started' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN has_started INTEGER DEFAULT 0")
        conn.commit()
    
    # Create referrals table
    # status can be 'pending' or 'active'
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        referrer_id INTEGER,
        referred_id INTEGER PRIMARY KEY,
        messages_sent INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (referred_id) REFERENCES users(user_id)
    )
    """)
    
    # Create message_counts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS message_counts (
        user_id INTEGER PRIMARY KEY,
        group_messages INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)
    
    # Create points table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS points (
        user_id INTEGER PRIMARY KEY,
        referral_points INTEGER DEFAULT 0,
        bonus_points INTEGER DEFAULT 0,
        interaction_points INTEGER DEFAULT 0,
        admin_adjusted_points INTEGER DEFAULT 0,
        total_points INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)
    
    # Create bans table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        reason TEXT,
        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)
    
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name, has_started=0):
    """Registers a user if they don't already exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if user already exists
        cursor.execute("SELECT user_id, has_started FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO users (user_id, username, first_name, has_started) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, has_started)
            )
            # Initialize message count
            cursor.execute(
                "INSERT OR IGNORE INTO message_counts (user_id, group_messages) VALUES (?, 0)",
                (user_id,)
            )
            # Initialize points
            cursor.execute(
                "INSERT OR IGNORE INTO points (user_id, referral_points, bonus_points, interaction_points, admin_adjusted_points, total_points) VALUES (?, 0, 0, 0, 0, 0)",
                (user_id,)
            )
            conn.commit()
            return True
        else:
            # Update username/first_name, and set has_started to 1 if passed as 1
            if has_started == 1:
                cursor.execute(
                    "UPDATE users SET username = ?, first_name = ?, has_started = 1 WHERE user_id = ?",
                    (username, first_name, user_id)
                )
            else:
                cursor.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (username, first_name, user_id)
                )
            conn.commit()
            return False
    finally:
        conn.close()

def is_user_banned(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return bool(row['is_banned'])
    return False

def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def add_referral(referrer_id, referred_id):
    """
    Registers a referral.
    Returns True if successfully registered, False if already registered or self-referred.
    """
    if referrer_id == referred_id:
        return False
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if referred user has already started the bot in the past
        cursor.execute("SELECT has_started FROM users WHERE user_id = ?", (referred_id,))
        row = cursor.fetchone()
        if row is not None and row['has_started'] == 1:
            # Already started bot privately before, cannot refer
            return False
            
        # Check if referral link already exists in referrals table
        cursor.execute("SELECT referred_id FROM referrals WHERE referred_id = ?", (referred_id,))
        if cursor.fetchone() is not None:
            return False
            
        # Get current group messages for this user if they exist
        cursor.execute("SELECT group_messages FROM message_counts WHERE user_id = ?", (referred_id,))
        row_msg = cursor.fetchone()
        current_msgs = row_msg['group_messages'] if row_msg else 0
        
        # Determine status based on current messages
        status = 'pending'
        if current_msgs >= config.REFERRAL_REQUIRED_MESSAGES:
            status = 'active'
            
        # Add to referrals table
        cursor.execute(
            "INSERT INTO referrals (referrer_id, referred_id, messages_sent, status) VALUES (?, ?, ?, ?)",
            (referrer_id, referred_id, current_msgs, status)
        )
        
        if status == 'active':
            # Ensure referrer is initialized in points table
            cursor.execute(
                "INSERT OR IGNORE INTO points (user_id, referral_points, bonus_points, interaction_points, admin_adjusted_points, total_points) VALUES (?, 0, 0, 0, 0, 0)",
                (referrer_id,)
            )
            # Recalculate referrer points
            recalculate_referrer_points(referrer_id, cursor)
            
        conn.commit()
        return True
    finally:
        conn.close()

def recalculate_referrer_points(referrer_id, cursor):
    """Recalculates points for a referrer within an open transaction."""
    # Count active referrals
    cursor.execute(
        "SELECT COUNT(*) as active_count FROM referrals WHERE referrer_id = ? AND status = 'active'",
        (referrer_id,)
    )
    active_count = cursor.fetchone()['active_count']
    
    # 1 point per active referral
    referral_points = active_count
    
    # 5 bonus points for every 10 active referrals
    bonus_points = (active_count // 10) * 5
    
    # Update points table
    cursor.execute(
        """
        UPDATE points 
        SET referral_points = ?, bonus_points = ?,
            total_points = ? + ? + interaction_points + admin_adjusted_points
        WHERE user_id = ?
        """,
        (referral_points, bonus_points, referral_points, bonus_points, referrer_id)
    )

def increment_message_count(user_id):
    """
    Increments user group message count.
    Also handles pending referral progression and interaction points (+1 for every 20 messages).
    
    Returns:
        dict: {
            'interaction_point_earned': bool,
            'referral_activated': bool,
            'referrer_id': int or None,
            'messages_sent': int,
            'group_messages': int
        }
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    result = {
        'interaction_point_earned': False,
        'referral_activated': False,
        'referrer_id': None,
        'messages_sent': 0,
        'group_messages': 0
    }
    
    try:
        # Get current message count
        cursor.execute("SELECT group_messages FROM message_counts WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO message_counts (user_id, group_messages) VALUES (?, 0)", (user_id,))
            old_messages = 0
        else:
            old_messages = row['group_messages']
            
        new_messages = old_messages + 1
        result['group_messages'] = new_messages
        
        # Update message count
        cursor.execute(
            "UPDATE message_counts SET group_messages = ? WHERE user_id = ?",
            (new_messages, user_id)
        )
        
        # Check interaction points (1 point per 20 messages)
        old_interaction_pts = old_messages // 20
        new_interaction_pts = new_messages // 20
        if new_interaction_pts > old_interaction_pts:
            result['interaction_point_earned'] = True
            cursor.execute(
                """
                UPDATE points 
                SET interaction_points = ?,
                    total_points = referral_points + bonus_points + ? + admin_adjusted_points
                WHERE user_id = ?
                """,
                (new_interaction_pts, new_interaction_pts, user_id)
            )
            
        # Check if user has a pending referral
        cursor.execute(
            "SELECT referrer_id, messages_sent, status FROM referrals WHERE referred_id = ? AND status = 'pending'",
            (user_id,)
        )
        ref_row = cursor.fetchone()
        if ref_row:
            referrer_id = ref_row['referrer_id']
            curr_ref_msgs = ref_row['messages_sent'] + 1
            result['messages_sent'] = curr_ref_msgs
            
            if curr_ref_msgs >= config.REFERRAL_REQUIRED_MESSAGES:
                # Activate referral
                cursor.execute(
                    "UPDATE referrals SET messages_sent = ?, status = 'active' WHERE referred_id = ?",
                    (curr_ref_msgs, user_id)
                )
                
                # Ensure referrer is initialized in points table
                cursor.execute(
                    "INSERT OR IGNORE INTO points (user_id, referral_points, bonus_points, interaction_points, admin_adjusted_points, total_points) VALUES (?, 0, 0, 0, 0, 0)",
                    (referrer_id,)
                )
                
                # Recalculate referrer points
                recalculate_referrer_points(referrer_id, cursor)
                
                result['referral_activated'] = True
                result['referrer_id'] = referrer_id
            else:
                # Update messages sent in referrals
                cursor.execute(
                    "UPDATE referrals SET messages_sent = ? WHERE referred_id = ?",
                    (curr_ref_msgs, user_id)
                )
                
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
        
    return result

def get_user_stats(user_id):
    """Gets stats for a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    # User info
    cursor.execute("SELECT username, first_name, joined_at, is_banned FROM users WHERE user_id = ?", (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return None
        
    stats['username'] = user_row['username']
    stats['first_name'] = user_row['first_name']
    stats['joined_at'] = user_row['joined_at']
    stats['is_banned'] = bool(user_row['is_banned'])
    
    # Message counts
    cursor.execute("SELECT group_messages FROM message_counts WHERE user_id = ?", (user_id,))
    msg_row = cursor.fetchone()
    stats['group_messages'] = msg_row['group_messages'] if msg_row else 0
    
    # Points details
    cursor.execute(
        """
        SELECT referral_points, bonus_points, interaction_points, admin_adjusted_points, total_points 
        FROM points WHERE user_id = ?
        """,
        (user_id,)
    )
    pts_row = cursor.fetchone()
    if pts_row:
        stats['referral_points'] = pts_row['referral_points']
        stats['bonus_points'] = pts_row['bonus_points']
        stats['interaction_points'] = pts_row['interaction_points']
        stats['admin_adjusted_points'] = pts_row['admin_adjusted_points']
        stats['total_points'] = pts_row['total_points']
    else:
        stats['referral_points'] = 0
        stats['bonus_points'] = 0
        stats['interaction_points'] = 0
        stats['admin_adjusted_points'] = 0
        stats['total_points'] = 0
        
    # Referrals counts
    cursor.execute("SELECT COUNT(*) as pending_count FROM referrals WHERE referrer_id = ? AND status = 'pending'", (user_id,))
    stats['pending_referrals'] = cursor.fetchone()['pending_count']
    
    cursor.execute("SELECT COUNT(*) as active_count FROM referrals WHERE referrer_id = ? AND status = 'active'", (user_id,))
    stats['active_referrals'] = cursor.fetchone()['active_count']
    
    # Check who referred this user
    cursor.execute("SELECT referrer_id, messages_sent, status FROM referrals WHERE referred_id = ?", (user_id,))
    ref_by_row = cursor.fetchone()
    if ref_by_row:
        stats['referred_by'] = ref_by_row['referrer_id']
        stats['referred_by_messages'] = ref_by_row['messages_sent']
        stats['referred_by_status'] = ref_by_row['status']
    else:
        stats['referred_by'] = None
        stats['referred_by_messages'] = 0
        stats['referred_by_status'] = None
        
    conn.close()
    return stats

def get_leaderboard(limit=10):
    """Gets top users sorted by points, then by active referrals count."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.user_id, u.username, u.first_name, p.total_points, mc.group_messages,
               (SELECT COUNT(*) FROM referrals r WHERE r.referrer_id = u.user_id AND r.status = 'active') as active_referrals
        FROM users u 
        JOIN points p ON u.user_id = p.user_id 
        LEFT JOIN message_counts mc ON u.user_id = mc.user_id 
        WHERE u.is_banned = 0 
        ORDER BY p.total_points DESC, active_referrals DESC 
        LIMIT ?
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_users(limit=100, offset=0):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_users_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    count = cursor.fetchone()['count']
    conn.close()
    return count

def search_users(query):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Search by username, first_name, or user_id
    search_pattern = f"%{query}%"
    try:
        user_id_query = int(query)
    except ValueError:
        user_id_query = -1
        
    cursor.execute(
        """
        SELECT * FROM users 
        WHERE username LIKE ? OR first_name LIKE ? OR user_id = ?
        LIMIT 20
        """,
        (search_pattern, search_pattern, user_id_query)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def ban_user(user_id, reason="No reason provided"):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        cursor.execute(
            "INSERT OR REPLACE INTO bans (user_id, reason) VALUES (?, ?)",
            (user_id, reason)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def unban_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def adjust_user_points(user_id, amount):
    """Manually add or subtract points for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Get current admin adjustment
        cursor.execute("SELECT admin_adjusted_points FROM points WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                "INSERT INTO points (user_id, referral_points, bonus_points, interaction_points, admin_adjusted_points, total_points) VALUES (?, 0, 0, 0, ?, ?)",
                (user_id, amount, amount)
            )
        else:
            new_adjustment = row['admin_adjusted_points'] + amount
            cursor.execute(
                """
                UPDATE points 
                SET admin_adjusted_points = ?,
                    total_points = referral_points + bonus_points + interaction_points + ?
                WHERE user_id = ?
                """,
                (new_adjustment, new_adjustment, user_id)
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def reset_user_data(user_id):
    """Resets user stats and points."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Reset group messages
        cursor.execute("UPDATE message_counts SET group_messages = 0 WHERE user_id = ?", (user_id,))
        
        # Reset points
        cursor.execute(
            """
            UPDATE points 
            SET referral_points = 0, bonus_points = 0, interaction_points = 0, 
                admin_adjusted_points = 0, total_points = 0 
            WHERE user_id = ?
            """,
            (user_id,)
        )
        
        # Delete referrals invited by this user
        cursor.execute("DELETE FROM referrals WHERE referrer_id = ?", (user_id,))
        
        # Reset referrals where they were invited (back to pending and 0 messages)
        cursor.execute(
            "UPDATE referrals SET messages_sent = 0, status = 'pending' WHERE referred_id = ?",
            (user_id,)
        )
        
        conn.commit()
        
        # We need to recalculate points for any referrers of the deleted referrals?
        # Actually, if we delete referrals where referrer_id = user_id, that's fine.
        # But if we change referrals where referred_id = user_id from 'active' to 'pending',
        # we must recalculate points for the referrer!
        cursor.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (user_id,))
        ref_row = cursor.fetchone()
        if ref_row:
            referrer_id = ref_row['referrer_id']
            recalculate_referrer_points(referrer_id, cursor)
            conn.commit()
            
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def get_general_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    stats = {}
    
    # Total users
    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    stats['total_users'] = cursor.fetchone()['cnt']
    
    # Total messages
    cursor.execute("SELECT SUM(group_messages) as cnt FROM message_counts")
    row = cursor.fetchone()
    stats['total_messages'] = row['cnt'] if row['cnt'] is not None else 0
    
    # Total referrals
    cursor.execute("SELECT COUNT(*) as cnt FROM referrals")
    stats['total_referrals'] = cursor.fetchone()['cnt']
    
    # Active referrals
    cursor.execute("SELECT COUNT(*) as cnt FROM referrals WHERE status = 'active'")
    stats['active_referrals'] = cursor.fetchone()['cnt']
    
    # Pending referrals
    cursor.execute("SELECT COUNT(*) as cnt FROM referrals WHERE status = 'pending'")
    stats['pending_referrals'] = cursor.fetchone()['cnt']
    
    # Banned users
    cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 1")
    stats['banned_users'] = cursor.fetchone()['cnt']
    
    conn.close()
    return stats

def reset_all_database():
    """
    Wipes ALL data from all tables (users, referrals, message_counts, points, bans).
    Keeps the schema intact (tables remain but are emptied).
    Returns True on success, False on error.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM referrals")
        cursor.execute("DELETE FROM bans")
        cursor.execute("DELETE FROM points")
        cursor.execute("DELETE FROM message_counts")
        cursor.execute("DELETE FROM users")
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()
