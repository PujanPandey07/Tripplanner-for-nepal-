def sidebar_conversations(request):
    """Makes the logged-in user's conversation list available in every
    template automatically, so the sidebar can render on any page without
    every view needing to pass it explicitly."""
    if request.user.is_authenticated:
        return {"sidebar_conversations": request.user.conversations.all()}
    return {"sidebar_conversations": []}
