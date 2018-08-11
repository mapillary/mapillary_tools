import json
import os
import urllib
from shutil import copyfile, rmtree
from time import sleep

import requests
from mapillary_messi.assertions.harvest_assertions import HarvestAssertion
from mapillary_messi.fixtures.app_fixture import MapillaryAppFixture
from mapillary_messi.fixtures.user_fixture import UserFixture
from mapillary_messi.models import User
from testtools import TestCase

from tests.utils import config

UPLOADED_FILENAME = "V0370574.JPG"
current_dir = os.path.abspath(__file__)
data_dir = os.path.dirname(current_dir)
image_path = os.path.join(data_dir, 'data/{}'.format(UPLOADED_FILENAME))
images_dir = "{}/data/images/".format(data_dir)
new_image_path = "{}/data/images/{}".format(data_dir, UPLOADED_FILENAME)

CLIENT_ID = os.getenv("MAPILLARY_WEB_CLIENT_ID", "MkJKbDA0bnZuZlcxeTJHTmFqN3g1dzo1YTM0NjRkM2EyZGU5MzBh")
if os.getenv("API_PROXY_HOST", None) is None:
    API_ENDPOINT = "https://a.mapillary.com"
else:
    API_ENDPOINT = "http://{}".format(os.getenv("API_PROXY_HOST"))
LOGIN_URL = "{}/v2/ua/login?client_id={}".format(API_ENDPOINT, CLIENT_ID)
USER_UPLOAD_URL = API_ENDPOINT + "/v3/users/{}/upload_tokens?client_id={}"


class ProcessImagesProviderTestCase(TestCase):

    def setUp(self):
        for file in os.listdir(images_dir):
            file_path = os.path.join(images_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path): rmtree(file_path)
            except Exception as e:
                print(e)
        self.useFixture(MapillaryAppFixture())
        super(ProcessImagesProviderTestCase, self).setUp()

    def test_processed_images_are_uploaded_and_harvested(self):
        user_a = User(username="mapillary_user")
        self.useFixture(UserFixture([user_a]))

        config.create_config("/mapillary_source/tests/.config/mapillary/config")
        config.update_config("/mapillary_source/tests/.config/mapillary/config",
                             user_a.username, self._get_user_items(user_a))

        copyfile(image_path, new_image_path)
        HarvestAssertion(self).assert_test_case(user_a.id)

    def _get_user_items(self, user):
        user_items = {}
        upload_token = self._get_upload_token(user)
        user_permission_hash, user_signature_hash = self._get_user_hashes(user.key, upload_token)

        user_items["MAPSettingsUsername"] = user.username
        user_items["MAPSettingsUserKey"] = user.key

        user_items["user_upload_token"] = upload_token
        user_items["user_permission_hash"] = user_permission_hash
        user_items["user_signature_hash"] = user_signature_hash

        return user_items

    def _get_upload_token(self, user):
        params = {"email": user.email, "password": user.password}
        response = requests.post(LOGIN_URL, data=params)
        return response.json()["token"]

    def _get_user_hashes(self, user_key, upload_token):
        resp = requests.get(USER_UPLOAD_URL.format(user_key, CLIENT_ID),
                            headers = {"Authorization":"Bearer " + upload_token}).json()
        return (resp['images_policy'], resp['images_hash'])