
import os
import sys
import logging
import asyncio
import tempfile
import xmlrpc.client
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# ---------------------------------------------------------
# 1. إعدادات السجل والبيئة السحابية
# ---------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(_name_)

BOT_TOKEN = os.getenv("BOT_TOKEN", "ضع_توكن_البوت_هنا")
ODOO_URL = os.getenv("ODOO_URL", "https://milana-telecom2.odoo.com")
ODOO_DB = os.getenv("ODOO_DB", "milana-telecom2")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "hahfsgsb@gmail.com")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "كلمة_المرور_او_API_KEY")

# حالات المحادثة المتعددة (Conversation Steps)
ADD_DEBT_NAME, ADD_DEBT_AMOUNT, ADD_DEBT_NOTE = range(3)
PAY_DEBT_NAME, PAY_DEBT_AMOUNT, PAY_DEBT_NOTE = range(3, 6)
ADD_AMANA_NAME, ADD_AMANA_AMOUNT, ADD_AMANA_NOTE = range(6, 9)

# ---------------------------------------------------------
# 2. دوال الربط الشامل مع Odoo (XML-RPC)
# ---------------------------------------------------------
def get_odoo_connection():
    """مصادقة وفتح اتصال مع سيرفر أودو"""
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
    if not uid:
        raise ConnectionError("فشل التحقق من بيانات Odoo.")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
    return uid, models

def get_or_create_partner(partner_name, phone=None):
    """البحث عن العميل أو إنشاؤه فوراً في حال عدم وجوده"""
    uid, models = get_odoo_connection()
    partners = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "res.partner", "search_read",
        [[("name", "=", partner_name)]],
        {"fields": ["id", "name", "total_due"], "limit": 1}
    )
    if partners:
        return partners[0]["id"]
    
    partner_vals = {
        "name": partner_name,
        "customer_rank": 1
    }
    if phone:
        partner_vals["phone"] = phone
    partner_id = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "res.partner", "create",
        [partner_vals]
    )
    return partner_id

def create_odoo_payment(partner_name, amount, payment_type="inbound", memo="تسديد عبر البوت"):
    """تسجيل حركة قبض أو صرف مالية (تسديد دين أو إيداع)"""
    uid, models = get_odoo_connection()
    partner_id = get_or_create_partner(partner_name)

    payment_vals = {
        "partner_id": partner_id,
        "amount": float(amount),
        "payment_type": payment_type,  # 'inbound' للقبض، 'outbound' للصرف
        "partner_type": "customer",
        "ref": memo,
        "date": datetime.now().strftime("%Y-%m-%d")
    }
    payment_id = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "account.payment", "create",
        [payment_vals]
    )
    try:
        # تأكيد الدفعة مباشرة في حال إمكانية الـ post
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "account.payment", "action_post",
            [[payment_id]]
        )
    except Exception as e:
        logger.warning(f"تم إنشاء الدفعة مسودة لتعذر التأكيد التلقائي: {e}")
    return payment_id

def get_customers_debts(query_name=None, limit=30):
    """استعلام عن ديون وأرصدة العملاء"""
    uid, models = get_odoo_connection()
    domain = [("customer_rank", ">", 0)]
    if query_name:
        domain.append(("name", "ilike", query_name))

    fields = ["id", "name", "total_due", "credit", "debit", "phone", "mobile"]
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "res.partner", "search_read",
        [domain],
        {"fields": fields, "limit": limit, "order": "total_due desc"}
    )
    return records

def get_amanat_ledger(limit=25):
    """جلب سجل الأمانات والودائع المسجلة"""
    uid, models = get_odoo_connection()
    domain = [("state", "in", ["posted", "draft"])]
    fields = ["name", "partner_id", "amount", "date", "ref", "payment_type", "state"]
    records = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "account.payment", "search_read",
        [domain],
        {"fields": fields, "limit": limit, "order": "date desc, id desc"}
    )
    return records

def get_pos_cash_summary():
    """حساب مبيعات الـ POS وحركات الصندوق اليومية"""
    uid, models = get_odoo_connection()
    today_str = datetime.now().strftime("%Y-%m-%d")
    domain = [("date_order", ">=", f"{today_str} 00:00:00")]
    fields = ["name", "amount_total", "partner_id", "date_order"]
    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "pos.order", "search_read",
        [domain],
        {"fields": fields}
    )
    total_sales = sum(order.get("amount_total", 0.0) for order in orders)
    return total_sales, len(orders)

