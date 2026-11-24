from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include, re_path

from config import views as error_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('customers/', include('masters.urls')),
    path('', include('receivables.urls')),
    # Catch-all for unknown URLs so the branded 404 page is shown even when DEBUG=True
    re_path(r'^(?!static/|media/).*$', error_views.custom_404),
]

handler404 = 'config.views.custom_404'
handler403 = 'config.views.custom_403'
handler400 = 'config.views.custom_400'
handler500 = 'config.views.custom_500'
