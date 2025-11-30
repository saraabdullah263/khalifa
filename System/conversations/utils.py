# conversations/utils.py
"""
Utility Functions
دوال مساعدة للنظام

المحتويات:
1. Phone Number Normalization
2. Ticket Number Generation
3. Activity Logging
4. KPI Calculation
5. Delay Detection
"""

from django.utils import timezone
from django.conf import settings
import re
from datetime import datetime, timedelta


# ============================================================================
# 1. PHONE NUMBER NORMALIZATION
# ============================================================================

def normalize_phone_number(phone):
    """
    تطبيع رقم الهاتف إلى الصيغة الموحدة: 20XXXXXXXXXX

    Examples:
        '1234567890'      → '201234567890'
        '01234567890'     → '201234567890'
        '201234567890'    → '201234567890'
        '+201234567890'   → '201234567890'
        '0 123 456 7890'  → '201234567890'
        '201234567890@c.us' → '201234567890'
        '25516987932689@lid' → '25516987932689'
    """
    if not phone:
        return None

    # إزالة @c.us أو @lid أو أي لاحقة WhatsApp
    if '@' in phone:
        phone = phone.split('@')[0]

    cleaned = re.sub(r'[^\d]', '', phone)

    if cleaned.startswith('00'):
        cleaned = cleaned[2:]

    if cleaned.startswith('0') and len(cleaned) == 11:
        cleaned = '20' + cleaned[1:]
    elif len(cleaned) == 10:
        cleaned = '20' + cleaned
    elif cleaned.startswith('20') and len(cleaned) == 12:
        pass
    else:
        # أرقام طويلة (LID) أو غير معروفة → غير صالحة لعرض phone_number
        raise ValueError(f"رقم الهاتف غير صالح للعرض: {phone}")

    # تحقق نهائي
    if not cleaned.startswith('20') or len(cleaned) != 12:
        raise ValueError(f"رقم الهاتف غير صالح: {phone}")

    return cleaned


# ============================================================================
# 2. TICKET NUMBER GENERATION
# ============================================================================

def generate_ticket_number():
    """
    توليد رقم تذكرة فريد
    Format: TKT-YYYYMMDD-XXXX
    
    Example: TKT-20251030-0001
    """
    from .models import Ticket
    
    # الحصول على التاريخ الحالي
    today = timezone.now().date()
    date_str = today.strftime('%Y%m%d')
    
    # البحث عن آخر تذكرة في نفس اليوم
    prefix = f'TKT-{date_str}-'
    last_ticket = Ticket.objects.filter(
        ticket_number__startswith=prefix
    ).order_by('-ticket_number').first()
    
    if last_ticket:
        # استخراج الرقم التسلسلي
        last_number = int(last_ticket.ticket_number.split('-')[-1])
        new_number = last_number + 1
    else:
        new_number = 1
    
    # تنسيق الرقم (4 أرقام)
    ticket_number = f'{prefix}{new_number:04d}'
    
    return ticket_number


# ============================================================================
# 3. ACTIVITY LOGGING
# ============================================================================

def log_activity(user, action, entity_type, entity_id, old_value=None, new_value=None, request=None):
    """
    تسجيل نشاط المستخدم
    
    Args:
        user: User object
        action: نوع العملية (create, update, delete, login, logout, etc.)
        entity_type: نوع الكيان (ticket, message, customer, etc.)
        entity_id: معرف الكيان
        old_value: القيمة القديمة (للتحديثات)
        new_value: القيمة الجديدة (للتحديثات)
        request: Django request object (للحصول على IP و User Agent)
    """
    from .models import ActivityLog
    
    ip_address = None
    user_agent = None
    
    if request:
        # الحصول على IP Address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        
        # الحصول على User Agent
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
    
    ActivityLog.objects.create(
        user=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        user_agent=user_agent
    )


# ============================================================================
# 4. KPI CALCULATION
# ============================================================================

