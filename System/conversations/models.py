# conversations/models.py
"""
نماذج قاعدة البيانات لنظام إدارة محادثات صيدليات خليفة
Django Models - 22 جدول

المجموعات:
1. User Management (3 models)
2. Customer & Contact (3 models)
3. Ticket Management (3 models)
4. Messages (3 models)
5. Templates (3 models)
6. Delay Tracking (2 models)
7. KPI & Performance (3 models)
8. Activity Log (1 model)
9. Authentication (1 model)
"""

from django.db import models
from django.db.models import F
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from decimal import Decimal


# ============================================================================
# GROUP 1: USER MANAGEMENT (3 Models)
# ============================================================================

class User(models.Model):
    """
    المستخدمون (Admin + Agent + QA + Supervisor + Manager)
    """
    ROLE_CHOICES = [
        ('agent', 'Agent'),
        ('admin', 'Admin'),
        ('qa', 'QA (Quality Assurance)'),
        ('supervisor', 'Supervisor'),
        ('manager', 'Manager'),
        ('agent_supervisor', 'Agent Supervisor'),
    ]
    
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(max_length=100, null=True, blank=True)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, null=True, blank=True)
    
    # Account Status
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)

    # Django Admin Compatibility
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['is_active']),
            models.Index(fields=['is_online']),
        ]
    
    def __str__(self):
        return f"{self.username} ({self.role})"
    
    def set_password(self, raw_password):
        """تشفير كلمة المرور"""
        self.password_hash = make_password(raw_password)
    
    def check_password(self, raw_password):
        """التحقق من كلمة المرور"""
        return check_password(raw_password, self.password_hash)

    @property
    def is_authenticated(self):
        """
        دائماً True للمستخدمين المسجلين
        مطلوب لـ Django Authentication
        """
        return True

    @property
    def is_anonymous(self):
        """
        دائماً False للمستخدمين المسجلين
        مطلوب لـ Django Authentication
        """
        return False
    
    def get_backend(self):
        """
        للتوافقية مع Django Auth
        """
        return None


class Agent(models.Model):
    """
    بيانات الموظفين (Agents)
    """
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('busy', 'Busy'),
        ('offline', 'Offline'),
        ('on_break', 'On Break'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='agent')
    max_capacity = models.IntegerField(default=15)
    current_active_tickets = models.IntegerField(default=0)
    is_online = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')

    # Break Tracking
    is_on_break = models.BooleanField(default=False)  # هل الموظف في استراحة؟
    break_started_at = models.DateTimeField(null=True, blank=True)  # متى بدأت الاستراحة
    total_break_minutes_today = models.IntegerField(default=0)  # إجمالي دقائق الاستراحة اليوم

    # Counters
    total_messages_sent = models.IntegerField(default=0)
    total_messages_received = models.IntegerField(default=0)

    # Permissions
    perm_no_choice = models.BooleanField(default=False)
    perm_consultation = models.BooleanField(default=False)
    perm_complaint = models.BooleanField(default=False)
    perm_medicine = models.BooleanField(default=False)
    perm_follow_up = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'agents'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['is_online']),
            models.Index(fields=['current_active_tickets']),
        ]
    
    def __str__(self):
        return f"Agent: {self.user.full_name}"


