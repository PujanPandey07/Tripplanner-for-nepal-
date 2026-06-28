import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required

from .forms import SignUpForm, ChatMessageForm
from .models import Conversation, ChatMessage
from Tripplanner import run_agent


def home(request):
    if request.user.is_authenticated:
        return redirect("conversation_list")
    return redirect("login")


def logout(request):
    auth_logout(request)
    return redirect("home")


def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            # log the user in immediately after signup
            auth_login(request, user)
            return redirect("conversation_list")
    else:
        form = SignUpForm()

    return render(request, "my_app/signup.html", {"form": form})


@login_required
def conversation_list(request):
    conversations = request.user.conversations.all()
    return render(request, "my_app/conversation_list.html", {"conversations": conversations})


@login_required
def new_conversation(request):
    conversation = Conversation.objects.create(
        user=request.user,
        thread_id=str(uuid.uuid4()),
    )
    return redirect("conversation_detail", conversation_id=conversation.id)


@login_required
def conversation_detail(request, conversation_id):
    conversation = get_object_or_404(
        Conversation, id=conversation_id, user=request.user)

    if request.method == "POST":
        form = ChatMessageForm(request.POST)
        if form.is_valid():
            user_text = form.cleaned_data["message"]

            # save the user's message
            ChatMessage.objects.create(
                conversation=conversation, role="user", content=user_text
            )

            # call the agent -- this is the one line that touches LangGraph
            reply_text = run_agent(conversation.thread_id, user_text)

            # save the agent's reply
            ChatMessage.objects.create(
                conversation=conversation, role="assistant", content=reply_text
            )

            # give the conversation a title from its first message, if it doesn't have one
            if not conversation.title:
                conversation.title = user_text[:50]
                conversation.save()

            return redirect("conversation_detail", conversation_id=conversation.id)
    else:
        form = ChatMessageForm()

    messages = conversation.messages.all()
    return render(
        request,
        "my_app/conversation_detail.html",
        {"conversation": conversation, "messages": messages, "form": form},
    )


@login_required
def delete_conversation(request, conversation_id):
    conversation = get_object_or_404(
        Conversation, id=conversation_id, user=request.user)

    if request.method == "POST":
        conversation.delete()
        return redirect("conversation_list")

    # GET requests just show a confirmation page rather than deleting immediately
    return render(request, "my_app/delete_confirm.html", {"conversation": conversation})
