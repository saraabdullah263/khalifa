"""
Frontend Views
صفحات HTML للواجهة الأمامية

تحتوي على:
- صفحة تسجيل الدخول
- صفحات Admin (7 صفحات)
- صفحات Agent (3 صفحات)
"""

from django.shortcuts import render, redirect
from django.http import HttpResponse
import csv
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from .models import (
    User, Agent, Customer, Ticket, Message,
    GlobalTemplate, AgentTemplate, AgentKPI,
    LoginAttempt
)
from .permissions import IsAdmin, IsAgent
from .utils import generate_ticket_number, log_activity


# ============================================
# Helper Functions
# ============================================

def has_admin_access(user):
    """
    Check if user has admin-level access
    Includes: admin, qa, manager, supervisor, agent_supervisor
    """
    return user.role in ['admin', 'qa', 'manager', 'supervisor', 'agent_supervisor']


# ============================================
# Authentication Views
# ============================================

def login_view(request):
    """
    صفحة تسجيل الدخول
    GET/POST /login/
    """
    # إذا كان المستخدم مسجل دخول بالفعل، إعادة توجيه
    if request.user.is_authenticated:
        if has_admin_access(request.user):
            return redirect('admin-dashboard')
        else:
            return redirect('agent-conversations')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username or not password:
            messages.error(request, 'يرجى إدخال اسم المستخدم وكلمة المرور')
            return render(request, 'login.html')
        
        # التحقق من محاولات تسجيل الدخول الفاشلة
        recent_attempts = LoginAttempt.objects.filter(
            username=username,
            success=False,
            attempt_time__gte=timezone.now() - timedelta(minutes=15)
        ).count()
        
        if recent_attempts >= 5:
            messages.error(request, 'تم تجاوز عدد المحاولات المسموح بها. يرجى المحاولة بعد 15 دقيقة')
            return render(request, 'login.html')
        
        # محاولة تسجيل الدخول
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # تسجيل الدخول ناجح
            auth_login(request, user)

            # جعل الجلسة دائمة - لا تنتهي أبداً
            request.session.set_expiry(86400 * 365 * 10)  # 10 سنوات
            request.session.modified = True

            # تحديث حالة المستخدم إلى Online
            user.is_online = True
            user.last_login = timezone.now()
            user.save(update_fields=['is_online', 'last_login'])

            # تحديث حالة Agent إذا كان الموظف
            if user.role == 'agent' and hasattr(user, 'agent'):
                user.agent.is_online = True
                user.agent.status = 'available'
                user.agent.save(update_fields=['is_online', 'status'])

            # تسجيل المحاولة الناجحة
            LoginAttempt.objects.create(
                username=username,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                success=True
            )

            # تسجيل النشاط
            log_activity(
                user=user,
                action='login',
                entity_type='user',
                entity_id=user.id,
                request=request
            )

            messages.success(request, f'مرحباً {user.full_name or user.username}!')

            # إعادة التوجيه حسب الدور
            if has_admin_access(user):
                return redirect('admin-dashboard')
            else:
                return redirect('agent-conversations')
        else:
            # تسجيل الدخول فاشل
            LoginAttempt.objects.create(
                username=username,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                success=False
            )
            
            messages.error(request, 'اسم المستخدم أو كلمة المرور غير صحيحة')
            return render(request, 'login.html')
    
    return render(request, 'login.html')


@login_required
def logout_view(request):
    """
    تسجيل الخروج
    GET /logout/
    """
    # تحديث حالة المستخدم إلى Offline قبل Logout
    if request.user.is_authenticated:
        user = request.user
        user.is_online = False
        user.save(update_fields=['is_online'])

        # تحديث حالة Agent إذا كان الموظف
        if user.role == 'agent' and hasattr(user, 'agent'):
            user.agent.is_online = False
            user.agent.status = 'offline'
            user.agent.save(update_fields=['is_online', 'status'])

        # تسجيل النشاط
        log_activity(
            user=user,
            action='logout',
            entity_type='user',
            entity_id=user.id,
            request=request
        )

    auth_logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح')
    return redirect('login')


@login_required
def profile_view(request):
    """
    الملف الشخصي
    GET /profile/
    """
    return render(request, 'profile.html', {
        'user': request.user
    })


# ============================================
# Admin Views (7 صفحات)
# ============================================

