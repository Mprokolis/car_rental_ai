from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from .views import (
    home,
    register_company,
    login_company,
    logout_company,
    select_car,
    add_car,
    edit_car,
    delete_car,
    choose_car,
    fleet_status,
    return_car,
    delete_cars_view,
)

app_name = "rentals"

urlpatterns: list[path] = [
    path("", home, name="home"),
    path("register/", register_company, name="register_company"),
    path("login/", login_company, name="login_company"),
    path("logout/", logout_company, name="logout_company"),

    # Password reset
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="rentals/password_reset_form.html",
            email_template_name="rentals/password_reset_email.html",
            subject_template_name="rentals/password_reset_subject.txt",
            success_url=reverse_lazy("rentals:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="rentals/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="rentals/password_reset_confirm.html",
            success_url=reverse_lazy("rentals:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="rentals/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

    # Fleet
    path("select-car/", select_car, name="select_car"),
    path("add-car/", add_car, name="add_car"),
    path("edit-car/<int:car_id>/", edit_car, name="edit_car"),
    path("delete-car/<int:car_id>/", delete_car, name="delete_car"),
    path("delete-cars/", delete_cars_view, name="delete_cars"),
    path("choose-car/<int:request_id>/<int:car_id>/", choose_car, name="choose_car"),
    path("fleet/", fleet_status, name="fleet_status"),
    path("return-car/<int:car_id>/", return_car, name="return_car"),
]
