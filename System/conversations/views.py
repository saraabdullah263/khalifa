# conversations/views.py
"""
Django REST Framework Views
API Endpoints + Business Logic

المجموعات:
1. Authentication Views (Login, Logout, Profile)
2. User Management Views (Admin, Agent)
3. Customer Management Views
4. Ticket Management Views (Core)
5. Message Management Views
6. Template Management Views
7. KPI & Analytics Views
8. Dashboard Views
9. Conversations Views (Real-time Updates)
"""

from rest_framework import viewsets, status, views
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.utils import timezone
from django.db.models import Q, Count, Avg, F
from datetime import datetime, timedelta

from .models import *
from .serializers import *
from .permissions import *
from .utils import *


# ============================================================================
# GROUP 1: AUTHENTICATION VIEWS
# ============================================================================

class LoginView(views.APIView):
    """
    تسجيل الدخول
    POST /api/auth/login/
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if not username or not password:
            return Response({
                'error': 'يرجى إدخال اسم المستخدم وكلمة المرور'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # التحقق من محاولات تسجيل الدخول الفاشلة (حسب الإجابة: 5 محاولات → 15 دقيقة)
        recent_attempts = LoginAttempt.objects.filter(
            username=username,
            success=False,
            attempt_time__gte=timezone.now() - timedelta(minutes=15)
        ).count()
        
        if recent_attempts >= 5:
            return Response({
                'error': 'تم تجاوز عدد المحاولات المسموح بها. يرجى المحاولة بعد 15 دقيقة'
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # محاولة تسجيل الدخول باستخدام Django's authenticate
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # التحقق من أن الحساب نشط
            if not user.is_active:
                # تسجيل المحاولة الفاشلة
                LoginAttempt.objects.create(
                    username=username,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    success=False
                )

                return Response({
                    'error': 'الحساب غير نشط'
                }, status=status.HTTP_403_FORBIDDEN)

            # تسجيل دخول ناجح
            django_login(request, user)  # استخدام Django's login

            user.last_login = timezone.now()
            user.is_online = True
            user.save()

            # تسجيل المحاولة الناجحة
            LoginAttempt.objects.create(
                username=username,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
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

            # تحديث حالة الموظف إذا كان موظفاً
            if user.role == 'agent':
                try:
                    agent = user.agent
                    agent.is_online = True
                    agent.status = 'available'
                    agent.save()
                except:
                    pass

            # إرجاع بيانات المستخدم
            serializer = UserSerializer(user)

            return Response({
                'message': 'تم تسجيل الدخول بنجاح',
                'user': serializer.data
            }, status=status.HTTP_200_OK)

        else:
            # فشل تسجيل الدخول
            LoginAttempt.objects.create(
                username=username,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                success=False
            )

            return Response({
                'error': 'اسم المستخدم أو كلمة المرور غير صحيحة'
            }, status=status.HTTP_401_UNAUTHORIZED)


class LogoutView(views.APIView):
    """
    تسجيل الخروج
    POST /api/auth/logout/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # استخدام request.user
        user = request.user

        if user and user.is_authenticated:
            user.is_online = False
            user.save()

            # تسجيل النشاط
            log_activity(
                user=user,
                action='logout',
                entity_type='user',
                entity_id=user.id,
                request=request
            )

            # تحديث حالة الموظف إذا كان موظفاً (حسب الإجابة س8: إعادة توزيع تلقائية)
            if user.role == 'agent':
                try:
                    agent = user.agent
                    agent.is_online = False
                    agent.status = 'offline'

                    # إعادة توزيع التذاكر النشطة
                    active_tickets = Ticket.objects.filter(
                        current_agent=agent,
                        status='open'
                    )

                    for ticket in active_tickets:
                        # البحث عن موظف متاح
                        new_agent = get_available_agent()

                        if new_agent:
                            # نقل التذكرة
                            old_agent = ticket.current_agent
                            ticket.current_agent = new_agent
                            ticket.save()

                            # تسجيل النقل
                            TicketTransferLog.objects.create(
                                ticket=ticket,
                                from_agent=old_agent,
                                to_agent=new_agent,
                                transferred_by=user,
                                reason='تسجيل خروج الموظف'
                            )

                            # تحديث عدد التذاكر
                            new_agent.current_active_tickets += 1
                            new_agent.save()

                    # تصفير عدد التذاكر النشطة
                    agent.current_active_tickets = 0
                    agent.save()

                except:
                    pass

        # استخدام Django's logout
        django_logout(request)

        return Response({
            'message': 'تم تسجيل الخروج بنجاح'
        }, status=status.HTTP_200_OK)


