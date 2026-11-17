from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('customers/', include('masters.urls')),
    path('', include('receivables.urls')),
]
