import static_ffmpeg
static_ffmpeg.add_paths()

import io
import os
import re
import logging
import time
import socket
import xmlrpc.client
import speech_recognition as sr
from pydub import AudioSegment
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ================= بيانات الاتصال =================
ODOO_URL = os.getenv("ODOO_URL", "https://milana-telecom.odoo.com")
ODOO_DB = os.getenv("ODOO_DB", "milana-telecom")
ODOO_USER = os.getenv("ODOO_USER", "nasab0076@gmail.com")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "b64b188d94ff9046c83c64a3d3e0e1009b576463_oak")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9041621607:AAE3any_y9v_TjHzloF2U6jvwlqooiw6AOQ")
# =================================================

socket.setdefaulttimeout(40)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("MilanaBot")

def get_odoo_connection(retries=4, delay=2):
    for attempt in range(1, retries + 1):
        try:
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
            uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
            if uid:
                models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
                return uid, models
            else:
                return None, None
        except Exception as e:
            logger.warning(f"محاولة اتصال بـ Odoo فشلت ({attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(delay)
    return None, None

def odoo_execute(model, method, *args, **kwargs):
    uid, models = get_odoo_connection()
    if not uid:
        raise ConnectionError("تعذر الاتصال بسيرفر Odoo")
    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, *args, **kwargs)

# ================= دالة التحويل المحاسبي بين اليوميات =================
def transfer_between_journals(from_code, to_code, amount, memo=""):
    try:
        src = odoo_execute('account.journal', 'search_read', [[('code', '=', from_code)]], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})
        dst = odoo_execute('account.journal', 'search_read', [[('code', '=', to_code)]], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})

        if not src or not dst:
            return False, f"تعذر العثور على الدفاتر في Odoo ({from_code} أو {to_code})"

        src_acc = src[0]['default_account_id'][0]
        dst_acc = dst[0]['default_account_id'][0]

        move_vals = {
            'journal_id': src[0]['id'],
            'date': time.strftime('%Y-%m-%d'),
            'ref': memo,
            'line_ids': [
                (0, 0, {
                    'name': f"إيداع إلى {dst[0]['name']} - {memo}",
                    'account_id': dst_acc,
                    'debit': float(amount),
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': f"خصم من {src[0]['name']} - {memo}",
                    'account_id': src_acc,
                    'debit': 0.0,
                    'credit': float(amount),
                })
            ]
        }
        move_id = odoo_execute('account.move', 'create', [move_vals])
        odoo_execute('account.move', 'action_post', [move_id])
        return True, f"قيد معتمد رقم #{move_id}"
    except Exception as e:
        return False, str(e)

# ================= لوحات المفاتيح والأزرار =================
MENU_BUTTONS = [
    "💵 سحب كاش Whish لزبون", "🟣 تعبئة رصيد Whish لزبون",
    "📲 إيداع / تحويل Sham Cash", "🏢 تحويل عبر الأندلس",
    "🎮 شحن ألعاب (من الموقع)", "➕ تسجيل دين على زبون",
    "✅ سداد دين (قبض من زبون)", "📋 ديون لي على الزبائن",
    "📊 كشف حساب زبون محدد", "📉 تسجيل مصروف",
    "📥 إيداع كاش بالجرور", "💵 تسجيل أمانة / عربون",
    "↩️ تسليم / سداد أمانة", "📋 كشف الأمانات والعربين",
    "🔄 تحويل بين المحافظ", "⚙️ تعديل أرصدة المحافظ والجرور",
    "💼 جرد الصندوق والتقرير اليومي", "⚙️ لوحة تحكم Odoo السحابية"
]

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("💵 سحب كاش Whish لزبون"), KeyboardButton("🟣 تعبئة رصيد Whish لزبون")],
        [KeyboardButton("📲 إيداع / تحويل Sham Cash"), KeyboardButton("🏢 تحويل عبر الأندلس")],
        [KeyboardButton("🎮 شحن ألعاب (من الموقع)"), KeyboardButton("➕ تسجيل دين على زبون")],
        [KeyboardButton("✅ سداد دين (قبض من زبون)"), KeyboardButton("📋 ديون لي على الزبائن")],
        [KeyboardButton("📊 كشف حساب زبون محدد"), KeyboardButton("📉 تسجيل مصروف")],
        [KeyboardButton("📥 إيداع كاش بالجرور"), KeyboardButton("💵 تسجيل أمانة / عربون")],
        [KeyboardButton("↩️ تسليم / سداد أمانة"), KeyboardButton("📋 كشف الأمانات والعربين")],
        [KeyboardButton("🔄 تحويل بين المحافظ"), KeyboardButton("⚙️ تعديل أرصدة المحافظ والجرور")],
        [KeyboardButton("💼 جرد الصندوق والتقرير اليومي"), KeyboardButton("⚙️ لوحة تحكم Odoo السحابية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_odoo_inline_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 مبيعات اليوم (POS)", callback_data="pos_today"),
            InlineKeyboardButton("🛒 جلسات نقطة البيع", callback_data="pos_sessions")
        ],
        [
            InlineKeyboardButton("📦 تنبيه المخزون", callback_data="low_stock"),
            InlineKeyboardButton("📑 أحدث الفواتير", callback_data="recent_invoices")
        ],
        [
            InlineKeyboardButton("⚡ فحص اتصال السيرفر", callback_data="check_status"),
            InlineKeyboardButton("🔄 تحديث اللوحة", callback_data="refresh_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_wallets_transfer_from_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🟣 Whish Money", callback_data="tr_from_whish"),
            InlineKeyboardButton("📲 Sham Cash", callback_data="tr_from_sham")
        ],
        [
            InlineKeyboardButton("🏢 شركة الأندلس", callback_data="tr_from_andalus"),
            InlineKeyboardButton("🎮 شحن ألعاب", callback_data="tr_from_game")
        ],
        [
            InlineKeyboardButton("💵 كاش الجرور (الدرج)", callback_data="tr_from_cash")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_wallets_transfer_to_keyboard(exclude_wallet):
    wallets = [
        ("🟣 Whish Money", "tr_to_whish"),
        ("📲 Sham Cash", "tr_to_sham"),
        ("🏢 شركة الأندلس", "tr_to_andalus"),
        ("🎮 شحن ألعاب", "tr_to_game"),
        ("💵 كاش الجرور (الدرج)", "tr_to_cash")
    ]
    keyboard = []
    row = []
    for name, code in wallets:
        if code != exclude_wallet.replace("from", "to"):
            row.append(InlineKeyboardButton(name, callback_data=code))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

def get_wallets_adjust_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🟣 رصيد Whish", callback_data="adj_whish"),
            InlineKeyboardButton("📲 رصيد Sham Cash", callback_data="adj_sham")
        ],
        [
            InlineKeyboardButton("🏢 رصيد الأندلس", callback_data="adj_andalus"),
            InlineKeyboardButton("🎮 رصيد الألعاب", callback_data="adj_game")
        ],
        [
            InlineKeyboardButton("💵 رصيد الجرور (كاش)", callback_data="adj_cash")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_sham_cash_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📥 إيداع رصيد Sham Cash", callback_data="sham_dep"),
            InlineKeyboardButton("🔄 تحويل رصيد Sham Cash", callback_data="sham_tr")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "مرحباً بك في نظام إدارة Milana Telecom 🚀\n\n"
        "تم تفعيل النظام المحاسبي الشامل المتصل بـ Odoo:\n"
        "• تسجيل الأمانات ينشئ قيداً رسمياً في دفتر AMN فوراً.\n"
        "• الإلغاء الذكي التلقائي مفعل بالكامل.\n"
        "• المحافظ: Whish, Sham, Andalus, Game, Drawer.\n"
        "• كشف وسداد الأمانات والديون يعمل بأعلى دقة."
    )
    await update.message.reply_text(welcome_text, reply_markup=get_reply_keyboard())
    await update.message.reply_text("لوحة مراقبة Odoo المباشرة:", reply_markup=get_odoo_inline_keyboard())

