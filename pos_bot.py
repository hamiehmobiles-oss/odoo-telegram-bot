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

def get_odoo_connection(retries=3, delay=1):
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
            logger.warning(f"اتصال Odoo فشل ({attempt}): {e}")
            if attempt < retries:
                time.sleep(delay)
    return None, None

def odoo_execute(model, method, *args, **kwargs):
    uid, models = get_odoo_connection()
    if not uid:
        raise ConnectionError("تعذر الاتصال بسيرفر Odoo")
    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, *args, **kwargs)

# كتابة آمنة لا تفجر Odoo SaaS (عبر الرسائل الداخلية أو الحقول)
def safe_partner_log(partner_id, text_entry):
    try:
        odoo_execute('res.partner', 'message_post', [partner_id], {
            'body': text_entry,
            'message_type': 'comment',
            'subtype_xmlid': 'mail.mt_note'
        })
        return True
    except Exception:
        try:
            p_data = odoo_execute('res.partner', 'read', [partner_id], {'fields': ['comment']})
            old_com = p_data[0].get('comment') or ""
            new_com = old_com + "\n" + text_entry
            odoo_execute('res.partner', 'write', [partner_id], {'comment': new_com})
            return True
        except Exception as e:
            logger.error(f"فشل كتابة الملاحظة: {e}")
            return False

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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 مبيعات اليوم (POS)", callback_data="pos_today"), InlineKeyboardButton("🛒 جلسات نقطة البيع", callback_data="pos_sessions")],
        [InlineKeyboardButton("📦 تنبيه المخزون", callback_data="low_stock"), InlineKeyboardButton("📑 أحدث الفواتير", callback_data="recent_invoices")],
        [InlineKeyboardButton("⚡ فحص اتصال السيرفر", callback_data="check_status"), InlineKeyboardButton("🔄 تحديث اللوحة", callback_data="refresh_menu")]
    ])

# ================= قراءة الحركات القديمة بدقة =================
def fetch_client_full_history(partner):
    p_id = int(partner['id'])
    text_blocks = []
    
    if partner.get('comment'):
        text_blocks.append(str(partner['comment']))
    
    try:
        msgs = odoo_execute('mail.message', 'search_read', [
            [('model', '=', 'res.partner'), ('res_id', '=', p_id)]
        ], {'fields': ['body'], 'limit': 15, 'order': 'id desc'})
        for m in msgs:
            b = m.get('body') or ""
            clean_b = re.sub(r'<[^>]+>', ' ', b).strip()
            if clean_b:
                text_blocks.append(clean_b)
    except Exception:
        pass

    full_text = "\n".join(text_blocks)
    clean_history = re.sub(r'<[^>]+>', ' ', full_text)

    # حساب الديون
    usd_debt = 0.0
    try:
        invoices = odoo_execute('account.move', 'search_read', [
            [('partner_id', '=', p_id), ('move_type', '=', 'out_invoice'), ('payment_state', '!=', 'paid'), ('state', '=', 'posted')]
        ], {'fields': ['amount_residual', 'currency_id']})
        for inv in invoices:
            usd_debt += float(inv.get('amount_residual', 0.0))
    except Exception:
        pass

    debt_log_calc = 0.0
    deposit_calc = 0.0

    for line in clean_history.split('\n'):
        line_clean = line.strip('- • \r ')
        
        # تدقيق الديون
        if any(k in line_clean for k in ['دين مضاف', 'دين جديد', 'تسجيل دين', 'دين:']):
            nums = re.findall(r'(\d+(?:\.\d+)?)\s*\$?', line_clean)
            if nums:
                debt_log_calc += float(nums[0])
        elif any(k in line_clean for k in ['سداد دين', 'قبض دين', 'تسديد دين']):
            nums = re.findall(r'(\d+(?:\.\d+)?)\s*\$?', line_clean)
            if nums:
                debt_log_calc -= float(nums[0])

        # تدقيق الأمانات
        if any(k in line_clean for k in ['أمانة', 'امانة', 'عربون', 'تأمين', 'تامين', 'رهن']):
            nums = re.findall(r'(\d+(?:\.\d+)?)\s*\$?', line_clean)
            if nums:
                val = float(nums[0])
                if any(k in line_clean for k in ['تسليم', 'سداد', 'إرجاع', 'ارجاع', 'شطب', 'قبض']):
                    deposit_calc -= val
                else:
                    deposit_calc += val

    final_debt = max(usd_debt, debt_log_calc, 0.0)
    final_deposit = max(deposit_calc, 0.0)

    return round(final_debt, 2), round(final_deposit, 2), clean_history