def calculate_agent_kpi(agent, date=None):
    """
    حساب مؤشرات الأداء للموظف

    Args:
        agent: Agent object
        date: التاريخ (افتراضياً اليوم)

    Returns:
        dict: KPI metrics
    """
    from .models import Ticket, Message, CustomerSatisfaction, AgentKPI, AgentBreakSession
    from django.db.models import Avg, Count, Q, Sum

    if date is None:
        date = timezone.now().date()

    # الحصول على التذاكر في هذا اليوم
    tickets = Ticket.objects.filter(
        assigned_agent=agent,
        created_at__date=date
    )

    total_tickets = tickets.count()
    closed_tickets = tickets.filter(status='closed').count()

    # حساب متوسط وقت الاستجابة
    avg_response_time = tickets.filter(
        response_time_seconds__isnull=False
    ).aggregate(Avg('response_time_seconds'))['response_time_seconds__avg'] or 0

    # عدد الرسائل
    messages_sent = Message.objects.filter(
        ticket__assigned_agent=agent,
        sender_type='agent',
        sender_id=agent.user.id,
        created_at__date=date
    ).count()

    messages_received = Message.objects.filter(
        ticket__assigned_agent=agent,
        sender_type='customer',
        created_at__date=date
    ).count()

    # عدد التأخيرات
    delay_count = tickets.filter(delay_count__gt=0).count()

    # متوسط رضا العملاء
    satisfaction = CustomerSatisfaction.objects.filter(
        agent=agent,
        created_at__date=date
    ).aggregate(Avg('rating'))['rating__avg'] or 0

    # ✅ حساب إجمالي وقت الاستراحة في هذا اليوم
    break_sessions = AgentBreakSession.objects.filter(
        agent=agent,
        break_start_time__date=date,
        break_duration_seconds__isnull=False
    )

    total_break_time_seconds = break_sessions.aggregate(
        total=Sum('break_duration_seconds')
    )['total'] or 0

    break_count = break_sessions.count()

    # حساب معدلات الأداء
    first_response_rate = 0
    if total_tickets > 0:
        tickets_with_response = tickets.filter(first_response_at__isnull=False).count()
        first_response_rate = (tickets_with_response / total_tickets) * 100

    resolution_rate = 0
    if total_tickets > 0:
        resolution_rate = (closed_tickets / total_tickets) * 100

    # حساب KPI Score الإجمالي (حسب الإجابة س1)
    overall_kpi_score = (first_response_rate + resolution_rate + (satisfaction * 20)) / 3

    # حفظ أو تحديث KPI
    kpi, created = AgentKPI.objects.update_or_create(
        agent=agent,
        kpi_date=date,
        defaults={
            'total_tickets': total_tickets,
            'closed_tickets': closed_tickets,
            'avg_response_time_seconds': int(avg_response_time),
            'messages_sent': messages_sent,
            'messages_received': messages_received,
            'delay_count': delay_count,
            'total_break_time_seconds': total_break_time_seconds,  # ✅ إضافة وقت الاستراحة
            'break_count': break_count,  # ✅ إضافة عدد مرات الاستراحة
            'customer_satisfaction_score': satisfaction,
            'first_response_rate': first_response_rate,
            'resolution_rate': resolution_rate,
            'overall_kpi_score': overall_kpi_score,
        }
    )
    
    return {
        'total_tickets': total_tickets,
        'closed_tickets': closed_tickets,
        'avg_response_time_seconds': int(avg_response_time),
        'messages_sent': messages_sent,
        'messages_received': messages_received,
        'delay_count': delay_count,
        'total_break_time_seconds': total_break_time_seconds,  # ✅ إضافة وقت الاستراحة
        'break_count': break_count,  # ✅ إضافة عدد مرات الاستراحة
        'customer_satisfaction_score': satisfaction,
        'first_response_rate': first_response_rate,
        'resolution_rate': resolution_rate,
        'overall_kpi_score': overall_kpi_score,
    }


# ============================================================================
# 5. DELAY DETECTION
# ============================================================================

def check_ticket_delay(ticket):
    """
    فحص ما إذا كانت التذكرة متأخرة (حسب الإجابة س11: 3 دقائق)

    التأخير يحدث عندما يرسل العميل رسالة ولا يرد الموظف خلال 3 دقائق

    Args:
        ticket: Ticket object

    Returns:
        bool: True إذا كانت متأخرة
    """
    if ticket.status != 'open':
        return False

    if not ticket.last_customer_message_at:
        return False

    if ticket.last_agent_message_at and ticket.last_agent_message_at > ticket.last_customer_message_at:
        return False

    # ✅ استخدام delay_threshold من SystemSettings
    from .models import SystemSettings
    system_settings = SystemSettings.get_settings()
    delay_threshold = system_settings.delay_threshold_minutes
    
    time_since_customer_message = timezone.now() - ticket.last_customer_message_at

    if time_since_customer_message.total_seconds() > (delay_threshold * 60):
        return True

    return False


