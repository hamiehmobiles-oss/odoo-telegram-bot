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

    if method == 'write' and len(args) == 2 and isinstance(args[1], dict):
        ids = args[0] if isinstance(args[0], list) else [args[0]]
        return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, [ids, args[1]])

    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, *args, **kwargs)

# ================= دالة التحويل المحاسبي بين اليوميات =================
def transfer_between_journals(from_code, to_code, amount, memo=""):
    try:
        amt = float(amount)
        if amt <= 0:
            return False, "المبلغ يجب أن يكون أكبر من صفر"

        src = odoo_execute('account.journal', 'search_read', [
            ['|', ('code', '=', from_code), ('name', 'ilike', from_code)]
        ], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})
        
        dst = odoo_execute('account.journal', 'search_read', [
            ['|', ('code', '=', to_code), ('name', 'ilike', to_code)]
        ], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})

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
                    'name': f"{dst[0]['name']}: {memo}",
                    'account_id': dst_acc,
                    'debit': amt,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': f"{src[0]['name']}: {memo}",
                    'account_id': src_acc,
                    'debit': 0.0,
                    'credit': amt,
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
    "📥 إيداع كاش بالجرور", "💵 أرباح إضافية بالجرور",
    "💵 تسجيل أمانة / عربون", "↩️ تسليم / سداد أمانة",
    "📋 كشف الأمانات والعربين", "🔄 تحويل بين المحافظ",
    "⚙️ تعديل أرصدة المحافظ والجرور", "💼 جرد الصندوق والتقرير اليومي",
    "⚙️ لوحة تحكم Odoo السحابية"
]

def get_reply_keyboard():
    keyboard = [
        [KeyboardButton("💵 سحب كاش Whish لزبون"), KeyboardButton("🟣 تعبئة رصيد Whish لزبون")],
        [KeyboardButton("📲 إيداع / تحويل Sham Cash"), KeyboardButton("🏢 تحويل عبر الأندلس")],
        [KeyboardButton("🎮 شحن ألعاب (من الموقع)"), KeyboardButton("➕ تسجيل دين على زبون")],
        [KeyboardButton("✅ سداد دين (قبض من زبون)"), KeyboardButton("📋 ديون لي على الزبائن")],
        [KeyboardButton("📊 كشف حساب زبون محدد"), KeyboardButton("📉 تسجيل مصروف")],
        [KeyboardButton("📥 إيداع كاش بالجرور"), KeyboardButton("💵 أرباح إضافية بالجرور")],
        [KeyboardButton("💵 تسجيل أمانة / عربون"), KeyboardButton("↩️ تسليم / سداد أمانة")],
        [KeyboardButton("📋 كشف الأمانات والعربين"), KeyboardButton("🔄 تحويل بين المحافظ")],
        [KeyboardButton("⚙️ تعديل أرصدة المحافظ والجرور"), KeyboardButton("💼 جرد الصندوق والتقرير اليومي")],
        [KeyboardButton("⚙️ لوحة تحكم Odoo السحابية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_expense_source_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💵 كاش الجرور (الدرج)", callback_data="exp_from_csh"),
            InlineKeyboardButton("🟣 محفظة Whish", callback_data="exp_from_wsh")
        ]
    ])

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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟣 Whish Money", callback_data="tr_from_whish"), InlineKeyboardButton("📲 Sham Cash", callback_data="tr_from_sham")],
        [InlineKeyboardButton("🏢 شركة الأندلس", callback_data="tr_from_andalus"), InlineKeyboardButton("🎮 شحن ألعاب", callback_data="tr_from_game")],
        [InlineKeyboardButton("💵 كاش الجرور (الدرج)", callback_data="tr_from_cash")]
    ])

def get_wallets_adjust_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟣 رصيد Whish", callback_data="adj_whish"), InlineKeyboardButton("📲 رصيد Sham Cash", callback_data="adj_sham")],
        [InlineKeyboardButton("🏢 رصيد الأندلس", callback_data="adj_andalus"), InlineKeyboardButton("🎮 رصيد الألعاب", callback_data="adj_game")],
        [InlineKeyboardButton("💵 رصيد الجرور (كاش)", callback_data="adj_cash")]
    ])

def get_sham_cash_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 إيداع رصيد Sham Cash", callback_data="sham_dep"),
            InlineKeyboardButton("🔄 تحويل رصيد Sham Cash", callback_data="sham_tr")
        ]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "مرحباً بك في نظام إدارة Milana Telecom 🚀\n\n"
        "تم تحديث ومطابقة تقرير الجرد اليومي وحركة كاش الجرور مع Odoo بدقة كاملة."
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

            if curr_name == 'USD' or residual < 10000:
                usd_debt += residual
    except Exception:
        pass

    raw_notes = (partner.get('comment') or "") + " " + (partner.get('narration') or "")
    clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()
    note_balance = 0.0
    for line in clean_notes.split('\n'):
        if "دين مضاف:" in line or "فتح حساب دين جديد:" in line:
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
            if amts:
                note_balance += float(amts[0])
        elif "سداد دين:" in line or "قبض دين:" in line:
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
            if amts:
                note_balance -= float(amts[0])

    final_debt = max(usd_debt, note_balance)
    return round(final_debt, 2), clean_notes

