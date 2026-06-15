import os
import shutil
import unittest
import config

# Use a separate test database
config.DB_NAME = "test_bot_database.db"

import database

class TestBotDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Remove any existing test database
        if os.path.exists(config.DB_NAME):
            os.remove(config.DB_NAME)

    def setUp(self):
        # Initialize fresh database for each test
        database.init_db()

    def tearDown(self):
        # Delete database file after each test to ensure clean state
        database.get_db_connection().close()
        if os.path.exists(config.DB_NAME):
            try:
                os.remove(config.DB_NAME)
            except PermissionError:
                pass

    def test_user_registration(self):
        # Add new user
        is_new = database.add_user(111, "alice", "Alice")
        self.assertTrue(is_new)
        
        # Check update username
        is_new = database.add_user(111, "alice_new", "Alice New")
        self.assertFalse(is_new)
        
        user = database.get_user(111)
        self.assertEqual(user['username'], "alice_new")
        self.assertEqual(user['first_name'], "Alice New")

    def test_referrals_and_self_referral(self):
        database.add_user(111, "alice", "Alice")
        
        # Self-referral should fail
        res = database.add_referral(111, 111)
        self.assertFalse(res)
        
        # Refer an existing user should fail
        database.add_user(222, "bob", "Bob", has_started=1)
        res = database.add_referral(111, 222)
        self.assertFalse(res)
        
        # Valid referral for new user
        res = database.add_referral(111, 333)
        self.assertTrue(res)

    def test_referral_activation_and_interaction_points(self):
        # Register referrer
        database.add_user(111, "alice", "Alice")
        
        # Register referral (referred_id = 222)
        res = database.add_referral(111, 222)
        self.assertTrue(res)
        
        # New user 222 starts the bot (adds to users table)
        database.add_user(222, "bob", "Bob")
        
        # Send 14 group messages, referral should still be pending
        for i in range(14):
            res_msg = database.increment_message_count(222)
            self.assertFalse(res_msg['referral_activated'])
            self.assertEqual(res_msg['messages_sent'], i + 1)
            
        stats_ref = database.get_user_stats(111)
        self.assertEqual(stats_ref['referral_points'], 0)
        self.assertEqual(stats_ref['total_points'], 0)
        
        # Send the 15th message. Referral should activate!
        res_msg = database.increment_message_count(222)
        self.assertTrue(res_msg['referral_activated'])
        self.assertEqual(res_msg['referrer_id'], 111)
        self.assertEqual(res_msg['messages_sent'], 15)
        
        # Check referrer stats
        stats_ref = database.get_user_stats(111)
        self.assertEqual(stats_ref['referral_points'], 1)
        self.assertEqual(stats_ref['total_points'], 1)
        
        # Continue Bob's messages up to 20 to check interaction points
        # Bob is at 15 messages. Let's send 4 more messages (total 19)
        for i in range(4):
            database.increment_message_count(222)
            
        bob_stats = database.get_user_stats(222)
        self.assertEqual(bob_stats['interaction_points'], 0)
        
        # Send Bob's 20th message. Bob gets +1 interaction point!
        res_msg = database.increment_message_count(222)
        self.assertTrue(res_msg['interaction_point_earned'])
        self.assertEqual(res_msg['group_messages'], 20)
        
        bob_stats = database.get_user_stats(222)
        self.assertEqual(bob_stats['interaction_points'], 1)
        self.assertEqual(bob_stats['total_points'], 1)

    def test_bonus_points_multiples_of_ten(self):
        # Register referrer
        database.add_user(111, "alice", "Alice")
        
        # Register 10 referrals and activate all of them
        for uid in range(200, 210):
            res_ref = database.add_referral(111, uid)
            self.assertTrue(res_ref)
            
            database.add_user(uid, f"user_{uid}", f"User {uid}")
            
            # Send 15 messages to activate this referral
            for _ in range(15):
                database.increment_message_count(uid)
                
        # Now Alice should have 10 active referrals, giving 10 points + 5 bonus points = 15 total points
        stats = database.get_user_stats(111)
        self.assertEqual(stats['active_referrals'], 10)
        self.assertEqual(stats['referral_points'], 10)
        self.assertEqual(stats['bonus_points'], 5)
        self.assertEqual(stats['total_points'], 15)

    def test_admin_functions_and_banning(self):
        database.add_user(111, "alice", "Alice")
        
        # Add points
        database.adjust_user_points(111, 25)
        stats = database.get_user_stats(111)
        self.assertEqual(stats['admin_adjusted_points'], 25)
        self.assertEqual(stats['total_points'], 25)
        
        # Deduct points
        database.adjust_user_points(111, -10)
        stats = database.get_user_stats(111)
        self.assertEqual(stats['admin_adjusted_points'], 15)
        self.assertEqual(stats['total_points'], 15)
        
        # Ban user
        self.assertFalse(database.is_user_banned(111))
        database.ban_user(111, "Abusing messages")
        self.assertTrue(database.is_user_banned(111))
        
        # Unban user
        database.unban_user(111)
        self.assertFalse(database.is_user_banned(111))

    def test_reset_user_data(self):
        # Set up a referrer (111) and referee (222)
        database.add_user(111, "alice", "Alice")
        database.add_referral(111, 222)
        database.add_user(222, "bob", "Bob")
        
        # Activate the referral
        for _ in range(15):
            database.increment_message_count(222)
            
        stats_111 = database.get_user_stats(111)
        self.assertEqual(stats_111['total_points'], 1)
        
        # Reset Alice's data
        database.reset_user_data(111)
        
        # Alice should have 0 active/pending referrals and 0 points
        stats_111 = database.get_user_stats(111)
        self.assertEqual(stats_111['active_referrals'], 0)
        self.assertEqual(stats_111['total_points'], 0)
        
        # The referral relation from Alice to Bob should be deleted
        stats_222 = database.get_user_stats(222)
        self.assertIsNone(stats_222['referred_by'])

    def test_reset_all_database(self):
        # Insert user, referrals, messages, etc.
        database.add_user(111, "alice", "Alice")
        database.add_referral(111, 222)
        database.add_user(222, "bob", "Bob")
        database.increment_message_count(222)
        
        # Verify they exist
        self.assertIsNotNone(database.get_user(111))
        self.assertIsNotNone(database.get_user(222))
        
        # Reset entire database
        res = database.reset_all_database()
        self.assertTrue(res)
        
        # Verify database is clean (no users)
        self.assertEqual(database.get_users_count(), 0)
        self.assertIsNone(database.get_user(111))

if __name__ == '__main__':
    unittest.main()