@login_required
def admin_dashboard(request):
    """
    لوحة التحكم - Admin
    GET /admin/dashboard/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    from .utils import update_ticket_delay_status
    
    for ticket in Ticket.objects.filter(status='open'):
        update_ticket_delay_status(ticket)
    
    # إحصائيات
    open_tickets = Ticket.objects.filter(status='open').count()
    pending_tickets = Ticket.objects.filter(status='pending').count()
    closed_tickets = Ticket.objects.filter(status='closed').count()
    delayed_tickets = Ticket.objects.filter(is_delayed=True, status__in=['open', 'pending']).count()
    
    # Active customers (customers with open or pending tickets)
    active_customers = Customer.objects.filter(
        tickets__status__in=['open', 'pending']
    ).distinct().count()
    
    # ✅ الموظفين المتاحين الآن (Online)
    available_agents = Agent.objects.filter(
        user__is_active=True,
        is_online=True
    ).select_related('user').order_by('user__full_name')
    
    available_agents_count = available_agents.count()
    
    # آخر التذاكر
    recent_tickets = Ticket.objects.select_related('customer', 'assigned_agent__user').order_by('-created_at')[:10]
    
    context = {
        'active_customers': active_customers,
        'open_tickets': open_tickets,
        'pending_tickets': pending_tickets,
        'closed_tickets': closed_tickets,
        'delayed_tickets': delayed_tickets,
        'available_agents': available_agents,
        'available_agents_count': available_agents_count,
        'recent_tickets': recent_tickets,
    }
    
    return render(request, 'admin/dashboard.html', context)


@login_required
def admin_agents(request):
    """
    إدارة الموظفين - Admin
    GET /admin/agents/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    # ✅ منع المشرفين من الوصول لهذه الصفحة
    if request.user.role in ['supervisor', 'agent_supervisor']:
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')
    
    users = User.objects.filter(role__in=['agent', 'supervisor', 'qa', 'manager', 'agent_supervisor']).prefetch_related('agent').all()
    
    for user in users:
        if user.role != 'agent':
            user.agent_data = None
        else:
            try:
                user.agent_data = user.agent
            except Agent.DoesNotExist:
                user.agent_data = None
    
    return render(request, 'admin/agents.html', {
        'agents': users
    })


@login_required
def admin_customers(request):
    """
    إدارة العملاء - Admin
    GET /admin/customers/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')

    customers = Customer.objects.all().order_by('-created_at')

    # معالجة tags لكل عميل (tags هو related_name لـ CustomerTag)
    for customer in customers:
        customer.tags_list = list(customer.tags.all())

    return render(request, 'admin/customers.html', {
        'customers': customers
    })


@login_required
def admin_tickets(request):
    """
    جميع التذاكر - Admin
    GET /admin/tickets/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    from .utils import update_ticket_delay_status
    from django.utils import timezone
    from datetime import datetime, time
    
    for ticket in Ticket.objects.filter(status='open'):
        update_ticket_delay_status(ticket)
    
    tickets = Ticket.objects.select_related('customer', 'assigned_agent__user').prefetch_related('transfers').order_by('-created_at')

    # تحديد بداية ونهاية اليوم الحالي
    today_start = timezone.make_aware(datetime.combine(timezone.now().date(), time.min))
    today_end = timezone.make_aware(datetime.combine(timezone.now().date(), time.max))

    # إحصائيات الفئات - لليوم الحالي فقط
    complaints_count = Ticket.objects.filter(
        category='complaint',
        created_at__gte=today_start,
        created_at__lte=today_end
    ).count()
    medicine_count = Ticket.objects.filter(
        category='medicine_order',
        created_at__gte=today_start,
        created_at__lte=today_end
    ).count()
    follow_up_count = Ticket.objects.filter(
        category='follow_up',
        created_at__gte=today_start,
        created_at__lte=today_end
    ).count()

    # ✅ إحصائيات التأخير
    delayed_count = Ticket.objects.filter(is_delayed=True, status='open').count()

    return render(request, 'admin/tickets.html', {
        'tickets': tickets,
        'complaints_count': complaints_count,
        'medicine_count': medicine_count,
        'follow_up_count': follow_up_count,
        'delayed_count': delayed_count,  # ✅ إضافة عدد التذاكر المتأخرة
    })


