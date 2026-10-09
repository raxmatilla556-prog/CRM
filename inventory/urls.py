from django.urls import path

from inventory import views

app_name = 'inventory'

urlpatterns = [
    path('', views.stock, name='stock'),
    path('tovar/yangi/', views.product_edit, name='product_create'),
    path('tovar/<int:pk>/', views.product_edit, name='product_edit'),
    path('tovar/<int:pk>/ochirish/', views.product_delete, name='product_delete'),
    path('api/tovarlar/', views.product_api, name='product_api'),
    path('kategoriyalar/', views.categories, name='categories'),
    path('yetkazib-beruvchilar/', views.suppliers, name='suppliers'),
    path('kirim/', views.receipt_list, name='receipt_list'),
    path('kirim/yangi/', views.receipt_create, name='receipt_create'),
    path('kirim/<int:pk>/', views.receipt_detail, name='receipt_detail'),
    path('kochirish/', views.transfer, name='transfer'),
    path('inventarizatsiya/', views.count_list, name='count_list'),
    path('inventarizatsiya/yangi/', views.count_create, name='count_create'),
    path('inventarizatsiya/<int:pk>/', views.count_detail, name='count_detail'),
    path('ogohlantirishlar/', views.alerts, name='alerts'),
]
