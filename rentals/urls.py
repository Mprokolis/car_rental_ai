from django.urls import path
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