@login_required
def admin_templates(request):
    """
    القوالب العامة - Admin
    GET /admin/templates/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')

    # ✅ منع المشرفين من الوصول لهذه الصفحة
    if request.user.role in ['supervisor', 'agent_supervisor']:
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')

    templates = GlobalTemplate.objects.filter(is_active=True).order_by('-updated_at')

    return render(request, 'admin/templates.html', {
        'templates': templates
    })


@login_required
def admin_reports(request):
    """
    التقارير - Admin
    GET /admin/reports/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')

    # ✅ منع المشرفين من الوصول لهذه الصفحة
    if request.user.role in ['supervisor', 'agent_supervisor']:
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')

    # تقارير الموظفين
    agents_kpi = AgentKPI.objects.select_related('agent__user').filter(
        kpi_date=timezone.now().date()
    )

    return render(request, 'admin/reports.html', {
        'agents_kpi': agents_kpi
    })


@login_required
def admin_settings(request):
    """
    الإعدادات - Admin
    GET /admin/settings/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    # ✅ منع المشرفين من الوصول لهذه الصفحة
    if request.user.role in ['supervisor', 'agent_supervisor']:
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')
    
    return render(request, 'admin/settings.html')


@login_required
def admin_agent_management(request):
    """
    إدارة الموظفين للمشرفين
    GET /admin/agent-management/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    # السماح فقط للمشرفين والمديرين
    if request.user.role not in ['admin', 'manager', 'supervisor']:
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')
    
    from .models import ActivityLog
    from django.db.models import Q
    
    # Get date range
    date_from_str = request.GET.get('date_from')
    date_to_str = request.GET.get('date_to')
    
    today = timezone.now().date()
    
    if date_from_str:
        try:
            date_from = timezone.datetime.strptime(date_from_str, '%Y-%m-%d').date()
        except ValueError:
            date_from = today
    else:
        date_from = today
        
    if date_to_str:
        try:
            date_to = timezone.datetime.strptime(date_to_str, '%Y-%m-%d').date()
        except ValueError:
            date_to = today
    else:
        date_to = today

    # الحصول على جميع الموظفين
    agents = Agent.objects.select_related('user').filter(user__is_active=True).order_by('user__full_name')
    
    agents_data = []
    for agent in agents:
        # الحصول على النشاط في الفترة المحددة
        activities = ActivityLog.objects.filter(
            created_at__date__range=[date_from, date_to]
        ).filter(
            Q(user=agent.user, action__in=['login', 'logout']) |
            Q(entity_type='agent', entity_id=agent.id, action__in=['break_start', 'break_end', 'force_logout'])
        ).order_by('created_at')
        
        # استخراج أوقات الدخول والخروج والاستراحة
        login_time = None
        logout_time = None
        breaks = []
        current_break_start = None
        
        for activity in activities:
            if activity.action == 'login':
                # نأخذ أول تسجيل دخول
                if not login_time:
                    login_time = timezone.localtime(activity.created_at)
            elif activity.action in ['logout', 'force_logout']:
                # نأخذ آخر تسجيل خروج
                logout_time = timezone.localtime(activity.created_at)
            elif activity.action == 'break_start':
                current_break_start = timezone.localtime(activity.created_at)
            elif activity.action == 'break_end':
                if current_break_start:
                    end_time = timezone.localtime(activity.created_at)
                    duration = (end_time - current_break_start).total_seconds() / 60
                    breaks.append({
                        'start': current_break_start,
                        'end': end_time,
                        'duration': int(duration)
                    })
                    current_break_start = None
        
        # إذا كان في استراحة حالياً (فقط إذا كان تاريخ اليوم ضمن النطاق)
        if agent.is_on_break and agent.break_started_at and date_to >= today:
            break_start = timezone.localtime(agent.break_started_at)
            # Check if break started within the range
            if date_from <= break_start.date() <= date_to:
                duration = (timezone.now() - agent.break_started_at).total_seconds() / 60
                breaks.append({
                    'start': break_start,
                    'end': None,
                    'duration': int(duration),
                    'is_active': True
                })
            
        agents_data.append({
            'agent': agent,
            'login_time': login_time,
            'logout_time': logout_time,
            'breaks': breaks,
            'total_break_minutes': sum(b['duration'] for b in breaks)
        })
    
    # Handle Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="agent_activity_{date_from}_{date_to}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Agent', 'Login Time', 'Logout Time', 'Total Break (min)', 'Status'])
        
        for item in agents_data:
            writer.writerow([
                item['agent'].user.full_name,
                item['login_time'].strftime("%Y-%m-%d %H:%M:%S") if item['login_time'] else '-',
                item['logout_time'].strftime("%Y-%m-%d %H:%M:%S") if item['logout_time'] else '-',
                item['total_break_minutes'],
                item['agent'].status if item['agent'].is_online else 'Offline'
            ])
            
        return response
    
    return render(request, 'admin/agent_management.html', {
        'agents_data': agents_data,
        'date_from': date_from.strftime('%Y-%m-%d'),
        'date_to': date_to.strftime('%Y-%m-%d'),
        'today': today.strftime('%Y-%m-%d'),
    })