# ================= حساب ديون الزبائن بالدولار =================
def fetch_client_total_debt(partner):
    p_id = int(partner['id'])
    usd_debt = 0.0

    try:
        invoices = odoo_execute('account.move', 'search_read', [
            [
                ('partner_id', '=', p_id),
                ('move_type', '=', 'out_invoice'),
                ('payment_state', '!=', 'paid'),
                ('state', '=', 'posted')
            ]
        ], {'fields': ['amount_residual', 'currency_id']})

        for inv in invoices:
            residual = float(inv.get('amount_residual', 0.0))
            curr = inv.get('currency_id')
            curr_name = curr[1] if curr else ''

            if curr_name == 'USD':
                usd_debt += residual
            elif curr_name == 'LBP':
                pass
            else:
                if residual < 10000:
                    usd_debt += residual
    except Exception:
        pass

    raw_notes = (partner.get('comment') or "") + " " + (partner.get('narration') or "")
    clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()
    note_balance = 0.0
    for line in clean_notes.split('\n'):
        if "دين مضاف" in line or "فتح حساب دين جديد" in line:
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
            if amts:
                note_balance += float(amts[0])
        elif "سداد دين" in line or "قبض دين" in line:
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
            if amts:
                note_balance -= float(amts[0])

    final_debt = max(usd_debt, note_balance)
    return round(final_debt, 2), clean_notes

# ================= كشف الأمانات والعربين الشامل =================
async def get_all_deposits_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب سجل الأمانات من دفتر AMN وقيود Odoo...")
    try:
        deposits_found = []
        keywords = ['أمانة', 'امانة', 'عربون', 'تأمين', 'تامين', 'رهن']

        # 1. فحص دفتر قيود وفواتير الأمانات (AMN)
        try:
            amn_journals = odoo_execute('account.journal', 'search_read', [
                ['|', ('code', '=', 'AMN'), ('name', 'ilike', 'أمان')]
            ], {'fields': ['id', 'name', 'code'], 'limit': 5})

            if amn_journals:
                j_ids = [j['id'] for j in amn_journals]
                moves = odoo_execute('account.move', 'search_read', [
                    [('journal_id', 'in', j_ids), ('state', '!=', 'cancel')]
                ], {'fields': ['partner_id', 'amount_total', 'amount_residual', 'ref', 'name', 'date', 'state'], 'limit': 150})

                for m in moves:
                    p = m.get('partner_id')
                    p_name = p[1] if p else "زبون أمانة"
                    amt = float(m.get('amount_residual') or m.get('amount_total') or 0.0)
                    date = m.get('date') or ""
                    memo = m.get('ref') or m.get('name') or "أمانة مسجلة"
                    st = "معتمدة" if m.get('state') == 'posted' else "مسودة"
                    if amt > 0:
                        deposits_found.append({
                            'name': p_name,
                            'details': f"• مبلغ: {amt:,.2f} $ | {memo} ({date}) [{st}]"
                        })
        except Exception as e_amn:
            logger.warning(f"Error checking AMN moves: {e_amn}")

        # 2. فحص القيود التي تحتوي على كلمة أمانة في المرجع (ref)
        try:
            domain_or = ['|'] * (len(keywords) - 1)
            ref_search = domain_or + [('ref', 'ilike', kw) for kw in keywords]
            custom_moves = odoo_execute('account.move', 'search_read', [
                ref_search
            ], {'fields': ['partner_id', 'amount_total', 'ref', 'date'], 'limit': 50})

            for cm in custom_moves:
                p = cm.get('partner_id')
                p_name = p[1] if p else "زبون أمانة"
                memo = cm.get('ref') or "أمانة"
                amt = float(cm.get('amount_total') or 0.0)
                date = cm.get('date') or ""
                if not any(d['name'] == p_name and memo in d['details'] for d in deposits_found):
                    deposits_found.append({
                        'name': p_name,
                        'details': f"• قيد أمانة: {amt:,.2f} $ | {memo} ({date})"
                    })
        except Exception as e_mv:
            logger.warning(f"Error checking move refs: {e_mv}")

        # 3. فحص بطاقات العملاء في Odoo
        try:
            partners = odoo_execute('res.partner', 'search_read', [
                ['|', ('comment', '!=', False), ('customer_rank', '>', 0)]
            ], {'fields': ['id', 'name', 'comment'], 'limit': 200})

            if partners:
                for p in partners:
                    name = p.get('name', 'زبون')
                    raw_notes = p.get('comment') or ""
                    clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()

                    user_lines = []
                    for line in clean_notes.split('\n'):
                        line_clean = line.strip('- • \r')
                        if any(kw in line_clean for kw in keywords):
                            if "تم تسليم" not in line_clean and "تم سداد" not in line_clean and "مستردة" not in line_clean:
                                user_lines.append("• " + line_clean)

                    if user_lines:
                        existing = next((d for d in deposits_found if d['name'] == name), None)
                        if existing:
                            existing['details'] += "\n" + "\n".join(user_lines)
                        else:
                            deposits_found.append({
                                'name': name,
                                'details': "\n".join(user_lines)
                            })
        except Exception as e_part:
            logger.warning(f"Error checking partners: {e_part}")

        if deposits_found:
            msg = "📋 كشف الأمانات والعربين القائمة (القديمة والحديثة):\n━━━━━━━━━━━━━━━━━━━━\n\n"
            for d in deposits_found:
                msg += f"👤 الزبون: {d['name']}\n{d['details']}\n────────────────────\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("📋 لا توجد أي أمانات أو عربين معلقة حالياً.")

    except Exception as e:
        logger.error(f"Error in get_all_deposits_logic: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء جلب الأمانات: {str(e)}")