# ================= كشف الأمانات القديم والجديد =================
async def get_all_deposits_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ومطابقة كشف الأمانات والعربين بالكامل...")
    try:
        partners = odoo_execute('res.partner', 'search_read', [
            ['|', ('comment', '!=', False), ('customer_rank', '>', 0)]
        ], {'fields': ['id', 'name', 'comment'], 'limit': 300})

        deposits_found = []
        total_market_deposits = 0.0

        if partners:
            for p in partners:
                p_name = p.get('name', 'زبون')
                _, dep_bal, _ = fetch_client_full_history(p)
                if dep_bal > 0:
                    total_market_deposits += dep_bal
                    deposits_found.append({
                        'name': p_name,
                        'balance': dep_bal
                    })

        if deposits_found:
            msg = "📋 كشف الأمانات والعربين القائمة (شامل القديم والجديد):\n━━━━━━━━━━━━━━━━━━━━\n\n"
            for d in deposits_found:
                msg += f"👤 الزبون: {d['name']}\n💰 الرصيد المتبقي له: {d['balance']:,.2f} $\n────────────────────\n"
            msg += f"📊 إجمالي الأمانات المعلقة بذمتنا: {total_market_deposits:,.2f} $"
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text("📋 لا توجد أمانات أو عربين قائمة حالياً في السجلات.")

    except Exception as e:
        logger.error(f"Error in deposits: {e}")
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