@login_required
def admin_monitor_agent_conversation(request, customer_id):
    """
    صفحة المحادثة للمدير ليتصرف كموظف
    GET /admin/monitor-agent-conversation/<customer_id>/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    try:
        customer = Customer.objects.get(id=customer_id)
        
        # الحصول على التذاكر المفتوحة للعميل
        tickets = Ticket.objects.filter(
            customer=customer,
            status__in=['open', 'pending']
        ).order_by('-created_at')
        
        # إذا لم توجد تذاكر مفتوحة، إنشاء واحدة جديدة
        if not tickets.exists():
            ticket = Ticket.objects.create(
                ticket_number=generate_ticket_number(),
                customer=customer,
                status='open',
                priority='normal',
                category='general'
            )
        else:
            ticket = tickets.first()
        
        return render(request, 'admin/admin_conversation.html', {
            'customer': customer,
            'ticket': ticket,
            'is_admin_as_agent': True
        })
        
    except Customer.DoesNotExist:
        messages.error(request, 'العميل غير موجود')
        return redirect('admin-tickets')

@login_required
def admin_monitor_agent(request, agent_id):
    """
    مراقبة محادثات موظف - Admin Only
    GET /admin/monitor-agent/<agent_id>/
    """
    if not has_admin_access(request.user):
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('agent-conversations')
    
    try:
        agent = Agent.objects.select_related('user').get(id=agent_id)
    except Agent.DoesNotExist:
        messages.error(request, 'الموظف غير موجود')
        return redirect('admin-agents')
    
    # الحصول على جميع التذاكر المعينة لهذا الموظف
    all_tickets = Ticket.objects.filter(
        assigned_agent=agent
    ).select_related('customer').order_by('-last_message_at')
    
    # تجميع التذاكر حسب العميل
    customers_map = {}
    for ticket in all_tickets:
        customer_id = ticket.customer.id
        if customer_id not in customers_map:
            customers_map[customer_id] = {
                'customer': ticket.customer,
                'tickets': [],
                'last_message_at': ticket.last_message_at,
                'has_delayed': False
            }
        customers_map[customer_id]['tickets'].append(ticket)
        if ticket.is_delayed:
            customers_map[customer_id]['has_delayed'] = True
        # تحديث آخر رسالة
        if ticket.last_message_at and (
            not customers_map[customer_id]['last_message_at'] or 
            ticket.last_message_at > customers_map[customer_id]['last_message_at']
        ):
            customers_map[customer_id]['last_message_at'] = ticket.last_message_at
    
    # تحويل الخريطة إلى قائمة وترتيبها
    conversations = sorted(
        customers_map.values(),
        key=lambda x: x['last_message_at'] if x['last_message_at'] else timezone.now(),
        reverse=True
    )
    
    return render(request, 'admin/monitor_agent.html', {
        'conversations': conversations,
        'agent': agent,
        'monitoring_mode': True  # علامة للإشارة إلى أن هذا وضع المراقبة
    })


# ============================================
# Agent Views (3 صفحات)
# ============================================

@login_required
def agent_conversations(request):
    """
    محادثاتي - Agent
    GET /agent/conversations/
    """
    if request.user.role != 'agent':
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')
    
    agent = Agent.objects.get(user=request.user)
    
    from .utils import check_ticket_delay, update_ticket_delay_status
    import logging
    logger = logging.getLogger(__name__)
    
    # الحصول على التذاكر المفتوحة المعينة لهذا الموظف فقط (current_agent للتحويلات)
    all_tickets = Ticket.objects.filter(
        current_agent=agent,
        status='open'
    ).select_related('customer').order_by('-last_message_at')
    
    # تجميع التذاكر حسب العميل
    customers_map = {}
    for ticket in all_tickets:
        # تحديث وحفظ حالة التأخير
        is_delayed_now = check_ticket_delay(ticket)
        logger.info(f"Ticket #{ticket.id}: last_customer_msg={ticket.last_customer_message_at}, last_agent_msg={ticket.last_agent_message_at}, is_delayed={is_delayed_now}")
        
        update_ticket_delay_status(ticket)
        # إعادة تحميل من الـ database للحصول على القيمة المحدثة
        ticket.refresh_from_db()
        
        customer_id = ticket.customer.id
        if customer_id not in customers_map:
            # حساب عدد الرسائل غير المقروءة من العميل
            unread_count = Message.objects.filter(
                ticket__customer_id=customer_id,
                ticket__current_agent=agent,
                ticket__status='open',
                sender_type='customer',
                is_read=False
            ).count()
            
            customers_map[customer_id] = {
                'customer': ticket.customer,
                'tickets': [],
                'last_message_at': ticket.last_message_at,
                'has_delayed': False,
                'has_transfer': False,
                'unread_count': unread_count
            }
        customers_map[customer_id]['tickets'].append(ticket)
        # استخدام check_ticket_delay للتأكد من الحالة الحالية
        if check_ticket_delay(ticket):
            customers_map[customer_id]['has_delayed'] = True
        # التحقق من التحويل
        if ticket.assigned_agent and ticket.current_agent and ticket.assigned_agent != ticket.current_agent:
            customers_map[customer_id]['has_transfer'] = True
        # تحديث آخر رسالة
        if ticket.last_message_at and (
            not customers_map[customer_id]['last_message_at'] or
            ticket.last_message_at > customers_map[customer_id]['last_message_at']
        ):
            customers_map[customer_id]['last_message_at'] = ticket.last_message_at
    
    # تحويل الخريطة إلى قائمة وترتيبها
    conversations = sorted(
        customers_map.values(),
        key=lambda x: x['last_message_at'] if x['last_message_at'] else timezone.now(),
        reverse=True
    )
    
    # حساب عدد العملاء لكل موظف
    all_agents = Agent.objects.filter(user__is_active=True).select_related('user')
    agents_client_counts = {}
    
    for agent_obj in all_agents:
        # حساب عدد العملاء الفعليين (لديهم تذاكر مفتوحة)
        client_count = Ticket.objects.filter(
            assigned_agent=agent_obj,
            status='open'
        ).values('customer').distinct().count()
        
        # حساب السعة القصوى للموظف
        max_capacity = agent_obj.max_capacity
        
        agents_client_counts[agent_obj.id] = {
            'current': client_count,
            'max': max_capacity,
            'name': agent_obj.user.full_name
        }
    
    return render(request, 'agent/conversations.html', {
        'conversations': conversations,
        'agent': agent,
        'agents_client_counts': agents_client_counts
    })


@login_required
def agent_templates(request):
    """
    قوالبي الخاصة - Agent
    GET /agent/templates/
    """
    if request.user.role != 'agent':
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')
    
    agent = Agent.objects.get(user=request.user)
    
    # القوالب الخاصة بالموظف
    my_templates = AgentTemplate.objects.filter(agent=agent, is_active=True)
    
    # القوالب العامة (للقراءة فقط)
    global_templates = GlobalTemplate.objects.filter(is_active=True)
    
    return render(request, 'agent/templates.html', {
        'my_templates': my_templates,
        'global_templates': global_templates
    })


@login_required
def agent_reports(request):
    """
    تقاريري الشخصية - Agent
    GET /agent/reports/
    """
    if request.user.role != 'agent':
        messages.error(request, 'ليس لديك صلاحية للوصول لهذه الصفحة')
        return redirect('admin-dashboard')
    
    agent = Agent.objects.get(user=request.user)
    
    # KPI اليوم
    today_kpi = AgentKPI.objects.filter(
        agent=agent,
        date=timezone.now().date()
    ).first()
    
    # KPI آخر 7 أيام
    last_7_days_kpi = AgentKPI.objects.filter(
        agent=agent,
        date__gte=timezone.now().date() - timedelta(days=7)
    ).order_by('-date')
    
    return render(request, 'agent/reports.html', {
        'today_kpi': today_kpi,
        'last_7_days_kpi': last_7_days_kpi,
        'agent': agent
    })

