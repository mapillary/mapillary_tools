from . import login, api_v4, config, types


def edit_config(
    user_name: str = None,
    user_email: str = None,
    user_password: str = None,
    jwt: str = None,
):
    if not user_name:
        user_name = input(
            "Enter the Mapillary username you would like to (re)authenticate: "
        )

    if jwt:
        user_items: types.UserItem = {
            "MAPSettingsUsername": user_name,
            "user_upload_token": jwt,
        }
        config.update_config(config.MAPILLARY_CONFIG_PATH, user_name, user_items)
        return

    if user_email and user_password:
        data = api_v4.get_upload_token(user_email, user_password)
        upload_token = data["access_token"]
        user_key = data["user_id"]

        if not upload_token:
            raise RuntimeError(
                f"Authentication failed for username {user_name}, please try again."
            )

        user_items = {
            "MAPSettingsUsername": user_name,
            "MAPSettingsUserKey": user_key,
            "user_upload_token": upload_token,
        }
    else:
        # fill in the items and save
        user_items = login.prompt_user_for_user_items(user_name)

    config.update_config(config.MAPILLARY_CONFIG_PATH, user_name, user_items)
