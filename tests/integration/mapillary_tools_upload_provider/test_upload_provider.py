import os
from shutil import copyfile, rmtree
from time import sleep

from mapillary_messi.fixtures.psql_main_fixtures.psql_main_user_fixture import PsqlMainUserFixture
from mapillary_messi.models import User
from testtools import TestCase

UPLOADED_FILENAME = "2018_07_19_17_33_15_820_+0200.jpg"

class UploadProviderTestCase(TestCase):

    def test_images_uploaded_are_harvested(self):
        user_a = User()
        self.useFixture(PsqlMainUserFixture([user_a]))

        current_dir = os.path.abspath(__file__)
        data_dir = os.path.dirname(current_dir)
        image_path = os.path.join(data_dir, 'data/{}'.format(UPLOADED_FILENAME))
        new_image_path = "{}/data/images/{}".format(data_dir, UPLOADED_FILENAME)

        # Remove .mapillary so that the uploader let us copy new images
        try:
            rmtree("{}/data/images/.mapillary/".format(data_dir))
        except Exception:
            pass

        print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
        print(new_image_path)
        print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
        copyfile(image_path, new_image_path)
        sleep(3000)