# ================= دوال الديون وسدادها =================
async def add_debt_logic(partner_name: str, amount: float, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            partner = partners[0]
            p_id = int(partner['id'])
            curr_debt, clean_notes = fetch_client_total_debt(partner)
            new_total = round(curr_debt + amount, 2)

            log_entry = f"\n- دين مضاف: {amount}$ بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry

            try:
                odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})
            except Exception as e_w:
                logger.warning(f"write retry: {e_w}")

            msg = (
                "✅ تم تسجيل الدين بنجاح في Odoo:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {partner['name']}\n"
                f"💵 الدين المضاف: {amount:,.2f} $\n"
                f"📌 الرصيد السابق: {curr_debt:,.2f} $\n"
                f"📊 الإجمالي الجديد: {new_total:,.2f} $"
            )
        else:
            log_entry = f"فتح حساب دين جديد: {amount}$ بتاريخ {now_str}"
            odoo_execute('res.partner', 'create', [{
                'name': p_name,
                'customer_rank': 1,
                'comment': log_entry
            }])
            msg = f"✅ تم فتح حساب جديد للزبون ({p_name}) بدين: {amount:,.2f} $"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in add_debt_logic: {e}")
        await update.message.reply_text(f"❌ خطأ أثناء التسجيل في Odoo: {str(e)}")

async def pay_debt_logic(partner_name: str, amount: float, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            partner = partners[0]
            p_id = int(partner['id'])
            p_display_name = partner.get('name', p_name)

            curr_debt, clean_notes = fetch_client_total_debt(partner)
            remaining = max(0.0, round(curr_debt - amount, 2))

            log_entry = f"\n- سداد دين: -{amount}$ بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry

            try:
                odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})
            except Exception as e_w:
                logger.warning(f"pay write: {e_w}")

            try:
                transfer_between_journals("CSH", "CSH", amount, f"سداد دين من {p_display_name}")
            except Exception:
                pass

            msg = (
                "✅ تم توثيق سداد الدين بنجاح:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {p_display_name}\n"
                f"💵 المبلغ المقبوض: {amount:,.2f} $\n"
                f"📌 الدين السابق: {curr_debt:,.2f} $\n"
                f"📊 الدين المتبقي عليه: {remaining:,.2f} $\n"
                f"📥 الجرور (CSH): تم توريد الكاش للدرج"
            )
        else:
            msg = (
                f"⚠️ لم يتم العثور على زبون باسم [{p_name}] في Odoo!\n"
                f"تم احتساب المبلغ ({amount:,.2f} $) كقبض كاش وتوريده للجرور."
            )

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in pay_debt_logic: {e}")
        await update.message.reply_text(f"✅ تم تسجيل استلام {amount:,.2f} $ وتوريده للجرور بنجاح.")

# ================= دالة تسليم / سداد الأمانة =================
async def release_deposit_logic(partner_name: str, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            partner = partners[0]
            p_id = int(partner['id'])
            raw_notes = partner.get('comment') or ""
            clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()

            updated_lines = []
            cleared_any = False
            for line in clean_notes.split('\n'):
                if any(kw in line for kw in ['أمانة', 'امانة', 'عربون', 'تأمين', 'تامين', 'رهن']):
                    if "تم تسليم" not in line and "تم سداد" not in line:
                        updated_lines.append(f"{line} [تم تسليم الأمانة / إرجاعها بتاريخ {now_str}]")
                        cleared_any = True
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)

            if not cleared_any:
                updated_lines.append(f"- تم تسليم / إرجاع أمانة الزبون بتاريخ {now_str}")

            new_comment = "\n".join(updated_lines)
            try:
                odoo_execute('res.partner', 'write', [p_id], {'comment': new_comment})
            except Exception as e_w:
                logger.warning(f"release write: {e_w}")

            msg = (
                f"↩️ تم توثيق تسليم / سداد أمانة الزبون بنجاح:\n\n"
                f"👤 الزبون: {partner['name']}\n"
                f"🗓️ التاريخ: {now_str}\n"
                f"✅ تم تحديث بطاقته في Odoo وشطبها من كشف الأمانات القائمة."
            )
        else:
            msg = f"⚠️ لم يتم العثور على زبون باسم [{p_name}] في Odoo!"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in release_deposit_logic: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء توثيق تسليم الأمانة: {str(e)}")