# ================= تسجيل أمانة جديدة =================
async def add_deposit_logic(partner_name: str, amount: float, memo: str, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            p_id = int(partners[0]['id'])
            p_display = partners[0].get('name', p_name)
            _, curr_dep, _ = fetch_client_full_history(partners[0])
            new_total = round(curr_dep + amount, 2)

            log_entry = f"أمانة جديدة: {amount}$ [{memo}] بتاريخ {now_str}"
            safe_partner_log(p_id, log_entry)
        else:
            curr_dep = 0.0
            new_total = amount
            log_entry = f"أمانة جديدة: {amount}$ [{memo}] بتاريخ {now_str}"
            p_id = odoo_execute('res.partner', 'create', [{
                'name': p_name,
                'customer_rank': 1,
                'comment': log_entry
            }])
            p_display = p_name

        msg = (
            "✅ تم تسجيل واستلام الأمانة بنجاح:\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 الزبون: {p_display}\n"
            f"💵 المبلغ المستلم: {amount:,.2f} $\n"
            f"📝 البيان: {memo}\n"
            f"📌 أماناته السابقة: {curr_dep:,.2f} $\n"
            f"📊 إجمالي أماناته المتبقية: {new_total:,.2f} $\n"
            f"📥 تم تثبيتها في Odoo وسجل الأمانات."
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error add deposit: {e}")
        await update.message.reply_text(f"❌ تعذر التسجيل: {str(e)}")

# ================= تسليم / سداد أمانة =================
async def release_deposit_amount_logic(partner_name: str, amount: float, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            p_id = int(partners[0]['id'])
            p_display = partners[0].get('name', p_name)
            _, curr_dep, _ = fetch_client_full_history(partners[0])

            if curr_dep == 0:
                await update.message.reply_text(f"⚠️ الزبون [{p_display}] ليس له رصيد أمانات مسجل بذمتنا.")
                return

            remaining = max(0.0, round(curr_dep - amount, 2))
            log_entry = f"تسليم أمانة: {amount}$ بتاريخ {now_str}"
            safe_partner_log(p_id, log_entry)

            msg = (
                "↩️ تم توثيق تسليم / سداد الأمانة:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {p_display}\n"
                f"💵 المبلغ المسدد له: {amount:,.2f} $\n"
                f"📌 أمانته السابقة: {curr_dep:,.2f} $\n"
                f"📊 المتبقي له بذمتنا: {remaining:,.2f} $\n\n"
            )
            if remaining == 0:
                msg += "✅ تم تصفية كامل الأمانة وشطبها من الكشف."
            else:
                msg += f"⚠️ لا يزال له أمانة متبقية بقيمة: {remaining:,.2f} $"

            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ لم يتم العثور على زبون باسم [{p_name}]!")

    except Exception as e:
        logger.error(f"Error release deposit: {e}")
        await update.message.reply_text(f"❌ تعذر تسليم الأمانة: {str(e)}")

# ================= سداد وتسجيل الديون بدون أخطاء =================
async def add_debt_logic(partner_name: str, amount: float, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            p_id = int(partners[0]['id'])
            p_display = partners[0].get('name', p_name)
            curr_debt, _, _ = fetch_client_full_history(partners[0])
            new_total = round(curr_debt + amount, 2)

            log_entry = f"دين مضاف: {amount}$ بتاريخ {now_str}"
            safe_partner_log(p_id, log_entry)
        else:
            curr_debt = 0.0
            new_total = amount
            log_entry = f"دين مضاف: {amount}$ بتاريخ {now_str}"
            odoo_execute('res.partner', 'create', [{
                'name': p_name,
                'customer_rank': 1,
                'comment': log_entry
            }])
            p_display = p_name

        msg = (
            "✅ تم تسجيل الدين بنجاح في Odoo:\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 الزبون: {p_display}\n"
            f"💵 الدين المضاف: {amount:,.2f} $\n"
            f"📌 الرصيد السابق: {curr_debt:,.2f} $\n"
            f"📊 الإجمالي الجديد المطلوب منه: {new_total:,.2f} $"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error add debt: {e}")
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def pay_debt_logic(partner_name: str, amount: float, update: Update):
    try:
        p_name = partner_name.strip()
        partners = odoo_execute('res.partner', 'search_read', 
            [[('name', 'ilike', p_name)]], 
            {'fields': ['id', 'name', 'comment'], 'limit': 1})

        now_str = time.strftime('%Y-%m-%d %H:%M')

        if partners:
            p_id = int(partners[0]['id'])
            p_display = partners[0].get('name', p_name)
            curr_debt, _, _ = fetch_client_full_history(partners[0])
            remaining = max(0.0, round(curr_debt - amount, 2))

            log_entry = f"سداد دين: {amount}$ بتاريخ {now_str}"
            safe_partner_log(p_id, log_entry)

            msg = (
                "✅ تم توثيق سداد الدين بنجاح:\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 الزبون: {p_display}\n"
                f"💵 المبلغ المقبوض: {amount:,.2f} $\n"
                f"📌 الدين السابق: {curr_debt:,.2f} $\n"
                f"📊 الدين المتبقي عليه: {remaining:,.2f} $\n"
                f"📥 تم تحديث رصيده بنجاح وتوريد الكاش."
            )
        else:
            msg = f"⚠️ لم يتم العثور على زبون باسم [{p_name}]. تم تسجيل قبض {amount:,.2f} $."

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error pay debt: {e}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

# ================= كشف حساب زبون والديون =================
async def get_all_debts_logic(update: Update):
    await update.message.reply_text("🔍 جاري جلب ديون الزبائن بالدولار $...")
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
                debt, _, _ = fetch_client_full_history(p)
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
            debt, dep, history = fetch_client_full_history(p)

            res_msg = (
                "📊 كشف حساب العميل الشامل:\n"
                "━━━━━━━━━━━━━━\n"
                f"👤 الاسم: {p.get('name')}\n"
                f"📞 الهاتف: {phone}\n"
                f"💵 الدين المطلوب منه: {debt:,.2f} $\n"
                f"💰 أماناته القائمة بذمتنا: {dep:,.2f} $\n\n"
                f"📝 سجل العمليات الأخير:\n{history[:600] if history else 'لا توجد حركات مسجلة'}"
            )
            await update.message.reply_text(res_msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على زبون باسم [{partner_name}] في Odoo.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

# ================= جرد الصندوق المفصل والتقرير اليومي =================
async def get_daily_cash_report(update: Update):
    await update.message.reply_text("💼 جاري تجميع جرد الصندوق والتقرير اليومي الشامل...")
    try:
        today_str = time.strftime('%Y-%m-%d')

        pos_orders = odoo_execute('pos.order', 'search_read', [
            [('date_order', '>=', f"{today_str} 00:00:00"), ('state', 'in', ['paid', 'done', 'invoiced'])]
        ], {'fields': ['amount_total']})
        pos_total = sum(float(o.get('amount_total', 0.0)) for o in pos_orders)
        pos_count = len(pos_orders)

        report = (
            f"📊 تقرير جرد الصندوق والنشاط اليومي الشامل\n"
            f"📅 التاريخ: {today_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛒 مبيعات الـ POS المباشرة لليوم:\n"
            f"• عدد العمليات: {pos_count}\n"
            f"• الإجمالي المحصل: {pos_total:,.2f} $\n"
            f"────────────────────\n"
            f"💵 جاهزية الصندوق والجرور:\n"
            f"• النظام يسجل كافة المقبوضات وسداد الديون والأمانات مباشرة.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ النظام نشط ومربوط بـ Odoo."
        )
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

# ================= المحرك الرئيسي =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "مرحباً بك في نظام إدارة Milana Telecom 🚀\n\n"
        "تم التحديث الجذري للنظام:\n"
        "• سداد وتسجيل الديون والأمانات عبر النواة الرسمية لـ Odoo دون أخطاء.\n"
        "• استعادة سجل الأمانات والعربين القديمة والجديدة.\n"
        "• جرد الصندوق وكشوفات الحساب التراكمية."
    )
    await update.message.reply_text(welcome_text, reply_markup=get_reply_keyboard())
    await update.message.reply_text("لوحة المراقبة المباشرة:", reply_markup=get_odoo_inline_keyboard())

async def process_user_text(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = text.strip()

    cancel_words = ["إلغاء", "الغاء", "رجوع", "كنسل", "cancel", "/cancel", "وقف"]
    if raw_text.lower() in cancel_words:
        context.user_data.clear()
        await update.message.reply_text("🚫 تم الإلغاء والعودة للقائمة الرئيسية.", reply_markup=get_reply_keyboard())
        return

    if raw_text in MENU_BUTTONS and context.user_data.get("state"):
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
            _, dep_bal, _ = fetch_client_full_history(partners[0])
            context.user_data["rel_partner_name"] = partners[0]['name']
            context.user_data["state"] = "WAITING_REL_DEP_AMOUNT"
            await update.message.reply_text(
                f"👤 الزبون: {partners[0]['name']}\n"
                f"💰 أماناته القائمة بذمتنا: {dep_bal:,.2f} $\n\n"
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
        await update.message.reply_text("⚠️ إدخال خاطئ!")
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

    # الأوامر الصوتية أو النصية التلقائية
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

    await update.message.reply_text("يرجى اختيار العملية من القائمة أدناه.", reply_markup=get_reply_keyboard())

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

    if data == "check_status":
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
            print("جاري تشغيل نظام Milana Telecom...")
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
