import os
import signal
import sys
import threading
import time

import requests

from . import login
from . import api_v3
from .post_process import get_local_mapping


class BlurDownloader(threading.Thread):
    def __init__(self, lock, downloaded_images, rows, output_folder, token):
        threading.Thread.__init__(self)

        self.lock = lock
        self.downloaded_images = downloaded_images
        self.rows = rows
        self.output_folder = output_folder
        self.token = token
        self.shutdown_flag = threading.Event()

    def download_file(self, image_key, filename):
        response = requests.get(
            f"{api_v3.API_ENDPOINT}/v3/images/{image_key}/download_original_uuid",
            params={"client_id": api_v3.MAPILLARY_WEB_CLIENT_ID},
            headers={"Authorization": f"Bearer {self.token}"},
            stream=True,
        )

        if response.status_code != 200:
            print(f"Upload status {response.status_code}")
            print(f"Upload request.url {response.request.url}")
            print(f"Upload response.text {response.text}")
            print(f"Upload request.headers {response.request.headers}")
            print(response.json())
            return False

        with open(filename, "wb") as f:
            dl = 0
            for data in response.iter_content(chunk_size=4096):
                dl += len(data)
                f.write(data)

        return True

    def run(self):
        while not self.shutdown_flag.is_set():
            self.lock.acquire()
            if self.downloaded_images["nbr"] >= len(self.rows):
                self.lock.release()
                break
            row_entry = self.rows[self.downloaded_images["nbr"]]
            self.downloaded_images["nbr"] += 1
            image_path = os.path.join(self.output_folder, row_entry[0])
            image_uuid = row_entry[1]

            if not os.path.exists(os.path.dirname(image_path)):
                os.makedirs(os.path.dirname(image_path))

            self.lock.release()

            if not os.path.isfile(image_path):
                success = self.download_file(image_uuid, image_path)
                self.lock.acquire()
                if success:
                    self.downloaded_images["success"] += 1
                else:
                    self.downloaded_images["failed"] += 1
                self.lock.release()
            else:
                self.lock.acquire()
                self.downloaded_images["success"] += 1
                self.lock.release()

            self.lock.acquire()
            total = len(self.rows)
            count = self.downloaded_images["nbr"]

            suffix = f"({self.downloaded_images['success']}/{total} DOWNLOADED, {self.downloaded_images['failed']}/{total} STILL PROCESSING)"

            bar_len = 60
            filled_len = int(round(bar_len * count / float(total)))
            percents = round(100.0 * count / float(total), 1)
            bar = "=" * filled_len + "-" * (bar_len - filled_len)
            sys.stdout.write(f"[{bar}] {percents}% {suffix}\r")
            sys.stdout.flush()
            self.lock.release()


class ServiceExit(Exception):
    pass


def service_shutdown(signum, frame):
    raise ServiceExit


def check_files_downloaded(local_mapping, output_folder, do_sleep):
    not_downloaded = 0

    for row in local_mapping:
        if not os.path.isfile(os.path.join(output_folder, row[0])):
            not_downloaded += 1

    if not_downloaded > 0:
        print(f"Trying to download {not_downloaded} not yet downloaded files")
        if do_sleep:
            print("Waiting 10 seconds before next try")
            time.sleep(10)

        return False
    else:
        print("All files are downloaded")
        return True


def download(import_path, user_name, output_folder, number_threads=10, verbose=False):
    local_mapping = get_local_mapping(import_path)

    signal.signal(signal.SIGTERM, service_shutdown)
    signal.signal(signal.SIGINT, service_shutdown)

    try:
        user_properties = login.authenticate_user(user_name)
    except:
        print("Error, user authentication failed for user " + user_name)
        print(
            "Make sure your user credentials are correct, user authentication is required for images to be downloaded from Mapillary."
        )
        return None
    if "user_upload_token" in user_properties:
        token = user_properties["user_upload_token"]
    else:
        print("Error, failed to obtain user token, please try again.")
        return None
    do_sleep = False
    while not check_files_downloaded(local_mapping, output_folder, do_sleep):
        do_sleep = True

        lock = threading.Lock()

        downloaded_images = {
            "failed": 0,
            "nbr": 0,
            "success": 0,
        }

        threads = []
        try:
            for i in range(number_threads):
                t = BlurDownloader(
                    lock, downloaded_images, local_mapping, output_folder, token
                )
                threads.append(t)
                t.start()
            while True:
                any_alive = False
                for t in threads:
                    any_alive = any_alive or t.is_alive()

                if not any_alive:
                    break

                time.sleep(0.5)
        except ServiceExit:
            for t in threads:
                t.shutdown_flag.set()
            for t in threads:
                t.join()
            break