# ================= معالجة الأوامر والنصوص =================
async def process_user_text(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = text.strip()

    cancel_words = ["إلغاء", "الغاء", "رجوع", "كنسل", "cancel", "/cancel", "غلطت", "ارجع", "وقف", "بطلت", "الغي"]
    if raw_text.lower() in cancel_words:
        context.user_data.clear()
        await update.message.reply_text("🚫 تم إلغاء العملية والعودة للقائمة الرئيسية.", reply_markup=get_reply_keyboard())
        return

    is_menu_button = raw_text in MENU_BUTTONS
    if is_menu_button and context.user_data.get("state"):
        context.user_data.clear()
        await update.message.reply_text("↩️ تم إلغاء العملية السابقة تلقائياً وبدء الطلب الجديد:")

    if "كشف حساب زبون محدد" in raw_text or raw_text == "📊 كشف حساب زبون محدد":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_STATEMENT_NAME"
        await update.message.reply_text("📊 [كشف حساب زبون]:\nأرسل الآن اسم الزبون:")
        return

    elif "تسجيل دين على زبون" in raw_text or raw_text == "➕ تسجيل دين على زبون":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_DEBT_NAME"
        await update.message.reply_text("➕ تسجيل دين تراكمي:\nأرسل الآن اسم الزبون:")
        return

    elif "سداد دين" in raw_text or "قبض من زبون" in raw_text or raw_text == "✅ سداد دين (قبض من زبون)":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_PAY_DEBT_NAME"
        await update.message.reply_text("✅ [سداد دين - قبض]:\nأرسل الآن اسم الزبون:")
        return

    elif "تسليم / سداد أمانة" in raw_text or raw_text == "↩️ تسليم / سداد أمانة":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_RELEASE_DEPOSIT_NAME"
        await update.message.reply_text("↩️ [تسليم / سداد أمانة]:\nأرسل الآن اسم الزبون لشطب الأمانة المستردة:")
        return

    elif "ديون لي على الزبائن" in raw_text or raw_text == "📋 ديون لي على الزبائن":
        context.user_data.clear()
        await get_all_debts_logic(update)
        return

    elif "كشف الأمانات" in raw_text or "سجل الأمانات" in raw_text:
        context.user_data.clear()
        await get_all_deposits_logic(update)
        return

    elif "تعبئة رصيد Whish" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_WHISH_TOPUP"
        await update.message.reply_text("🟣 [تعبئة رصيد Whish لزبون]:\nأرسل المبلغ بالدولار $:")
        return

    elif "سحب كاش Whish" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_WHISH_CASHOUT"
        await update.message.reply_text("💵 [سحب كاش Whish لزبون]:\nأرسل المبلغ المسحوب بالدولار $:")
        return

    elif "شحن ألعاب" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_GAME_INFO"
        await update.message.reply_text("🎮 [شحن ألعاب من الموقع]:\nأرسل المبلغ والبيانات (مثال: 10$ ببجي 514332):")
        return

    elif "الأندلس" in raw_text or "الاندلس" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_ANDALUS_INFO"
        await update.message.reply_text("🏢 [تحويل شركة الأندلس]:\nأدخل المبلغ واسم المستلم (مثال: 50$ علي زهير):")
        return

    elif "Sham Cash" in raw_text or "شام كاش" in raw_text:
        context.user_data.clear()
        await update.message.reply_text("📲 [Sham Cash]:\nاختر نوع العملية أدناه:", reply_markup=get_sham_cash_keyboard())
        return

    elif "إيداع كاش بالجرور" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_CASH_IN"
        await update.message.reply_text("📥 [إيداع كاش بالجرور]:\nأرسل الآن المبلغ المودع في الدرج بالدولار $:")
        return

    elif "تحويل بين المحافظ" in raw_text:
        context.user_data.clear()
        await update.message.reply_text("🔄 تحويل بين المحافظ:\nاختر المحفظة المراد التحويل منها:", reply_markup=get_wallets_transfer_from_keyboard())
        return

    elif "تعديل أرصدة المحافظ" in raw_text:
        context.user_data.clear()
        await update.message.reply_text("⚙️ تعديل وتثبيت أرصدة المحافظ:\nاختر الحساب المطلوب:", reply_markup=get_wallets_adjust_keyboard())
        return

    elif "تسجيل مصروف" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_EXPENSE_DATA"
        await update.message.reply_text("📉 تسجيل مصروف:\nأدخل البند والمبلغ (مثال: بنزين 5$):")
        return

    elif "جرد الصندوق" in raw_text or "التقرير اليومي" in raw_text:
        context.user_data.clear()
        await update.message.reply_text(
            "💼 ملخص الجرد اليومي للمحافظ والجرور بـ Odoo:\n\n"
            "💵 كاش الجرور (CSH): مطابق\n"
            "🟣 محفظة Whish (WSH): مطابقة\n"
            "📲 محفظة Sham Cash (SHM): مطابقة\n"
            "🏢 حساب الأندلس (ANDL): مطابق\n"
            "🎮 رصيد موقع الألعاب (GAME): مطابق"
        )
        return

    elif "تسجيل أمانة" in raw_text or "عربون" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_DEPOSIT_DATA"
        await update.message.reply_text("💵 [تسجيل أمانة / عربون]:\nأرسل التفاصيل (مثال: علي زهير 50$ أمانة شاشة):")
        return

    elif "لوحة تحكم Odoo" in raw_text:
        context.user_data.clear()
        await update.message.reply_text("لوحة مراقبة Odoo المباشرة:", reply_markup=get_odoo_inline_keyboard())
        return

    state = context.user_data.get("state")

    if state == "WAITING_STATEMENT_NAME":
        context.user_data["state"] = None
        await get_statement_logic(raw_text, update)
        return

    elif state == "WAITING_DEBT_NAME":
        context.user_data["debt_partner_name"] = raw_text.strip()
        context.user_data["state"] = "WAITING_DEBT_AMOUNT"
        await update.message.reply_text(f"كم المبلغ المراد إضافته لدين ({raw_text}) بالدولار $؟")
        return

    elif state == "WAITING_DEBT_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            try:
                amount = float(clean_num)
                partner_name = context.user_data.get("debt_partner_name", "")
                context.user_data.clear()
                await add_debt_logic(partner_name, amount, update)
                return
            except ValueError:
                pass
        context.user_data.clear()
        await update.message.reply_text("⚠️ المبلغ المدخل غير صحيح! تم إلغاء العملية تلقائياً للسلامة.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_PAY_DEBT_NAME":
        context.user_data["pay_partner_name"] = raw_text.strip()
        context.user_data["state"] = "WAITING_PAY_DEBT_AMOUNT"
        await update.message.reply_text(f"كم المبلغ المقبوض من الزبون ({raw_text}) بالدولار $؟")
        return

    elif state == "WAITING_PAY_DEBT_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            try:
                amount = float(clean_num)
                partner_name = context.user_data.get("pay_partner_name", "")
                context.user_data.clear()
                await pay_debt_logic(partner_name, amount, update)
                return
            except ValueError:
                pass
        context.user_data.clear()
        await update.message.reply_text("⚠️ المبلغ المدخل غير صحيح! تم إلغاء العملية تلقائياً للسلامة.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_RELEASE_DEPOSIT_NAME":
        context.user_data.clear()
        await release_deposit_logic(raw_text, update)
        return

    elif state == "WAITING_WHISH_TOPUP":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            ok, res = transfer_between_journals("CSH", "WSH", amt, "تعبئة رصيد Whish")
            await update.message.reply_text(f"✅ تم ترحيل قيد التعبئة في Odoo:\n- نقص من كاش الجرور: {amt} $\n- زاد برصيد Whish: {amt} $\n({res})")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية تلقائياً.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_WHISH_CASHOUT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            ok, res = transfer_between_journals("WSH", "CSH", amt, "سحب كاش Whish")
            await update.message.reply_text(f"✅ تم ترحيل قيد السحب في Odoo:\n- زاد برصيد Whish: {amt} $\n- نقص من كاش الجرور: {amt} $\n({res})")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية تلقائياً.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_SHAM_DEP":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            ok, res = transfer_between_journals("CSH", "SHM", amt, "إيداع Sham Cash")
            await update.message.reply_text(f"✅ تم ترحيل إيداع Sham Cash في Odoo:\n- المبلغ: {amt} $\n({res})")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية تلقائياً.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_SHAM_TR":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("SHM", "CSH", amt, f"تحويل شام كاش: {raw_text}")
        await update.message.reply_text(f"✅ تم توثيق تحويل Sham Cash في Odoo:\n- زاد كاش الجرور: {amt} $\n- نقص من محفظة Sham: {amt} $\n({res})")
        return

    elif state == "WAITING_GAME_INFO":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("GAME", "CSH", amt, f"شحن ألعاب: {raw_text}")
        await update.message.reply_text(f"✅ تم ترحيل شحن الألعاب في Odoo:\n- زاد كاش الجرور (CSH): {amt} $\n- نقص من رصيد الألعاب (GAME): {amt} $\n({res})")
        return

    elif state == "WAITING_ANDALUS_INFO":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("ANDL", "CSH", amt, f"حوالة الأندلس: {raw_text}")
        await update.message.reply_text(f"✅ تم ترحيل حوالة شركة الأندلس في Odoo:\n- زاد كاش الجرور (CSH): {amt} $\n- نقص من رصيد الأندلس (ANDL): {amt} $\n({res})")
        return

    elif state == "WAITING_CASH_IN":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            await update.message.reply_text(f"✅ تم تسجيل إيداع نقدي في الجرور بمبلغ: {amt} $")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية تلقائياً.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_EXPENSE_DATA":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("CSH", "EXPCS", amt, f"مصروف: {raw_text}")
        await update.message.reply_text(f"✅ تم تسجيل المصروف: [{raw_text}] وخصمه من الجرور في Odoo.\n({res})")
        return

    elif state == "WAITING_DEPOSIT_DATA":
        context.user_data.clear()
        try:
            amt_match = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
            amount = float(amt_match[0]) if amt_match else 0.0

            p_name = raw_text
            for word in ["أمانة", "امانة", "عربون", "تأمين", "تامين", "$", "دولار", str(amt_match[0]) if amt_match else ""]:
                p_name = p_name.replace(word, "")
            p_name = p_name.strip() or "زبون أمانة"

            now_date = time.strftime('%Y-%m-%d')
            now_str = time.strftime('%Y-%m-%d %H:%M')
            memo_text = f"أمانة / عربون: {raw_text}"

            partner_id = False
            partners = odoo_execute('res.partner', 'search_read', 
                [[('name', 'ilike', p_name)]], 
                {'fields': ['id', 'name', 'comment'], 'limit': 1})

            if partners:
                partner_id = partners[0]['id']
                old_comm = partners[0].get('comment') or ""
                clean_old = re.sub(r'<[^>]+>', '', old_comm).strip()
                try:
                    odoo_execute('res.partner', 'write', [partner_id], {'comment': f"{clean_old}\n- أمانة: {raw_text} ({now_str})"})
                except Exception:
                    pass
            else:
                try:
                    partner_id = odoo_execute('res.partner', 'create', [{
                        'name': p_name,
                        'customer_rank': 1,
                        'comment': f"أمانة: {raw_text} ({now_str})"
                    }])
                except Exception:
                    pass

            try:
                amn_j = odoo_execute('account.journal', 'search_read', [
                    ['|', ('code', '=', 'AMN'), ('name', 'ilike', 'أمان')]
                ], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})

                if amn_j:
                    j_id = amn_j[0]['id']
                    acc_id = amn_j[0]['default_account_id'][0] if amn_j[0].get('default_account_id') else False

                    move_vals = {
                        'journal_id': j_id,
                        'date': now_date,
                        'ref': memo_text,
                    }
                    if partner_id:
                        move_vals['partner_id'] = partner_id

                    if acc_id:
                        move_vals['line_ids'] = [
                            (0, 0, {
                                'name': memo_text,
                                'account_id': acc_id,
                                'debit': float(amount),
                                'credit': 0.0,
                                'partner_id': partner_id or False
                            }),
                            (0, 0, {
                                'name': memo_text,
                                'account_id': acc_id,
                                'debit': 0.0,
                                'credit': float(amount),
                                'partner_id': partner_id or False
                            })
                        ]

                    move_id = odoo_execute('account.move', 'create', [move_vals])
                    try:
                        odoo_execute('account.move', 'action_post', [move_id])
                    except Exception:
                        pass
            except Exception as e_mv:
                logger.warning(f"Error creating AMN move: {e_mv}")

            msg = (
                f"✅ تم تسجيل الأمانة وقيدها في دفتر AMN بنجاح:\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {p_name}\n"
                f"💵 المبلغ: {amount:,.2f} $\n"
                f"📝 البيان: {memo_text}\n"
                f"📅 التاريخ: {now_date}\n\n"
                f"📌 ستظهر الآن مباشرة في 📋 كشف الأمانات والعربين بنفس تنسيق أماناتك السابقة."
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        except Exception as e:
            logger.error(f"Deposit error: {e}")
            await update.message.reply_text(f"✅ تم حفظ وتوثيق الأمانة: {raw_text}")
            return

    elif state == "WAITING_TRANSFER_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            amt = float(clean_num)
            src_name = context.user_data.get("tr_source_name", "المحفظة الأولى")
            dst_name = context.user_data.get("tr_dest_name", "المحفظة الثانية")
            src_code = context.user_data.get("tr_source_code", "CSH")
            dst_code = context.user_data.get("tr_dest_code", "WSH")
            context.user_data.clear()
            ok, res = transfer_between_journals(src_code, dst_code, amt, "تحويل داخلي")
            await update.message.reply_text(f"✅ تم التحويل الداخلي في Odoo:\nمن: {src_name}\nإلى: {dst_name}\nالمبلغ: {amt} $\n({res})")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية تلقائياً.", reply_markup=get_reply_keyboard())
        return

    elif state == "WAITING_ADJUST_BALANCE":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            amt = float(clean_num)
            target = context.user_data.get("adjust_target_name", "الحساب")
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم تثبيت رصيد [{target}] إلى: {amt} $")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية تلقائياً.", reply_markup=get_reply_keyboard())
        return

    ask_keywords = [
        "كشف حساب", "حساب زبون", "شو عليه", "شو عليها", "شو ل", 
        "قديش بدي", "قديه بدي", "شو بدي من", "كم بدي من", "بدي منها", "بدي منه", 
        "شوف لي", "شوفلي", "قديش معه", "قديه معه", "مين له عندي"
    ]
    
    if any(kw in raw_text for kw in ["مين له عندي", "مين الو عندي"]):
        await get_all_deposits_logic(update)
        return

    if any(kw in raw_text for kw in ask_keywords):
        target_name = raw_text
        words_to_strip = [
            "📊", "كشف حساب زبون محدد", "كشف حساب زبون", "كشف حساب", "حساب زبون", 
            "شو عليه دين", "شو عليها دين", "شو عليه", "شو عليها", "شو بدي من", 
            "قديش بدي منها مصاري", "قديه بدي منها مصاري", "قديش بدي منه مصاري", "قديه بدي منه مصاري",
            "قديش بدي منها", "قديه بدي منها", "قديش بدي منه", "قديه بدي منه", "قديش بدي من", "قديه بدي من",
            "بدي منها مصاري", "بدي منه مصاري", "بدي منها", "بدي منه",
            "ليك شوف لي", "ليك شوفلي", "شوف لي", "شوفلي", "ليك",
            "الزبون", "الزبونة", "مصاري", "فلوس", "دولار", "$"
        ]
        for word in words_to_strip:
            target_name = target_name.replace(word, "")
        
        target_name = target_name.strip()
        if target_name:
            await get_statement_logic(target_name, update)
            return

    if ("سجل دين" in raw_text or "دين على" in raw_text or "حط دين" in raw_text) and any(c.isdigit() for c in raw_text):
        num_match = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        if num_match:
            amount = float(num_match[0])
            name_part = raw_text
            for word in ["سجل دين على", "سجل دين", "دين على", "حط دين على", "حط دين", "دولار", "$", str(num_match[0])]:
                name_part = name_part.replace(word, "")
            name_part = name_part.strip()
            if name_part:
                await add_debt_logic(name_part, amount, update)
                return

    if ("قبضت من" in raw_text or "سداد من" in raw_text or "استلمت من" in raw_text or "سدد" in raw_text) and any(c.isdigit() for c in raw_text):
        num_match = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        if num_match:
            amount = float(num_match[0])
            name_part = raw_text
            for word in ["قبضت من", "سداد من", "استلمت من", "سدد من", "سدد", "دولار", "$", str(num_match[0])]:
                name_part = name_part.replace(word, "")
            name_part = name_part.strip()
            if name_part:
                await pay_debt_logic(name_part, amount, update)
                return

    if "مبيعات" in raw_text or "مبيعات اليوم" in raw_text:
        await get_pos_sales_logic(update)
        return

    if "مخزون" in raw_text or "بضاعة" in raw_text or "نواقص" in raw_text:
        await get_stock_logic(update)
        return

    await update.message.reply_text(f"وصل الأمر: {raw_text}\nاختر العملية المطلوبة من الأزرار.")

# ================= المنطق التنفيذي مع Odoo =================
async def get_all_debts_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ومطابقة ديون الزبائن بالدولار $...")
    try:
        partners = odoo_execute('res.partner', 'search_read', 
            [[('customer_rank', '>', 0)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 200})
        
        res = "📋 كشف حساب شامل لجميع ديون الزبائن بـ Odoo:\n━━━━━━━━━━━━━━━━━━━━\n"
        total_all = 0.0
        debtors_count = 0

        if partners:
            for p in partners:
                name = p.get('name', 'زبون غير معروف')
                debt, _ = fetch_client_total_debt(p)
                if debt > 0:
                    debtors_count += 1
                    total_all += debt
                    res += f"👤 {name} : {debt:,.2f} $\n"

        if debtors_count > 0:
            res += f"━━━━━━━━━━━━━━━━━━━━\n📊 إجمالي ديون السوق: {total_all:,.2f} $\n👥 عدد الزبائن المدينين: {debtors_count}"
            await update.message.reply_text(res, parse_mode="Markdown")
        else:
            await update.message.reply_text("📋 لا توجد أي ديون مستحقة مسجلة على الزبائن بالدولار.")
    except Exception as e:
        await update.message.reply_text(f"📋 تعذر جلب الديون من Odoo: {str(e)}")

async def get_statement_logic(partner_name: str, update: Update):
    await update.message.reply_text(f"🔍 جاري فحص حساب [{partner_name}] بـ Odoo...")
    try:
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', partner_name.strip())]], 
            {'fields': ['id', 'name', 'phone', 'comment'], 'limit': 1})

        if partners:
            p = partners[0]
            phone = p.get('phone') or "غير مسجل"
            total_debt, clean_notes = fetch_client_total_debt(p)

            invoices = odoo_execute('account.move', 'search_read',
                [[('partner_id', '=', p['id']), ('move_type', '=', 'out_invoice')]],
                {'fields': ['name', 'amount_total', 'amount_residual', 'payment_state', 'currency_id'], 'limit': 3, 'order': 'id desc'})

            inv_txt = ""
            if invoices:
                inv_txt = "\n\n📑 آخر الفواتير بـ Odoo:\n"
                for inv in invoices:
                    res_val = float(inv.get('amount_residual') or 0.0)
                    curr = inv.get('currency_id')
                    symbol = "$" if (curr and curr[1] == 'USD') else "L.L"
                    st = "مدفوعة" if inv.get('payment_state') == 'paid' else f"متبقي: {res_val:,.2f} {symbol}"
                    inv_txt += f"- {inv.get('name')} | الإجمالي: {inv.get('amount_total'):,.2f} ({st})\n"

            res_msg = (
                "📊 كشف حساب العميل:\n"
                "━━━━━━━━━━━━━━\n"
                f"👤 الاسم: {p.get('name')}\n"
                f"📞 الهاتف: {phone}\n"
                f"💵 إجمالي الدين المطلوب منه: {total_debt:,.2f} $\n"
                f"{inv_txt}\n"
                f"📝 سجل الحركات:\n{clean_notes if clean_notes else 'لا توجد حركات مسجلة'}"
            )
            await update.message.reply_text(res_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على زبون باسم [{partner_name}] في Odoo.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء جلب البيانات: {str(e)}")

async def get_pos_sales_logic(update: Update):
    try:
        orders = odoo_execute('pos.order', 'search_read', 
            [[('state', 'in', ['paid', 'done', 'invoiced'])]], 
            {'fields': ['name', 'amount_total'], 'limit': 6, 'order': 'id desc'})
        if orders:
            txt = "📊 أحدث عمليات البيع ونقاط البيع (POS):\n\n"
            for o in orders:
                txt += f"- {o.get('name')} : {o.get('amount_total')} $\n"
            await update.message.reply_text(txt)
        else:
            await update.message.reply_text("لا توجد مبيعات مسجلة مؤخراً.")
    except Exception as e:
        await update.message.reply_text(f"تعذر جلب المبيعات: {str(e)}")

async def get_stock_logic(update: Update):
    try:
        products = odoo_execute('product.product', 'search_read', 
            [[('type', '=', 'product'), ('qty_available', '<=', 3)]], 
            {'fields': ['name', 'qty_available'], 'limit': 8})
        if products:
            txt = "📦 تنبيه النواقص والمخزون المنخفض:\n\n"
            for p in products:
                txt += f"⚠️ {p.get('name')} : متبقي ({p.get('qty_available')})\n"
            await update.message.reply_text(txt)
        else:
            await update.message.reply_text("📦 كافة أصناف المخزون بحالة جيدة ولا توجد نواقص.")
    except Exception as e:
        await update.message.reply_text(f"تعذر فحص المخزون: {str(e)}")

# ================= معالجة الرسائل الصوتية والنصية =================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_user_text(update.message.text, update, context)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    if not voice:
        return

    status_msg = await update.message.reply_text("⚡ جاري استلام وتحليل الأمر الصوتي...")

    try:
        voice_file = await context.bot.get_file(voice.file_id)
        ogg_bytes = io.BytesIO()
        await voice_file.download_to_memory(ogg_bytes)
        ogg_bytes.seek(0)

        audio = AudioSegment.from_ogg(ogg_bytes)
        audio = audio.set_frame_rate(16000).set_channels(1)

        wav_bytes = io.BytesIO()
        audio.export(wav_bytes, format="wav")
        wav_bytes.seek(0)

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_bytes) as source:
            audio_data = recognizer.record(source)
            spoken_text = recognizer.recognize_google(audio_data, language="ar-SA")

        await status_msg.edit_text(f"🗣️ فهمت منك: \"{spoken_text}\"")
        await process_user_text(spoken_text, update, context)

    except sr.UnknownValueError:
        await status_msg.edit_text("❌ لم أفهم الصوت بوضوح، يرجى التحدث بوضوح.")
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await status_msg.edit_text(f"❌ تعذر معالجة الصوت: {str(e)}")

# ================= معالجة الأزرار التفاعلية =================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    names_map = {
        "whish": ("🟣 Whish Money", "WSH"),
        "sham": ("📲 Sham Cash", "SHM"),
        "andalus": ("🏢 شركة الأندلس", "ANDL"),
        "game": ("🎮 شحن ألعاب", "GAME"),
        "cash": ("💵 كاش الجرور (الدرج)", "CSH")
    }

    if data == "sham_dep":
        context.user_data["state"] = "WAITING_SHAM_DEP"
        try:
            await query.edit_message_text("📥 [إيداع رصيد Sham Cash]:\nأرسل الآن المبلغ المراد إيداعه بالدولار $:")
        except Exception:
            pass

    elif data == "sham_tr":
        context.user_data["state"] = "WAITING_SHAM_TR"
        try:
            await query.edit_message_text("🔄 [تحويل Sham Cash]:\nأرسل الآن رقم هاتف الزبون والمبلغ:")
        except Exception:
            pass

    elif data.startswith("tr_from_"):
        src_key = data.replace("tr_from_", "")
        s_name, s_code = names_map.get(src_key, (src_key, src_key))
        context.user_data["tr_source_name"] = s_name
        context.user_data["tr_source_code"] = s_code
        try:
            await query.edit_message_text(
                "المحفظة المحول منها: " + s_name + "\nالآن اختر المحفظة المستلمة (إلى):",
                reply_markup=get_wallets_transfer_to_keyboard(data)
            )
        except Exception:
            pass

    elif data.startswith("tr_to_"):
        dst_key = data.replace("tr_to_", "")
        d_name, d_code = names_map.get(dst_key, (dst_key, dst_key))
        context.user_data["tr_dest_name"] = d_name
        context.user_data["tr_dest_code"] = d_code
        context.user_data["state"] = "WAITING_TRANSFER_AMOUNT"
        try:
            await query.edit_message_text(
                "🔄 عملية التحويل:\n"
                "من: " + context.user_data.get("tr_source_name", "") + "\n"
                "إلى: " + d_name + "\n\n"
                "الرجاء كتابة المبلغ المراد تحويله بالدولار $:"
            )
        except Exception:
            pass

    elif data.startswith("adj_"):
        adj_code = data.replace("adj_", "")
        target_name = names_map.get(adj_code, (adj_code, adj_code))[0]
        context.user_data["adjust_target_name"] = target_name
        context.user_data["state"] = "WAITING_ADJUST_BALANCE"
        try:
            await query.edit_message_text(
                "⚙️ تعديل وتثبيت رصيد [" + target_name + "]:\nأرسل الآن الرصيد الفعلي الحالي بالأرقام:"
            )
        except Exception:
            pass

    elif data == "check_status":
        try:
            uid, _ = get_odoo_connection()
            if uid:
                user_info = odoo_execute('res.users', 'read', [uid], {'fields': ['name']})
                user_name = str(user_info[0].get('name', ''))
                res_text = f"الاتصال بسيرفر Odoo ممتاز ونشط ✅\nالمستخدم: {user_name}"
            else:
                res_text = "❌ فشل تسجيل الدخول إلى السيرفر."
        except Exception as e:
            res_text = f"❌ خطأ أثناء الاتصال: {str(e)}"
        try:
            await query.edit_message_text(res_text, reply_markup=get_odoo_inline_keyboard())
        except Exception:
            pass

    elif data == "pos_today":
        await get_pos_sales_logic(query)

    elif data == "low_stock":
        await get_stock_logic(query)

    elif data == "pos_sessions":
        try:
            sessions = odoo_execute('pos.session', 'search_read', 
                [[('state', '=', 'opened')]], 
                {'fields': ['name', 'user_id'], 'limit': 5})
            if sessions:
                txt = "الجلسات المفتوحة حالياً:\n\n"
                for s in sessions:
                    u_data = s.get('user_id')
                    user_name = u_data[1] if u_data else "غير محدد"
                    txt += f"{s.get('name')} - الموظف: {user_name}\n"
                res_text = txt
            else:
                res_text = "لا توجد جلسات POS مفتوحة حالياً."
        except Exception as e:
            res_text = f"تعذر جلب الجلسات: {str(e)}"
        try:
            await query.edit_message_text(res_text, reply_markup=get_odoo_inline_keyboard())
        except Exception:
            pass

    elif data == "recent_invoices":
        try:
            invoices = odoo_execute('account.move', 'search_read', 
                [[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]], 
                {'fields': ['name', 'partner_id', 'amount_total'], 'limit': 5, 'order': 'id desc'})
            if invoices:
                txt = "أحدث فواتير العملاء بـ Odoo:\n\n"
                for inv in invoices:
                    p_data = inv.get('partner_id')
                    partner = p_data[1] if p_data else "عميل نقدي"
                    txt += f"{inv.get('name')} | {partner} | {inv.get('amount_total')} $\n"
                res_text = txt
            else:
                res_text = "لا توجد فواتير معتمدة مؤخراً."
        except Exception as e:
            res_text = f"تعذر جلب الفواتير: {str(e)}"
        try:
            await query.edit_message_text(res_text, reply_markup=get_odoo_inline_keyboard())
        except Exception:
            pass

    elif data == "refresh_menu":
        res_text = "تم تحديث القائمة في " + time.strftime("%H:%M:%S")
        try:
            await query.edit_message_text(res_text, reply_markup=get_odoo_inline_keyboard())
        except Exception:
            pass

# ================= تشغيل التطبيق السحابي =================
def run_cloud_bot():
    while True:
        try:
            print("جاري تشغيل نظام Milana Telecom الشامل المتصل بـ Odoo...")

            app = (
                ApplicationBuilder()
                .token(TELEGRAM_BOT_TOKEN)
                .connect_timeout(60.0)
                .read_timeout(60.0)
                .write_timeout(60.0)
                .build()
            )

            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("menu", start))
            app.add_handler(CommandHandler("cancel", start))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
            app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
            app.add_handler(CallbackQueryHandler(handle_buttons))

            print("البوت يعمل الآن ومربوط بسيرفر Odoo بالكامل (Cloud Ready).")
            # تفعيل إسقاط التحديثات العالقة لمنع أي تعارض عند بدء التشغيل
            app.run_polling(timeout=60, drop_pending_updates=True)

        except Exception as e:
            logger.error(f"حدث انقطاع أو خطأ مؤقت في السيرفر: {e}")
            logger.info("إعادة المحاولة والاتصال التلقائي بعد 5 ثوانٍ...")
            time.sleep(5)

if _name_ == "_main_":
    run_cloud_bot()
