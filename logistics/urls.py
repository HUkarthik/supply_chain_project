from django.urls import path
from . import views

app_name = 'logistics'  

urlpatterns = [
    path('optimize_route/<int:order_id>/', views.optimize_route, name='optimize_route'),
]