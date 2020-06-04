import os
from shutil import copyfile, rmtree
import requests

from mapillary_messi.db.s3_base_driver import S3BaseDriver
from mapillary_messi.fixtures.app_fixture import MapillaryAppFixture
from mapillary_messi.fixtures.user_fixture import UserFixture
from mapillary_messi.matchers.matcher import Eventually
from mapillary_messi.models import User
from testtools import TestCase
from testtools.matchers import Equals

from tests.utils import config

UPLOADED_FILENAME = "V0370574.JPG"
current_dir = os.path.abspath(__file__)
data_dir = os.path.dirname(current_dir)
images_dir = "{}/data/images/".format(data_dir)

CLIENT_ID = os.getenv("MAPILLARY_WEB_CLIENT_ID")
API_ENDPOINT = "http://{}".format(os.getenv("API_PROXY_HOST"))
LOGIN_URL = "{}/v2/ua/login?client_id={}".format(API_ENDPOINT, CLIENT_ID)
USER_UPLOAD_URL = API_ENDPOINT + "/v3/users/{}/upload_tokens?client_id={}"
UPLOAD_BUCKET = os.getenv("AWS_S3_UPLOAD_BUCKET")


class ProcessImagesProviderTestCase(TestCase):

    def setUp(self):
        for file in os.listdir(images_dir):
            file_path = os.path.join(images_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    rmtree(file_path)
            except Exception as e:
                print(e)
        self.useFixture(MapillaryAppFixture())

        self.user = User(username="mapillary_user")
        self.useFixture(UserFixture([self.user]))

        config_path = "/mapillary_source/tests/.config/mapillary/configs/{}".format(CLIENT_ID)

        config.create_config(config_path)
        config.update_config(config_path,
                             self.user.username, self._get_user_items(self.user))

        super(ProcessImagesProviderTestCase, self).setUp()

    def test_images_are_uploaded(self):
        image1_path = os.path.join(data_dir, 'data/{}'.format("DSC00497.JPG"))
        image2_path = os.path.join(data_dir, 'data/{}'.format("DSC00001.JPG"))

        new_image1_path = "{}/data/images/{}".format(data_dir, "DSC00497.JPG")
        new_image2_path = "{}/data/images/{}".format(data_dir, "DSC00001.JPG")

        copyfile(image1_path, new_image1_path)
        copyfile(image2_path, new_image2_path)

        s3_driver = S3BaseDriver()
        bucket = s3_driver.get_bucket(UPLOAD_BUCKET)
        prefix = "{}/uploads/images/sequence".format(self.user.key)

        def has_done_file():
            keys = bucket.get_all_keys(prefix=prefix)

            return any(filter(lambda f: f.key.endswith("DONE"), keys))

        self.assertThat(
            lambda: has_done_file(),
            Eventually(Equals(True), timeout=180)
        )

        def get_image_files():
            keys = bucket.get_all_keys(prefix=prefix)

            return filter(lambda f: f.key.endswith("JPG"), keys)

        self.assertThat(
            lambda: len(list(get_image_files())),
            Eventually(Equals(2), timeout=180)
        )

    def _get_user_items(self, user):
        user_items = {}
        upload_token = self._get_upload_token(user)
        user_permission_hash, user_signature_hash, aws_access_key_id = self._get_user_hashes(user.key, upload_token)

        user_items["MAPSettingsUsername"] = user.username
        user_items["MAPSettingsUserKey"] = user.key

        user_items["user_upload_token"] = upload_token
        user_items["user_permission_hash"] = user_permission_hash
        user_items["user_signature_hash"] = user_signature_hash
        user_items["aws_access_key_id"] = aws_access_key_id

        return user_items

    def _get_upload_token(self, user):
        params = {"email": user.email, "password": user.password}
        response = requests.post(LOGIN_URL, data=params)
        return response.json()["token"]

    def _get_user_hashes(self, user_key, upload_token):
        resp = requests.get(USER_UPLOAD_URL.format(user_key, CLIENT_ID),
                            headers = {"Authorization":"Bearer " + upload_token}).json()
        return (resp['images_policy'], resp['images_hash'], resp['aws_access_key_id'])
