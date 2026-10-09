from django.urls import path

from reports import views

app_name = 'reports'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('telegram/', views.send_report, name='send_report'),
]
