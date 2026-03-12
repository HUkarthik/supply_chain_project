from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('user_logout/', views.logout_view, name='user_logout'),
    path('register/', views.register, name='register'),
    path('dashboard/', views.dashboard, name='dashboard'), 
    path('supplier_dashboard/', views.dashboard, name='supplier_dashboard'), 
    path('customer_dashboard/', views.dashboard, name='customer_dashboard'), 
    path('edit_profile/', views.edit_profile, name='edit_profile'),
    path('create_order/', views.create_order, name='create_order'),
    path('confirm_receipt/', views.confirm_receipt, name='confirm_receipt'),
    path('rate_supplier/<int:order_id>/', views.rate_supplier, name='rate_supplier'),
    path('edit_supplier/<int:user_id>/', views.edit_supplier, name='edit_supplier'),
    path('edit_customer/<int:user_id>/', views.edit_customer, name='edit_customer'),
    path('manage_warehouse/', views.manage_warehouse, name='manage_warehouse'),
    path('track_orders/', views.track_orders, name='track_orders'),
    path('update_order_status/<int:order_id>/', views.update_order_status, name='update_order_status'),
    path('admin_activity/', views.admin_activity, name='admin_activity'),
    path('mark_notification_read/<int:notification_id>/', views.mark_notification_read, name='mark_notification_read'),
    path('get_supplier_products/<int:supplier_id>/', views.get_supplier_products, name='get_supplier_products'),
    path('download_receipt/<int:order_id>/', views.download_receipt, name='download_receipt'),
]