# ================= حساب أمانة الزبون الصافية بدقة =================
def fetch_client_deposit_data(partner):
    p_id = int(partner['id'])
    raw_notes = (partner.get('comment') or "") + " " + (partner.get('narration') or "")
    clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()
    keywords = ['أمانة', 'امانة', 'عربون', 'تأمين', 'تامين', 'رهن']

    total_received = 0.0
    total_released = 0.0
    active_lines = []

    release_keywords = ["تسليم أمانة", "سداد أمانة", "إرجاع أمانة", "تم تسليم", "تم سداد", "إرجاعها"]

    for line in clean_notes.split('\n'):
        line_clean = line.strip('- • \r ')
        if any(kw in line_clean for kw in keywords):
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$?', line_clean)
            if amts:
                val = float(amts[0])
                if any(rw in line_clean for rw in release_keywords):
                    total_released += val
                else:
                    total_received += val
                    active_lines.append(line_clean)

    try:
        amn_moves = odoo_execute('account.move', 'search_read', [
            [('partner_id', '=', p_id), ('state', '!=', 'cancel')]
        ], {'fields': ['amount_residual', 'amount_total', 'ref', 'name']})
        for m in amn_moves:
            ref_txt = (m.get('ref') or "") + " " + (m.get('name') or "")
            if any(kw in ref_txt for kw in keywords) or "AMN" in ref_txt:
                amt = float(m.get('amount_residual') or m.get('amount_total') or 0.0)
                if amt > 0 and amt not in [float(re.findall(r'(\d+(?:\.\d+)?)', l)[0]) for l in active_lines if re.findall(r'(\d+(?:\.\d+)?)', l)]:
                    total_received += amt
                    active_lines.append(f"قيد أمانة دفتري: {amt}$")
    except Exception:
        pass

    net_dep = max(0.0, round(total_received - total_released, 2))
    return net_dep, active_lines, clean_notes

# ================= كشف الأمانات والعربين الشامل =================
async def get_all_deposits_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ومطابقة سجل الأمانات الشامل...")
    try:
        deposits_found = []
        total_market_deposits = 0.0

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
                            'details': f"• قيد دفتري: {amt:,.2f} $ | {memo} ({date}) [{st}]"
                        })
                        total_market_deposits += amt
        except Exception as e_amn:
            logger.warning(f"Error checking AMN moves: {e_amn}")

        try:
            partners = odoo_execute('res.partner', 'search_read', [
                ['|', ('comment', '!=', False), ('customer_rank', '>', 0)]
            ], {'fields': ['id', 'name', 'comment'], 'limit': 300})

            if partners:
                for p in partners:
                    name = p.get('name', 'زبون')
                    net_dep, active_lines, _ = fetch_client_deposit_data(p)

                    if net_dep > 0:
                        existing = next((d for d in deposits_found if d['name'] == name), None)
                        if existing:
                            existing['details'] = f"• صافي الأمانة المتبقية: `{net_dep:,.2f} $`"
                        else:
                            total_market_deposits += net_dep
                            last_action = f" (آخر قيد: {active_lines[-1]})" if active_lines else ""
                            deposits_found.append({
                                'name': name,
                                'details': f"• صافي الأمانة المتبقية: `{net_dep:,.2f} $`{last_action}"
                            })
                    else:
                        deposits_found = [d for d in deposits_found if d['name'] != name]
        except Exception as e_part:
            logger.warning(f"Error checking partners: {e_part}")

        if deposits_found:
            msg = "📋 *كشف الأمانات والعربين المعلقة بذمتنا:*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            for d in deposits_found:
                msg += f"👤 *الزبون:* {d['name']}\n{d['details']}\n────────────────────\n"
            msg += f"\n📊 *إجمالي الأمانات المستحقة للناس:* `{total_market_deposits:,.2f} $`"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("📋 لا توجد أي أمانات معلقة بذمتك حالياً (تم تسليم جميع الأمانات بالكامل ✅).")

    except Exception as e:
        logger.error(f"Error in get_all_deposits_logic: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء جلب الأمانات: {str(e)}")