class Admin(models.Model):
    """
    صلاحيات المديرين (Admins)
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin')
    can_manage_agents = models.BooleanField(default=True)
    can_manage_templates = models.BooleanField(default=True)
    can_view_analytics = models.BooleanField(default=True)
    can_edit_global_templates = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'admins'
    
    def __str__(self):
        return f"Admin: {self.user.full_name}"


# ============================================================================
# GROUP 2: CUSTOMER & CONTACT MANAGEMENT (3 Models)
# ============================================================================

class Customer(models.Model):
    """
    بيانات العملاء
    """
    CUSTOMER_TYPE_CHOICES = [
        ('regular', 'Regular'),
        ('vip', 'VIP'),
        ('sick', 'Sick'),
        ('needs_visits', 'Needs Visits'),
    ]

    SOURCE_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('web', 'Web'),
        ('mobile', 'Mobile App'),
        ('other', 'Other'),
    ]

    phone_number = models.CharField(max_length=20, unique=True)
    wa_id = models.CharField(max_length=50, unique=True)  # WhatsApp ID
    name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(max_length=100, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE_CHOICES, default='regular')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='whatsapp')
    is_blocked = models.BooleanField(default=False)
    total_tickets_count = models.IntegerField(default=0)
    
    # Timestamps
    first_contact_date = models.DateTimeField(auto_now_add=True)
    last_contact_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customers'
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['wa_id']),
            models.Index(fields=['customer_type']),
        ]
    
    def __str__(self):
        return f"{self.name or self.phone_number}"


class CustomerTag(models.Model):
    """
    تصنيفات العملاء (Tags)
    """
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='tags')
    tag = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_tags'
        unique_together = [['customer', 'tag']]
        indexes = [
            models.Index(fields=['customer', 'tag']),
        ]
    
    def __str__(self):
        return f"{self.customer.name}: {self.tag}"


class CustomerNote(models.Model):
    """
    ملاحظات على العملاء
    """
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='notes_list')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    note_text = models.TextField()
    is_important = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customer_notes'
        indexes = [
            models.Index(fields=['customer']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Note for {self.customer.name}"


# ============================================================================
# GROUP 3: TICKET MANAGEMENT (3 Models)
# ============================================================================

class Ticket(models.Model):
    """
    التذاكر (قلب النظام) ⭐
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('delayed', 'Delayed'),
        ('closed', 'Closed'),
    ]
    
    CATEGORY_CHOICES = [
        ('medicine_order', 'Medicine Order'),
        ('complaint', 'Complaint'),
        ('consultation', 'Consultation'),
        ('follow_up', 'Follow Up'),
        ('general', 'General'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    ticket_number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='tickets')
    assigned_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')
    current_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='current_tickets')
    
    # Status & Category
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    
    # Delay Tracking
    is_delayed = models.BooleanField(default=False)
    delay_started_at = models.DateTimeField(null=True, blank=True)
    total_delay_minutes = models.IntegerField(default=0)
    delay_count = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_agent_message_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    category_selected_at = models.DateTimeField(null=True, blank=True)  # متى اختار العميل نوع الخدمة (شكوى/أدوية/متابعة)
    
    # Metrics
    response_time_seconds = models.IntegerField(null=True, blank=True)
    handling_time_seconds = models.IntegerField(null=True, blank=True)
    messages_count = models.IntegerField(default=0)
    
    # Closure Info
    closed_by_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_tickets')
    closure_reason = models.CharField(max_length=255, null=True, blank=True)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tickets'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['assigned_agent']),
            models.Index(fields=['customer']),
            models.Index(fields=['created_at']),
            models.Index(fields=['is_delayed']),
            models.Index(fields=['assigned_agent', 'status']),
        ]
    
    def __str__(self):
        return f"Ticket #{self.ticket_number}"
    
    def get_category_arabic(self):
        """
        عرض نوع التذكرة بالعربية
        """
        category_map = {
            'medicine_order': 'ادوية',
            'complaint': 'شكوى',
            'consultation': 'استشارة',
            'follow_up': 'متابعة',
            'general': 'عام',
        }
        return category_map.get(self.category, self.category)
    
    get_category_arabic.short_description = 'النوع'
    
    @property
    def has_real_transfer(self):
        """
        Check if ticket has real transfers between different agents
        (excluding transfers from None/system)
        """
        return self.transfers.filter(
            from_agent__isnull=False,
            to_agent__isnull=False
        ).exclude(
            from_agent=F('to_agent')
        ).exists()


