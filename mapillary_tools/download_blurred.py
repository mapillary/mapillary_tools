import hashlib
import os
import requests
import shutil
import sys
import threading
import uploader
import urllib
import queue
import time


MAPILLARY_ENDPOINT = 'http://localhost:4000'
MAPILLARY_API_IM_SEARCH_URL = "{}/v3/images?".format(MAPILLARY_ENDPOINT)


class WorkerMonitor(threading.Thread):
    """
    This class should be used for logging state from currently running workers
    against a Queue. Each worker is assumed to have `self.worker_stats`
    property which is a number.
    """

    def __init__(self, threads, q):
        threading.Thread.__init__(self)
        self.threads = threads
        self.q = q
        self.shutdown_flag = threading.Event()

    def run(self):
        while not self.q.empty():
            stats = []
            message = ''
            total = 0
            for index, worker in enumerate(self.threads):
                stats = worker.worker_stats
                total += stats
                message += 'T{}: {}/{} '.format(index, stats, self.q.maxsize)

            output = message + 'Total: {}/{}\r'.format(total, self.q.maxsize)
            sys.stdout.write(output)
            sys.stdout.flush()
        sys.stdout.write('\nDownload complete: {}\n'.format(self.q.maxsize))


def create_dirs(base_path):
    """
    Create directory if it doesn't exist.
    :param base_path: where to create the directory
    :type  base_path: string
    """
    try:
        shutil.rmtree(base_path)
    except Exception:
        pass
    os.mkdir(base_path)


def get_token(user_name):
    """
    :param user_name: user name, string
    :type user_name: string

    :return authentication token for requests
    :rtype string or Exception/None
    """
    try:
        user_properties = uploader.authenticate_user(user_name)
    except Exception:
        print("Error, user authentication failed for user " + user_name)
        print("Make sure your user credentials are correct, user authentication is required for images to be downloaded from Mapillary.")
        return None
    if "user_upload_token" in user_properties:
        return user_properties["user_upload_token"]


def get_headers_for_username(user_name):
    """
    :param user_name: user name, string
    :type user_name: string

    :return headers for requests
    :rtype { 'Authrization': string } or Exception/None
    """
    token = get_token(user_name)
    return {'Authorization': 'Bearer {}'.format(token)}


def query_search_api(headers, **kwargs):
    """
    :param arg['client_id']: CLIENT_ID to be used with requests
    :type arg['client_id']: string, required

    :param arg['organization_keys']: organization keys to filter results by
    :type  arg['organization_keys']: List<string>, required

    :param arg['start_time']: beginning of time range to filter results by
    :type  arg['start_time']: string (YYYY-MM-DD), optional

    :param arg['end_time']: end of time range to filter results by
    :type arg['end_time']: string (YYYY-MM-DD), optional

    :return image keys to attempt download of
    :rtype List<string>
    """
    set_params = []
    per_page = int(kwargs['per_page'])
    for k, v in kwargs.iteritems():
        if v is not None:
            set_params.append((k, str(v)))

    set_params.append(('private', 'true'))
    params = urllib.urlencode(set_params)

    # Get data from server, then parse JSON
    keys = []
    pages = 0
    r = requests.get(MAPILLARY_API_IM_SEARCH_URL + params, headers=headers)

    get_keys = (lambda xs: map(lambda x: x['properties']['key'], xs))
    m = get_keys(r.json()['features'])

    last_page_len = len(m)

    keys = keys + m
    print("Found: {} images".format(len(keys)))

    has_next_link = last_page_len == per_page
    while has_next_link:
        pages += 1
        link = r.links['next']['url']
        r = requests.get(link, headers=headers)
        mm = get_keys(r.json()['features'])
        keys = keys + mm
        print("Found: {} images".format(len(keys)))
        last_page_len = len(mm)
        has_next_link = last_page_len == per_page

    return keys


