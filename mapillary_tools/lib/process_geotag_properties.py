import os
import datetime
from dateutil.tz import tzlocal
import time
import processing
import uploader
from exif_read import ExifRead
from geo import normalize_bearing, interpolate_lat_lon
from gps_parser import get_lat_lon_time_from_gpx
from process_video import timestamps_from_filename


def exif_time(filename):
    '''
    Get image capture time from exif
    '''
    metadata = ExifRead(filename)
    return metadata.extract_capture_time()


def estimate_sub_second_time(files, interval):
    '''
    Estimate the capture time of a sequence with sub-second precision
    EXIF times are only given up to a second of precission. This function
    uses the given interval between shots to Estimate the time inside that
    second that each picture was taken.
    '''
    if interval <= 0.0:
        return [exif_time(f) for f in files]

    onesecond = datetime.timedelta(seconds=1.0)
    T = datetime.timedelta(seconds=interval)
    for i, f in enumerate(files):
        m = exif_time(f)
        if i == 0:
            smin = m
            smax = m + onesecond
        else:
            m0 = m - T * i
            smin = max(smin, m0)
            smax = min(smax, m0 + onesecond)

    if smin > smax:
        print('Interval not compatible with EXIF times')
        return None
    else:
        s = smin + (smax - smin) / 2
        return [s + T * i for i in range(len(files))]


def process_geotag_properties(import_path,
                              geotag_source,
                              video_duration,
                              sample_interval,
                              video_start_time,
                              use_gps_start_time,
                              duration_ratio,
                              rerun,
                              offset_time=0.0,
                              local_time=False,
                              interval=0.0,
                              geotag_source_path=None,
                              offset_angle=0,
                              timestamp_from_filename=False,
                              verbose=False):

    # get list of file to process
    process_file_list = processing.get_process_file_list(import_path,
                                                         "geotag_process",
                                                         rerun)
    if verbose:
        processing.inform_processing_start(import_path,
                                           len(process_file_list),
                                           "geotag_process")
    if not len(process_file_list):
        if verbose:
            print("No images to run geotag process")
            print("If the images have already been processed and not yet uploaded, they can be processed again, by passing the argument --rerun")
        return

    # sanity checks
    if geotag_source_path == None and geotag_source != "exif":
        # if geotagging from external log file, path to the external log file
        # needs to be provided, if not, exit
        print("Error, if geotagging from external log, rather than image EXIF, you need to provide full path to the log file.")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "geotag_process"
                                                  "failed",
                                                  verbose)
        return

    elif geotag_source != "exif" and not os.path.isfile(geotag_source_path):
        print("Error, " + geotag_source_path +
              " file source of gps/time properties does not exist. If geotagging from external log, rather than image EXIF, you need to provide full path to the log file.")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "geotag_process"
                                                  "failed",
                                                  verbose)
        return

    if geotag_source == "exif":
        geotag_from_exif(process_file_list,
                         import_path,
                         offset_angle,
                         verbose)
    elif geotag_source == "gpx":
        geotag_from_gpx(process_file_list,
                        import_path,
                        geotag_source_path,
                        offset_time,
                        offset_angle,
                        local_time,
                        interval,
                        timestamp_from_filename,
                        video_duration,
                        sample_interval,
                        video_start_time,
                        use_gps_start_time,
                        duration_ratio,
                        verbose)
    elif geotag_source == "csv":
        geotag_from_csv(process_file_list,
                        import_path,
                        geotag_source_path,
                        offset_time,
                        offset_angle,
                        verbose)
    else:
        geotag_from_json(process_file_list,
                         import_path,
                         geotag_source_path,
                         offset_time,
                         offset_angle,
                         verbose)


def geotag_from_exif(process_file_list,
                     import_path,
                     offset_angle,
                     verbose):
    for image in process_file_list:
        mapillary_description = {}
        try:
            exif = ExifRead(image)
            # required tags
            try:
                lon, lat = exif.extract_lon_lat()
                if lat != None and lon != None:
                    mapillary_description["MAPLatitude"] = lat
                    mapillary_description["MAPLongitude"] = lon
                else:
                    print("Error, " + image + " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information.")
                    processing.create_and_log_process(image,
                                                      import_path,
                                                      "geotag_process",
                                                      "failed",
                                                      verbose=verbose)
                    continue

            except:
                print("Error, " + image +
                      " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information.")
                processing.create_and_log_process(image,
                                                  import_path,
                                                  "geotag_process",
                                                  "failed",
                                                  verbose=verbose)
                continue
            try:
                timestamp = exif.extract_capture_time()
                mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(timestamp,
                                                                                     "%Y_%m_%d_%H_%M_%S_%f")[:-3]
            except:
                print("Error, " + image +
                      " image capture time tag not in EXIF. Geotagging process failed for this image, since this is required information.")
                processing.create_and_log_process(image,
                                                  import_path,
                                                  "geotag_process",
                                                  "failed",
                                                  verbose=verbose)
                continue
            # optional fields
            try:
                mapillary_description["MAPAltitude"] = exif.extract_altitude()
            except:
                if verbose:
                    print("Warning, image altitude tag not in EXIF.")
            try:
                heading = exif.extract_direction()
                if heading is None:
                    heading = 0.0
                heading = normalize_bearing(heading + offset_angle)
                # bearing of the image
                mapillary_description["MAPCompassHeading"] = {"TrueHeading": heading,
                                                              "MagneticHeading": heading}
            except:
                if verbose:
                    print("Warning, image direction tag not in EXIF.")
        except:
            print("Error, EXIF could not be read for image " +
                  image + ", geotagging process failed for this image since gps/time properties not read.")

        processing.create_and_log_process(image,
                                          import_path,
                                          "geotag_process",
                                          "success",
                                          mapillary_description,
                                          verbose)


