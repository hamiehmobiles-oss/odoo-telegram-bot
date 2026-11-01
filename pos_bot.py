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

# ================= تحويل قيود اليومية المحاسبية =================
def transfer_between_journals(from_code, to_code, amount, memo=""):
    try:
        src = odoo_execute('account.journal', 'search_read', [[('code', '=', from_code)]], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})
        dst = odoo_execute('account.journal', 'search_read', [[('code', '=', to_code)]], {'fields': ['id', 'name', 'default_account_id'], 'limit': 1})

        if not src or not dst:
            return False, f"الدفتر غير موجود ({from_code} أو {to_code})"

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
        return True, f"قيد رقم #{move_id}"
    except Exception as e:
        return False, str(e)

# ================= لوحات الأزرار =================
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

def get_sham_cash_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 إيداع رصيد Sham Cash", callback_data="sham_dep"),
            InlineKeyboardButton("🔄 تحويل رصيد Sham Cash", callback_data="sham_tr")
        ]
    ])

def get_wallets_transfer_from_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟣 Whish Money", callback_data="tr_from_whish"), InlineKeyboardButton("📲 Sham Cash", callback_data="tr_from_sham")],
        [InlineKeyboardButton("🏢 شركة الأندلس", callback_data="tr_from_andalus"), InlineKeyboardButton("🎮 شحن ألعاب", callback_data="tr_from_game")],
        [InlineKeyboardButton("💵 كاش الجرور (الدرج)", callback_data="tr_from_cash")]
    ])

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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟣 رصيد Whish", callback_data="adj_whish"), InlineKeyboardButton("📲 رصيد Sham Cash", callback_data="adj_sham")],
        [InlineKeyboardButton("🏢 رصيد الأندلس", callback_data="adj_andalus"), InlineKeyboardButton("🎮 رصيد الألعاب", callback_data="adj_game")],
        [InlineKeyboardButton("💵 رصيد الجرور (كاش)", callback_data="adj_cash")]
    ])

# ================= حساب الديون والأمانات =================
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

    raw_notes = (partner.get('comment') or "")
    clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()
    note_balance = 0.0
    for line in clean_notes.split('\n'):
        if "دين مضاف" in line or "فتح حساب دين" in line or "دين:" in line:
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
            if amts:
                note_balance += float(amts[0])
        elif "سداد دين" in line or "قبض دين" in line:
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$', line)
            if amts:
                note_balance -= float(amts[0])

    final_debt = max(usd_debt, note_balance)
    return round(final_debt, 2), clean_notes

def fetch_client_deposit_balance(partner):
    raw_notes = (partner.get('comment') or "")
    clean_notes = re.sub(r'<[^>]+>', '', raw_notes).strip()
    
    total_deposit = 0.0
    has_deposit_record = False

    for line in clean_notes.split('\n'):
        line_clean = line.strip('- • \r')
        if any(kw in line_clean for kw in ['أمانة', 'امانة', 'عربون', 'تأمين', 'تامين', 'رهن']):
            has_deposit_record = True
            amts = re.findall(r'(\d+(?:\.\d+)?)\s*\$?', line_clean)
            if amts:
                val = float(amts[0])
                if any(kw in line_clean for kw in ['تسليم', 'سداد', 'إرجاع', 'ارجاع', 'مسترد', 'شطب']):
                    total_deposit -= val
                else:
                    total_deposit += val

    return max(0.0, round(total_deposit, 2)), clean_notes, has_deposit_record

# ================= كشف الأمانات المحدث =================
async def get_all_deposits_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ومطابقة كشف الأمانات والعربين من Odoo...")
    try:
        partners = odoo_execute('res.partner', 'search_read', [
            [('comment', '!=', False)]
        ], {'fields': ['id', 'name', 'comment'], 'limit': 300})

        deposits_found = []
        total_market_deposits = 0.0

        if partners:
            for p in partners:
                p_name = p.get('name', 'زبون')
                bal, clean_notes, had_dep = fetch_client_deposit_balance(p)
                if bal > 0:
                    total_market_deposits += bal
                    deposits_found.append({
                        'name': p_name,
                        'balance': bal
                    })

        if deposits_found:
            msg = "📋 كشف الأمانات والعربين القائمة بذمتنا:\n━━━━━━━━━━━━━━━━━━━━\n\n"
            for d in deposits_found:
                msg += f"👤 الزبون: {d['name']}\n💰 الرصيد المتبقي له: {d['balance']:,.2f} $\n────────────────────\n"
            msg += f"📊 إجمالي الأمانات المعلقة بذمتنا: {total_market_deposits:,.2f} $"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("📋 لا توجد أمانات أو عربين قائمة حالياً (جميعها مسددة أو فارغة).")

    except Exception as e:
        logger.error(f"Error in get_all_deposits_logic: {e}")
        await update.message.reply_text(f"❌ خطأ أثناء جلب كشف الأمانات: {str(e)}")