def download(client_id,
             organization_keys,
             start_time,
             end_time,
             output_folder,
             user_name,
             number_threads=4):
    """
    The main function to spin up the downloads threads.

    :param client_id: CLIENT_ID required for requests
    :type client_id: string

    :param organization_keys: list of orgs to filter by
    :type  organization_keys: List<string>

    :param start_time: start of time range to use for requests
    :type  start_time: None or string (YYYY-MM-DD)

    :param end_time: end of time range to use for requests
    :type  end_time: None or string (YYYY-MM-DD)

    :param output_folder: destination for the files
    :type output_folder: string

    :param user_name: user name of the requesting user
    :type  user_name: string
    """
    headers = get_headers_for_username(user_name)

    start_time_b64 = '' if not start_time else start_time
    end_time_hash = '' if not end_time else end_time
    download_id = b','.join([client_id,
                             organization_keys,
                             start_time_b64,
                             end_time_hash,
                             output_folder,
                             user_name,
                             ])
    hash_object = hashlib.md5(download_id)
    download_id = str(hash_object.hexdigest())

    # create directories for saving
    create_dirs(output_folder)
    save_path = download_id

    # create most of the bookkeeping files
    all_file = '{}_all.txt'.format(save_path)
    all_file_exists = os.path.isfile(all_file)
    all_file_obj = open(
        all_file, 'r') if all_file_exists is True else open(all_file, 'a+')

    done_file = '{}_done.txt'.format(save_path)
    done_file_exists = os.path.isfile(done_file)

    err_file = '{}_err.txt'.format(save_path)
    err_file_exists = os.path.isfile(err_file)

    # fetch image keys and store basic state for downloads from bookkeeping files
    image_keys = []
    if all_file_exists:
        all_keys = all_file_obj.read().split('\n')

        done_file_obj = open(
            done_file, 'r+') if done_file_exists is True else open(done_file, 'r+')

        err_file_obj = open(
            err_file, 'r') if err_file_exists is True else open(err_file, 'r+')

        done_keys = done_file_obj.read().split('\n')
        err_keys = err_file_obj.read().split('\n')
        set_all = set(all_keys)
        set_done = set(done_keys)
        set_err = set(err_keys)

        diff = list(set_all.difference(set_done).difference(set_err))
        print("Download {} continued: {}/{}".format(download_id, len(diff), len(all_keys)))

        image_keys = diff
        done_file_obj.close()
        err_file_obj.close()
    else:
        headers = get_headers_for_username("knikel")
        image_keys = query_search_api(
            headers,
            client_id=uploader,
            organization_keys=organization_keys,
            start_time=start_time,
            end_time=end_time,
            per_page='1000'
        )

        all_file_obj.writelines('\n'.join(image_keys))
        all_file_obj.close()
        print('wrote')

    done_file_obj = open(
            done_file, 'w') if done_file_exists is True else open(done_file, 'a+')
    err_file_obj = open(
            err_file, 'w') if err_file_exists is True else open(err_file, 'w+')

    # download begins here

    if len(image_keys) == 0:
        print('All images downloaded for this query. Remove the download_XXXX_todo/all/err files to re-download.')
        return

    lock = threading.Lock()

    counter = {
        'todo': 0,
        'done': 0,
        'err': 0,
        'ok': 0
    }

    # Set up a queue for the downloads so threads can take downloads from
    # it asynchronously
    q = queue.Queue(len(image_keys))

    for i in image_keys:
        q.put(i)

    threads = []
    monitor = None
    try:
        for i in range(number_threads):
            t = BlurredOriginalsDownloader(
                lock,
                q,
                output_folder,
                headers,
                counter,
                done_file_obj,
                err_file_obj)
            threads.append(t)
            t.start()

        monitor = WorkerMonitor(threads, q)
        monitor.start()

        while True:
            any_alive = False
            for t in threads:
                any_alive = (any_alive or t.is_alive())

            if not any_alive:
                break
            time.sleep(0.5)
            monitor.shutdown_flag.set()
            monitor.join()

    except ServiceExit:
        monitor.shutdown_flag.set()
        monitor.join()
        for t in threads:
            t.shutdown_flag.set()
            t.join()

        all_file_obj.close()
        done_file_obj.close()
        err_file_obj.close()

    # TODO
    # Kill all threads on Ctrl-C
    # otherwise Ctrl-z, ps, kill proc_num


class BlurredOriginalsDownloader(threading.Thread):
    """
    """

    def __init__(self,
                 lock,
                 q,
                 output_folder,
                 headers,
                 counter,
                 done_file,
                 err_file):
        threading.Thread.__init__(self)

        self.counter = counter
        self.done_file = done_file
        self.err_file = err_file
        self.headers = headers
        self.queue = q
        self.lock = lock
        self.output_folder = output_folder
        self.shutdown_flag = threading.Event()
        self.worker_stats = 0

    def download_file(self, image_key, filename):
        download_url = "{}/v3/images/{}/download_original?client_id={}".format(
            MAPILLARY_ENDPOINT,
            image_key,
            uploader.CLIENT_ID)

        response = requests.get(
            download_url, stream=True, headers=self.headers)

        if response.status_code != 200:
            print(response.json())
            return False

        with open(filename, "wb") as f:
            total_length = response.headers.get('content-length')

            dl = 0
            total_length = int(total_length)
            for data in response.iter_content(chunk_size=4096):
                dl += len(data)
                f.write(data)
        return True

    def run(self):
        while not self.shutdown_flag.is_set():
            self.lock.acquire()
            if (self.queue.empty()):
                self.lock.release()
                break

            current_image_key = self.queue.get_nowait()

            image_path = os.path.join(
                self.output_folder, '{}.jpg'.format(current_image_key))

            if not os.path.exists(os.path.dirname(image_path)):
                os.makedirs(os.path.dirname(image_path))

            self.lock.release()

            if not os.path.isfile(image_path):
                success = self.download_file(current_image_key, image_path)
                self.lock.acquire()
                if success:
                    self.counter['ok'] += 1
                    self.done_file.write(current_image_key)
                else:
                    self.counter['err'] += 1
                    self.err_file.write(current_image_key)
                self.lock.release()
            else:
                self.lock.acquire()
                self.counter['ok'] += 1
                self.lock.release()

            self.lock.acquire()
            self.counter['done'] += 1
            self.worker_stats += 1
            count = self.counter['done']
            total = self.queue.maxsize
            self.lock.release()

            if self.queue.empty():
                return


class ServiceExit(Exception):
    pass


def service_shutdown(signum, frame):
    raise ServiceExit
