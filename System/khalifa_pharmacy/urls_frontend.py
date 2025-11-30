"""
Frontend URLs
مسارات الواجهة الأمامية (HTML Pages)
"""

from django.urls import path
from conversations.views_frontend import (
    # Authentication
    login_view,
    logout_view,
    profile_view,
    
    # Admin Views
    admin_dashboard,
    admin_agents,
    admin_customers,
    admin_tickets,
    admin_templates,
    admin_reports,
    admin_settings,
    admin_monitor_agent,
    admin_monitor_agent_conversation,
    admin_agent_management,  # ✅ إضافة الاستيراد
    
    # Agent Views
    agent_conversations,
    agent_templates,
    agent_reports,
)

urlpatterns = [
    # Authentication
    path('', login_view, name='login'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('profile/', profile_view, name='profile'),
    
    # Admin Pages
    path('admin/dashboard/', admin_dashboard, name='admin-dashboard'),
    path('admin/agents/', admin_agents, name='admin-agents'),
    path('admin/agent-management/', admin_agent_management, name='admin-agent-management'),  # ✅ صفحة إدارة الموظفين الجديدة
    path('admin/customers/', admin_customers, name='admin-customers'),
    path('admin/tickets/', admin_tickets, name='admin-tickets'),
    path('admin/templates/', admin_templates, name='admin-templates'),
    path('admin/reports/', admin_reports, name='admin-reports'),
    path('admin/settings/', admin_settings, name='admin-settings'),
    path('admin/monitor-agent/<int:agent_id>/', admin_monitor_agent, name='admin-monitor-agent'),
    path('admin/monitor-agent-conversation/<int:customer_id>/', admin_monitor_agent_conversation, name='admin-monitor-agent-conversation'),
    
    # Agent Pages
    path('agent/conversations/', agent_conversations, name='agent-conversations'),
    # path('agent/templates/', agent_templates, name='agent-templates'),  # ✅ تم الحذف - القوالب من الأدمن فقط
    path('agent/reports/', agent_reports, name='agent-reports'),
]

