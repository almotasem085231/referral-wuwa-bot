#!/data/data/com.termux/files/usr/bin/bash

SESSION_NAME="referral_bot"

# الانتقال إلى مجلد البوت تلقائياً (المجلد الذي يتواجد فيه هذا السكربت)
cd "$(dirname "$0")" || exit 1

# قتل أي جلسة قديمة بنفس الاسم لتفادي تكرار التشغيل
tmux kill-session -t "$SESSION_NAME" 2>/dev/null

# تشغيل البوت داخل جلسة tmux جديدة في الخلفية
tmux new-session -d -s "$SESSION_NAME" "python bot.py"

echo "✅ تم تشغيل بوت الإحالات ($SESSION_NAME) داخل tmux بنجاح!"
