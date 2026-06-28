from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import StyledLoginForm

urlpatterns = [
    path("", views.home, name="home"),

    # auth
    path("signup/", views.signup, name="signup"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="my_app/login.html",
            authentication_form=StyledLoginForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="home"), name="logout"),

    # conversations
    path("conversations/", views.conversation_list, name="conversation_list"),
    path("conversations/new/", views.new_conversation, name="new_conversation"),
    path("conversations/<int:conversation_id>/",
         views.conversation_detail, name="conversation_detail"),
    path("conversations/<int:conversation_id>/delete/",
         views.delete_conversation, name="delete_conversation"),
]