def geotag_from_gpx(process_file_list,
                    import_path,
                    geotag_source_path,
                    offset_time,
                    offset_angle,
                    local_time,
                    interval,
                    timestamp_from_filename,
                    video_duration,
                    sample_interval,
                    video_start_time,
                    use_gps_start_time,
                    duration_ratio,
                    verbose):
    # set flag for geotagging error
    error_geotaging = 0

    # print time now to warn in case local_time
    if local_time:
        now = datetime.datetime.now(tzlocal())
        if verbose:
            print("Your local timezone is {0}. If not, the geotags will be wrong."
                  .format(now.strftime('%Y-%m-%d %H:%M:%S %Z')))
    else:
        # if not local time to be used, warn UTC will be used
        if verbose:
            print(
                "It is assumed that the image timestamps are in UTC. If not, try using the option --local_time.")

    # read gpx file to get track locations
    gpx = get_lat_lon_time_from_gpx(geotag_source_path,
                                    local_time)

    # Estimate capture time with sub-second precision, reading from image EXIF
    # or estimating from filename
    if timestamp_from_filename:
        if use_gps_start_time or not video_start_time:
            video_start_time = gpx[0][0]

        sub_second_times = timestamps_from_filename(process_file_list,
                                                    video_duration,
                                                    sample_interval,
                                                    video_start_time,
                                                    duration_ratio)
    else:
        sub_second_times = estimate_sub_second_time(process_file_list,
                                                    interval)
    if not sub_second_times:
        print("Error, capture times could not be estimated to sub second precision, images can not be geotagged.")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "geotag_process"
                                                  "failed",
                                                  verbose)
        return

    if not gpx:
        print("Error, gpx file was not read, images can not be geotagged.")
        processing.create_and_log_process_in_list(process_file_list,
                                                  import_path,
                                                  "geotag_process"
                                                  "failed",
                                                  verbose)
        return

    for image, capture_time in zip(process_file_list,
                                   sub_second_times):
        mapillary_description = {}
        capture_time = capture_time - \
            datetime.timedelta(seconds=offset_time)
        try:
            lat, lon, bearing, elevation = interpolate_lat_lon(gpx,
                                                               capture_time)
        except:
            print("Image capture time not in scope of the gpx file.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "geotag_process",
                                              "failed",
                                              verbose=verbose)
            continue

        corrected_bearing = (bearing + offset_angle) % 360

        if lat != None and lon != None:
            mapillary_description["MAPLatitude"] = lat
            mapillary_description["MAPLongitude"] = lon
        else:
            print("Error, " + image + " image latitude or longitude tag not in EXIF. Geotagging process failed for this image, since this is required information.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "geotag_process",
                                              "failed",
                                              verbose=verbose)
            continue

        if capture_time:
            mapillary_description["MAPCaptureTime"] = datetime.datetime.strftime(capture_time,
                                                                                 "%Y_%m_%d_%H_%M_%S_%f")[:-3]
        else:
            print("Error, " + image +
                  " image capture time tag not in EXIF. Geotagging process failed for this image, since this is required information.")
            processing.create_and_log_process(image,
                                              import_path,
                                              "geotag_process",
                                              "failed",
                                              verbose=verbose)
            continue

        if elevation:
            mapillary_description["MAPAltitude"] = elevation
        else:
            if verbose:
                print("Warning, image altitude tag not set.")
        if corrected_bearing:
            mapillary_description["MAPCompassHeading"] = {
                "TrueHeading": corrected_bearing, "MagneticHeading": corrected_bearing}
        else:
            if verbose:
                print("Warning, image direction tag not set.")

        processing.create_and_log_process(image,
                                          import_path,
                                          "geotag_process",
                                          "success",
                                          mapillary_description,
                                          verbose=verbose)


def geotag_from_csv(process_file_list,
                    import_path,
                    offset_angle,
                    geotag_source_path,
                    verbose):
    pass


def geotag_from_json(process_file_list,
                     import_path,
                     offset_angle,
                     geotag_source_path,
                     verbose):
    pass