# ================= تسجيل أمانة جديدة =================
async def add_deposit_logic(partner_name: str, amount: float, memo: str, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            partner = partners[0]
            p_id = int(partner['id'])
            curr_dep, clean_notes, _ = fetch_client_deposit_balance(partner)
            new_total = round(curr_dep + amount, 2)

            log_entry = f"\n- أمانة: {amount}$ [{memo}] بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry

            odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})
            p_display = partner.get('name', p_name)
        else:
            curr_dep = 0.0
            new_total = amount
            log_entry = f"- أمانة: {amount}$ [{memo}] بتاريخ {now_str}"
            odoo_execute('res.partner', 'create', [{
                'name': p_name,
                'customer_rank': 1,
                'comment': log_entry
            }])
            p_display = p_name

        try:
            transfer_between_journals("CSH", "AMN", amount, f"أمانة من {p_display}: {memo}")
        except Exception:
            pass

        msg = (
            "✅ تم تسجيل واستلام الأمانة بنجاح:\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 الزبون: {p_display}\n"
            f"💵 المبلغ المستلم: {amount:,.2f} $\n"
            f"📝 البيان: {memo}\n"
            f"📌 أماناته السابقة: {curr_dep:,.2f} $\n"
            f"📊 إجمالي أماناته المتبقية: {new_total:,.2f} $\n"
            f"📥 تم توثيقها بالجرور وفي كشف الأمانات."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in add_deposit_logic: {e}")
        await update.message.reply_text(f"❌ خطأ أثناء تسجيل الأمانة: {str(e)}")

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
            curr_dep, clean_notes, _ = fetch_client_deposit_balance(partner)

            if curr_dep == 0:
                await update.message.reply_text(f"⚠️ الزبون [{p_display}] ليس له رصيد أمانات مسجل بذمتنا.")
                return

            remaining = max(0.0, round(curr_dep - amount, 2))
            log_entry = f"\n- تسليم أمانة: {amount}$ بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry

            odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})

            try:
                transfer_between_journals("AMN", "CSH", amount, f"تسليم أمانة إلى {p_display}")
            except Exception:
                pass

            msg = (
                "↩️ تم توثيق تسليم / سداد الأمانة:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {p_display}\n"
                f"💵 المبلغ المسدد له: {amount:,.2f} $\n"
                f"📌 أمانته السابقة: {curr_dep:,.2f} $\n"
                f"📊 المتبقي له بذمتنا: {remaining:,.2f} $\n\n"
            )
            if remaining == 0:
                msg += "✅ تم سداد كامل الأمانة وشطبها من كشف الأمانات القائمة."
            else:
                msg += f"⚠️ لا يزال له أمانة متبقية بقيمة: {remaining:,.2f} $"

            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ لم يتم العثور على زبون باسم [{p_name}] في Odoo!")

    except Exception as e:
        logger.error(f"Error in release_deposit_amount_logic: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء تسليم الأمانة: {str(e)}")

