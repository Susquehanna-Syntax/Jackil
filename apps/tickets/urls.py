from django.urls import path
from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("my-tickets/", views.customer_tickets, name="customer_tickets"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/create/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("tickets/<int:pk>/assign/", views.ticket_assign, name="ticket_assign"),
    path("api/users/search/", views.user_search, name="user_search"),
]