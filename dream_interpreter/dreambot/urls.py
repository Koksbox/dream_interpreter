# dreambot/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('chat/', views.chat_view, name='chat'),
    path('profile/', views.profile_view, name='profile'),
    path('history/', views.history_view, name='history'),
    path('api/message/', views.send_message, name='send_message'),
    path('api/profile/', views.update_profile, name='update_profile'),
    path('guide/', views.guide_view, name='guide'),
    path('api/clear-chat/', views.clear_chat, name='clear_chat'),
    path('premium/checkout/', views.premium_checkout, name='premium_checkout'),
    path('robokassa/result/', views.robokassa_result, name='robokassa_result'),
]