def update_ticket_delay_status(ticket):
    """
    تحديث حالة التأخير للتذكرة
    
    Args:
        ticket: Ticket object
    """
    from .models import TicketStateLog
    
    is_delayed = check_ticket_delay(ticket)
    
    if is_delayed and not ticket.is_delayed:
        # التذكرة أصبحت متأخرة
        ticket.is_delayed = True
        ticket.delay_started_at = timezone.now()
        ticket.delay_count += 1
        ticket.save(update_fields=['is_delayed', 'delay_started_at', 'delay_count'])
        
        # تسجيل تغيير الحالة
        TicketStateLog.objects.create(
            ticket=ticket,
            changed_by=None,  # تلقائي
            old_state=ticket.status,
            new_state='delayed',
            reason='تأخر الرد لأكثر من 3 دقائق'
        )
    
    elif not is_delayed and ticket.is_delayed:
        # التذكرة لم تعد متأخرة (الموظف رد)
        if ticket.delay_started_at:
            # حساب مدة التأخير
            delay_duration = timezone.now() - ticket.delay_started_at
            ticket.total_delay_minutes += int(delay_duration.total_seconds() / 60)
        
        ticket.is_delayed = False
        ticket.delay_started_at = None
        ticket.save()
        
        # تسجيل تغيير الحالة
        TicketStateLog.objects.create(
            ticket=ticket,
            changed_by=None,  # تلقائي
            old_state='delayed',
            new_state=ticket.status,
            reason='الموظف رد على الرسالة'
        )


# ============================================================================
# 6. AUTO-ASSIGNMENT ALGORITHM
# ============================================================================

def get_available_agent():
    """
    الحصول على موظف متاح باستخدام خوارزمية Least Loaded (حسب الإجابة س6)

    ✅ التحديث: استبعاد الموظفين في استراحة (is_on_break=True)

    Returns:
        Agent object أو None
    """
    from .models import Agent
    from django.db.models import F

    # البحث عن موظف متاح (ليس في استراحة)
    available_agents = Agent.objects.filter(
        is_online=True,
        status='available',
        is_on_break=False,  # ✅ استبعاد الموظفين في استراحة
        current_active_tickets__lt=F('max_capacity')
    ).order_by('current_active_tickets')

    if available_agents.exists():
        return available_agents.first()

    return None


def assign_ticket_to_agent(ticket, agent):
    """
    تعيين تذكرة لموظف
    
    Args:
        ticket: Ticket object
        agent: Agent object
    """
    ticket.assigned_agent = agent
    ticket.current_agent = agent
    ticket.save()
    
    # تحديث عدد التذاكر النشطة للموظف
    agent.current_active_tickets += 1
    
    # تحديث حالة الموظف (حسب الإجابة س7: تلقائي)
    if agent.current_active_tickets >= agent.max_capacity:
        agent.status = 'busy'
    
    agent.save()


# ============================================================================
# 6. WELCOME MESSAGE & DROPDOWN MENU
# ============================================================================

