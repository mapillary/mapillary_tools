import os
from time import sleep

from mapillary_messi.fixtures.psql_main_fixtures.psql_main_user_fixture import PsqlMainUserFixture
from mapillary_messi.models import User
from testtools import TestCase

UPLOADED_FILENAME = "2016_05_14_11_50_34_383.jpg"

class UploadProviderTestCase(TestCase):

    def test_images_uploaded_are_harvested(self):
        user_a = User()
        self.useFixture(PsqlMainUserFixture([user_a]))

        current_dir = os.path.abspath(__file__)
        data_dir = os.path.dirname(current_dir)
        image_path = os.path.join(data_dir, 'data/{}'.format(UPLOADED_FILENAME))

        sleep(3000)