class TicketTransferLog(models.Model):
    """
    سجل نقل التذاكر بين الموظفين
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='transfers')
    from_agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_from')
    to_agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='transfers_to')
    transferred_by = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ticket_transfers_log'
        indexes = [
            models.Index(fields=['ticket']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Transfer: Ticket #{self.ticket.ticket_number}"


class TicketStateLog(models.Model):
    """
    سجل تغييرات حالة التذاكر
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='state_changes')
    old_state = models.CharField(max_length=50, null=True, blank=True)
    new_state = models.CharField(max_length=50)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ticket_states_log'
        indexes = [
            models.Index(fields=['ticket']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.old_state} → {self.new_state}"


# ============================================================================
# GROUP 4: MESSAGES (3 Models)
# ============================================================================

class Message(models.Model):
    """
    الرسائل
    """
    SENDER_TYPE_CHOICES = [
        ('customer', 'Customer'),
        ('agent', 'Agent'),
        ('admin', 'Admin'),
        ('system', 'System'),
    ]

    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('document', 'Document'),
        ('audio', 'Audio'),
        ('ptt', 'Voice Message'),  # WhatsApp voice messages
        ('video', 'Video'),
        ('file', 'File'),
        ('interactive', 'Interactive'),
        ('template', 'Template'),
    ]

    WHATSAPP_STATUS_CHOICES = [
        ('pending', 'Pending'),      # ✅ في الانتظار (لم يتم الإرسال بعد)
        ('queued', 'Queued'),        # ✅ في قائمة الانتظار
        ('sending', 'Sending'),      # ✅ جاري الإرسال
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ]

    DIRECTION_CHOICES = [
        ('incoming', 'Incoming'),  # من العميل
        ('outgoing', 'Outgoing'),  # من الموظف
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    sender_type = models.CharField(max_length=50, choices=SENDER_TYPE_CHOICES)
    direction = models.CharField(max_length=50, choices=DIRECTION_CHOICES, default='outgoing')
    message_text = models.TextField(null=True, blank=True)
    message_type = models.CharField(max_length=50, choices=MESSAGE_TYPE_CHOICES, default='text')
    media_url = models.CharField(max_length=500, null=True, blank=True)
    mime_type = models.CharField(max_length=100, null=True, blank=True)

    # WhatsApp Integration (المرحلة 2)
    whatsapp_message_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    delivery_status = models.CharField(max_length=50, choices=WHATSAPP_STATUS_CHOICES, default='pending')  # ✅ الافتراضي pending
    
    # ✅ Deduplication & Queue Management
    message_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)  # SHA256 hash لمنع التكرار
    retry_count = models.IntegerField(default=0)  # عدد محاولات الإرسال
    last_retry_at = models.DateTimeField(null=True, blank=True)  # آخر محاولة
    error_message = models.TextField(null=True, blank=True)  # رسالة الخطأ
    sent_at = models.DateTimeField(null=True, blank=True)  # وقت الإرسال الفعلي

    # Flags
    is_deleted = models.BooleanField(default=False)
    is_forwarded = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'messages'
        indexes = [
            models.Index(fields=['ticket']),
            models.Index(fields=['sender_type']),
            models.Index(fields=['created_at']),
            models.Index(fields=['whatsapp_message_id']),
            models.Index(fields=['is_read']),
        ]

    def __str__(self):
        return f"Message from {self.sender_type}"


class MessageDeliveryLog(models.Model):
    """
    سجل حالة توصيل الرسائل
    """
    DELIVERY_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ]

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='delivery_logs')
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES)
    error_message = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'message_delivery_log'
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.delivery_status}"


class MessageSearchIndex(models.Model):
    """
    فهرس البحث في الرسائل
    """
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    search_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'message_search_index'
        indexes = [
            models.Index(fields=['customer']),
        ]

    def __str__(self):
        return f"Search index for message #{self.message.id}"


# ============================================================================
# GROUP 5: TEMPLATES & QUICK REPLIES (3 Models)
# ============================================================================

class GlobalTemplate(models.Model):
    """
    القوالب العامة (Admin فقط)
    """
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('normal', 'Normal'),
        ('low', 'Low'),
    ]
    
    name = models.CharField(max_length=255)
    content = models.TextField()
    category = models.CharField(max_length=100, null=True, blank=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(Admin, on_delete=models.CASCADE, related_name='created_templates')
    updated_by = models.ForeignKey(Admin, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_templates')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'global_templates'
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['category']),
            models.Index(fields=['priority']),
        ]

    def __str__(self):
        return self.name