# ================= تسجيل أمانة جديدة =================
async def add_deposit_logic(partner_name: str, amount: float, memo: str, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        partner_id = False
        if partners:
            partner = partners[0]
            partner_id = partner['id']
            curr_dep, _, clean_notes = fetch_client_deposit_data(partner)
            new_total = round(curr_dep + amount, 2)

            log_entry = f"\n- أمانة: {amount}$ [{memo}] بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry
            odoo_execute('res.partner', 'write', [partner_id], {'comment': updated_notes})
            p_display = partner.get('name', p_name)
        else:
            curr_dep = 0.0
            new_total = amount
            log_entry = f"أمانة: {amount}$ [{memo}] بتاريخ {now_str}"
            partner_id = odoo_execute('res.partner', 'create', [{
                'name': p_name,
                'customer_rank': 1,
                'comment': log_entry
            }])
            p_display = p_name

        msg = (
            f"✅ *تم تسجيل الأمانة بنجاح (تراكمي):*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *الزبون:* {p_display}\n"
            f"💵 *المبلغ المضاف:* {amount:,.2f} $\n"
            f"📝 *البيان:* {memo}\n"
            f"📌 *أماناته السابقة:* {curr_dep:,.2f} $\n"
            f"📊 *إجمالي أماناته المتبقية:* `{new_total:,.2f} $`\n\n"
            f"📌 تظهر مباشرة في *📋 كشف الأمانات والعربين*."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error add deposit: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء تسجيل الأمانة: {str(e)}")

# ================= تسليم / سداد أمانة =================
async def release_deposit_amount_logic(partner_name: str, amount: float, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            partner = partners[0]
            p_id = int(partner['id'])
            p_display = partner.get('name', p_name)
            curr_dep, _, clean_notes = fetch_client_deposit_data(partner)

            remaining = max(0.0, round(curr_dep - amount, 2))

            log_entry = f"\n- تسليم أمانة: {amount}$ بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry
            odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})

            msg = (
                f"↩️ *تم توثيق تسليم / سداد الأمانة بنجاح:*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *الزبون:* {p_display}\n"
                f"💵 *المبلغ المسدد له الآن:* `{amount:,.2f} $`\n"
                f"📌 *أماناته السابقة:* `{curr_dep:,.2f} $`\n"
                f"📊 *صافي المتبقي بذمتنا:* `{remaining:,.2f} $`\n\n"
            )
            if remaining == 0:
                msg += "✅ *تم تصفية أمانة الزبون بالكامل وشطب اسمه من كشف الأمانات المعلقة.*"
            else:
                msg += f"⚠️ ما زال له بذمتنا أمانة متبقية بقيمة `{remaining:,.2f} $`."

            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ لم يتم العثور على زبون باسم [{p_name}] في Odoo!")

    except Exception as e:
        logger.error(f"Error release deposit: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء سداد الأمانة: {str(e)}")

# ================= تسجيل وسداد الديون =================
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
            odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})

            msg = (
                "✅ *تم تسجيل الدين بنجاح في Odoo:*\n"
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
            odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})

            # تسجيل قيد قبض كاش بالجرور لزيادة الصندوق
            try:
                transfer_between_journals("CSH", "CSH", amount, f"سداد دين من الزبون: {p_display_name}")
            except Exception:
                pass

            msg = (
                "✅ *تم توثيق سداد الدين بنجاح:*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *الزبون:* {p_display_name}\n"
                f"💵 *المبلغ المقبوض:* {amount:,.2f} $\n"
                f"📌 *الدين السابق:* {curr_debt:,.2f} $\n"
                f"📊 *الدين المتبقي عليه:* `{remaining:,.2f} $`\n"
                f"📥 تم تحديث البطاقة في Odoo وتوريد الكاش للجرور."
            )
        else:
            msg = f"⚠️ لم يتم العثور على زبون باسم [{p_name}] في Odoo."

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in pay_debt_logic: {e}")
        await update.message.reply_text(f"❌ خطأ أثناء توثيق السداد: {str(e)}")

