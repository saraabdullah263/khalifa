# conversations/serializers.py
"""
Django REST Framework Serializers
تحويل Models إلى JSON والعكس

المجموعات:
1. User Management (3 serializers)
2. Customer & Contact (3 serializers)
3. Ticket Management (3 serializers)
4. Messages (3 serializers)
5. Templates (3 serializers)
6. Delay Tracking (2 serializers)
7. KPI & Performance (3 serializers)
8. Activity Log (1 serializer)
9. Authentication (1 serializer)
"""

from rest_framework import serializers
from .models import (
    User, Agent, Admin,
    Customer, CustomerTag, CustomerNote,
    Ticket, TicketTransferLog, TicketStateLog,
    Message, MessageDeliveryLog, MessageSearchIndex,
    GlobalTemplate, AgentTemplate, AutoReplyTrigger,
    ResponseTimeTracking, AgentDelayEvent,
    AgentKPI, AgentKPIMonthly, CustomerSatisfaction,
    ActivityLog, LoginAttempt, SystemSettings
)


# ============================================================================
# GROUP 1: USER MANAGEMENT SERIALIZERS (3)
# ============================================================================

class UserSerializer(serializers.ModelSerializer):
    """
    Serializer للمستخدمين (Admin + Agent)
    """
    password = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'password', 'role', 'full_name',
            'phone', 'is_active', 'is_online', 'last_login',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_login']
        extra_kwargs = {
            'password': {'write_only': True},
            'email': {'required': False, 'allow_blank': True},
        }
    
    def create(self, validated_data):
        """
        إنشاء مستخدم جديد مع تشفير كلمة المرور
        """
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user
    
    def update(self, instance, validated_data):
        """
        تحديث مستخدم مع تشفير كلمة المرور إذا تم تغييرها
        """
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        if password:
            instance.set_password(password)
        
        instance.save()
        return instance


class AgentSerializer(serializers.ModelSerializer):
    """
    Serializer للموظفين
    """
    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='agent'),
        source='user',
        write_only=True
    )
    
    # Computed fields
    available_capacity = serializers.SerializerMethodField()
    is_available = serializers.SerializerMethodField()
    
    class Meta:
        model = Agent
        fields = [
            'id', 'user', 'user_id', 'max_capacity', 'current_active_tickets',
            'is_online', 'status', 'total_messages_sent', 'total_messages_received',
            'is_on_break', 'break_started_at', 'total_break_minutes_today',  # ✅ حقول الاستراحة
            'available_capacity', 'is_available', 'created_at', 'updated_at',
            'perm_no_choice', 'perm_consultation', 'perm_complaint', 'perm_medicine', 'perm_follow_up'
        ]
        read_only_fields = [
            'id', 'current_active_tickets', 'total_messages_sent',
            'total_messages_received', 'break_started_at', 'total_break_minutes_today',  # ✅ للقراءة فقط
            'created_at', 'updated_at'
        ]
    
    def get_available_capacity(self, obj):
        """
        حساب السعة المتاحة
        """
        return obj.max_capacity - obj.current_active_tickets
    
    def get_is_available(self, obj):
        """
        هل الموظف متاح لاستقبال تذاكر جديدة؟
        """
        return (
            obj.is_online and 
            obj.status == 'available' and 
            obj.current_active_tickets < obj.max_capacity
        )


