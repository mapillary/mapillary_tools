import os
from shutil import copyfile, rmtree
from mapillary_messi.assertions.harvest_assertions import HarvestAssertion
from mapillary_messi.fixtures.psql_main_fixtures.psql_main_user_fixture import PsqlMainUserFixture
from mapillary_messi.models import User
from testtools import TestCase

UPLOADED_FILENAME = "2018_07_19_17_33_15_820_+0200.jpg"
current_dir = os.path.abspath(__file__)
data_dir = os.path.dirname(current_dir)
image_path = os.path.join(data_dir, 'data/{}'.format(UPLOADED_FILENAME))
images_dir = "{}/data/images/".format(data_dir)
new_image_path = "{}/data/images/{}".format(data_dir, UPLOADED_FILENAME)


class UploadProviderTestCase(TestCase):

    def setUp(self):
        for file in os.listdir(images_dir):
            file_path = os.path.join(images_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path): rmtree(file_path)
            except Exception as e:
                print(e)
        super(UploadProviderTestCase, self).setUp()

    def test_images_uploaded_are_harvested(self):
        user_a = User(key="24cc3715-7661-4411-81f9-942c842124c7")
        self.useFixture(PsqlMainUserFixture([user_a]))
        copyfile(image_path, new_image_path)

        HarvestAssertion(self).assert_test_case(user_a.id)