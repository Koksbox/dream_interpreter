from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),          # Ввод номера
    path('chat/', views.chat_view, name='chat'),
    path('api/message/', views.send_message, name='send_message'),
]