def send_welcome_message(customer, ticket=None):
    """
    إرسال رسالة ترحيب مع قائمة منسدلة للعميل الجديد
    
    Args:
        customer: كائن العميل
        ticket: التذكرة المرتبطة (اختياري)
    
    Returns:
        bool: True إذا تم الإرسال بنجاح، False خلاف ذلك
    """
    try:
        from .whatsapp_driver import get_whatsapp_driver
        from .message_queue import get_message_queue
        from .models import Message, Ticket
        from django.utils import timezone
        import logging
        
        logger = logging.getLogger(__name__)
        
        # رسالة الترحيب
        from .models import SystemSettings
        system_settings = SystemSettings.get_settings()
        welcome_text = system_settings.welcome_message
        
        # العثور على التذكرة إذا لم يتم تمريرها
        if not ticket:
            ticket = Ticket.objects.filter(
                customer=customer,
                status__in=['open', 'pending']
            ).first()
            
        if not ticket:
            logger.warning(f"No active ticket found for customer {customer.phone_number} to save welcome message")
            return False
        
        # ✅ التحقق من عدم إرسال رسالة ترحيب مكررة
        existing_welcome = Message.objects.filter(
            ticket=ticket,
            sender_type='agent',
            message_text__contains='مرحباً بك في صيدليات خليفة'
        ).first()
        
        if existing_welcome:
            logger.info(f"Welcome message already sent for ticket {ticket.ticket_number} - skipping")
            return True  # نرجع True لأن الرسالة موجودة بالفعل
        
        # الحصول على driver
        driver = get_whatsapp_driver()
        
        # إرسال الرسالة عبر النظام
        result = driver.send_text_message(
            phone=customer.wa_id,
            message=welcome_text
        )
        
        # حفظ الرسالة في قاعدة البيانات إذا تم الإرسال بنجاح
        if result.get('success', False):
            welcome_message = Message.objects.create(
                ticket=ticket,
                sender=ticket.assigned_agent.user if ticket.assigned_agent else None,
                sender_type='agent',
                direction='outgoing',
                message_text=welcome_text,
                message_type='text',
                delivery_status='sent',
                created_at=timezone.now()
            )
            
            # تحديث آخر رسالة في التذكرة (بدون تحديث last_agent_message_at لأنها رسالة ترحيب تلقائية)
            ticket.last_message_at = timezone.now()
            ticket.save(update_fields=['last_message_at'])
            
            logger.info(f"Welcome message sent and saved to database - Customer: {customer.phone_number}, Message ID: {welcome_message.id}")
            return True
        else:
            logger.warning(f"Welcome message sending failed for {customer.phone_number}: {result}")
            return False
        
    except Exception as e:
        logger.error(f"Error sending welcome message: {str(e)}", exc_info=True)
        return False


def handle_menu_selection(customer, message_text, ticket):
    """
    معالجة اختيار العميل من القائمة المنسدلة
    
    Args:
        customer: كائن العميل
        message_text: نص الرسالة
        ticket: التذكرة الحالية
    
    Returns:
        dict: نتيجة المعالجة مع رسالة الرد
    """
    try:
        from .whatsapp_driver import get_whatsapp_driver
        import logging
        
        logger = logging.getLogger(__name__)
        driver = get_whatsapp_driver()
        
        # تنظيف النص واستخراج الرقم
        selection = message_text.strip()
        
        # معالجة الاختيارات
        if selection in ['1', '١', 'شكوى', 'شكوي', 'استفسار']:
            # شكوى أو استفسار
            ticket.category = 'complaint'
            ticket.priority = 'high'
            ticket.category_selected_at = timezone.now()  # ✅ تسجيل وقت اختيار الفئة
            ticket.save(update_fields=['category', 'priority', 'category_selected_at'])
            logger.info(f"✅ Ticket {ticket.ticket_number} category updated to 'complaint' for customer {customer.phone_number}")

            response_text = """✅ تم تسجيل طلبك كشكوى/استفسار

🔍 سيتم تحويلك لموظف متخصص للتعامل مع شكواك
⏰ وقت الاستجابة المتوقع: خلال 3 دقائق

يرجى وصف مشكلتك بالتفصيل ليتمكن فريقنا من مساعدتك بأفضل شكل ممكن 📝"""

        elif selection in ['2', '٢', 'ادوية', 'أدوية', 'دواء']:
            # طلب أدوية
            ticket.category = 'medicine_order'
            ticket.priority = 'medium'
            ticket.category_selected_at = timezone.now()  # ✅ تسجيل وقت اختيار الفئة
            ticket.save(update_fields=['category', 'priority', 'category_selected_at'])
            logger.info(f"✅ Ticket {ticket.ticket_number} category updated to 'medicine_order' for customer {customer.phone_number}")

            response_text = """💊 تم تسجيل طلبك لطلب أدوية

📋 يرجى إرسال:
• صورة من الروشتة الطبية
• أو كتابة أسماء الأدوية المطلوبة
• عنوان التوصيل إذا كنت تريد الطلب للمنزل

🚚 خدمة التوصيل متوفرة خلال ساعة واحدة داخل النطاق المحدد"""

        elif selection in ['3', '٣', 'متابعة', 'متابعه', 'طلب سابق']:
            # متابعة طلب سابق
            ticket.category = 'follow_up'
            ticket.priority = 'low'
            ticket.category_selected_at = timezone.now()  # ✅ تسجيل وقت اختيار الفئة
            ticket.save(update_fields=['category', 'priority', 'category_selected_at'])
            logger.info(f"✅ Ticket {ticket.ticket_number} category updated to 'follow_up' for customer {customer.phone_number}")
            
            response_text = """📋 تم تسجيل طلبك لمتابعة طلب سابق

🔍 يرجى تزويدنا بـ:
• رقم الطلب السابق
• أو تاريخ الطلب
• أو وصف مختصر للطلب

سيتم البحث في سجلاتك وتزويدك بآخر التحديثات 📊"""
            
        else:
            # اختيار غير صحيح
            response_text = """❌ عذراً، الاختيار غير صحيح
يرجى الاختيار من الخيارات التالية:
1 شكوى أو استفسار
2 طلب أدوية
3 متابعة طلب سابق
يرجى الرد برقم الخيار المطلوب (1، 2، أو 3) 📝"""
            
            return {
                'success': False,
                'message': 'invalid_selection',
                'response_text': response_text
            }
        
        # إرسال رسالة الرد
        result = driver.send_text_message(
            phone=customer.wa_id,
            message=response_text
        )
        
        # حفظ رسالة الرد في قاعدة البيانات إذا تم الإرسال بنجاح
        if result.get('success', False):
            from .models import Message
            
            response_message = Message.objects.create(
                ticket=ticket,
                sender=ticket.assigned_agent.user if ticket.assigned_agent else None,
                sender_type='agent',
                direction='outgoing',
                message_text=response_text,
                message_type='text',
                delivery_status='sent',
                created_at=timezone.now()
            )
            
            # تحديث آخر رسالة في التذكرة (بدون تحديث last_agent_message_at لأنها رسالة قائمة تلقائية)
            ticket.last_message_at = timezone.now()
            ticket.save(update_fields=['last_message_at'])
            
            logger.info(f"Menu selection response saved to database - Message ID: {response_message.id}")
        
        logger.info(f"Menu selection processed for {customer.phone_number}: {selection}")
        
        return {
            'success': True,
            'message': f'selection_processed_{selection}',
            'response_text': response_text,
            'category': ticket.category,
            'priority': ticket.priority
        }
        
    except Exception as e:
        logger.error(f"Error handling menu selection: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': 'error',
            'response_text': 'حدث خطأ في معالجة اختيارك. يرجى المحاولة مرة أخرى.'
        }


