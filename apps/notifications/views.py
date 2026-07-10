from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render


@login_required
def notifications_list(request):
    notes = request.user.notifications.select_related("actor", "ticket")[:50]
    return render(request, "notifications/list.html", {"notes": notes})


@login_required
def notification_open(request, pk):
    note = get_object_or_404(request.user.notifications, pk=pk)
    note.is_read = True
    note.save(update_fields=["is_read"])
    if note.ticket_id:
        return redirect("tickets:ticket_detail", pk=note.ticket_id)
    return redirect("notifications:list")


@login_required
def notifications_read_all(request):
    if request.method == "POST":
        request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("notifications:list")