class AgentTemplate(models.Model):
    """
    قوالب الموظفين (خاصة بكل موظف)
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='templates')
    name = models.CharField(max_length=255)
    content = models.TextField()
    category = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    usage_count = models.IntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_templates'
        unique_together = [['agent', 'name']]
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.agent.user.full_name}: {self.name}"


class AutoReplyTrigger(models.Model):
    """
    محفزات الرد التلقائي
    """
    TRIGGER_TYPE_CHOICES = [
        ('keyword', 'Keyword'),
        ('category', 'Category'),
        ('greeting', 'Greeting'),
    ]

    trigger_keyword = models.CharField(max_length=100)
    template = models.ForeignKey(GlobalTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    reply_text = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    trigger_type = models.CharField(max_length=20, choices=TRIGGER_TYPE_CHOICES, default='keyword')
    created_by = models.ForeignKey(Admin, on_delete=models.CASCADE)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auto_reply_triggers'
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['trigger_keyword']),
        ]

    def __str__(self):
        return f"Trigger: {self.trigger_keyword}"


# ============================================================================
# GROUP 6: DELAY TRACKING & MONITORING (2 Models)
# ============================================================================

class ResponseTimeTracking(models.Model):
    """
    تتبع وقت الاستجابة
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='response_tracking')
    agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True)
    message_received_at = models.DateTimeField()
    first_response_at = models.DateTimeField(null=True, blank=True)
    response_time_seconds = models.IntegerField(null=True, blank=True)
    is_delayed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'response_time_tracking'
        indexes = [
            models.Index(fields=['agent']),
            models.Index(fields=['is_delayed']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Response tracking for Ticket #{self.ticket.ticket_number}"


class AgentDelayEvent(models.Model):
    """
    أحداث التأخير للموظفين
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='delay_events')
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='delay_events')
    delay_start_time = models.DateTimeField()
    delay_end_time = models.DateTimeField(null=True, blank=True)
    delay_duration_seconds = models.IntegerField(null=True, blank=True)
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_delay_events'
        indexes = [
            models.Index(fields=['agent']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Delay event for {self.agent.user.full_name}"


class AgentBreakSession(models.Model):
    """
    جلسات استراحة الموظفين
    تتبع كل استراحة يأخذها الموظف مع الوقت والمدة

    ✅ يتم إنشاء سجل جديد عند بدء الاستراحة
    ✅ يتم تحديث break_end_time و break_duration_seconds عند العودة للعمل
    ✅ يستخدم في حساب KPI لمعرفة تأثير الاستراحة على الأداء
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='break_sessions')
    break_start_time = models.DateTimeField()
    break_end_time = models.DateTimeField(null=True, blank=True)
    break_duration_seconds = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'agent_break_sessions'
        indexes = [
            models.Index(fields=['agent']),
            models.Index(fields=['break_start_time']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Break: {self.agent.user.full_name} - {self.break_start_time}"


# ============================================================================
# GROUP 7: KPI & PERFORMANCE METRICS (3 Models)
# ============================================================================

class AgentKPI(models.Model):
    """
    مؤشرات أداء الموظفين (يومي)
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='daily_kpis')
    kpi_date = models.DateField()

    # Metrics
    total_tickets = models.IntegerField(default=0)
    closed_tickets = models.IntegerField(default=0)
    avg_response_time_seconds = models.IntegerField(null=True, blank=True)
    messages_sent = models.IntegerField(default=0)
    messages_received = models.IntegerField(default=0)
    delay_count = models.IntegerField(default=0)

    # Break Time Tracking (NEW)
    total_break_time_seconds = models.IntegerField(default=0)  # إجمالي وقت الاستراحة في اليوم (بالثواني)
    break_count = models.IntegerField(default=0)  # عدد مرات الاستراحة في اليوم

    # Scores
    customer_satisfaction_score = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    first_response_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resolution_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    overall_kpi_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_kpi'
        unique_together = [['agent', 'kpi_date']]
        indexes = [
            models.Index(fields=['kpi_date']),
        ]

    def __str__(self):
        return f"KPI: {self.agent.user.full_name} - {self.kpi_date}"


class AgentKPIMonthly(models.Model):
    """
    مؤشرات أداء الموظفين (شهري)
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='monthly_kpis')
    month = models.DateField()  # First day of month

    # Metrics
    total_tickets = models.IntegerField(default=0)
    closed_tickets = models.IntegerField(default=0)
    avg_response_time_seconds = models.IntegerField(null=True, blank=True)
    messages_sent = models.IntegerField(default=0)
    messages_received = models.IntegerField(default=0)
    delay_count = models.IntegerField(default=0)

    # Scores
    avg_customer_satisfaction = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    overall_kpi_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rank = models.IntegerField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_kpi_monthly'
        unique_together = [['agent', 'month']]
        indexes = [
            models.Index(fields=['month']),
        ]

    def __str__(self):
        return f"Monthly KPI: {self.agent.user.full_name} - {self.month}"


class CustomerSatisfaction(models.Model):
    """
    تقييم رضا العملاء
    """
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='satisfaction_ratings')
    agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True)
    rating = models.IntegerField()  # 1-5
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customer_satisfaction'
        indexes = [
            models.Index(fields=['agent']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        return f"Rating: {self.rating}/5 for Ticket #{self.ticket.ticket_number}"


# ============================================================================
# GROUP 8: ACTIVITY LOG & AUDIT (1 Model)
# ============================================================================

class ActivityLog(models.Model):
    """
    سجل النشاطات والتدقيق
    """
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=50, null=True, blank=True)
    entity_id = models.IntegerField(null=True, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'activity_log'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.action} by {self.user.username if self.user else 'System'}"


# ============================================================================
# GROUP 9: AUTHENTICATION (1 Model)
# ============================================================================

class LoginAttempt(models.Model):
    """
    محاولات تسجيل الدخول (Brute Force Protection)
    """
    username = models.CharField(max_length=100)
    ip_address = models.CharField(max_length=45)
    user_agent = models.TextField(null=True, blank=True)
    success = models.BooleanField(default=False)
    attempt_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'login_attempts'
        indexes = [
            models.Index(fields=['username']),
            models.Index(fields=['ip_address']),
            models.Index(fields=['attempt_time']),
            models.Index(fields=['success']),
        ]

    def __str__(self):
        status = "Success" if self.success else "Failed"
        return f"{status} login attempt: {self.username}"


# ============================================================================
# GROUP 10: SYSTEM SETTINGS (1 Model)
# ============================================================================

class SystemSettings(models.Model):
    """
    إعدادات النظام
    
    ✅ Singleton Pattern - سجل واحد فقط في الجدول
    """
    # Assignment Settings
    assignment_algorithm = models.CharField(
        max_length=20, 
        default='least_loaded',
        choices=[
            ('least_loaded', 'Least Loaded'),
            ('round_robin', 'Round Robin'),
            ('random', 'Random'),
        ]
    )
    
    # Delay Settings
    delay_threshold_minutes = models.IntegerField(default=1)
    
    # Agent Settings
    default_max_capacity = models.IntegerField(default=10)
    
    # Welcome Message
    welcome_message = models.TextField(
        default="""🌟 مرحباً بك في صيدليات خليفة! 
👋 نحن سعداء لخدمتك
يرجى اختيار نوع الخدمة المطلوبة:
1 شكوى أو استفسار
2 طلب أدوية
3 متابعة طلب سابق
يرجى الرد برقم الخيار المطلوب (1، 2، أو 3) 📝"""
    )
    
    # Working Hours
    work_start_time = models.TimeField(default='09:00')
    work_end_time = models.TimeField(default='17:00')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'system_settings'
        verbose_name = 'System Settings'
        verbose_name_plural = 'System Settings'
    
    def __str__(self):
        return f"System Settings (Updated: {self.updated_at})"
    
    @classmethod
    def get_settings(cls):
        """
        الحصول على الإعدادات (Singleton Pattern)
        
        Returns:
            SystemSettings object
        """
        settings, created = cls.objects.get_or_create(id=1)
        return settings
    
    def save(self, *args, **kwargs):
        """
        تأكد من وجود سجل واحد فقط (Singleton)
        """
        self.id = 1
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """
        منع حذف الإعدادات
        """
        pass
