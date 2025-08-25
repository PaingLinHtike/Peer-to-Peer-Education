from django.contrib import admin
from django.urls import path, include
from users import views
from django.conf import settings
from django.conf.urls.static import static
from users import views as user_views
from dashboard import views as dashboard_views
from reports import views as reports_views
from payments import views as payment_views
from courses import views as courses_views
from reviews import views as reviews_views
from messages_app import views as msg_views
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static

# Instrutctor Part
# Import all views modules directly
from users import views as users_views
from courses import views as courses_views
from enrollments import views as enrollments_views
from payments import views as payments_views
from reviews import views as reviews_views
from messages_app import views as messages_views
def instructor_dashboard(request):
    return render(request, 'instructor_dashboard.html')

def instructor_login(request):
    return render(request, 'instructor_login.html')

import os

urlpatterns = [
    # Home Page
    path('', views.home, name='home'),
    
    # Admin Part
    # path('admin/', admin.site.urls),
    path('admin_login/', views.admin_login, name='admin_login'),
    path('admin_logout/', views.admin_logout, name='admin_logout'),
    path('admin_page/', views.admin_page, name='admin_page'),
    path('admin_profile/', views.admin_profile_view, name='admin_profile'),
    path('admin_profile/edit/', views.admin_edit_profile, name='admin_edit_profile'),
    path('user/<str:username>/', views.view_user, name='view_user'),

    # Ban
    path('user/<str:username>/ban/', views.ban_user, name='ban_user'),
    # Warning
    path('user/<str:username>/warn/', views.warn_user, name='warn_user'),

    # Dashboard
    path('dashboard/', dashboard_views.dashboard_home, name='dashboard_home'),

    # Clean Recent Activity
    path('dashboard/clear-logs/', dashboard_views.clear_activity_logs, name='clear_activity_logs'),
    
    # Clear Activity View (without deleting from database)
    path('dashboard/clear-view/', dashboard_views.clear_activity_view, name='clear_activity_view'),

    # Earning Overview
    path('dashboard/earnings/', dashboard_views.earnings_overview, name='earnings_overview'),

    # User Growth
    path('dashboard/user-growth/', dashboard_views.user_growth, name='user_growth'),

    # Course Overview
    path('dashboard/course-overview/', dashboard_views.course_overview, name='course_overview'),

    # View All Course
    path('dashboard/courses/all/', dashboard_views.view_all_courses, name='view_all_courses'),
    # path('dashboard/courses/<str:course_id>/view/', dashboard_views.view_course_detail, name='view_course_detail'),

    # Delete course and warn
    path('dashboard/courses/delete/<str:course_id>/', dashboard_views.delete_course_and_warn, name='delete_course_and_warn'),

    # Course Approve or Reject
    path('dashboard/courses/', dashboard_views.course_overview, name='course_overview'),
    path('dashboard/courses/<str:course_id>/approve/', dashboard_views.approve_course, name='approve_course'),
    path('dashboard/courses/<str:course_id>/reject/', dashboard_views.reject_course, name='reject_course'),

    # Admin Enrollments Monitor
    path('dashboard/enrollments/', dashboard_views.enrollments_monitor, name='admin_enrollments'),
    # Admin Payouts
    path('dashboard/payouts/', dashboard_views.admin_payouts, name='admin_payouts'),
    path('dashboard/payouts/mark-paid/<str:enrollment_id>/', dashboard_views.mark_payout_paid, name='mark_payout_paid'),
    path('dashboard/payouts/process-pending/<str:enrollment_id>/', dashboard_views.process_pending_payout, name='process_pending_payout'),
    # Admin Platform Commission Withdrawal
    path('dashboard/admin-withdraw/', dashboard_views.admin_withdraw_view, name='admin_withdraw'),
    path('dashboard/admin-withdraw/process/', dashboard_views.admin_withdraw_platform_commission, name='admin_withdraw_process'),
    path('dashboard/admin-withdraw/clear/', dashboard_views.clear_withdrawals, name='clear_withdrawals'),

    # ✅ View All Reports
    path('dashboard/reports/all/', reports_views.all_reports, name='all_reports'),

    # ✅ Resolve action
    path('dashboard/reports/<str:report_id>/resolve/', reports_views.resolve_report, name='resolve_report'),

    # Report
    path("dashboard/reports/", dashboard_views.report_view, name="report_view"),

    # View All Payment
    path('dashboard/payments/all/', payment_views.view_all_payments, name='view_all_payments'),

    # View All Withdrawals
    path('dashboard/withdrawals/', payment_views.view_withdrawals, name='view_withdrawals'),



    # Student Part

    # Student Registration
    path("student/register/", views.student_register, name="student_register"),
    path("student/send_otp/", views.send_otp, name="send_otp"),
    path("student/verify_otp/", views.verify_otp, name="verify_otp"),

    # Student Login
    path("student/login/", views.student_login, name="student_login"),
    path("student/dashboard/", views.student_dashboard, name="student_dashboard"),

    # Student Logout
    path("student_logout/", views.student_logout, name="student_logout"),
    
    # Edit Profile
    path("edit_student_profile/", views.edit_student_profile, name="edit_student_profile"),
    path("send_otp", views.send_otp, name="send_otp"),
    path("verify_otp", views.verify_otp, name="verify_otp"),

    # Enrolled Course ``
    path('courses/my_courses/', courses_views.my_courses, name='my_courses'),

    # Reviews
    path("write-review/", reviews_views.write_review, name="write_review"), 

    # View Reviews
    path("my-reviews/", reviews_views.my_reviews, name="my_reviews"),
    
    # Delete All Reviews
    path("delete-all-reviews/", reviews_views.delete_all_reviews, name="delete_all_reviews"),
    
    # Messages
    path('student/inbox/', msg_views.inbox, name='student_inbox'),

    # Student Conversation Detail
    path('student/conversation/<str:conversation_id>/', msg_views.student_conversation_detail, name='student_conversation_detail'),

    # Clear Student Conversation
    path('student/conversation/<str:conversation_id>/clear/', msg_views.clear_student_conversation, name='clear_student_conversation'),

    # Write Message
    path('student/send_message/', msg_views.send_message, name='send_message'),

    # Student Reports
    path('student/write-report/', reports_views.student_write_report, name='student_write_report'),
    path('student/my-reports/', reports_views.student_view_reports, name='student_view_reports'),

    # Enroll Course
    path("enroll/<str:course_id>/", views.enroll_course, name="enroll_course"),

    # Pay Course
    path("student/pay_course/<str:course_id>/", views.pay_course, name="pay_course"),
    
    # Get Course Info
    path("get_course_info/<str:course_id>/", views.get_course_info, name="get_course_info"),


    # Instructor Part
    path('instructor/register/', users_views.instructor_register_view, name='instructor_register'),
    path('instructor/check_email/', users_views.check_instructor_email, name='check_instructor_email'),
    path('instructor/send_otp/', users_views.send_instructor_otp, name='send_instructor_otp'),
    path('instructor/verify_otp/', users_views.verify_instructor_otp, name='verify_instructor_otp'),
    path('instructor/login/', users_views.instructor_login, name='instructor_login'),
    path('instructor/logout/', users_views.instructor_logout, name='instructor_logout'),
    path('instructor/dashboard/', users_views.instructor_dashboard_view, name='instructor_dashboard'),
    path('instructor/profile/', users_views.instructor_profile_view, name='instructor_profile'),
    path('instructor/forgot-password/', users_views.forgot_password_view, name='forgot_password'),

    # --- Course URLs (from courses app) ---
    path('instructor/courses/', courses_views.instructor_course_list, name='instructor_course_list'),
    path('instructor/courses/create/', courses_views.instructor_course_create, name='instructor_course_create'),
    path('instructor/courses/<str:pk>/', courses_views.instructor_course_detail, name='instructor_course_detail'),
    path('instructor/courses/<str:pk>/update/', courses_views.instructor_course_update, name='instructor_course_update'),
    path('instructor/courses/<str:pk>/delete/', courses_views.instructor_course_delete, name='instructor_course_delete'),



    # --- Enrollment URLs (from enrollments app) ---
                  path('enrollments/', enrollments_views.instructor_enrollments_view, name='instructor_enrollments'),
                  path('enrollments/<str:course_id>/', enrollments_views.course_enrollments_detail_view,
                       name='course_enrollments_detail'),
                  path('enrollments/approve/<str:enrollment_id>/', enrollments_views.approve_enrollment,
                       name='approve_enrollment'),
    # --- Payment URLs (from payments app) ---
    path('instructor/earnings/', payments_views.instructor_earnings_view, name='instructor_earnings'),
    path('instructor/withdrawals/',payments_views.instructor_withdrawals_view, name='instructor_withdrawals'),

    # --- Review URLs (from reviews app) ---
    path('instructor/reviews/', reviews_views.instructor_reviews_view, name='instructor_reviews'),



    # --- Messages App URLs (from messages_app) ---
                  path('instructor/messages/', messages_views.instructor_conversations_list,
                       name='instructor_conversations_list'),
                  path('instructor/messages/new/', messages_views.instructor_new_conversation,
                       name='instructor_new_conversation'),
                  path('instructor/messages/<str:pk>/', messages_views.instructor_conversation_detail,
                       name='instructor_conversation_detail'),
                  path('instructor/messages/<str:pk>/clear/', messages_views.clear_instructor_conversation,
                       name='clear_instructor_conversation'),
                  
    # --- Health Check ---
    path('health-check/', messages_views.health_check, name='health_check'),
    # --- Media files serving during development ---
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += static(
    '/users_media/',  # ✅ this will be the URL prefix
    document_root=os.path.join(settings.BASE_DIR, 'users', 'media')
)