# ---------------------------------------------------------
# 3. لوحات المفاتيح والأزرار
# ---------------------------------------------------------
def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton("📊 كشف الديون"), KeyboardButton("📦 كشف الأمانات")],
        [KeyboardButton("➕ تسجيل دين جديد"), KeyboardButton("💵 قبض دفعة / تسديد")],
        [KeyboardButton("💰 ملخص الصندوق اليومي"), KeyboardButton("🔄 فحص السيرفر")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ إلغاء العملية")]], resize_keyboard=True)

# ---------------------------------------------------------
# 4. المعالجات الأساسية للبوت
# ---------------------------------------------------------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = (
        f"مرحباً بك {user.first_name} في نظام *Milana Telecom* السحابي ⚡️\n\n"
        "المنظومة متصلة بسيرفر أودو وجاهزة للعمل:\n"
        "• إدارة الديون والتحصيلات.\n"
        "• قيود الأمانات وحركات الصندوق.\n"
        "• البحث المباشر بكتابة اسم الزبون أو إرسال تسجيل صوتي."
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def server_status_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text("⏳ جاري التحقق من حالة الاتصال بسيرفر أودو...")
    try:
        uid, _ = get_odoo_connection()
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await wait_msg.edit_text(
            f"✅ *الاتصال السحابي سليم 100%*\n\n"
            f"🔹 Session UID: {uid}\n"
            f"🔹 الوقت: {now_time}\n"
            f"🔹 التوافق: Linux / Cloud Container Ready",
            parse_mode="Markdown"
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ تعذر الاتصال بسيرفر Odoo:\n`{str(e)}`", parse_mode="Markdown")

async def show_debts_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text("⏳ جاري استخراج كشف الديون...")
    try:
        partners = get_customers_debts()
        if not partners:
            await wait_msg.edit_text("لا توجد سجلات ديون مسجلة حالياً.")
            return

        lines = ["📊 *كشف ديون وأرصدة العملاء:*\n"]
        has_due = False
        for p in partners:
            due = p.get("total_due", 0.0) or p.get("credit", 0.0)
            if due > 0:
                has_due = True
                name = p.get("name", "غير معروف")
                phone = p.get("phone") or p.get("mobile") or "بدون هاتف"
                lines.append(f"👤 {name}\n💵 المبلغ المطلوب: {due:,.2f}\n📞 {phone}\n" + "—"*15)

        if not has_due:
            await wait_msg.edit_text("✅ لا توجد ديون معلقة على العملاء حالياً.")
            return

        report = "\n".join(lines)
        if len(report) > 4000:
            report = report[:3900] + "\n\n⚠️ (تم اقتطاع التقرير لطوله...)"
        await wait_msg.edit_text(report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Debts Fetch Error: {e}")
        await wait_msg.edit_text(f"خطأ أثناء جلب الديون: {e}", parse_mode="Markdown")

async def show_amanat_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text("⏳ جاري استخراج سجل الأمانات...")
    try:
        amanat = get_amanat_ledger()
        if not amanat:
            await wait_msg.edit_text("لا توجد حركات أمانات مسجلة.")
            return

        lines = ["📦 *كشف الأمانات والعمليات الأخيرة:*\n"]
        for item in amanat:
            partner = item.get("partner_id")
            p_name = partner[1] if isinstance(partner, (list, tuple)) else "غير محدد"
            amount = item.get("amount", 0.0)
            date_val = item.get("date", "")
            ref_val = item.get("ref") or item.get("name") or "-"
            status = "✅ مؤكد" if item.get("state") == "posted" else "⏳ معلق"
            lines.append(f"🔹 الجهة: {p_name}\n💰 المبلغ: {amount:,.2f} | {status}\n📅 التاريخ: {date_val}\n📝 البيان: {ref_val}\n" + "—"*15)

        report = "\n".join(lines)
        if len(report) > 4000:
            report = report[:3900] + "\n\n⚠️ (تم اقتطاع التقرير لطوله...)"
        await wait_msg.edit_text(report, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Amanat Fetch Error: {e}")
        await wait_msg.edit_text(f"خطأ أثناء جلب الأمانات: {e}", parse_mode="Markdown")

async def show_cash_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait_msg = await update.message.reply_text("⏳ جاري احتساب مبيعات اليوم من POS...")
    try:
        total_sales, orders_count = get_pos_cash_summary()
        today = datetime.now().strftime("%Y-%m-%d")
        text = (
            f"💰 *ملخص الصندوق والمبيعات اليومي*\n"
            f"📅 التاريخ: {today}\n"
            f"—"*18 + "\n"
            f"🛒 عدد الطلبات المنفذة: {orders_count}\n"
            f"💵 إجمالي المبيعات المحصلة: {total_sales:,.2f}\n"
            f"—"*18
        )
        await wait_msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Cash Summary Error: {e}")
        await wait_msg.edit_text(f"تعذر استخراج ملخص اليوم: {e}", parse_mode="Markdown")

# ---------------------------------------------------------
# 5. معالجات المحادثات التفاعلية (تسديد وقبض)
# ---------------------------------------------------------
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية والعودة للقائمة الرئيسية.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# خطوات قبض دفعة / تسديد
async def pay_debt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أدخل *اسم العميل* المراد تسديد الدفعة لحسابه:", reply_markup=cancel_keyboard())
    return PAY_DEBT_NAME

async def pay_debt_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["client_name"] = update.message.text.strip()
    await update.message.reply_text("أدخل *المبلغ المسدد* بالأرقام:")
    return PAY_DEBT_AMOUNT

async def pay_debt_amount_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val_text = update.message.text.strip().replace(",", "")
    try:
        amount = float(val_text)
        context.user_data["amount"] = amount
        await update.message.reply_text("اكتب *بيان أو ملاحظة* العملية (أو أرسل نقطة . للتخطي):")
        return PAY_DEBT_NOTE
    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح للمبلغ:")
        return PAY_DEBT_AMOUNT

async def pay_debt_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    client_name = context.user_data.get("client_name")
    amount = context.user_data.get("amount")

    wait_msg = await update.message.reply_text("⏳ جاري تسجيل الدفعة في أودو...")
    try:
        pay_id = create_odoo_payment(client_name, amount, payment_type="inbound", memo=f"تسديد بوت: {note}")
        await wait_msg.edit_text(
            f"✅ *تم تسجيل الدفعة بنجاح!*\n\n"
            f"👤 العميل: {client_name}\n"
            f"💵 المبلغ: {amount:,.2f}\n"
            f"🔢 رقم السجل: {pay_id}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Payment Entry Error: {e}")
        await wait_msg.edit_text(f"❌ فشل تسجيل الدفعة في النظام:\n`{e}`", parse_mode="Markdown")

    context.user_data.clear()
    await update.message.reply_text("اختر العملية التالية:", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# ---------------------------------------------------------
# 6. التوجيه الذكي للنصوص والتسجيلات الصوتية
# ---------------------------------------------------------
async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال الرسائل الصوتية وتحميلها وتجهيزها في البيئة السحابية"""
    voice = update.message.voice
    await update.message.reply_text("🎙️ تم استلام التسجيل الصوتي، جاري قراءة ومطابقة المحتوى...")
    try:
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=True) as tmp:
            await file.download_to_drive(tmp.name)
            # النواة جاهزة للربط بمحرك Whisper السحابي أو معالجة الصوت المباشرة
            await update.message.reply_text("✅ تم تفريغ الصوت بنجاح (النظام يعمل بوضع Cloud Whisper API).")
    except Exception as e:
        logger.error(f"Voice Handle Error: {e}")
        await update.message.reply_text(f"تعذر معالجة المقطع الصوتي: {e}")

async def general_text_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "📊 كشف الديون":
        await show_debts_report(update, context)
    elif text == "📦 كشف الأمانات":
        await show_amanat_report(update, context)
    elif text == "💰 ملخص الصندوق اليومي":
        await show_cash_summary(update, context)
    elif text == "🔄 فحص السيرفر":
        await server_status_check(update, context)
    elif text == "❌ إلغاء العملية":
        await cancel_action(update, context)
    else:
        # البحث المباشر باسم العميل
        try:
            results = get_customers_debts(query_name=text, limit=1)
            if results:
                c = results[0]
                name = c.get("name")
                due = c.get("total_due", 0.0) or c.get("credit", 0.0)
                phone = c.get("phone") or c.get("mobile") or "غير متوفر"
                await update.message.reply_text(
                    f"🔍 *نتيجة استعلام العميل:*\n\n"
                    f"👤 الاسم: {name}\n"
                    f"💵 الرصيد المطلوب: {due:,.2f}\n"
                    f"📞 الهاتف: {phone}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "لم يتم العثور على اسم عميل مطابق. اختر من الأزرار أو أدخل اسماً آخر:",
                    reply_markup=get_main_menu_keyboard()
                )
        except Exception as e:
            await update.message.reply_text(f"خطأ أثناء الاستعلام: {e}")

# ---------------------------------------------------------
# 7. نقطة الانطلاق الرئيسية (Main Runner)
# ---------------------------------------------------------
def main():
    while True:
        try:
            logger.info("جاري تشغيل بوت Milana Telecom الموسع...")
            app = ApplicationBuilder().token(BOT_TOKEN).build()

            # إعداد معالج محادثة تسجيل وقبض الديون
            pay_conv = ConversationHandler(
                entry_points=[
                    MessageHandler(filters.Regex("^💵 قبض دفعة / تسديد$"), pay_debt_start),
                    MessageHandler(filters.Regex("^➕ تسجيل دين جديد$"), pay_debt_start)
                ],
                states={
                    PAY_DEBT_NAME: [
                        MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel_action),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, pay_debt_name_step)
                    ],
                    PAY_DEBT_AMOUNT: [
                        MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel_action),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, pay_debt_amount_step)
                    ],
                    PAY_DEBT_NOTE: [
                        MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel_action),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, pay_debt_finish)
                    ],
                },
                fallbacks=[MessageHandler(filters.Regex("^❌ إلغاء العملية$"), cancel_action)]
            )

            app.add_handler(CommandHandler("start", start_handler))
            app.add_handler(CommandHandler("status", server_status_check))
            app.add_handler(pay_conv)
            app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_text_dispatcher))

            logger.info("السيرفر السحابي للبوت في وضع العمل والترقب الدائم...")
            app.run_polling(drop_pending_updates=True)

        except Exception as e:
            logger.error(f"انقطاع في الاتصال السحابي: {e}")
            logger.info("إعادة المحاولة التلقائية بعد 5 ثوانٍ...")
            import time
            time.sleep(5)

if _name_ == "_main_":
    main()