class AdminSerializer(serializers.ModelSerializer):
    """
    Serializer للمديرين
    """
    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='admin'),
        source='user',
        write_only=True
    )
    
    class Meta:
        model = Admin
        fields = [
            'id', 'user', 'user_id', 'can_manage_agents', 'can_manage_templates',
            'can_view_analytics', 'can_edit_global_templates',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ============================================================================
# GROUP 2: CUSTOMER MANAGEMENT SERIALIZERS (3)
# ============================================================================

class CustomerTagSerializer(serializers.ModelSerializer):
    """
    Serializer لتصنيفات العملاء
    """
    class Meta:
        model = CustomerTag
        fields = ['id', 'customer', 'tag', 'created_at']
        read_only_fields = ['id', 'created_at']


class CustomerNoteSerializer(serializers.ModelSerializer):
    """
    Serializer لملاحظات العملاء
    """
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    
    class Meta:
        model = CustomerNote
        fields = [
            'id', 'customer', 'created_by', 'created_by_name', 'note_text',
            'is_important', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustomerSerializer(serializers.ModelSerializer):
    """
    Serializer للعملاء
    """
    tags = CustomerTagSerializer(many=True, read_only=True)
    notes = CustomerNoteSerializer(many=True, read_only=True)

    # Computed fields
    tags_list = serializers.SerializerMethodField()

    # wa_id optional - سيتم توليده تلقائياً من phone_number
    wa_id = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'phone_number', 'wa_id', 'name', 'email', 'notes',
            'customer_type', 'source', 'is_blocked', 'total_tickets_count',
            'first_contact_date', 'last_contact_date',
            'tags', 'tags_list', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'total_tickets_count', 'first_contact_date',
            'created_at', 'updated_at'
        ]
    
    def get_tags_list(self, obj):
        """
        قائمة التصنيفات كنص
        """
        return [tag.tag for tag in obj.tags.all()]
    
    def validate_phone_number(self, value):
        """
        التحقق من صحة رقم الهاتف
        """
        # إزالة المسافات والرموز
        cleaned = ''.join(filter(str.isdigit, value))

        # إزالة 0 من البداية إذا كانت موجودة
        if cleaned.startswith('0'):
            cleaned = cleaned[1:]

        # التأكد من أن الرقم يبدأ بـ 20 (مصر)
        if not cleaned.startswith('20'):
            cleaned = '20' + cleaned

        # التأكد من طول الرقم (12 رقم: 20 + 10 أرقام)
        if len(cleaned) != 12:
            raise serializers.ValidationError(
                "رقم الهاتف يجب أن يكون 10 أرقام (بعد كود الدولة 20)"
            )

        return cleaned

    def validate_wa_id(self, value):
        """
        التحقق من صحة WhatsApp ID
        """
        if not value:
            return value
        # نفس التحقق من رقم الهاتف
        return self.validate_phone_number(value)

    def create(self, validated_data):
        """
        إنشاء عميل جديد
        إذا لم يتم توفير wa_id، سيتم استخدام phone_number
        """
        if 'wa_id' not in validated_data or not validated_data.get('wa_id'):
            validated_data['wa_id'] = validated_data['phone_number']

        return super().create(validated_data)


# ============================================================================
# GROUP 3: TICKET MANAGEMENT SERIALIZERS (3)
# ============================================================================

class TicketStateLogSerializer(serializers.ModelSerializer):
    """
    Serializer لسجل تغييرات حالة التذكرة
    """
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True)
    
    class Meta:
        model = TicketStateLog
        fields = [
            'id', 'ticket', 'changed_by', 'changed_by_name',
            'old_state', 'new_state', 'reason', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TicketTransferLogSerializer(serializers.ModelSerializer):
    """
    Serializer لسجل نقل التذاكر
    """
    from_agent_name = serializers.CharField(source='from_agent.user.full_name', read_only=True)
    to_agent_name = serializers.CharField(source='to_agent.user.full_name', read_only=True)
    transferred_by_name = serializers.CharField(source='transferred_by.full_name', read_only=True)
    
    class Meta:
        model = TicketTransferLog
        fields = [
            'id', 'ticket', 'from_agent', 'from_agent_name',
            'to_agent', 'to_agent_name', 'transferred_by', 'transferred_by_name',
            'reason', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TicketSerializer(serializers.ModelSerializer):
    """
    Serializer للتذاكر (قلب النظام)
    """
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    assigned_agent_name = serializers.CharField(source='assigned_agent.user.full_name', read_only=True)
    current_agent_name = serializers.CharField(source='current_agent.user.full_name', read_only=True)
    closed_by_name = serializers.CharField(source='closed_by_user.full_name', read_only=True)
    
    # Nested serializers
    state_logs = TicketStateLogSerializer(many=True, read_only=True)
    transfer_logs = TicketTransferLogSerializer(many=True, read_only=True)
    
    # Computed fields
    is_overdue = serializers.SerializerMethodField()
    time_since_last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Ticket
        fields = [
            'id', 'ticket_number', 'customer', 'customer_name', 'customer_phone',
            'assigned_agent', 'assigned_agent_name', 'current_agent', 'current_agent_name',
            'closed_by_user', 'closed_by_name', 'status', 'category', 'priority',
            'is_delayed', 'delay_started_at', 'total_delay_minutes', 'delay_count',
            'created_at', 'first_response_at', 'last_message_at',
            'last_customer_message_at', 'last_agent_message_at', 'closed_at',
            'category_selected_at',  # ✅ إضافة الحقل الجديد
            'response_time_seconds', 'handling_time_seconds', 'messages_count',
            'closure_reason', 'updated_at', 'state_logs', 'transfer_logs',
            'is_overdue', 'time_since_last_message'
        ]
        read_only_fields = [
            'id', 'ticket_number', 'is_delayed', 'delay_started_at',
            'total_delay_minutes', 'delay_count', 'first_response_at',
            'category_selected_at',  # ✅ إضافة للحقول للقراءة فقط
            'last_message_at', 'last_customer_message_at', 'last_agent_message_at',
            'response_time_seconds', 'handling_time_seconds', 'messages_count',
            'created_at', 'updated_at'
        ]
    
    def get_is_overdue(self, obj):
        """
        هل التذكرة متأخرة؟
        """
        return obj.is_delayed
    
    def get_time_since_last_message(self, obj):
        """
        الوقت منذ آخر رسالة (بالدقائق)
        """
        if obj.last_message_at:
            from django.utils import timezone
            delta = timezone.now() - obj.last_message_at
            return int(delta.total_seconds() / 60)
        return None


# ============================================================================
# GROUP 4: MESSAGE SERIALIZERS (3)
# ============================================================================

class MessageDeliveryLogSerializer(serializers.ModelSerializer):
    """
    Serializer لسجل توصيل الرسائل
    """
    class Meta:
        model = MessageDeliveryLog
        fields = ['id', 'message', 'delivery_status', 'error_message', 'created_at']
        read_only_fields = ['id', 'created_at']


class MessageSearchIndexSerializer(serializers.ModelSerializer):
    """
    Serializer لفهرس البحث في الرسائل
    """
    class Meta:
        model = MessageSearchIndex
        fields = ['id', 'message', 'customer', 'search_text', 'created_at']
        read_only_fields = ['id', 'created_at']


class MessageSerializer(serializers.ModelSerializer):
    """
    Serializer للرسائل
    """
    sender_name = serializers.SerializerMethodField()
    delivery_log = MessageDeliveryLogSerializer(read_only=True)
    image = serializers.ImageField(write_only=True, required=False, allow_null=True)

    # Computed fields
    time_ago = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'ticket', 'sender', 'sender_type', 'sender_name',
            'message_text', 'message_type', 'media_url', 'mime_type',
            'whatsapp_message_id', 'delivery_status', 'is_deleted',
            'is_forwarded', 'is_read', 'read_at', 'created_at', 'updated_at',
            'delivery_log', 'time_ago', 'image'
        ]
        read_only_fields = [
            'id', 'whatsapp_message_id', 'delivery_status',
            'read_at', 'created_at', 'updated_at', 'media_url', 'mime_type',
            'sender', 'sender_type'  # حقول مُدارة من الـ backend
        ]
    
    def validate_image(self, value):
        """
        التحقق من الصورة المرفوعة
        """
        if value and value.size > 5 * 1024 * 1024:  # 5MB
            raise serializers.ValidationError('حجم الصورة يجب أن يكون أقل من 5 ميجابايت')
        return value
    
    def validate(self, data):
        """
        التحقق من البيانات الكلية
        """
        # إذا لم يكن هناك نص ولا صورة، رفع خطأ
        if not data.get('message_text') and not data.get('image'):
            raise serializers.ValidationError('يجب توفير نص أو صورة على الأقل')
        
        return data
    
    def create(self, validated_data):
        """
        إنشاء رسالة جديدة
        نزع حقل image من البيانات لأنه يتم التعامل معه في perform_create
        """
        # Remove image from validated_data since it's handled in perform_create
        validated_data.pop('image', None)
        
        return super().create(validated_data)

    def get_sender_name(self, obj):
        """
        اسم المرسل
        """
        if obj.sender_type == 'customer':
            return obj.ticket.customer.name or obj.ticket.customer.phone_number
        elif obj.sender_type == 'agent' and obj.sender:
            return obj.sender.full_name
        elif obj.sender_type == 'system':
            return 'النظام'
        return 'Unknown'

    def get_time_ago(self, obj):
        """
        الوقت منذ إرسال الرسالة (بالدقائق)
        """
        from django.utils import timezone
        delta = timezone.now() - obj.created_at
        minutes = int(delta.total_seconds() / 60)

        if minutes < 1:
            return 'الآن'
        elif minutes < 60:
            return f'{minutes} دقيقة'
        elif minutes < 1440:  # 24 hours
            hours = minutes // 60
            return f'{hours} ساعة'
        else:
            days = minutes // 1440
            return f'{days} يوم'


# ============================================================================
# GROUP 5: TEMPLATE SERIALIZERS (3)
# ============================================================================

class GlobalTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer للقوالب العامة
    """
    created_by_name = serializers.CharField(source='created_by.user.full_name', read_only=True)
    updated_by_name = serializers.CharField(source='updated_by.user.full_name', read_only=True)

    class Meta:
        model = GlobalTemplate
        fields = [
            'id', 'name', 'content', 'category', 'priority', 'is_active',
            'created_by', 'created_by_name', 'updated_by', 'updated_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'updated_by', 'created_at', 'updated_at']


class AgentTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer لقوالب الموظفين
    """
    agent_name = serializers.CharField(source='agent.user.full_name', read_only=True)

    class Meta:
        model = AgentTemplate
        fields = [
            'id', 'agent', 'agent_name', 'name', 'content', 'category',
            'is_active', 'usage_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'agent', 'usage_count', 'created_at', 'updated_at']


class AutoReplyTriggerSerializer(serializers.ModelSerializer):
    """
    Serializer لمحفزات الرد التلقائي
    """
    template_name = serializers.CharField(source='template.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.user.full_name', read_only=True)

    class Meta:
        model = AutoReplyTrigger
        fields = [
            'id', 'trigger_keyword', 'reply_text', 'template', 'template_name',
            'created_by', 'created_by_name', 'is_active', 'trigger_type',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ============================================================================
# GROUP 6: DELAY TRACKING SERIALIZERS (2)
# ============================================================================

class ResponseTimeTrackingSerializer(serializers.ModelSerializer):
    """
    Serializer لتتبع وقت الاستجابة
    """
    agent_name = serializers.CharField(source='agent.user.full_name', read_only=True)
    ticket_number = serializers.CharField(source='ticket.ticket_number', read_only=True)

    class Meta:
        model = ResponseTimeTracking
        fields = [
            'id', 'ticket', 'ticket_number', 'agent', 'agent_name',
            'message_received_at', 'first_response_at', 'response_time_seconds',
            'is_delayed', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class AgentDelayEventSerializer(serializers.ModelSerializer):
    """
    Serializer لأحداث التأخير
    """
    agent_name = serializers.CharField(source='agent.user.full_name', read_only=True)
    ticket_number = serializers.CharField(source='ticket.ticket_number', read_only=True)

    class Meta:
        model = AgentDelayEvent
        fields = [
            'id', 'agent', 'agent_name', 'ticket', 'ticket_number',
            'delay_start_time', 'delay_end_time', 'delay_duration_seconds',
            'reason', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


# ============================================================================
# GROUP 7: KPI & PERFORMANCE SERIALIZERS (3)
# ============================================================================

class AgentKPISerializer(serializers.ModelSerializer):
    """
    Serializer لمؤشرات الأداء اليومية
    """
    agent_name = serializers.CharField(source='agent.user.full_name', read_only=True)

    class Meta:
        model = AgentKPI
        fields = [
            'id', 'agent', 'agent_name', 'kpi_date', 'total_tickets',
            'closed_tickets', 'avg_response_time_seconds', 'messages_sent',
            'messages_received', 'delay_count',
            'total_break_time_seconds', 'break_count',  # ✅ إضافة حقول الاستراحة
            'customer_satisfaction_score',
            'first_response_rate', 'resolution_rate', 'overall_kpi_score',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AgentKPIMonthlySerializer(serializers.ModelSerializer):
    """
    Serializer لمؤشرات الأداء الشهرية
    """
    agent_name = serializers.CharField(source='agent.user.full_name', read_only=True)

    class Meta:
        model = AgentKPIMonthly
        fields = [
            'id', 'agent', 'agent_name', 'month', 'total_tickets',
            'closed_tickets', 'avg_response_time_seconds', 'messages_sent',
            'messages_received', 'delay_count', 'avg_customer_satisfaction',
            'overall_kpi_score', 'rank', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustomerSatisfactionSerializer(serializers.ModelSerializer):
    """
    Serializer لتقييم رضا العملاء
    """
    agent_name = serializers.CharField(source='agent.user.full_name', read_only=True)
    ticket_number = serializers.CharField(source='ticket.ticket_number', read_only=True)

    class Meta:
        model = CustomerSatisfaction
        fields = [
            'id', 'ticket', 'ticket_number', 'agent', 'agent_name',
            'rating', 'comment', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def validate_rating(self, value):
        """
        التحقق من أن التقييم بين 1 و 5
        """
        if value < 1 or value > 5:
            raise serializers.ValidationError("التقييم يجب أن يكون بين 1 و 5")
        return value


# ============================================================================
# GROUP 8: ACTIVITY LOG SERIALIZER (1)
# ============================================================================

class ActivityLogSerializer(serializers.ModelSerializer):
    """
    Serializer لسجل النشاطات
    """
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = ActivityLog
        fields = [
            'id', 'user', 'user_name', 'action', 'entity_type', 'entity_id',
            'old_value', 'new_value', 'ip_address', 'user_agent', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


# ============================================================================
# GROUP 9: AUTHENTICATION SERIALIZER (1)
# ============================================================================

class LoginAttemptSerializer(serializers.ModelSerializer):
    """
    Serializer لمحاولات تسجيل الدخول
    """
    class Meta:
        model = LoginAttempt
        fields = [
            'id', 'username', 'ip_address', 'user_agent',
            'success', 'attempt_time'
        ]
        read_only_fields = ['id', 'attempt_time']




# ============================================================================
# GROUP 10: SYSTEM SETTINGS
# ============================================================================

class SystemSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer لإعدادات النظام
    """
    class Meta:
        model = SystemSettings
        fields = [
            'id',
            'assignment_algorithm',
            'delay_threshold_minutes',
            'default_max_capacity',
            'welcome_message',
            'work_start_time',
            'work_end_time',
            'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']
