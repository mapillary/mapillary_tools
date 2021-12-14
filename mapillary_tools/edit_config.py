from . import login, api_v4, config, types


def edit_config(
    user_name: str = None,
    user_email: str = None,
    user_password: str = None,
    jwt: str = None,
):
    if user_name:
        user_name = user_name.strip()

    while not user_name:
        user_name = input(
            "Enter the Mapillary username you would like to (re)authenticate: "
        )
        user_name = user_name.strip()

    if jwt:
        user_items: types.UserItem = {
            "user_upload_token": jwt,
        }
    elif user_email and user_password:
        data = api_v4.get_upload_token(user_email, user_password)
        user_items = {
            "MAPSettingsUserKey": data["user_id"],
            "user_upload_token": data["access_token"],
        }
    else:
        user_items = login.prompt_user_for_user_items(user_name)

    config.update_config(user_name, user_items)