def should_send_welcome_message(customer, message_text, current_ticket=None):
    """
    تحديد ما إذا كان يجب إرسال رسالة الترحيب
    
    Args:
        customer: كائن العميل
        message_text: نص الرسالة
        current_ticket: التذكرة الحالية (اختياري)
    
    Returns:
        bool: True إذا كان يجب إرسال رسالة الترحيب
    """
    import logging
    from .models import Message
    logger = logging.getLogger(__name__)
    
    try:
        # ✅ إذا كان لدينا التذكرة الحالية، نتحقق من حالتها
        if current_ticket:
            logger.info(f"Checking ticket {current_ticket.ticket_number}: category={current_ticket.category}, category_selected_at={current_ticket.category_selected_at}")
            
            # إذا كانت التذكرة مصنفة بالفعل، لا نرسل رسالة ترحيب
            if current_ticket.category_selected_at is not None:
                logger.info(f"Ticket {current_ticket.ticket_number} already classified - skipping welcome message")
                return False
            
            # ✅ التحقق من عدد رسائل العميل في التذكرة الحالية
            customer_messages_count = Message.objects.filter(
                ticket=current_ticket, 
                sender_type='customer'
            ).count()
            
            logger.info(f"Customer {customer.phone_number} has {customer_messages_count} message(s) in ticket {current_ticket.ticket_number}")
            
            # ✅ إذا كانت أول رسالة، نرسل رسالة ترحيب (بغض النظر عن محتوى الرسالة)
            if customer_messages_count == 1:
                logger.info(f"First message from customer - sending welcome message")
                return True
            else:
                logger.info(f"Not first message - skipping welcome message")
                return False
        
        # ✅ إذا لم يكن لدينا تذكرة حالية، نتحقق من عدد التذاكر الإجمالي
        if customer.total_tickets_count <= 1:
            logger.info(f"New customer {customer.phone_number} - sending welcome message")
            return True
        
        logger.info(f"No welcome conditions met - skipping welcome message")        
        return False
        
    except Exception as e:
        # في حالة حدوث خطأ، لا نرسل رسالة الترحيب
        logger.error(f"Error in should_send_welcome_message: {e}")
        return False