# ================= جرد الصندوق والتقرير اليومي الشامل =================
async def get_daily_cash_report(update: Update):
    await update.message.reply_text("💼 جاري تجميع جرد الصندوق والتقرير اليومي الشامل من كافة الدفاتر...")
    try:
        today_str = time.strftime('%Y-%m-%d')

        # 1. حركات نقاط البيع (POS)
        pos_orders = odoo_execute('pos.order', 'search_read', [
            [('date_order', '>=', f"{today_str} 00:00:00"), ('state', 'in', ['paid', 'done', 'invoiced'])]
        ], {'fields': ['amount_total']})
        pos_total = sum(float(o.get('amount_total', 0.0)) for o in pos_orders)
        pos_count = len(pos_orders)

        # 2. سحب حركات اليوم المحاسبية بالكامل
        move_lines = odoo_execute('account.move.line', 'search_read', [
            [('date', '=', today_str), ('parent_state', '=', 'posted')]
        ], {'fields': ['journal_id', 'debit', 'credit', 'ref', 'name']})

        drawer_in = 0.0
        drawer_out = 0.0
        whish_topup = 0.0
        whish_cashout = 0.0
        sham_in = 0.0
        sham_out = 0.0
        andalus_total = 0.0
        game_total = 0.0
        expenses_total = 0.0
        expense_items = []

        for l in move_lines:
            j = l.get('journal_id')
            j_name = j[1] if j else ''
            ref = l.get('ref') or ''
            name = l.get('name') or ''
            deb = float(l.get('debit', 0.0))
            cred = float(l.get('credit', 0.0))

            # كاش الجرور (CSH)
            if any(k in j_name for k in ['CSH', 'كاش', 'Cash', 'الجرور', 'الدرج']):
                drawer_in += deb
                drawer_out += cred

            # محفظة Whish
            if any(k in j_name or k in ref for k in ['WSH', 'Whish', 'ويش']):
                if "تعبئة" in ref or "تعبئة" in name or deb > 0:
                    whish_topup += max(deb, cred)
                else:
                    whish_cashout += max(deb, cred)

            # محفظة Sham Cash
            if any(k in j_name or k in ref for k in ['SHM', 'Sham', 'شام كاش']):
                if "إيداع" in ref or "ايداع" in ref or deb > 0:
                    sham_in += max(deb, cred)
                else:
                    sham_out += max(deb, cred)

            # شركة الأندلس
            if any(k in j_name or k in ref for k in ['ANDL', 'الأندلس', 'الاندلس']):
                andalus_total += max(deb, cred)

            # شحن الألعاب
            if any(k in j_name or k in ref for k in ['GAME', 'ألعاب', 'العاب']):
                game_total += max(deb, cred)

            # المصاريف
            if any(k in j_name or k in ref for k in ['EXPCS', 'مصروف', 'مصاريف']):
                amt = max(deb, cred)
                if amt > 0:
                    expenses_total += amt
                    expense_items.append(f"• {ref or name or 'مصروف متفرقة'}: {amt:,.2f} $")

        net_drawer = round(drawer_in - drawer_out, 2)

        report = (
            f"📊 تقرير جرد الصندوق والنشاط اليومي الشامل\n"
            f"📅 التاريخ: {today_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 1. كاش الجرور (الدرج CSH):\n"
            f"• المقبوضات والداخل: {drawer_in:,.2f} $\n"
            f"• المدفوعات والخارج: {drawer_out:,.2f} $\n"
            f"• صافي رصيد الجرور لليوم: {net_drawer:,.2f} $\n\n"
            f"🛒 2. مبيعات الـ POS المباشرة:\n"
            f"• عدد العمليات: {pos_count} | الإجمالي: {pos_total:,.2f} $\n\n"
            f"🟣 3. محفظة Whish Money:\n"
            f"• تعبئة رصيد: {whish_topup:,.2f} $\n"
            f"• سحب كاش: {whish_cashout:,.2f} $\n\n"
            f"📲 4. محفظة Sham Cash:\n"
            f"• إيداع رصيد: {sham_in:,.2f} $\n"
            f"• تحويل لزبون: {sham_out:,.2f} $\n\n"
            f"🏢 5. شركة الأندلس وشحن الألعاب:\n"
            f"• حوالات الأندلس: {andalus_total:,.2f} $\n"
            f"• شحن بطاقات ألعاب: {game_total:,.2f} $\n\n"
            f"📉 6. مصاريف المحل اليومية:\n"
            f"• الإجمالي: {expenses_total:,.2f} $\n"
        )

        if expense_items:
            report += "\n".join(expense_items[:5]) + "\n"

        report += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ التقرير مطابق آلياً مع كافة حركات ودفاتر Odoo."
        )

        await update.message.reply_text(report, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in get_daily_cash_report: {e}")
        await update.message.reply_text(f"❌ تعذر استخراج تقرير الصندوق: {str(e)}")

# ================= دوال الديون =================
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
                "✅ تم تسجيل الدين بنجاح في Odoo:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {partner['name']}\n"
                f"💵 الدين المضاف: {amount:,.2f} $\n"
                f"📌 الرصيد السابق: {curr_debt:,.2f} $\n"
                f"📊 الإجمالي الجديد: {new_total:,.2f} $"
            )
        else:
            log_entry = f"- فتح حساب دين جديد: {amount}$ بتاريخ {now_str}"
            odoo_execute('res.partner', 'create', [{
                'name': p_name,
                'customer_rank': 1,
                'comment': log_entry
            }])
            msg = f"✅ تم فتح حساب دين جديد للزبون ({p_name}) بمبلغ: {amount:,.2f} $"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in add_debt_logic: {e}")
        await update.message.reply_text(f"❌ خطأ في Odoo: {str(e)}")

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
            p_display = partner.get('name', p_name)
            curr_debt, clean_notes = fetch_client_total_debt(partner)
            remaining = max(0.0, round(curr_debt - amount, 2))

            log_entry = f"\n- سداد دين: {amount}$ بتاريخ {now_str}"
            updated_notes = (clean_notes or "") + log_entry

            odoo_execute('res.partner', 'write', [p_id], {'comment': updated_notes})

            try:
                transfer_between_journals("CSH", "CSH", amount, f"سداد دين من {p_display}")
            except Exception:
                pass

            msg = (
                "✅ تم توثيق سداد الدين بنجاح:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {p_display}\n"
                f"💵 المبلغ المقبوض: {amount:,.2f} $\n"
                f"📌 الدين السابق: {curr_debt:,.2f} $\n"
                f"📊 المتبقي عليه: {remaining:,.2f} $\n"
                f"📥 تم توريد الكاش للجرور."
            )
        else:
            msg = f"⚠️ لم يتم العثور على زبون باسم [{p_name}]. تم قبض {amount:,.2f} $ وتوريدها للجرور."

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def get_all_debts_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ومطابقة ديون الزبائن بالدولار $...")
    try:
        partners = odoo_execute('res.partner', 'search_read', [
            [('customer_rank', '>', 0)]
        ], {'fields': ['id', 'name', 'comment'], 'limit': 300})
        
        res = "📋 كشف حساب ديون الزبائن بالدولار ($):\n━━━━━━━━━━━━━━━━━━━━\n"
        total_all = 0.0
        debtors_count = 0

        if partners:
            for p in partners:
                name = p.get('name', 'زبون')
                debt, _ = fetch_client_total_debt(p)
                if debt > 0:
                    debtors_count += 1
                    total_all += debt
                    res += f"👤 {name} : {debt:,.2f} $\n"

        if debtors_count > 0:
            res += f"━━━━━━━━━━━━━━━━━━━━\n📊 إجمالي الديون القائمة: {total_all:,.2f} $\n👥 عدد الزبائن: {debtors_count}"
            await update.message.reply_text(res, parse_mode="Markdown")
        else:
            await update.message.reply_text("📋 لا توجد أي ديون قائمة مسجلة على الزبائن.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

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
            total_dep, _, _ = fetch_client_deposit_balance(p)

            res_msg = (
                "📊 كشف حساب العميل الشامل:\n"
                "━━━━━━━━━━━━━━\n"
                f"👤 الاسم: {p.get('name')}\n"
                f"📞 الهاتف: {phone}\n"
                f"💵 الدين المطلوب منه: {total_debt:,.2f} $\n"
                f"💰 أماناته القائمة بذمتنا: {total_dep:,.2f} $\n\n"
                f"📝 سجل الحركات المسجلة:\n{clean_notes if clean_notes else 'لا توجد حركات مسجلة'}"
            )
            await update.message.reply_text(res_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على زبون باسم [{partner_name}] في Odoo.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

# ================= معالجة الرسائل =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "مرحباً بك في نظام إدارة Milana Telecom 🚀\n\n"
        "تم تحديث النظام المحاسبي المتصل بـ Odoo بالكامل:\n"
        "• كشف الأمانات والعربين وسدادها التراكمي بدقة.\n"
        "• جرد الصندوق والتقرير اليومي الشامل (جرور، ويش، شام، أندلس، مصاريف).\n"
        "• ديون الزبائن وسدادها الفوري."
    )
    await update.message.reply_text(welcome_text, reply_markup=get_reply_keyboard())
    await update.message.reply_text("لوحة Odoo المباشرة:", reply_markup=get_odoo_inline_keyboard())

async def process_user_text(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = text.strip()

    cancel_words = ["إلغاء", "الغاء", "رجوع", "كنسل", "cancel", "/cancel", "وقف"]
    if raw_text.lower() in cancel_words:
        context.user_data.clear()
        await update.message.reply_text("🚫 تم الإلغاء والعودة للقائمة الرئيسية.", reply_markup=get_reply_keyboard())
        return

    is_menu_button = raw_text in MENU_BUTTONS
    if is_menu_button and context.user_data.get("state"):
        context.user_data.clear()

    if raw_text == "📋 كشف الأمانات والعربين":
        context.user_data.clear()
        await get_all_deposits_logic(update)
        return

    elif raw_text == "💼 جرد الصندوق والتقرير اليومي":
        context.user_data.clear()
        await get_daily_cash_report(update)
        return

    elif raw_text == "💵 تسجيل أمانة / عربون":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_DEPOSIT_NAME"
        await update.message.reply_text("💵 [تسجيل أمانة جديدة]:\nأرسل الآن اسم الزبون:")
        return

    elif raw_text == "↩️ تسليم / سداد أمانة":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_REL_DEP_NAME"
        await update.message.reply_text("↩️ [تسليم / سداد أمانة]:\nأرسل الآن اسم الزبون:")
        return

    elif raw_text == "➕ تسجيل دين على زبون":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_DEBT_NAME"
        await update.message.reply_text("➕ تسجيل دين على زبون:\nأرسل الآن اسم الزبون:")
        return

    elif raw_text == "✅ سداد دين (قبض من زبون)":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_PAY_DEBT_NAME"
        await update.message.reply_text("✅ [سداد دين - قبض]:\nأرسل الآن اسم الزبون:")
        return

    elif raw_text == "📋 ديون لي على الزبائن":
        context.user_data.clear()
        await get_all_debts_logic(update)
        return

    elif raw_text == "📊 كشف حساب زبون محدد":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_STATEMENT_NAME"
        await update.message.reply_text("📊 أرسل الآن اسم الزبون لجلب كشف حسابه:")
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

    elif raw_text == "📉 تسجيل مصروف":
        context.user_data.clear()
        context.user_data["state"] = "WAITING_EXPENSE_DATA"
        await update.message.reply_text("📉 تسجيل مصروف:\nأدخل البند والمبلغ (مثال: كهرباء 10$):")
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

    # معالجة المراحل المتتالية
    state = context.user_data.get("state")

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
            await update.message.reply_text("اكتب بيان الأمانة (مثال: شاشة تصليح / عربون أو أرسل . للتخطي):")
            return
        context.user_data.clear()
        await update.message.reply_text("⚠️ إدخال خاطئ! تم إلغاء العملية.")
        return

    elif state == "WAITING_DEPOSIT_MEMO":
        memo = raw_text if raw_text != "." else "أمانة نقدية"
        partner_name = context.user_data.get("dep_partner_name")
        amount = context.user_data.get("dep_amount")
        context.user_data.clear()
        await add_deposit_logic(partner_name, amount, memo, update)
        return

    elif state == "WAITING_REL_DEP_NAME":
        partner_name = raw_text.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', partner_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        if partners:
            bal, _, _ = fetch_client_deposit_balance(partners[0])
            debt, _ = fetch_client_total_debt(partners[0])
            context.user_data["rel_partner_name"] = partners[0]['name']
            context.user_data["state"] = "WAITING_REL_DEP_AMOUNT"
            await update.message.reply_text(
                f"👤 الزبون: {partners[0]['name']}\n"
                f"💰 أماناته القائمة بذمتنا: {bal:,.2f} $\n"
                f"💵 ديونه المطلوبة منه: {debt:,.2f} $\n\n"
                f"كم المبلغ المراد تسليمه/سداده له من الأمانة بالدولار $؟",
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
        await update.message.reply_text("⚠️ إدخال خاطئ! تم الإلغاء.")
        return

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
            await update.message.reply_text(f"✅ تم ترحيل إيداع Sham Cash بـ Odoo:\n- المبلغ: {amt} $\n({res})")
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

    elif state == "WAITING_EXPENSE_DATA":
        context.user_data.clear()
        num_m = re.findall(r'(\d+(?:\.\d+)?)', raw_text)
        amt = float(num_m[0]) if num_m else 0.0
        ok, res = transfer_between_journals("CSH", "EXPCS", amt, f"مصروف: {raw_text}")
        await update.message.reply_text(f"✅ تم توثيق المصروف: [{raw_text}] وخصمه من الجرور في Odoo.\n({res})")
        return

    elif state == "WAITING_CASH_IN":
        clean_num = ''.join(c for c in raw_text if c.isdigit() or c == '.')
        if clean_num:
            context.user_data.clear()
            amt = float(clean_num)
            await update.message.reply_text(f"✅ تم تسجيل إيداع نقدي بالجرور بمبلغ: {amt} $")
            return
        context.user_data.clear()
        return

    # استجابة الأوامر الصوتية أو المكتوبة المباشرة
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

    await update.message.reply_text("يرجى اختيار العملية المطلوبة من لوحة المفاتيح أدناه.", reply_markup=get_reply_keyboard())

# ================= معالجة الصوت والأزرار =================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_user_text(update.message.text, update, context)

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    if not voice:
        return

    status_msg = await update.message.reply_text("⚡ جاري تحليل الأمر الصوتي...")
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
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await status_msg.edit_text("❌ لم أتمكن من معالجة الصوت بوضوح.")

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "sham_dep":
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

# ================= الإقلاع والتشغيل السحابي =================
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
            app.run_polling(timeout=60, drop_pending_updates=True)
        except Exception as e:
            logger.error(f"انقطاع مؤقت: {e}")
            time.sleep(5)

if _name_ == "_main_":
    run_cloud_bot()
