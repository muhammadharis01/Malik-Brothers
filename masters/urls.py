from django.urls import path
from . import views

app_name = 'masters'

urlpatterns = [
    path('', views.customer_master_view, name='customer_master'),
    path('<int:customer_id>/edit/', views.customer_edit_view, name='customer_edit'),
]

