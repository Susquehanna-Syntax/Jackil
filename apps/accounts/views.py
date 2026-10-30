from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.mfa.totp import has_second_factor
from apps.mfa.views import begin

from .mfa_policy import required
from .models import User


class RegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "password"]

    def clean(self):
        cleaned = super().clean()
        pwd = cleaned.get("password")
        confirm = cleaned.get("password_confirm")
        if pwd and confirm and pwd != confirm:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            login(request, user)
            messages.success(request, "Registration successful.")
            return redirect("tickets:dashboard")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


def user_login(request):
    if request.user.is_authenticated:
        return redirect("tickets:dashboard")

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            if user:
                # A staff password only starts the sign-in; the second factor
                # finishes it in apps.mfa. Customers sign in as before.
                if required(user):
                    return begin(
                        request,
                        user,
                        request.POST.get("next")
                        or request.GET.get("next")
                        or reverse("tickets:dashboard"),
                        user.backend,
                    )
                login(request, user)
                messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
                return redirect("tickets:dashboard")
            messages.error(request, "Invalid username or password.")
    else:
        form = LoginForm()
    return render(request, "accounts/login.html", {"form": form})


@login_required
def user_logout(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("accounts:login")


AVATAR_COLORS = ["lavender", "mint", "peach", "sky", "rose", "coral", "lemon"]


@login_required
def upload_avatar(request):
    """Store an uploaded profile photo as a base64 data URI on the user, or
    clear it. Kept in the DB (no media storage) to stay self-contained."""
    if request.method != "POST":
        return redirect("accounts:profile")
    if request.POST.get("remove"):
        request.user.avatar = ""
        request.user.save(update_fields=["avatar"])
        messages.success(request, "Profile photo removed.")
        return redirect("accounts:profile")
    file = request.FILES.get("avatar")
    if not file:
        return redirect("accounts:profile")
    if not (file.content_type or "").startswith("image/"):
        messages.error(request, "Please choose an image file.")
        return redirect("accounts:profile")
    if file.size and file.size > 2 * 1024 * 1024:
        messages.error(request, "That image is too large (max 2 MB).")
        return redirect("accounts:profile")

    import base64

    b64 = base64.b64encode(file.read()).decode("ascii")
    request.user.avatar = f"data:{file.content_type};base64,{b64}"
    request.user.save(update_fields=["avatar"])
    messages.success(request, "Profile photo updated.")
    return redirect("accounts:profile")


@login_required
def profile(request):
    user = request.user
    if request.method == "POST":
        user.first_name = request.POST.get("first_name", user.first_name).strip()
        user.last_name = request.POST.get("last_name", user.last_name).strip()
        user.email = request.POST.get("email", user.email).strip()
        user.phone = request.POST.get("phone", user.phone).strip()
        color = request.POST.get("avatar_color", user.avatar_color)
        if color in AVATAR_COLORS:
            user.avatar_color = color
        user.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    # Nothing reads the stored preferences any more: the profile form's only
    # preference was the old fixed dashboard's "Needs Attention" toggle.
    return render(
        request,
        "accounts/profile.html",
        {
            "avatar_colors": AVATAR_COLORS,
            "mfa_required": required(user),
            "mfa_set_up": has_second_factor(user),
        },
    )