async def get_all_debts_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ومطابقة ديون الزبائن بالدولار $...")
    try:
        partners = odoo_execute('res.partner', 'search_read', 
            [[('customer_rank', '>', 0)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 300})
        
        res = "📋 *كشف حساب شامل لجميع ديون الزبائن بـ Odoo:*\n━━━━━━━━━━━━━━━━━━━━\n"
        total_all = 0.0
        debtors_count = 0

        if partners:
            for p in partners:
                name = p.get('name', 'زبون غير معروف')
                debt, _ = fetch_client_total_debt(p)
                if debt > 0:
                    debtors_count += 1
                    total_all += debt
                    res += f"👤 {name} : *{debt:,.2f} $*\n"

        if debtors_count > 0:
            res += f"━━━━━━━━━━━━━━━━━━━━\n📊 *إجمالي ديون السوق:* {total_all:,.2f} $\n👥 *عدد الزبائن المدينين:* {debtors_count}"
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
            dep_bal, _, _ = fetch_client_deposit_data(p)

            res_msg = (
                "📊 *كشف حساب العميل:*\n"
                "━━━━━━━━━━━━━━\n"
                f"👤 *الاسم:* {p.get('name')}\n"
                f"📞 *الهاتف:* {phone}\n"
                f"💵 *الدين المطلوب منه:* `{total_debt:,.2f} $`\n"
                f"💰 *أماناته القائمة بذمتنا:* `{dep_bal:,.2f} $`\n\n"
                f"📝 *سجل الحركات:*\n{clean_notes if clean_notes else 'لا توجد حركات مسجلة'}"
            )
            await update.message.reply_text(res_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على زبون باسم [{partner_name}] في Odoo.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء جلب البيانات: {str(e)}")

# ================= جرد الصندوق والتقرير اليومي الشامل (مضبوط 100% لكاش الجرور) =================
async def get_daily_cash_report(update: Update):
    await update.message.reply_text("💼 جاري تجميع جرد الصندوق والتقرير اليومي...")
    try:
        today_str = time.strftime('%Y-%m-%d')

        # 1. مبيعات الـ POS
        pos_orders = odoo_execute('pos.order', 'search_read', [
            [('date_order', '>=', f"{today_str} 00:00:00"), ('state', 'in', ['paid', 'done', 'invoiced'])]
        ], {'fields': ['amount_total']})
        pos_total = sum(float(o.get('amount_total', 0.0)) for o in pos_orders)
        pos_count = len(pos_orders)

        # 2. قراءة قيود اليوم من Odoo
        move_lines = odoo_execute('account.move.line', 'search_read', [
            [('date', '=', today_str), ('parent_state', '=', 'posted')]
        ], {'fields': ['journal_id', 'debit', 'credit', 'ref', 'name']})

        whish_topup = 0.0
        whish_cashout = 0.0
        sham_in = 0.0
        sham_out = 0.0
        andalus_total = 0.0
        game_total = 0.0
        extra_profits_total = 0.0
        extra_profits_count = 0
        cash_in_direct = 0.0
        exp_drawer_total = 0.0
        exp_whish_total = 0.0
        expense_items = []

        for l in move_lines:
            ref = l.get('ref') or ''
            name = l.get('name') or ''
            deb = float(l.get('debit', 0.0))

            if deb > 0:
                if "أرباح إضافية" in ref or "أرباح إضافية" in name:
                    extra_profits_total += deb
                    extra_profits_count += 1
                elif "إيداع كاش مباشر بالجرور" in ref or "إيداع كاش مباشر بالجرور" in name:
                    cash_in_direct += deb
                elif "تعبئة رصيد Whish" in ref or "تعبئة رصيد Whish" in name:
                    whish_topup += deb
                elif "سحب كاش Whish" in ref or "سحب كاش Whish" in name:
                    whish_cashout += deb
                elif "إيداع Sham Cash" in ref or "إيداع Sham Cash" in name:
                    sham_in += deb
                elif "تحويل شام كاش" in ref or "تحويل شام كاش" in name:
                    sham_out += deb
                elif "حوالة الأندلس" in ref or "حوالة الأندلس" in name:
                    andalus_total += deb
                elif "شحن ألعاب" in ref or "شحن ألعاب" in name:
                    game_total += deb
                elif "مصروف [Whish]" in ref or "مصروف [Whish]" in name:
                    exp_whish_total += deb
                    expense_items.append(f"• {ref or name}: {deb:,.2f} $ [Whish]")
                elif "مصروف [جرور]" in ref or "مصروف [جرور]" in name or "EXPCS" in ref:
                    exp_drawer_total += deb
                    expense_items.append(f"• {ref or name}: {deb:,.2f} $ [جرور]")

        # 3. قراءة حركة الأمانات والديون لليوم
        partners = odoo_execute('res.partner', 'search_read', [
            [('comment', '!=', False)]
        ], {'fields': ['comment'], 'limit': 300})

        dep_in_count = 0
        dep_in_total = 0.0
        dep_out_count = 0
        dep_out_total = 0.0

        debt_in_count = 0
        debt_in_total = 0.0
        debt_pay_count = 0
        debt_pay_total = 0.0

        release_keywords = ["تسليم أمانة", "سداد أمانة", "إرجاع أمانة", "تم تسليم", "تم سداد", "إرجاعها"]

        for p in partners:
            notes = str(p.get('comment') or "")
            for line in notes.split('\n'):
                if today_str in line:
                    nums = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
                    if not nums:
                        nums = re.findall(r':\s*(\d+(?:\.\d+)?)', line)

                    if nums:
                        val = float(nums[0])
                        if any(rw in line for rw in release_keywords):
                            dep_out_count += 1
                            dep_out_total += val
                        elif any(kw in line for kw in ['أمانة', 'امانة', 'عربون', 'تأمين', 'تامين', 'رهن']):
                            dep_in_count += 1
                            dep_in_total += val
                        elif "دين مضاف:" in line:
                            debt_in_count += 1
                            debt_in_total += val
                        elif "سداد دين:" in line or "قبض دين:" in line:
                            debt_pay_count += 1
                            debt_pay_total += val

        # 4. حساب المقبوضات والمدفوعات الحقيقية لكاش الجرور بدقة محاسبية
        # المقبوضات النقدية الداخلة للجرور
        drawer_in = round(
            pos_total +                # كاش مبيعات المحل المباشرة
            whish_cashout +            # سحب كاش ويش للزبون
            sham_out +                 # قبض كاش من الزبون لتحويل شام كاش
            andalus_total +            # قبض كاش من الزبون لحوالة الأندلس
            game_total +               # قبض كاش من الزبون لشحن ألعاب
            extra_profits_total +       # أرباح إضافية كاش
            cash_in_direct +           # إيداع كاش مباشر بالجرور
            debt_pay_total +           # كاش مقبوض لسداد ديون الزبائن
            dep_in_total,              # كاش أمانات مستلمة اليوم
            2
        )

        # المدفوعات النقدية الخارجة من الجرور
        drawer_out = round(
            whish_topup +              # كاش خرج لتعبئة رصيد ويش
            sham_in +                  # كاش خرج لإيداع شام كاش
            exp_drawer_total +         # مصاريف دفعت من كاش الجرور
            dep_out_total,             # أمانات سددت وسلمت للزبائن كاش
            2
        )

        net_drawer = round(drawer_in - drawer_out, 2)
        total_all_expenses = exp_drawer_total + exp_whish_total

        report = (
            f"📊 *تقرير جرد الصندوق والنشاط اليومي المفصل*\n"
            f"📅 *التاريخ:* `{today_str}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 *1. حركة كاش الجرور (الدرج CSH):*\n"
            f"• المقبوضات النقدية الداخلة: `{drawer_in:,.2f} $`\n"
            f"• المدفوعات النقدية الخارجة: `{drawer_out:,.2f} $`\n"
            f"• 💰 *صافي رصيد الجرور لليوم:* `{net_drawer:,.2f} $`\n\n"
            f"📉 *2. مصاريف المحل اليومية:*\n"
            f"• مصاريف خُصمت من الجرور: `{exp_drawer_total:,.2f} $`\n"
            f"• مصاريف خُصمت من Whish: `{exp_whish_total:,.2f} $`\n"
            f"• إجمالي المصاريف: `{total_all_expenses:,.2f} $`\n"
        )

        if expense_items:
            report += "قائمة المصاريف:\n" + "\n".join(expense_items[:6]) + "\n\n"

        report += (
            f"✨ *3. أرباح إضافية وإيداعات بالجرور:*\n"
            f"• أرباح إضافية نقدية: `{extra_profits_total:,.2f} $` ({extra_profits_count} عملية)\n"
            f"• إيداع كاش مباشر بالدرج: `{cash_in_direct:,.2f} $`\n\n"
            f"🛒 *4. مبيعات الـ POS المباشرة:*\n"
            f"• عدد العمليات: `{pos_count}` | الإجمالي: `{pos_total:,.2f} $`\n\n"
            f"📥 *5. حركة الأمانات والعربين لليوم:*\n"
            f"• أمانات مستلمة (دخلت الصندوق): `{dep_in_total:,.2f} $` ({dep_in_count} عملية)\n"
            f"• أمانات مسددة (خرجت من الصندوق): `{dep_out_total:,.2f} $` ({dep_out_count} عملية)\n\n"
            f"📋 *6. حركة ديون الزبائن لليوم:*\n"
            f"• ديون جديدة مسجلة: `{debt_in_total:,.2f} $` ({debt_in_count} عملية)\n"
            f"• ديون مقبوضة ومحصلة كاش: `{debt_pay_total:,.2f} $` ({debt_pay_count} عملية)\n\n"
            f"🟣 *7. محفظة Whish Money:*\n"
            f"• تعبئة رصيد (خرج من الجرور): `{whish_topup:,.2f} $`\n"
            f"• سحب كاش (دخل إلى الجرور): `{whish_cashout:,.2f} $`\n\n"
            f"📲 *8. محفظة Sham Cash:*\n"
            f"• إيداع رصيد (خرج من الجرور): `{sham_in:,.2f} $`\n"
            f"• تحويل رصيد (دخل إلى الجرور): `{sham_out:,.2f} $`\n\n"
            f"🏢 *9. شركة الأندلس وشحن الألعاب:*\n"
            f"• حوالات الأندلس (دخلت الجرور): `{andalus_total:,.2f} $`\n"
            f"• شحن بطاقات ألعاب (دخلت الجرور): `{game_total:,.2f} $`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ الحسابات مطابقة بالكامل لحركة الدرج الفعلية ودفاتر Odoo."
        )

        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in cash report: {e}")
        await update.message.reply_text(f"❌ تعذر استخراج تقرير الصندوق: {str(e)}")

# ================= معالجة النصوص والأوامر =================
async def process_user_text(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = text.strip()

    cancel_words = ["إلغاء", "الغاء", "رجوع", "كنسل", "cancel", "/cancel", "وقف", "ارجع", "بطلت"]
    if raw_text.lower() in cancel_words:
        context.user_data.clear()
        await update.message.reply_text("🚫 تم إلغاء العملية والعودة للقائمة الرئيسية.", reply_markup=get_reply_keyboard())
        return

    is_menu_button = raw_text in MENU_BUTTONS
    if is_menu_button and context.user_data.get("state"):
        context.user_data.clear()

    if raw_text == "📋 كشف الأمانات والعربين" or "كشف الأمانات" in raw_text:
        context.user_data.clear()
        await get_all_deposits_logic(update)
        return

    elif raw_text == "💼 جرد الصندوق والتقرير اليومي" or "جرد الصندوق" in raw_text:
        context.user_data.clear()
        await get_daily_cash_report(update)
        return

    elif raw_text == "💵 أرباح إضافية بالجرور":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_EXTRA_PROFIT_AMT"
        await update.message.reply_text("💵 [أرباح إضافية بالجرور]:\nأرسل الآن المبلغ بالدولار $ (مثال: 15):")
        return

    elif raw_text == "📉 تسجيل مصروف":
        context.user_data.clear()
        await update.message.reply_text("📉 تسجيل مصروف جديد:\nحدد مصدر دفع المصروف:", reply_markup=get_expense_source_keyboard())
        return

    elif raw_text == "💵 تسجيل أمانة / عربون" or "تسجيل أمانة" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_DEPOSIT_NAME"
        await update.message.reply_text("💵 [تسجيل أمانة / عربون]:\nأرسل الآن *اسم الزبون*:")
        return

    elif raw_text == "↩️ تسليم / سداد أمانة" or "تسليم أمانة" in raw_text:
        context.user_data.clear()
        context.user_data["state"] = "WAITING_REL_DEP_NAME"
        await update.message.reply_text("↩️ [تسليم / سداد أمانة]:\nأرسل الآن *اسم الزبون*:")
        return

    elif raw_text == "➕ تسجيل دين على زبون":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_DEBT_NAME"
        await update.message.reply_text("➕ تسجيل دين على زبون:\nأرسل الآن *اسم الزبون*:")
        return

    elif raw_text == "✅ سداد دين (قبض من زبون)":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_PAY_DEBT_NAME"
        await update.message.reply_text("✅ [سداد دين - قبض]:\nأرسل الآن *اسم الزبون*:")
        return

    elif raw_text == "📋 ديون لي على الزبائن":
        context.user_data.clear()
        await get_all_debts_logic(update)
        return

    elif raw_text == "📊 كشف حساب زبون محدد":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_STATEMENT_NAME"
        await update.message.reply_text("📊 أرسل الآن *اسم الزبون* لجلب كشف حسابه:")
        return

    elif raw_text == "🟣 تعبئة رصيد Whish لزبون":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_WHISH_TOPUP"
        await update.message.reply_text("🟣 [تعبئة رصيد Whish]:\nأرسل المبلغ بالدولار $:")
        return

    elif raw_text == "💵 سحب كاش Whish لزبون":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_WHISH_CASHOUT"
        await update.message.reply_text("💵 [سحب كاش Whish]:\nأرسل المبلغ بالدولار $:")
        return

    elif raw_text == "📲 إيداع / تحويل Sham Cash":
        context.user_data.clear()
        await update.message.reply_text("📲 اختر نوع حركة Sham Cash:", reply_markup=get_sham_cash_keyboard())
        return

    elif raw_text == "🏢 تحويل عبر الأندلس":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_ANDALUS_INFO"
        await update.message.reply_text("🏢 [تحويل الأندلس]:\nأدخل المبلغ واسم المستلم (مثال: 50$ محمد):")
        return

    elif raw_text == "🎮 شحن ألعاب (من الموقع)":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_GAME_INFO"
        await update.message.reply_text("🎮 [شحن ألعاب]:\nأدخل المبلغ والبيانات (مثال: 10$ لعبة):")
        return

    elif raw_text == "📥 إيداع كاش بالجرور":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_CASH_IN"
        await update.message.reply_text("📥 [إيداع كاش بالجرور]:\nأرسل المبلغ بالدولار $:")
        return

    elif raw_text == "🔄 تحويل بين المحافظ":
        context.user_data.clear()
        await update.message.reply_text("🔄 اختر المحفظة المحول منها:", reply_markup=get_wallets_transfer_from_keyboard())
        return

    elif raw_text == "⚙️ تعديل أرصدة المحافظ والجرور":
        context.user_data.clear()
        await update.message.reply_text("⚙️ اختر الحساب المراد تعديل رصيده:", reply_markup=get_wallets_adjust_keyboard())
        return

    elif raw_text == "⚙️ لوحة تحكم Odoo السحابية":
        context.user_data.clear()
        await update.message.reply_text("لوحة مراقبة Odoo المباشرة:", reply_markup=get_odoo_inline_keyboard())
        return

    state = context.user_data.get("state")

    # إدخال الأمانة
    if state == "WAITING_DEPOSIT_NAME":
        context.user_data["dep_partner_name"] = raw_text.strip()
        context.user_data["state"] = "WAITING_DEPOSIT_AMOUNT"
        await update.message.reply_text(f"كم مبلغ أمانة الزبون ({raw_text}) بالدولار $؟")
        return

    elif state == "WAITING_DEPOSIT_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data["dep_amount"] = float(clean_num)
            context.user_data["state"] = "WAITING_DEPOSIT_MEMO"
            await update.message.reply_text("اكتب بيان أو سبب الأمانة (أو أرسل نقطة . للتخطي):")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ للمبلغ! تم الإلغاء.")
        return

    elif state == "WAITING_DEPOSIT_MEMO":
        memo = raw_text if raw_text != "." else "أمانة نقدية"
        partner_name = context.user_data.get("dep_partner_name")
        amount = context.user_data.get("dep_amount")
        context.user_data.clear()
        await add_deposit_logic(partner_name, amount, memo, update)
        return

    # سداد أمانة
    elif state == "WAITING_REL_DEP_NAME":
        partner_name = raw_text.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', partner_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        if partners:
            dep_bal, _, _ = fetch_client_deposit_data(partners[0])
            context.user_data["rel_partner_name"] = partners[0]['name']
            context.user_data["state"] = "WAITING_REL_DEP_AMOUNT"
            await update.message.reply_text(
                f"👤 الزبون: *{partners[0]['name']}*\n"
                f"💰 أماناته الحالية بذمتنا: `{dep_bal:,.2f} $`\n\n"
                f"كم المبلغ المراد تسليمه/سداده له بالدولار $؟",
                parse_mode="Markdown"
            )
            return
        else:
            context.user_data.clear()
            await update.message.reply_text(f"⚠️ لم يتم العثور على زبون باسم [{partner_name}] في Odoo!")
            return

    elif state == "WAITING_REL_DEP_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            amount = float(clean_num)
            partner_name = context.user_data.get("rel_partner_name")
            context.user_data.clear()
            await release_deposit_amount_logic(partner_name, amount, update)
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ للمبلغ!")
        return

    # إدخال المصاريف
    elif state == "WAITING_EXPENSE_DATA":
        source_code = context.user_data.get("exp_source_code", "CSH")
        source_name = context.user_data.get("exp_source_name", "كاش الجرور")
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        
        tag = "[Whish]" if source_code == "WSH" else "[جرور]"
        memo = f"مصروف {tag}: {raw_text}"
        
        context.user_data.clear()
        ok, res = transfer_between_journals(source_code, "EXPCS", amt, memo)
        
        msg = (
            f"✅ *تم توثيق وخصم المصروف بنجاح:*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 *المبلغ:* `{amt:,.2f} $`\n"
            f"📝 *البيان:* {raw_text}\n"
            f"🏦 *المصدر:* تم خصمه من *{source_name}*\n"
            f"({res})"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # أرباح إضافية
    elif state == "WAITING_EXTRA_PROFIT_AMT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data["profit_amt"] = float(clean_num)
            context.user_data["state"] = "WAITING_EXTRA_PROFIT_MEMO"
            await update.message.reply_text("اكتب تفاصيل أو مصدر الربح (مثال: صيانة شاشة أو أرسل نقطة . للتخطي):")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ للمبلغ!")
        return

    elif state == "WAITING_EXTRA_PROFIT_MEMO":
        memo = raw_text if raw_text != "." else "أرباح إضافية"
        amt = context.user_data.get("profit_amt", 0.0)
        context.user_data.clear()
        try:
            transfer_between_journals("CSH", "CSH", amt, f"أرباح إضافية بالجرور: {memo}")
        except Exception:
            pass
        msg = (
            "✅ *تم توثيق الأرباح الإضافية بالجرور:*\n"
            f"💵 *المبلغ:* `{amt:,.2f} $`\n"
            f"📝 *البيان:* {memo}\n"
            f"📥 أضيفت فوراً لكاش الجرور وستظهر بتقرير الجرد اليومي."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # تسجيل دين
    elif state == "WAITING_DEBT_NAME":
        context.user_data["debt_partner_name"] = raw_text.strip()
        context.user_data["state"] = "WAITING_DEBT_AMOUNT"
        await update.message.reply_text(f"كم المبلغ المراد إضافته لدين ({raw_text}) بالدولار $؟")
        return

    elif state == "WAITING_DEBT_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            amount = float(clean_num)
            p_name = context.user_data.get("debt_partner_name")
            context.user_data.clear()
            await add_debt_logic(p_name, amount, update)
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ للمبلغ!")
        return

    # سداد دين
    elif state == "WAITING_PAY_DEBT_NAME":
        context.user_data["pay_partner_name"] = raw_text.strip()
        context.user_data["state"] = "WAITING_PAY_DEBT_AMOUNT"
        await update.message.reply_text(f"كم المبلغ المقبوض من ({raw_text}) بالدولار $؟")
        return

    elif state == "WAITING_PAY_DEBT_AMOUNT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            amount = float(clean_num)
            p_name = context.user_data.get("pay_partner_name")
            context.user_data.clear()
            await pay_debt_logic(p_name, amount, update)
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ للمبلغ!")
        return

    elif state == "WAITING_STATEMENT_NAME":
        context.user_data.clear()
        await get_statement_logic(raw_text, update)
        return

    elif state == "WAITING_WHISH_TOPUP":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            ok, res = transfer_between_journals("CSH", "WSH", amt, "تعبئة رصيد Whish")
            await update.message.reply_text(f"✅ تم ترحيل تعبئة Whish بـ Odoo:\n- نقص من الجرور: {amt} $\n- زاد برصيد Whish: {amt} $\n({res})")
            return
        context.user_data.clear()
        return

    elif state == "WAITING_WHISH_CASHOUT":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            ok, res = transfer_between_journals("WSH", "CSH", amt, "سحب كاش Whish")
            await update.message.reply_text(f"✅ تم ترحيل سحب Whish بـ Odoo:\n- زاد كاش الجرور: {amt} $\n- نقص من Whish: {amt} $\n({res})")
            return
        context.user_data.clear()
        return

    elif state == "WAITING_SHAM_DEP":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            ok, res = transfer_between_journals("CSH", "SHM", amt, "إيداع Sham Cash")
            await update.message.reply_text(f"✅ تم ترحيل إيداع Sham Cash بـ Odoo:\n- خرج من الجرور: {amt} $\n- زاد برصيد Sham: {amt} $\n({res})")
            return
        context.user_data.clear()
        return

    elif state == "WAITING_SHAM_TR":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("SHM", "CSH", amt, f"تحويل شام كاش: {raw_text}")
        await update.message.reply_text(f"✅ تم توثيق تحويل Sham Cash بـ Odoo:\n- زاد كاش الجرور: {amt} $\n- نقص من محفظة Sham: {amt} $\n({res})")
        return

    elif state == "WAITING_ANDALUS_INFO":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("ANDL", "CSH", amt, f"حوالة الأندلس: {raw_text}")
        await update.message.reply_text(f"✅ تم ترحيل حوالة شركة الأندلس بـ Odoo:\n- زاد كاش الجرور: {amt} $\n- نقص من رصيد الأندلس: {amt} $\n({res})")
        return

    elif state == "WAITING_GAME_INFO":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("GAME", "CSH", amt, f"شحن ألعاب: {raw_text}")
        await update.message.reply_text(f"✅ تم ترحيل شحن الألعاب بـ Odoo:\n- زاد كاش الجرور: {amt} $\n- نقص من رصيد الألعاب: {amt} $\n({res})")
        return

    elif state == "WAITING_CASH_IN":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            try:
                transfer_between_journals("CSH", "CSH", amt, "إيداع كاش مباشر بالجرور")
            except Exception:
                pass
            await update.message.reply_text(f"✅ تم تسجيل إيداع نقدي مباشر بالجرور بمبلغ: {amt:,.2f} $ وتمت إضافته لرصيد الصندوق.")
            return
        context.user_data.clear()
        return

    # التلقائي الصوتي والنصي
    if "مين له عندي" in raw_text or "مين الو عندي" in raw_text:
        await get_all_deposits_logic(update)
        return

    if any(kw in raw_text for kw in ["كشف حساب", "شو عليه", "شو عليها", "قديه بدي", "قديش بدي"]):
        target = raw_text
        for w in ["كشف حساب", "شو عليه", "شو عليها", "قديه بدي من", "قديش بدي من", "قديه بدي", "قديش بدي", "الزبون", "$"]:
            target = target.replace(w, "")
        target = target.strip()
        if target:
            await get_statement_logic(target, update)
            return

    await update.message.reply_text("اختر العملية من لوحة الأزرار أدناه.", reply_markup=get_reply_keyboard())

# ================= معالجة الصوت والأزرار =================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_user_text(update.message.text, update, context)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    if not voice:
        return
    status_msg = await update.message.reply_text("⚡ جاري استماع وتحليل الصوت...")
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

        await status_msg.edit_text(f"🗣️ \"{spoken_text}\"")
        await process_user_text(spoken_text, update, context)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await status_msg.edit_text("❌ لم أفهم الصوت بوضوح.")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "exp_from_csh":
        context.user_data["exp_source_code"] = "CSH"
        context.user_data["exp_source_name"] = "كاش الجرور"
        context.user_data["state"] = "WAITING_EXPENSE_DATA"
        await query.edit_message_text("💵 [مصروف من كاش الجرور]:\nأرسل الآن البند والمبلغ (مثال: كهرباء 10$):")

    elif data == "exp_from_wsh":
        context.user_data["exp_source_code"] = "WSH"
        context.user_data["exp_source_name"] = "محفظة Whish"
        context.user_data["state"] = "WAITING_EXPENSE_DATA"
        await query.edit_message_text("🟣 [مصروف من محفظة Whish]:\nأرسل الآن البند والمبلغ (مثال: اشتراك انترنت 25$):")

    elif data == "sham_dep":
        context.user_data["state"] = "WAITING_SHAM_DEP"
        await query.edit_message_text("📥 [إيداع رصيد Sham Cash]:\nأرسل المبلغ بالدولار $:")

    elif data == "sham_tr":
        context.user_data["state"] = "WAITING_SHAM_TR"
        await query.edit_message_text("🔄 [تحويل Sham Cash]:\nأرسل رقم الهاتف والمبلغ:")

    elif data == "check_status":
        uid, _ = get_odoo_connection()
        if uid:
            await query.edit_message_text("الاتصال بسيرفر Odoo ممتاز ونشط ✅", reply_markup=get_odoo_inline_keyboard())
        else:
            await query.edit_message_text("❌ السيرفر غير متصل.", reply_markup=get_odoo_inline_keyboard())

    elif data == "refresh_menu":
        await query.edit_message_text("تم تحديث اللوحة بنجاح ✅", reply_markup=get_odoo_inline_keyboard())

# ================= تشغيل البوت =================
def run_cloud_bot():
    while True:
        try:
            print("تشغيل بوت Milana Telecom النظيف...")
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
            app.run_polling(timeout=60, drop_pending_updates=True)
        except Exception as e:
            logger.error(f"انقطاع: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_cloud_bot()
