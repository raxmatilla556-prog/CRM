from django.urls import path

from sales import views

app_name = 'sales'

urlpatterns = [
    path('smena/', views.shift_view, name='shift'),
    path('smena/<int:pk>/', views.shift_detail, name='shift_detail'),
    path('smenalar/', views.shift_list, name='shift_list'),
    path('tolov/<int:pk>/ochirish/', views.payment_delete, name='payment_delete'),
    path('klient/<int:pk>/ochirish/', views.customer_delete, name='customer_delete'),
    path('kassa/', views.pos, name='pos'),
    path('kassa/sotish/', views.checkout, name='checkout'),
    path('chek/<int:pk>/', views.receipt, name='receipt'),
    path('sotuv/<int:pk>/vozvrat/', views.sale_return, name='sale_return'),
    path('sotuvlar/', views.sale_list, name='sale_list'),
    path('qarz-daftari/', views.debt_book, name='debt_book'),
    path('klient/yangi/', views.customer_edit, name='customer_create'),
    path('klient/<int:pk>/', views.customer_detail, name='customer_detail'),
    path('klient/<int:pk>/tahrir/', views.customer_edit, name='customer_edit'),
    path('klient/<int:pk>/eslatma/', views.customer_remind, name='customer_remind'),
    path('api/klientlar/', views.customer_api, name='customer_api'),
]