class ProfileView(views.APIView):
    """
    عرض وتحديث الملف الشخصي
    GET/PUT /api/auth/profile/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # استخدام request.user بدلاً من session
        user = request.user

        if not user or not user.is_authenticated:
            return Response({
                'error': 'غير مصرح'
            }, status=status.HTTP_401_UNAUTHORIZED)

        serializer = UserSerializer(user)

        # إضافة بيانات إضافية حسب الدور
        data = serializer.data

        if user.role == 'agent':
            try:
                agent = user.agent
                data['agent'] = AgentSerializer(agent).data
            except:
                pass

        elif user.role == 'admin':
            try:
                admin = user.admin
                data['admin'] = AdminSerializer(admin).data
            except:
                pass

        return Response(data, status=status.HTTP_200_OK)

    def put(self, request):
        # استخدام request.user بدلاً من session
        user = request.user

        if not user or not user.is_authenticated:
            return Response({
                'error': 'غير مصرح'
            }, status=status.HTTP_401_UNAUTHORIZED)

        serializer = UserSerializer(user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()

            # تسجيل النشاط
            log_activity(
                user=user,
                action='update',
                entity_type='user',
                entity_id=user.id,
                request=request
            )

            return Response({
                'message': 'تم تحديث الملف الشخصي بنجاح',
                'user': serializer.data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# GROUP 2: USER MANAGEMENT VIEWS
# ============================================================================

class UserViewSet(viewsets.ModelViewSet):
    """
    إدارة المستخدمين (Admin only)
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdmin]

    def perform_create(self, serializer):
        user = serializer.save()

        # تسجيل النشاط
        try:
            current_user = self.request.user
            if current_user and current_user.is_authenticated:
                log_activity(
                    user=current_user,
                    action='create',
                    entity_type='user',
                    entity_id=user.id,
                    request=self.request
                )
        except:
            pass

    @action(detail=True, methods=['post'])
    def force_logout(self, request, pk=None):
        """
        تسجيل خروج إجباري للموظف
        POST /api/agents/{id}/force_logout/
        """
        agent = self.get_object()
        user = agent.user

        # التحقق من الصلاحيات (مشرف أو مدير)
        if request.user.role not in ['admin', 'manager', 'supervisor', 'agent_supervisor']:
            return Response({
                'success': False,
                'error': 'غير مصرح لك بهذا الإجراء'
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            # تحديث حالة المستخدم
            user.is_online = False
            user.save(update_fields=['is_online'])

            # تحديث حالة الموظف
            agent.is_online = False
            agent.status = 'offline'
            
            # إذا كان في استراحة، إنهاؤها
            if agent.is_on_break:
                agent.is_on_break = False
                agent.break_started_at = None
            
            agent.save()

            # تسجيل النشاط
            try:
                log_activity(
                    user=request.user,
                    action='force_logout',
                    entity_type='agent',
                    entity_id=agent.id,
                    request=request
                )
            except:
                pass

            serializer = self.get_serializer(agent)
            return Response({
                'success': True,
                'data': serializer.data,
                'message': f'تم تسجيل خروج الموظف {user.full_name} بنجاح'
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """
        إعادة تعيين كلمة المرور للمستخدم
        POST /api/users/{id}/reset_password/
        
        Body:
        {
            "new_password": "newpassword123"
        }
        """
        user = self.get_object()

        new_password = request.data.get('new_password')
        if not new_password:
            return Response({
                'success': False,
                'error': 'كلمة المرور الجديدة مطلوبة'
            }, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 6:
            return Response({
                'success': False,
                'error': 'كلمة المرور يجب أن تكون على الأقل 6 أحرف'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user.set_password(new_password)
            user.save()

            try:
                log_activity(
                    user=request.user,
                    action='reset_password',
                    entity_type='user',
                    entity_id=user.id,
                    new_value=f'تم تغيير كلمة المرور للمستخدم {user.username}',
                    request=request
                )
            except:
                pass

            return Response({
                'success': True,
                'message': 'تم تغيير كلمة المرور بنجاح'
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': f'حدث خطأ أثناء تغيير كلمة المرور: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AgentViewSet(viewsets.ModelViewSet):
    """
    إدارة الموظفين
    """
    queryset = Agent.objects.select_related('user').all()
    serializer_class = AgentSerializer
    permission_classes = [IsAdmin]

    @action(detail=False, methods=['get'])
    def status_list(self, request):
        """
        Get status of all agents for real-time monitoring
        GET /api/agents/status_list/
        """
        agents = Agent.objects.select_related('user').all()
        data = []
        
        for agent in agents:
            status_display = 'Offline'
            status_class = 'badge-offline'
            
            if agent.is_online:
                if agent.status == 'available':
                    status_display = 'Online'
                    status_class = 'badge-online'
                else:
                    status_display = 'Busy'
                    status_class = 'badge-busy'
            
            data.append({
                'id': agent.id,
                'user_id': agent.user.id,
                'is_online': agent.is_online,
                'status': agent.status,
                'status_display': status_display,
                'status_class': status_class,
                'current_active_tickets': agent.current_active_tickets,
                'max_capacity': agent.max_capacity
            })
            
        return Response(data)

    @action(detail=False, methods=['get'])
    def activity_list(self, request):
        """
        Get detailed activity status of all agents for supervisor monitoring
        GET /api/agents/activity_list/
        """
        # Check permissions
        if request.user.role not in ['admin', 'manager', 'supervisor', 'agent_supervisor']:
             return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        agents = Agent.objects.select_related('user').filter(user__is_active=True).order_by('user__full_name')
        today = timezone.now().date()
        date_from_str = request.GET.get('date_from')
        date_to_str = request.GET.get('date_to')
        if date_from_str:
            try:
                date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            except ValueError:
                date_from = today
        else:
            date_from = today
        if date_to_str:
            try:
                date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            except ValueError:
                date_to = today
        else:
            date_to = today
        includes_today = (date_from <= today <= date_to)
        data = []

        for agent in agents:
            activities = ActivityLog.objects.filter(
                created_at__date__range=[date_from, date_to]
            ).filter(
                Q(user=agent.user, action__in=['login', 'logout']) |
                Q(entity_type='agent', entity_id=agent.id, action__in=['break_start', 'break_end', 'force_logout'])
            ).order_by('created_at')
            
            login_time = None
            logout_time = None
            breaks = []
            current_break_start = None
            
            for activity in activities:
                if activity.action == 'login':
                    if not login_time:
                        login_time = activity.created_at
                elif activity.action in ['logout', 'force_logout']:
                    logout_time = activity.created_at
                elif activity.action == 'break_start':
                    current_break_start = activity.created_at
                elif activity.action == 'break_end':
                    if current_break_start:
                        duration = (activity.created_at - current_break_start).total_seconds() / 60
                        breaks.append({
                            'start': current_break_start,
                            'end': activity.created_at,
                            'duration': int(duration)
                        })
                        current_break_start = None
            
            if includes_today and agent.is_on_break and agent.break_started_at:
                bs_date = agent.break_started_at.date()
                if date_from <= bs_date <= date_to:
                    duration = (timezone.now() - agent.break_started_at).total_seconds() / 60
                    breaks.append({
                        'start': agent.break_started_at,
                        'end': None,
                        'duration': int(duration),
                        'is_active': True
                    })
            
            # Format for JSON
            # Convert to local time before formatting
            login_str = timezone.localtime(login_time).strftime('%I:%M %p') if login_time else None
            logout_str = timezone.localtime(logout_time).strftime('%I:%M %p') if logout_time else None
            
            breaks_data = []
            for b in breaks:
                breaks_data.append({
                    'start': timezone.localtime(b['start']).strftime('%I:%M %p'),
                    'end': timezone.localtime(b['end']).strftime('%I:%M %p') if b['end'] else None,
                    'duration': b['duration'],
                    'is_active': b.get('is_active', False)
                })

            data.append({
                'id': agent.id,
                'user_id': agent.user.id,
                'full_name': agent.user.full_name,
                'username': agent.user.username,
                'is_online': agent.is_online,
                'status': agent.status,
                'is_on_break': agent.is_on_break,
                'login_time': login_str,
                'logout_time': logout_str,
                'breaks': breaks_data,
                'total_break_minutes': sum(b['duration'] for b in breaks)
            })
            
        return Response(data)

    @action(detail=False, methods=['post'])
    def create_with_user(self, request):
        """
        إنشاء موظف جديد مع حساب مستخدم
        POST /api/agents/create_with_user/

        Body:
        {
            "username": "agent1",
            "password": "password123",
            "first_name": "أحمد",
            "last_name": "محمد",
            "email": "agent1@example.com",
            "phone": "01234567890",
            "max_capacity": 15,
            "is_active": true
        }
        """
        from django.db import transaction

        # التحقق من البيانات المطلوبة
        username = request.data.get('username')
        password = request.data.get('password')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')

        # دعم full_name أيضاً للتوافق مع الكود القديم
        full_name = request.data.get('full_name')

        if not username or not password:
            return Response({
                'success': False,
                'error': 'اسم المستخدم وكلمة المرور مطلوبان'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not full_name and (not first_name or not last_name):
            return Response({
                'success': False,
                'error': 'الاسم الأول والأخير مطلوبان'
            }, status=status.HTTP_400_BAD_REQUEST)

        # بناء full_name من first_name و last_name إذا لم يكن موجوداً
        if not full_name:
            full_name = f"{first_name} {last_name}"

        try:
            with transaction.atomic():
                # ✅ الحصول على الدور (Role)
                role = request.data.get('role', 'agent')
                
                # التحقق من صحة الدور
                valid_roles = ['agent', 'admin', 'qa', 'supervisor', 'manager', 'agent_supervisor']
                if role not in valid_roles:
                    return Response({
                        'success': False,
                        'error': f'الدور غير صحيح. الأدوار المتاحة: {", ".join(valid_roles)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # ✅ الحصول على الإعدادات
                system_settings = SystemSettings.get_settings()
                default_max_capacity = system_settings.default_max_capacity
                
                # ✅ التحقق من max_capacity (للموظفين فقط)
                max_capacity = 0
                if role == 'agent':
                    requested_capacity = request.data.get('max_capacity')
                    if requested_capacity:
                        requested_capacity = int(requested_capacity)
                        if requested_capacity > default_max_capacity:
                            return Response({
                                'success': False,
                                'error': f'السعة القصوى للموظف لا يمكن أن تتجاوز {default_max_capacity} (الحد الأقصى المسموح)'
                            }, status=status.HTTP_400_BAD_REQUEST)
                        max_capacity = requested_capacity
                    else:
                        max_capacity = default_max_capacity
                
                # 1. إنشاء User
                user = User.objects.create(
                    username=username,
                    full_name=full_name,
                    email=request.data.get('email', ''),
                    phone=request.data.get('phone', ''),
                    role=role,  # ✅ استخدام الدور المحدد
                    is_active=request.data.get('is_active', True)
                )
                user.set_password(password)
                user.save()

                # 2. إنشاء Agent (للموظفين فقط) أو Admin (للأدوار الأخرى)
                if role == 'agent':
                    agent = Agent.objects.create(
                        user=user,
                        max_capacity=max_capacity,
                        status=request.data.get('status', 'offline'),
                        is_online=False,
                        # ✅ إضافة الصلاحيات
                        perm_no_choice=request.data.get('perm_no_choice', False),
                        perm_consultation=request.data.get('perm_consultation', False),
                        perm_complaint=request.data.get('perm_complaint', False),
                        perm_medicine=request.data.get('perm_medicine', False),
                        perm_follow_up=request.data.get('perm_follow_up', False)
                    )
                    entity_type = 'agent'
                    entity_id = agent.id
                    serializer = self.get_serializer(agent)
                else:
                    # إنشاء Admin record للأدوار الأخرى
                    admin = Admin.objects.create(
                        user=user,
                        can_manage_agents=True,
                        can_manage_templates=True,
                        can_view_analytics=True,
                        can_edit_global_templates=True
                    )
                    entity_type = 'admin'
                    entity_id = admin.id
                    # Return user data for non-agent roles
                    from .serializers import UserSerializer
                    serializer = UserSerializer(user)

                # 3. تسجيل النشاط
                try:
                    log_activity(
                        user=request.user,
                        action='create',
                        entity_type=entity_type,
                        entity_id=entity_id,
                        request=request
                    )
                except:
                    pass

                # 4. إرجاع البيانات
                role_names = {
                    'agent': 'الموظف',
                    'admin': 'المدير',
                    'qa': 'مراقب الجودة',
                    'supervisor': 'المشرف',
                    'manager': 'المدير العام',
                    'agent_supervisor': 'مشرف الموظفين'
                }
                return Response({
                    'success': True,
                    'data': serializer.data,
                    'message': f'تم إنشاء {role_names.get(role, "الحساب")} بنجاح'
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def available(self, request):
        """
        الحصول على الموظفين المتاحين
        GET /api/agents/available/
        """
        available_agents = Agent.objects.filter(
            is_online=True,
            status='available',
            current_active_tickets__lt=F('max_capacity')
        ).select_related('user')

        serializer = self.get_serializer(available_agents, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """
        الحصول على بيانات الموظف الحالي
        GET /api/agents/me/

        ✅ يمكن للموظف الحصول على بياناته الخاصة
        """
        if request.user.role != 'agent':
            return Response({
                'success': False,
                'error': 'هذا الـ Endpoint للموظفين فقط'
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            agent = request.user.agent
            serializer = self.get_serializer(agent)
            return Response(serializer.data)
        except Agent.DoesNotExist:
            return Response({
                'success': False,
                'error': 'لم يتم العثور على بيانات الموظف'
            }, status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated], url_path='me/set_online')
    def set_online_status(self, request):
        """
        تحديث حالة الموظف (online/offline)
        POST /api/agents/me/set_online/
        
        Body: { "is_online": true/false }
        """
        if request.user.role != 'agent':
            return Response({
                'success': False,
                'error': 'هذا الـ Endpoint للموظفين فقط'
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            agent = request.user.agent
            is_online = request.data.get('is_online', True)
            
            agent.is_online = is_online
            if is_online:
                agent.status = 'available'
            else:
                agent.status = 'offline'
            
            agent.save(update_fields=['is_online', 'status'])
            
            return Response({
                'success': True,
                'is_online': agent.is_online,
                'status': agent.status
            })
        except Agent.DoesNotExist:
            return Response({
                'success': False,
                'error': 'لم يتم العثور على بيانات الموظف'
            }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'])
    def kpi(self, request, pk=None):
        """
        الحصول على مؤشرات الأداء للموظف
        GET /api/agents/{id}/kpi/
        """
        agent = self.get_object()

        # حساب KPI لليوم الحالي
        kpi_data = calculate_agent_kpi(agent)

        return Response(kpi_data)

    @action(detail=True, methods=['patch'])
    def toggle_status(self, request, pk=None):
        """
        تفعيل/تعطيل الموظف
        PATCH /api/agents/{id}/toggle_status/

        Body:
        {
            "is_active": true/false
        }
        """
        agent = self.get_object()
        user = agent.user

        is_active = request.data.get('is_active')
        if is_active is None:
            return Response({
                'success': False,
                'error': 'الحقل is_active مطلوب'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user.is_active = is_active
            user.save()

            # إذا تم تعطيل الموظف، تحديث حالته
            if not is_active:
                agent.is_online = False
                agent.status = 'offline'
                agent.save()

            # تسجيل النشاط
            try:
                log_activity(
                    user=request.user,
                    action='update',
                    entity_type='agent',
                    entity_id=agent.id,
                    request=request
                )
            except:
                pass

            serializer = self.get_serializer(agent)
            return Response({
                'success': True,
                'data': serializer.data,
                'message': f'تم {"تفعيل" if is_active else "تعطيل"} الموظف بنجاح'
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def take_break(self, request, pk=None):
        """
        بدء استراحة للموظف
        POST /api/agents/{id}/take_break/

        ✅ الموظف لن يستقبل تذاكر جديدة أثناء الاستراحة
        ✅ يمكن للموظف أو الأدمن استخدام هذا الـ Endpoint
        """
        try:
            agent = self.get_object()
        except Agent.DoesNotExist:
            return Response({
                'success': False,
                'error': 'لم يتم العثور على الموظف'
            }, status=status.HTTP_404_NOT_FOUND)

        # التحقق من الصلاحيات: الموظف نفسه أو أدمن
        try:
            if request.user.role == 'agent' and request.user.agent.id != agent.id:
                return Response({
                    'success': False,
                    'error': 'غير مصرح لك بهذا الإجراء'
                }, status=status.HTTP_403_FORBIDDEN)
        except AttributeError:
            return Response({
                'success': False,
                'error': 'المستخدم الحالي ليس موظفاً'
            }, status=status.HTTP_403_FORBIDDEN)

        # التحقق من أن الموظف ليس في استراحة بالفعل
        if agent.is_on_break:
            return Response({
                'success': False,
                'error': 'الموظف في استراحة بالفعل'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # ✅ تحويل التذاكر المفتوحة لموظفين آخرين
            from .utils import get_available_agent
            open_tickets = Ticket.objects.filter(
                current_agent=agent,
                status='open'
            )
            
            transferred_count = 0
            for ticket in open_tickets:
                # البحث عن موظف متاح
                new_agent = get_available_agent()
                if new_agent:
                    # تحويل التذكرة
                    ticket.current_agent = new_agent
                    ticket.save()
                    
                    # إنشاء سجل التحويل
                    TicketTransferLog.objects.create(
                        ticket=ticket,
                        from_agent=agent,
                        to_agent=new_agent,
                        reason='تحويل تلقائي - الموظف في استراحة',
                        transferred_by=request.user
                    )
                    
                    transferred_count += 1
                    
                    # تحديث عدد التذاكر للموظف الجديد
                    new_agent.current_active_tickets = Ticket.objects.filter(
                        current_agent=new_agent,
                        status='open'
                    ).count()
                    if new_agent.current_active_tickets >= new_agent.max_capacity:
                        new_agent.status = 'busy'
                    new_agent.save()
            
            # تحديث حالة الموظف
            agent.is_on_break = True
            agent.break_started_at = timezone.now()
            agent.status = 'on_break'
            agent.current_active_tickets = 0  # ✅ تصفير عدد التذاكر
            agent.save()

            # تسجيل النشاط
            try:
                log_activity(
                    user=request.user,
                    action='break_start',
                    entity_type='agent',
                    entity_id=agent.id,
                    request=request
                )
            except Exception as log_error:
                # Log the error but don't fail the request
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to log break_start activity: {str(log_error)}")

            serializer = self.get_serializer(agent)
            message = f'تم بدء الاستراحة بنجاح. تم تحويل {transferred_count} تذكرة لموظفين آخرين.' if transferred_count > 0 else 'تم بدء الاستراحة بنجاح. لن تستقبل تذاكر جديدة حتى تنهي الاستراحة.'
            
            return Response({
                'success': True,
                'data': serializer.data,
                'message': message,
                'transferred_tickets': transferred_count
            })

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in take_break for agent {agent.id}: {str(e)}")
            return Response({
                'success': False,
                'error': f'حدث خطأ أثناء بدء الاستراحة: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def end_break(self, request, pk=None):
        """
        إنهاء استراحة الموظف
        POST /api/agents/{id}/end_break/

        ✅ الموظف سيعود لاستقبال التذاكر الجديدة
        ✅ يمكن للموظف أو الأدمن استخدام هذا الـ Endpoint
        """
        try:
            agent = self.get_object()
        except Agent.DoesNotExist:
            return Response({
                'success': False,
                'error': 'لم يتم العثور على الموظف'
            }, status=status.HTTP_404_NOT_FOUND)

        # التحقق من الصلاحيات: الموظف نفسه أو أدمن
        try:
            if request.user.role == 'agent' and request.user.agent.id != agent.id:
                return Response({
                    'success': False,
                    'error': 'غير مصرح لك بهذا الإجراء'
                }, status=status.HTTP_403_FORBIDDEN)
        except AttributeError:
            return Response({
                'success': False,
                'error': 'المستخدم الحالي ليس موظفاً'
            }, status=status.HTTP_403_FORBIDDEN)

        # التحقق من أن الموظف في استراحة
        if not agent.is_on_break:
            return Response({
                'success': False,
                'error': 'الموظف ليس في استراحة'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            from .models import AgentBreakSession

            # حساب مدة الاستراحة
            break_minutes = 0
            break_seconds = 0
            break_start_time = agent.break_started_at

            if agent.break_started_at:
                break_duration = timezone.now() - agent.break_started_at
                break_seconds = int(break_duration.total_seconds())
                break_minutes = int(break_seconds / 60)
                agent.total_break_minutes_today += break_minutes

                # ✅ إنشاء سجل جلسة الاستراحة
                AgentBreakSession.objects.create(
                    agent=agent,
                    break_start_time=break_start_time,
                    break_end_time=timezone.now(),
                    break_duration_seconds=break_seconds
                )

            # تحديث حالة الموظف
            agent.is_on_break = False
            agent.break_started_at = None

            # تحديد الحالة بناءً على عدد التذاكر
            if agent.current_active_tickets >= agent.max_capacity:
                agent.status = 'busy'
            else:
                agent.status = 'available'

            agent.save()

            # تسجيل النشاط
            try:
                log_activity(
                    user=request.user,
                    action='break_end',
                    entity_type='agent',
                    entity_id=agent.id,
                    request=request
                )
            except Exception as log_error:
                # Log the error but don't fail the request
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to log break_end activity: {str(log_error)}")

            serializer = self.get_serializer(agent)
            return Response({
                'success': True,
                'data': serializer.data,
                'message': f'تم إنهاء الاستراحة بنجاح. مدة الاستراحة: {break_minutes} دقيقة. يمكنك الآن استقبال التذاكر.'
            })

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in end_break for agent {agent.id}: {str(e)}")
            return Response({
                'success': False,
                'error': f'حدث خطأ أثناء إنهاء الاستراحة: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def force_logout(self, request, pk=None):
        """
        تسجيل خروج إجباري للموظف
        POST /api/agents/{id}/force_logout/
        """
        agent = self.get_object()
        user = agent.user

        # التحقق من الصلاحيات (مشرف أو مدير)
        if request.user.role not in ['admin', 'manager', 'supervisor', 'agent_supervisor']:
            return Response({
                'success': False,
                'error': 'غير مصرح لك بهذا الإجراء'
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            # تحديث حالة المستخدم
            user.is_online = False
            user.save(update_fields=['is_online'])

            # تحديث حالة الموظف
            agent.is_online = False
            agent.status = 'offline'
            
            # إذا كان في استراحة، إنهاؤها
            if agent.is_on_break:
                agent.is_on_break = False
                agent.break_started_at = None
            
            agent.save()

            # تسجيل النشاط
            try:
                log_activity(
                    user=request.user,
                    action='force_logout',
                    entity_type='agent',
                    entity_id=agent.id,
                    request=request
                )
            except:
                pass

            serializer = self.get_serializer(agent)
            return Response({
                'success': True,
                'data': serializer.data,
                'message': f'تم تسجيل خروج الموظف {user.full_name} بنجاح'
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """
        إعادة تعيين كلمة المرور للموظف
        POST /api/agents/{id}/reset_password/

        Body:
        {
            "new_password": "newpassword123"
        }
        """
        agent = self.get_object()
        user = agent.user

        new_password = request.data.get('new_password')
        if not new_password:
            return Response({
                'success': False,
                'error': 'كلمة المرور الجديدة مطلوبة'
            }, status=status.HTTP_400_BAD_REQUEST)

        # التحقق من طول كلمة المرور
        if len(new_password) < 6:
            return Response({
                'success': False,
                'error': 'كلمة المرور يجب أن تكون على الأقل 6 أحرف'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # تغيير كلمة المرور
            user.set_password(new_password)
            user.save()

            # تسجيل النشاط
            try:
                log_activity(
                    user=request.user,
                    action='update',
                    entity_type='agent',
                    entity_id=agent.id,
                    details={'action': 'password_reset'},
                    request=request
                )
            except:
                pass

            return Response({
                'success': True,
                'message': f'تم تغيير كلمة المرور للموظف {user.full_name or user.username} بنجاح'
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# GROUP 3: CUSTOMER MANAGEMENT VIEWS
# ============================================================================

class CustomerViewSet(viewsets.ModelViewSet):
    """
    إدارة العملاء
    """
    queryset = Customer.objects.prefetch_related('tags', 'notes_list').all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAdminOrAgent]

    def get_queryset(self):
        queryset = super().get_queryset()

        # البحث
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(email__icontains=search)
            )

        # التصفية حسب النوع
        customer_type = self.request.query_params.get('type', None)
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)

        # التصفية حسب الحظر
        is_blocked = self.request.query_params.get('blocked', None)
        if is_blocked is not None:
            queryset = queryset.filter(is_blocked=is_blocked.lower() == 'true')

        return queryset

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        """
        حظر عميل
        POST /api/customers/{id}/block/
        """
        customer = self.get_object()
        customer.is_blocked = True
        customer.save()

        # تسجيل النشاط
        try:
            user = request.user
            if user and user.is_authenticated:
                log_activity(
                    user=user,
                    action='block',
                    entity_type='customer',
                    entity_id=customer.id,
                    request=request
                )
        except:
            pass

        return Response({
            'message': 'تم حظر العميل بنجاح'
        })

    @action(detail=True, methods=['post'])
    def unblock(self, request, pk=None):
        """
        إلغاء حظر عميل
        POST /api/customers/{id}/unblock/
        """
        customer = self.get_object()
        customer.is_blocked = False
        customer.save()

        # تسجيل النشاط
        try:
            user = request.user
            if user and user.is_authenticated:
                log_activity(
                    user=user,
                    action='unblock',
                    entity_type='customer',
                    entity_id=customer.id,
                    request=request
                )
        except:
            pass

        return Response({
            'message': 'تم إلغاء حظر العميل بنجاح'
        })


# ============================================================================
# GROUP 4: TICKET MANAGEMENT VIEWS (CORE)
# ============================================================================

class TicketViewSet(viewsets.ModelViewSet):
    """
    إدارة التذاكر (قلب النظام)
    """
    queryset = Ticket.objects.select_related(
        'customer', 'assigned_agent__user', 'current_agent__user'
    ).prefetch_related('state_changes', 'transfers').all()
    serializer_class = TicketSerializer
    permission_classes = [IsAdminOrAgent]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user or not user.is_authenticated:
            return queryset.none()

        # الموظفون: التذاكر المعينة لهم + التذاكر المغلقة للعملاء الذين يشاهدونها
        if user.role == 'agent':
            try:
                agent = user.agent
                
                # التصفية حسب العميل (إذا كان محدداً في المعاملات)
                customer_id = self.request.query_params.get('customer', None)
                
                if customer_id:
                    # إذا كان يشاهد محادثة عميل معين، اعرض:
                    # 1. التذاكر المفتوحة المعينة له
                    # 2. جميع التذاكر المغلقة لهذا العميل (حتى لو لم تكن معينة له)
                    queryset = queryset.filter(
                        Q(customer_id=customer_id) & 
                        (
                            Q(assigned_agent=agent) | 
                            Q(current_agent=agent) | 
                            Q(status='closed')
                        )
                    )
                else:
                    # عرض عام: فقط التذاكر المعينة له
                    queryset = queryset.filter(
                        Q(assigned_agent=agent) | Q(current_agent=agent)
                    )
            except:
                return queryset.none()

        # المديرون: جميع التذاكر
        # (لا حاجة لتصفية)
        else:
            # التصفية حسب العميل للمديرين
            customer_id = self.request.query_params.get('customer', None)
            if customer_id:
                queryset = queryset.filter(customer_id=customer_id)

        # التصفية حسب الحالة
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # التصفية حسب الأولوية
        priority = self.request.query_params.get('priority', None)
        if priority:
            queryset = queryset.filter(priority=priority)

        # التصفية حسب التأخير
        is_delayed = self.request.query_params.get('delayed', None)
        if is_delayed is not None:
            queryset = queryset.filter(is_delayed=is_delayed.lower() == 'true')

        # البحث
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(ticket_number__icontains=search) |
                Q(customer__name__icontains=search) |
                Q(customer__phone_number__icontains=search)
            )

        return queryset.order_by('-created_at')

    def retrieve(self, request, *args, **kwargs):
        """
        استرجاع تذكرة محددة - مع التحقق من الصلاحيات
        """
        instance = self.get_object()

        # التحقق من صلاحية الوصول
        user = request.user
        if user.role == 'agent':
            try:
                agent = user.agent
                # تحقق من أن التذكرة معينة لهذا الموظف
                if instance.assigned_agent != agent and instance.current_agent != agent:
                    return Response(
                        {'detail': 'ليس لديك صلاحية الوصول لهذه التذكرة'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except:
                return Response(
                    {'detail': 'خطأ في التحقق من الصلاحيات'},
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """
        إنشاء تذكرة جديدة مع توزيع تلقائي
        """
        # توليد رقم التذكرة
        ticket_number = generate_ticket_number()

        # البحث عن موظف متاح
        agent = get_available_agent()

        if not agent:
            # لا يوجد موظف متاح
            ticket = serializer.save(
                ticket_number=ticket_number,
                status='open'
            )
        else:
            # تعيين التذكرة للموظف
            ticket = serializer.save(
                ticket_number=ticket_number,
                assigned_agent=agent,
                current_agent=agent,
                status='open'
            )

            # تحديث عدد التذاكر النشطة
            agent.current_active_tickets += 1
            if agent.current_active_tickets >= agent.max_capacity:
                agent.status = 'busy'
            agent.save()

        # تسجيل النشاط
        try:
            user = self.request.user
            if user and user.is_authenticated:
                log_activity(
                    user=user,
                    action='create',
                    entity_type='ticket',
                    entity_id=ticket.id,
                    request=self.request
                )
        except:
            pass

        # تحديث KPI للموظف تلقائياً
        if agent:
            try:
                from .utils import calculate_agent_kpi
                calculate_agent_kpi(agent)
            except:
                pass

    @action(detail=False, methods=['post'])
    def close_all_open(self, request):
        """
        إغلاق جميع التذاكر المفتوحة
        POST /api/tickets/close_all_open/
        """
        # التحقق من أن المستخدم admin
        if request.user.role != 'admin':
            return Response({
                'error': 'ليس لديك صلاحية لتنفيذ هذا الإجراء'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # الحصول على جميع التذاكر المفتوحة
        open_tickets = Ticket.objects.filter(status__in=['open', 'pending'])
        count = open_tickets.count()
        
        if count == 0:
            return Response({
                'message': 'لا توجد تذاكر مفتوحة',
                'closed_count': 0
            })
        
        # إغلاق جميع التذاكر
        for ticket in open_tickets:
            old_status = ticket.status
            ticket.status = 'closed'
            ticket.closed_at = timezone.now()
            ticket.closure_reason = 'إغلاق جماعي بواسطة المدير'
            ticket.closed_by_user = request.user
            
            # حساب وقت المعالجة
            if ticket.created_at:
                handling_time = timezone.now() - ticket.created_at
                ticket.handling_time_seconds = int(handling_time.total_seconds())
            
            ticket.save()
            
            # تحديث عدد التذاكر النشطة للموظف
            if ticket.current_agent:
                agent = ticket.current_agent
                agent.current_active_tickets = max(0, agent.current_active_tickets - 1)
                if agent.current_active_tickets < agent.max_capacity:
                    agent.status = 'available'
                agent.save()
            
            # تسجيل تغيير الحالة
            TicketStateLog.objects.create(
                ticket=ticket,
                changed_by=request.user,
                old_state=old_status,
                new_state='closed',
                reason='إغلاق جماعي'
            )
        
        # تسجيل النشاط
        try:
            log_activity(
                user=request.user,
                action='bulk_close_tickets',
                entity_type='ticket',
                entity_id=None,
                request=request
            )
        except Exception as e:
            # تجاهل أخطاء التسجيل
            pass
        
        return Response({
            'success': True,
            'message': f'تم إغلاق {count} تذكرة بنجاح',
            'closed_count': count
        })
    
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """
        إغلاق تذكرة
        POST /api/tickets/{id}/close/
        """
        ticket = self.get_object()

        if ticket.status == 'closed':
            return Response({
                'error': 'التذكرة مغلقة بالفعل'
            }, status=status.HTTP_400_BAD_REQUEST)

        # إغلاق التذكرة
        old_status = ticket.status
        ticket.status = 'closed'
        ticket.closed_at = timezone.now()
        ticket.closure_reason = request.data.get('reason', '')

        user = request.user
        if user and user.is_authenticated:
            ticket.closed_by_user = user

        # حساب وقت المعالجة
        if ticket.created_at:
            handling_time = timezone.now() - ticket.created_at
            ticket.handling_time_seconds = int(handling_time.total_seconds())

        ticket.save()

        # تحديث عدد التذاكر النشطة للموظف
        if ticket.current_agent:
            agent = ticket.current_agent
            agent.current_active_tickets = max(0, agent.current_active_tickets - 1)

            # تحديث الحالة
            if agent.current_active_tickets < agent.max_capacity:
                agent.status = 'available'

            agent.save()

        # تسجيل تغيير الحالة
        try:
            user = request.user
            if user and user.is_authenticated:
                TicketStateLog.objects.create(
                    ticket=ticket,
                    changed_by=user,
                    old_state=old_status,
                    new_state='closed',
                    reason=ticket.closure_reason
                )

                log_activity(
                    user=user,
                    action='close',
                    entity_type='ticket',
                    entity_id=ticket.id,
                    old_value=old_status,
                    new_value='closed',
                    request=request
                )
        except:
            pass

        # تحديث KPI للموظف تلقائياً
        if ticket.assigned_agent:
            try:
                from .utils import calculate_agent_kpi
                calculate_agent_kpi(ticket.assigned_agent)
            except:
                pass

        return Response({
            'message': 'تم إغلاق التذكرة بنجاح'
        })

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        """
        نقل تذكرة لموظف آخر
        POST /api/tickets/{id}/transfer/
        """
        ticket = self.get_object()
        new_agent_id = request.data.get('agent_id')
        reason = request.data.get('reason', '')

        if not new_agent_id:
            return Response({
                'error': 'يرجى تحديد الموظف'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_agent = Agent.objects.get(id=new_agent_id)
        except Agent.DoesNotExist:
            return Response({
                'error': 'الموظف غير موجود'
            }, status=status.HTTP_404_NOT_FOUND)

        # التحقق من سعة الموظف
        if new_agent.current_active_tickets >= new_agent.max_capacity:
            return Response({
                'error': 'الموظف وصل للحد الأقصى من التذاكر'
            }, status=status.HTTP_400_BAD_REQUEST)

        # نقل التذكرة
        old_agent = ticket.current_agent
        ticket.current_agent = new_agent
        ticket.save()

        # تحديث عدد التذاكر
        if old_agent:
            old_agent.current_active_tickets = max(0, old_agent.current_active_tickets - 1)
            if old_agent.current_active_tickets < old_agent.max_capacity:
                old_agent.status = 'available'
            old_agent.save()

        new_agent.current_active_tickets += 1
        if new_agent.current_active_tickets >= new_agent.max_capacity:
            new_agent.status = 'busy'
        new_agent.save()

        # تسجيل النقل
        try:
            user = request.user
            if user and user.is_authenticated:
                TicketTransferLog.objects.create(
                    ticket=ticket,
                    from_agent=old_agent,
                    to_agent=new_agent,
                    transferred_by=user,
                    reason=reason
                )

                log_activity(
                    user=user,
                    action='transfer',
                    entity_type='ticket',
                entity_id=ticket.id,
                request=request
            )
        except:
            pass

        # تحديث KPI للموظفين (القديم والجديد)
        try:
            from .utils import calculate_agent_kpi
            if old_agent:
                calculate_agent_kpi(old_agent)
            calculate_agent_kpi(new_agent)
        except:
            pass

        return Response({
            'message': 'تم نقل التذكرة بنجاح'
        })


# ============================================================================
# GROUP 9: CONVERSATIONS VIEWS (Real-time Updates)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversations_list_api(request):
    """
    قائمة المحادثات للموظف (JSON)
    GET /api/conversations/
    
    يُستخدم للتحديث التلقائي (Auto-Refresh) في صفحة المحادثات
    """
    if request.user.role != 'agent':
        return Response({
            'error': 'هذا الـ Endpoint للموظفين فقط'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        return Response({
            'error': 'الموظف غير موجود'
        }, status=status.HTTP_404_NOT_FOUND)
    
    from .utils import update_ticket_delay_status
    
    all_open_tickets = Ticket.objects.filter(status='open')
    for ticket in all_open_tickets:
        update_ticket_delay_status(ticket)
    
    # الحصول على التذاكر المفتوحة المعينة لهذا الموظف فقط
    all_tickets = Ticket.objects.filter(
        current_agent=agent,
        status='open'
    ).select_related('customer').order_by('-last_message_at')
    
    # تجميع التذاكر حسب العميل
    customers_map = {}
    for ticket in all_tickets:
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
                'customer_id': ticket.customer.id,
                'customer_name': ticket.customer.name or 'عميل',
                'customer_phone': ticket.customer.phone_number,
                'customer_avatar': (ticket.customer.name or 'ع')[0].upper(),
                'tickets': [],
                'ticket_ids': [],
                'last_message_time': ticket.last_message_at.isoformat() if ticket.last_message_at else None,  # ✅ اسم متطابق
                'last_message_text': '',
                'is_delayed': False,  # ✅ اسم متطابق
                'status': ticket.status,
                'unread_count': unread_count
            }
        
        customers_map[customer_id]['tickets'].append({
            'id': ticket.id,
            'ticket_number': ticket.ticket_number,
            'status': ticket.status,
            'priority': ticket.priority,
            'is_delayed': ticket.is_delayed
        })
        customers_map[customer_id]['ticket_ids'].append(ticket.id)
        
        if ticket.is_delayed:
            customers_map[customer_id]['is_delayed'] = True  # ✅ اسم متطابق
        
        # تحديث آخر رسالة
        if ticket.last_message_at:
            current_last = customers_map[customer_id]['last_message_time']  # ✅ اسم متطابق
            if not current_last or ticket.last_message_at.isoformat() > current_last:
                customers_map[customer_id]['last_message_time'] = ticket.last_message_at.isoformat()  # ✅ اسم متطابق
                
                # الحصول على آخر رسالة
                try:
                    last_message = Message.objects.filter(ticket=ticket).order_by('-created_at').first()
                    if last_message:
                        customers_map[customer_id]['last_message_text'] = last_message.message_text[:50] or '📷 صورة'
                except:
                    pass
    
    # تحويل الخريطة إلى قائمة وترتيبها
    conversations = sorted(
        customers_map.values(),
        key=lambda x: x['last_message_time'] if x['last_message_time'] else '',  # ✅ اسم متطابق
        reverse=True
    )
    
    return Response({
        'conversations': conversations,
        'total': len(conversations)
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def transfer_ticket_api(request):
    """
    تحويل التذكرة لموظف آخر
    POST /api/transfer-ticket/
    
    البيانات المطلوبة:
    - customer_id: معرف العميل
    - to_agent_id: معرف الموظف المحول إليه
    - note: ملاحظة التحويل (اختيارية)
    """
    if request.user.role != 'agent':
        return Response({
            'error': 'هذا الـ Endpoint للموظفين فقط'
        }, status=status.HTTP_403_FORBIDDEN)
    
    try:
        from_agent = Agent.objects.get(user=request.user)
    except Agent.DoesNotExist:
        return Response({
            'error': 'الموظف غير موجود'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # التحقق من البيانات المطلوبة
    customer_id = request.data.get('customer_id')
    to_agent_id = request.data.get('to_agent_id')
    note = request.data.get('note', '')
    
    if not customer_id or not to_agent_id:
        return Response({
            'error': 'معرف العميل ومعرف الموظف المحول إليه مطلوبان'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        customer = Customer.objects.get(id=customer_id)
        to_agent = Agent.objects.get(id=to_agent_id)
    except Customer.DoesNotExist:
        return Response({
            'error': 'العميل غير موجود'
        }, status=status.HTTP_404_NOT_FOUND)
    except Agent.DoesNotExist:
        return Response({
            'error': 'الموظف المحول إليه غير موجود'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # التحقق من وجود تذاكر مفتوحة للعميل مع الموظف الحالي
    # نستخدم current_agent لأنه اللي شغال على التذكرة دلوقتي
    open_tickets = Ticket.objects.filter(
        customer=customer,
        current_agent=from_agent,
        status='open'
    )
    
    if not open_tickets.exists():
        return Response({
            'error': 'لا توجد تذاكر مفتوحة للتحويل لهذا العميل'
        }, status=status.HTTP_404_NOT_FOUND)
    
    # تحويل جميع التذاكر المفتوحة
    transferred_tickets = []
    for ticket in open_tickets:
        # تحديث التذكرة
        ticket.current_agent = to_agent
        ticket.save()
        
        # إنشاء سجل التحويل
        transfer_log = TicketTransferLog.objects.create(
            ticket=ticket,
            from_agent=from_agent,
            to_agent=to_agent,
            reason=note if note else 'تحويل من الموظف',
            transferred_by=request.user
        )
        
        transferred_tickets.append({
            'ticket_id': ticket.id,
            'ticket_number': ticket.ticket_number
        })
    
    # تحديث عدد التذاكر للموظفين
    from_agent.current_active_tickets = Ticket.objects.filter(
        current_agent=from_agent,
        status='open'
    ).count()
    if from_agent.current_active_tickets < from_agent.max_capacity:
        from_agent.status = 'available'
    from_agent.save()
    
    to_agent.current_active_tickets = Ticket.objects.filter(
        current_agent=to_agent,
        status='open'
    ).count()
    if to_agent.current_active_tickets >= to_agent.max_capacity:
        to_agent.status = 'busy'
    to_agent.save()
    
    return Response({
        'success': True,
        'message': f'تم تحويل {len(transferred_tickets)} تذكرة بنجاح',
        'transferred_tickets': transferred_tickets,
        'to_agent': to_agent.user.full_name,
        'to_agent_id': to_agent.id
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def available_agents_api(request):
    """
    قائمة الموظفين المتاحين للتحويل
    GET /api/available-agents/
    """
    try:
        # Debug info
        print(f"DEBUG: User authenticated: {request.user.is_authenticated}")
        print(f"DEBUG: User: {request.user}")
        print(f"DEBUG: User role: {getattr(request.user, 'role', 'No role')}")
        
        if not hasattr(request.user, 'role') or request.user.role != 'agent':
            return Response({
                'error': 'هذا الـ Endpoint للموظفين فقط',
                'debug': f'User role: {getattr(request.user, "role", "No role attribute")}'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # جلب جميع الموظفين النشطين ما عدا الموظف الحالي
        # ✅ استبعاد الموظفين في استراحة أو غير متصلين
        agents = Agent.objects.filter(
            user__is_active=True,
            is_online=True,  # ✅ فقط المتصلين
            is_on_break=False  # ✅ ليسوا في استراحة
        ).exclude(user=request.user).select_related('user')
        
        print(f"DEBUG: Found {agents.count()} available agents (online and not on break)")
        
        agents_list = []
        for agent in agents:
            # حساب عدد العملاء الذين يتحدث معهم هذا الموظف
            client_count = Ticket.objects.filter(
                current_agent=agent,
                status='open'
            ).values('customer').distinct().count()
            
            agents_list.append({
                'id': agent.id,
                'name': agent.user.full_name,
                'username': agent.user.username,
                'is_online': agent.is_online,
                'status': agent.status,
                'is_on_break': agent.is_on_break,
                'client_count': client_count,
                'current_active_tickets': agent.current_active_tickets,
                'max_capacity': agent.max_capacity
            })
        
        return Response({
            'agents': agents_list,
            'debug': f'Total agents found: {len(agents_list)}'
        })
        
    except Exception as e:
        print(f"DEBUG: Exception in available_agents_api: {str(e)}")
        return Response({
            'error': f'حدث خطأ في النظام: {str(e)}',
            'debug': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def debug_agents_api(request):
    """
    Debug endpoint to check agents in database
    GET /api/debug-agents/
    """
    try:
        total_users = User.objects.count()
        total_agents = Agent.objects.count()
        active_agents = Agent.objects.filter(user__is_active=True).count()
        
        agents = Agent.objects.all().select_related('user')[:10]  # First 10 agents
        agents_list = []
        for agent in agents:
            agents_list.append({
                'id': agent.id,
                'name': agent.user.full_name,
                'username': agent.user.username,
                'status': agent.status,
                'user_active': agent.user.is_active,
                'role': agent.user.role
            })
        
        return Response({
            'total_users': total_users,
            'total_agents': total_agents,
            'active_agents': active_agents,
            'agents_sample': agents_list,
            'current_user': str(request.user) if request.user.is_authenticated else 'Anonymous'
        })
        
    except Exception as e:
        return Response({
            'error': str(e),
            'debug': 'Exception in debug_agents_api'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def all_conversations_api(request):
    """
    جميع المحادثات من جميع الموظفين (مفتوحة ومغلقة)
    GET /api/all-conversations/
    
    Parameters:
    - search: البحث في رقم الهاتف أو نص الرسائل
    - status: تصفية حسب حالة التذكرة (open, closed, delayed)
    - agent_id: تصفية حسب الموظف
    - limit: عدد النتائج (افتراضي: 50)
    - offset: نقطة البداية (افتراضي: 0)
    """
    try:
        from .utils import update_ticket_delay_status
        
        all_open_tickets = Ticket.objects.filter(status='open')
        for ticket in all_open_tickets:
            update_ticket_delay_status(ticket)
        
        # المعاملات
        search_query = request.GET.get('search', '').strip()
        status_filter = request.GET.get('status', '')
        agent_id = request.GET.get('agent_id', '')
        limit = int(request.GET.get('limit', 50))
        offset = int(request.GET.get('offset', 0))
        
        # بناء الاستعلام الأساسي
        tickets_query = Ticket.objects.select_related(
            'customer', 'assigned_agent__user', 'current_agent__user'
        )
        
        # تصفية حسب حالة التذكرة
        if status_filter:
            tickets_query = tickets_query.filter(status=status_filter)
        
        # تصفية حسب الموظف
        if agent_id:
            try:
                agent_id = int(agent_id)
                tickets_query = tickets_query.filter(
                    Q(assigned_agent_id=agent_id) | Q(current_agent_id=agent_id)
                )
            except ValueError:
                pass
        
        # البحث
        search_in_messages = False
        if search_query:
            # Check if search matches phone, name, or ticket number first
            basic_matches = tickets_query.filter(
                Q(customer__phone_number__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(ticket_number__icontains=search_query)
            )
            
            # Check if search matches message content
            message_matches = tickets_query.filter(
                Q(messages__message_text__icontains=search_query)
            )
            
            # Combine both searches
            tickets_query = (basic_matches | message_matches).distinct()
            
            # Flag to indicate we're searching in messages
            search_in_messages = message_matches.exists()
        
        # ترتيب حسب آخر رسالة
        tickets_query = tickets_query.order_by('-last_message_at', '-created_at')
        
        # العدد الإجمالي
        total_count = tickets_query.count()
        
        # تطبيق الحد والإزاحة
        tickets = tickets_query[offset:offset + limit]
        
        # تجميع النتائج
        conversations = []
        for ticket in tickets:
            # آخر رسالة
            last_message = Message.objects.filter(ticket=ticket).order_by('-created_at').first()
            last_message_text = ''
            if last_message:
                if last_message.message_text:
                    last_message_text = last_message.message_text[:100]
                else:
                    last_message_text = f"📷 {last_message.message_type}"
            
            # البحث عن الرسائل المطابقة إذا كان البحث في النصوص
            matching_messages = []
            if search_query and search_in_messages:
                matching_msgs = Message.objects.filter(
                    ticket=ticket,
                    message_text__icontains=search_query
                ).order_by('-created_at')[:3]  # أحدث 3 رسائل مطابقة
                
                for msg in matching_msgs:
                    if msg.message_text:
                        matching_messages.append({
                            'id': msg.id,
                            'text': msg.message_text,
                            'sender_type': msg.sender_type,
                            'created_at': msg.created_at.isoformat(),
                        })
            
            # عدد الرسائل غير المقروءة
            unread_count = Message.objects.filter(
                ticket=ticket,
                sender_type='customer',
                is_read=False
            ).count()
            
            # بيانات الموظف المعين
            assigned_agent_info = None
            if ticket.assigned_agent:
                assigned_agent_info = {
                    'id': ticket.assigned_agent.id,
                    'name': ticket.assigned_agent.user.full_name,
                    'username': ticket.assigned_agent.user.username,
                    'status': ticket.assigned_agent.status,
                    'is_online': ticket.assigned_agent.is_online
                }
            
            # بيانات الموظف الحالي
            current_agent_info = None
            if ticket.current_agent and ticket.current_agent != ticket.assigned_agent:
                current_agent_info = {
                    'id': ticket.current_agent.id,
                    'name': ticket.current_agent.user.full_name,
                    'username': ticket.current_agent.user.username,
                    'status': ticket.current_agent.status,
                    'is_online': ticket.current_agent.is_online
                }
            
            conversation_data = {
                'ticket_id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'status': ticket.status,
                'priority': ticket.priority,
                'category': ticket.category,
                'category_arabic': ticket.get_category_arabic(),
                'is_delayed': ticket.is_delayed,
                'delay_minutes': ticket.total_delay_minutes,
                'customer': {
                    'id': ticket.customer.id,
                    'name': ticket.customer.name or 'عميل',
                    'phone_number': ticket.customer.phone_number,
                    'customer_type': ticket.customer.customer_type,
                    'avatar': (ticket.customer.name or 'ع')[0].upper(),
                },
                'assigned_agent': assigned_agent_info,
                'current_agent': current_agent_info,
                'messages_count': ticket.messages_count,
                'unread_count': unread_count,
                'last_message': {
                    'text': last_message_text,
                    'time': ticket.last_message_at.isoformat() if ticket.last_message_at else None,
                    'sender_type': last_message.sender_type if last_message else None,
                },
                'timestamps': {
                    'created_at': ticket.created_at.isoformat(),
                    'first_response_at': ticket.first_response_at.isoformat() if ticket.first_response_at else None,
                    'last_customer_message_at': ticket.last_customer_message_at.isoformat() if ticket.last_customer_message_at else None,
                    'last_agent_message_at': ticket.last_agent_message_at.isoformat() if ticket.last_agent_message_at else None,
                    'closed_at': ticket.closed_at.isoformat() if ticket.closed_at else None,
                },
                'metrics': {
                    'response_time_seconds': ticket.response_time_seconds,
                    'handling_time_seconds': ticket.handling_time_seconds,
                },
                'search_matches': {
                    'query': search_query if search_query else '',
                    'in_messages': search_in_messages,
                    'matching_messages': matching_messages
                }
            }
            conversations.append(conversation_data)
        
        return Response({
            'conversations': conversations,
            'pagination': {
                'total': total_count,
                'limit': limit,
                'offset': offset,
                'has_more': offset + limit < total_count,
                'next_offset': offset + limit if offset + limit < total_count else None
            },
            'filters': {
                'search': search_query,
                'status': status_filter,
                'agent_id': agent_id
            }
        })
        
    except Exception as e:
        return Response({
            'error': f'خطأ في جلب المحادثات: {str(e)}',
            'debug': 'Exception in all_conversations_api'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



# ============================================================================
# GROUP 10: SYSTEM SETTINGS VIEWS
# ============================================================================

class SystemSettingsViewSet(viewsets.ModelViewSet):
    """
    إدارة إعدادات النظام (Admin only)
    """
    queryset = SystemSettings.objects.all()
    serializer_class = SystemSettingsSerializer
    permission_classes = [IsAdmin]
    
    def list(self, request):
        """
        الحصول على الإعدادات الحالية
        GET /api/settings/
        """
        settings = SystemSettings.get_settings()
        serializer = self.get_serializer(settings)
        return Response(serializer.data)
    
    def update(self, request, pk=None, partial=False):
        """
        تحديث الإعدادات
        PUT/PATCH /api/settings/1/
        """
        settings = SystemSettings.get_settings()
        serializer = self.get_serializer(settings, data=request.data, partial=partial)
        
        if serializer.is_valid():
            serializer.save()
            
            # تسجيل النشاط
            log_activity(
                user=request.user,
                action='update',
                entity_type='system_settings',
                entity_id=settings.id,
                request=request
            )
            
            return Response({
                'success': True,
                'message': 'تم حفظ الإعدادات بنجاح',
                'data': serializer.data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def partial_update(self, request, pk=None):
        """
        تحديث جزئي للإعدادات
        PATCH /api/settings/1/
        """
        return self.update(request, pk=pk, partial=True)
