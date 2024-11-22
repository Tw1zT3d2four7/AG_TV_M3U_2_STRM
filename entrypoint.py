#!/usr/bin/env python3

import json
import logging
import os
import re
import sys
import threading
from time import sleep, time

import requests as requests

from consts import (
    AGTV_FILE,
    APOLLO_GROUP_TV_BASE_URL,
    BREAK_LINE,
    CLEAN_CHARS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TV_SHOWS_PAGES,
    EMPTY_STRING,
    ENV_AGTV_MAX_TV_SHOWS_PAGES,
    ENV_AGTV_PASSWORD,
    ENV_AGTV_USERNAME,
    ENV_DEBUG,
    ENV_SCAN_INTERVAL,
    ENV_TMDB_API_KEY,
    EXTRACT_KEYS,
    IMDB_ID,
    LOG_FORMAT,
    M3U_EXT_INF,
    MAX_THREADS_IO,
    MAX_THREADS_NO_IO,
    MOVIES_URL,
    STREAM_EPISODE,
    STREAM_FILE_MEDIA_PATH,
    STREAM_FILE_TMDB,
    STREAM_FILES,
    STREAM_SEASON,
    STREAM_STATUS,
    STREAM_STATUS_EXISTS,
    STREAM_STATUS_FAULT,
    STREAM_STATUS_MODIFIED,
    STREAM_STATUS_NEW,
    STREAM_STATUS_READY,
    STREAM_TV_VALIDATION_POSITIONS,
    STREAM_TV_VALIDATIONS,
    STREAM_URL,
    STREAMS_FILE,
    TMDB_FILE,
    TMDB_MEDIA_FIRST_AIR_DATE,
    TMDB_MEDIA_NAME,
    TMDB_MEDIA_RELEASE_DATE,
    TMDB_MEDIA_TITLE,
    TMDB_MEDIA_TYPE,
    TMDB_MEDIA_TYPE_MOVIE,
    TMDB_MEDIA_TYPE_TV_SHOW,
    TMDB_MEDIA_TYPES,
    TV_SHOWS_URL,
)

DEBUG = str(os.environ.get(ENV_DEBUG, False)).lower() == str(True).lower()

log_level = logging.DEBUG if DEBUG else logging.INFO

root = logging.getLogger()
root.setLevel(log_level)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(log_level)
formatter = logging.Formatter(LOG_FORMAT)
stream_handler.setFormatter(formatter)
root.addHandler(stream_handler)

_LOGGER = logging.getLogger(__name__)


class MediaSyncManager:
    def __init__(self):
        self._max_tv_shows_pages: int = int(
            str(os.environ.get(ENV_AGTV_MAX_TV_SHOWS_PAGES, DEFAULT_TV_SHOWS_PAGES))
        )
        self._username: str = os.environ.get(ENV_AGTV_USERNAME)
        self._password: str = os.environ.get(ENV_AGTV_PASSWORD)
        self._tmdb_api_key: str | None = os.environ.get(ENV_TMDB_API_KEY)
        self._scan_interval = int(
            str(os.environ.get(ENV_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        )

        self._is_ready = self._username is not None and self._password is not None
        self._semaphore_io = threading.Semaphore(value=MAX_THREADS_IO)
        self._semaphore_no_io = threading.Semaphore(value=MAX_THREADS_NO_IO)
        self._tmdb_data = {}
        self._streams_data = {}
        self._agtv_data = {}
        self._endpoints = []
        self._reported_as_fault = []
        self._process_number = 0
        self._has_cache = False

        self._headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self._tmdb_api_key}",
        }

    def initialize(self):
        if self._is_ready:
            _LOGGER.info("Initializing AGTV2STRM")

            self._load_tmdb_file()
            self._load_streams_file()

            self._endpoints = [
                f"{TV_SHOWS_URL}/{i + 1}" for i in range(0, self._max_tv_shows_pages)
            ]

            self._endpoints.append(MOVIES_URL)

            while True:
                self._process()

                sleep(60 * self._scan_interval)

        else:
            _LOGGER.error("Failed to initialize AGTV2STRM, Please set credentials")

    def _process(self):
        self._process_number += 1

        start_time = time()

        self._load_agtv_data()
        self._extract_streams()
        self._load_tmdb_data()
        self._merge_tmdb_into_streams()
        self._prepare_directories()
        self._finalize_stream_files()
        self._fault_report()

        execution_time = time() - start_time

        _LOGGER.info(f"Complete processing, Duration: {execution_time:.3f} seconds")

    def _load_agtv_data(self):
        start_time = time()
        _LOGGER.info("Loading Apollo Group TV lists")

        threads = []

        for endpoint in self._endpoints:
            thread = threading.Thread(target=self._load_endpoint_data, args=[endpoint])
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self._save_agtv_file()

        execution_time = time() - start_time

        _LOGGER.info(
            f"Loaded {len(self._endpoints)} lists, Duration: {execution_time:.3f} seconds"
        )

    def _load_endpoint_data(self, endpoint):
        self._semaphore_io.acquire()

        try:
            _LOGGER.debug(f"Load endpoint data, Endpoint: {endpoint}")

            url = f"{APOLLO_GROUP_TV_BASE_URL}/{self._username}/{self._password}/{endpoint}"

            response = requests.get(url)

            if response.ok:
                content = response.text
                lines = content.split(BREAK_LINE)

                self._agtv_data[endpoint] = lines

                _LOGGER.debug(f"Endpoint '{endpoint}' data loaded, Lines: {len(lines)}")

        except Exception as ex:
            exc_type, exc_obj, exc_tb = sys.exc_info()

            _LOGGER.error(
                f"Failed to load endpoint data, Endpoint: {endpoint}, Error: {ex}, Line: {exc_tb.tb_lineno}"
            )

        self._semaphore_io.release()

    def _extract_streams(self):
        start_time = time()
        _LOGGER.info("Extract streams from Apollo Group TV lists")

        threads = []
        for name in self._agtv_data:
            thread = threading.Thread(
                target=self._extract_streams_from_list, args=[name]
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self._save_file(STREAMS_FILE, json.dumps(self._streams_data, indent=4))

        execution_time = time() - start_time

        _LOGGER.info(
            f"Extracted {len(self._streams_data.keys()):,} streams, Duration: {execution_time:.3f} seconds"
        )

    def _extract_streams_from_list(self, name):
        self._semaphore_no_io.acquire()

        try:
            lines = self._agtv_data[name]

            for line_number in range(0, len(lines)):
                line_content = lines[line_number]

                if line_content.startswith(M3U_EXT_INF):
                    stream_info = line_content.replace(BREAK_LINE, EMPTY_STRING)
                    url = lines[line_number + 1].replace(BREAK_LINE, EMPTY_STRING)

                    if self._verify_url(url):
                        self._add_stream_info(stream_info, url)

                    else:
                        _LOGGER.warning(
                            f"Invalid media URL for stream: {stream_info}, URL: {url}"
                        )

        except Exception as ex:
            exc_type, exc_obj, exc_tb = sys.exc_info()

            _LOGGER.error(
                f"Failed to add stream, Error: {ex}, Line: {exc_tb.tb_lineno}"
            )

        self._semaphore_no_io.release()

    def _add_stream_info(self, stream_info, media_url):
        stream_data = self._get_stream_info(stream_info)
        imdb_id = stream_data.get(IMDB_ID)

        stream_id = self._get_stream_key(stream_data)

        current_stream_data = self._streams_data.get(stream_id)

        if current_stream_data is None:
            _LOGGER.debug(f"Add new stream '{stream_id}', URL: {media_url}")

            stream_data[STREAM_URL] = media_url

        else:
            existing_url = current_stream_data.get(STREAM_URL)
            was_modified = existing_url != media_url

            if was_modified:
                _LOGGER.debug(
                    f"Update stream '{stream_id}', URL: {media_url} | {existing_url}"
                )

                stream_data.update(
                    {STREAM_STATUS: STREAM_STATUS_MODIFIED, STREAM_URL: media_url}
                )

            else:
                _LOGGER.debug(f"Stream '{stream_id}' already exists")

                stream_data = current_stream_data

        self._streams_data[stream_id] = stream_data

        is_stream_fault = (
            stream_data.get(STREAM_STATUS, STREAM_STATUS_NEW) == STREAM_STATUS_FAULT
        )
        in_tmdb_list = imdb_id in self._tmdb_data

        if is_stream_fault and in_tmdb_list:
            self._tmdb_data.pop(imdb_id)

        elif not is_stream_fault and not in_tmdb_list:
            self._tmdb_data[imdb_id] = None

    def _load_tmdb_data(self):
        start_time = time()
        _LOGGER.info("Load TMDB data")

        threads = []
        tmdb_data_items = [
            tmdb_id
            for tmdb_id in self._tmdb_data
            if tmdb_id not in self._tmdb_data or self._tmdb_data.get(tmdb_id) is None
        ]

        for imdb_id in tmdb_data_items:
            thread = threading.Thread(target=self._load_tmdb_media_data, args=[imdb_id])
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self._save_file(TMDB_FILE, json.dumps(self._tmdb_data, indent=4))

        execution_time = time() - start_time

        _LOGGER.info(
            f"Loaded {len(tmdb_data_items):,} items from TMDB, Duration: {execution_time:.3f} seconds"
        )

    def _load_tmdb_media_data(self, imdb_id):
        self._semaphore_io.acquire()

        try:
            _LOGGER.debug(f"Loading TMDB data for {imdb_id}")

            url = f"https://api.themoviedb.org/3/find/{imdb_id}?external_source=imdb_id"

            response = requests.get(url, headers=self._headers)
            data = response.json()

            if data.get("success", True):
                for media_type in TMDB_MEDIA_TYPES:
                    data_objects = data.get(f"{media_type}_results")

                    if data_objects is not None and len(data_objects) > 0:
                        data_object = data_objects[0]

                        self._tmdb_data[imdb_id] = data_object

            _LOGGER.debug(f"Loaded TMDB data for {imdb_id}, Data: {data}")

        except Exception as ex:
            exc_type, exc_obj, exc_tb = sys.exc_info()

            _LOGGER.error(
                f"Failed to enrich media data, IMDB ID: {imdb_id}, Error: {ex}, Line: {exc_tb.tb_lineno}"
            )

        self._semaphore_io.release()

    def _merge_tmdb_into_streams(self):
        start_time = time()
        _LOGGER.info("Merging TMDB data into streams")

        threads = []
        relevant_streams = [
            stream_id
            for stream_id in self._streams_data
            if self._can_merge_tmdb_into_stream(stream_id)
        ]

        for stream_id in relevant_streams:
            thread = threading.Thread(
                target=self._merge_tmdb_into_stream, args=[stream_id]
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self._save_file(STREAMS_FILE, json.dumps(self._streams_data, indent=4))

        execution_time = time() - start_time

        _LOGGER.info(
            f"Merged {len(relevant_streams):,} streams from TMDB data, Duration: {execution_time:.3f} seconds"
        )

    def _can_merge_tmdb_into_stream(self, stream_id):
        stream_info = self._streams_data[stream_id]

        has_data = (
            TMDB_MEDIA_RELEASE_DATE in stream_info and TMDB_MEDIA_TITLE in stream_info
        )
        stream_status = stream_info.get(STREAM_STATUS, STREAM_STATUS_NEW)
        not_ready = stream_status in [STREAM_STATUS_NEW, STREAM_STATUS_MODIFIED]

        can_merge = not_ready and not has_data

        return can_merge

    def _merge_tmdb_into_stream(self, stream_id):
        self._semaphore_no_io.acquire()

        try:
            stream_info = self._streams_data[stream_id]

            imdb_id = stream_info.get(IMDB_ID)
            tmdb_info = self._tmdb_data.get(imdb_id)

            if tmdb_info is None:
                _LOGGER.debug(f"Unable to process media {imdb_id}")

            else:
                media_type = tmdb_info.get(TMDB_MEDIA_TYPE)

                title_key: str | None = None
                release_date_key: str | None = None
                stream_status: str = STREAM_STATUS_READY

                if media_type == TMDB_MEDIA_TYPE_TV_SHOW:
                    title_key = TMDB_MEDIA_NAME
                    release_date_key = TMDB_MEDIA_FIRST_AIR_DATE

                    if STREAM_SEASON not in stream_info:
                        stream_status = STREAM_STATUS_FAULT

                elif media_type == TMDB_MEDIA_TYPE_MOVIE:
                    title_key = TMDB_MEDIA_TITLE
                    release_date_key = TMDB_MEDIA_RELEASE_DATE

                else:
                    _LOGGER.error(
                        f"Unsupported media type, Info: {stream_info}, TMDB: {tmdb_info}"
                    )

                media_title = tmdb_info.get(title_key)
                media_release_date = tmdb_info.get(release_date_key)

                if media_type in [TMDB_MEDIA_TYPE_TV_SHOW, TMDB_MEDIA_TYPE_MOVIE]:
                    stream_info[TMDB_MEDIA_TYPE] = media_type
                    stream_info[TMDB_MEDIA_TITLE] = media_title
                    stream_info[TMDB_MEDIA_RELEASE_DATE] = media_release_date
                    stream_info[STREAM_STATUS] = stream_status

                    if (
                        stream_status != STREAM_STATUS_FAULT
                        and STREAM_FILES not in stream_info
                    ):
                        release_date_parts = media_release_date.split("-")
                        year = release_date_parts[0]
                        root_path = self._clean_name(f"{media_title} ({year})")

                        agtv_media_type = TMDB_MEDIA_TYPES.get(media_type)
                        stream_path: str | None = f"{root_path}/{root_path}"

                        if media_type == TMDB_MEDIA_TYPE_TV_SHOW:
                            season = stream_info.get(STREAM_SEASON)
                            episode = stream_info.get(STREAM_EPISODE)

                            season_name = season.replace("S", "Season ")
                            stream_path = f"{stream_path} - {season_name}/{root_path} - {season}{episode}"

                        tmdb_path = (
                            f"media/{agtv_media_type}/{root_path}/{root_path}.json"
                        )
                        media_path = f"media/{agtv_media_type}/{stream_path}.strm"

                        stream_info[STREAM_FILES] = {
                            STREAM_FILE_TMDB: tmdb_path,
                            STREAM_FILE_MEDIA_PATH: media_path,
                        }

        except Exception as ex:
            exc_type, exc_obj, exc_tb = sys.exc_info()

            _LOGGER.error(
                f"Failed to merge TMDB into stream, ID: {stream_id}, Error: {ex}, Line: {exc_tb.tb_lineno}"
            )

        self._semaphore_no_io.release()

    def _prepare_directories(self):
        start_time = time()
        _LOGGER.info("Preparing directories")

        media_directories = []

        relevant_streams = [
            stream_id
            for stream_id in self._streams_data
            if self._is_ready_stream(stream_id)
        ]

        for stream_id in relevant_streams:
            stream_info = self._streams_data[stream_id]
            stream_files = stream_info.get(STREAM_FILES)
            media_path = stream_files.get(STREAM_FILE_MEDIA_PATH)

            media_path_parts = media_path.split("/")
            media_directory_parts = media_path_parts[:-1]
            media_directory = "/".join(media_directory_parts)

            if media_directory not in media_directories:
                media_directories.append(media_directory)

        for media_directory in media_directories:
            self._prepare_directory(media_directory)

        execution_time = time() - start_time

        _LOGGER.info(
            f"Created {len(media_directories):,} unique directories, Duration: {execution_time:.3f} seconds"
        )

    def _is_ready_stream(self, stream_id):
        stream_info = self._streams_data[stream_id]

        stream_status = stream_info.get(STREAM_STATUS, STREAM_STATUS_NEW)

        is_ready = stream_status == STREAM_STATUS_READY

        return is_ready

    def _finalize_stream_files(self):
        start_time = time()
        _LOGGER.info("Finalizing stream files")

        threads = []
        relevant_streams = [
            stream_id
            for stream_id in self._streams_data
            if self._is_ready_stream(stream_id)
        ]

        for stream_id in relevant_streams:
            thread = threading.Thread(target=self._update_stream_file, args=[stream_id])
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self._save_file(STREAMS_FILE, json.dumps(self._streams_data, indent=4))

        execution_time = time() - start_time

        _LOGGER.info(
            f"Finalized {len(relevant_streams):,} stream files, Duration: {execution_time:.3f} seconds"
        )

    def _update_stream_file(self, stream_id):
        self._semaphore_no_io.acquire()

        try:
            stream_info = self._streams_data[stream_id]
            imdb_id = stream_info.get(IMDB_ID)
            stream_files = stream_info.get(STREAM_FILES)
            media_url = stream_info.get(STREAM_URL)

            media_path = stream_files.get(STREAM_FILE_MEDIA_PATH)
            tmdb_path = stream_files.get(STREAM_FILE_TMDB)

            tmdb_info = self._tmdb_data.get(imdb_id)

            if media_url is None:
                _LOGGER.error(f"Media URL is empty, Stream: {stream_info}")
            else:
                self._save_file(media_path, media_url)

            self._save_file(tmdb_path, json.dumps(tmdb_info, indent=4))

            if self._has_cache or self._process_number > 1:
                title = stream_info.get(TMDB_MEDIA_TITLE)
                media_type = stream_info.get(TMDB_MEDIA_TYPE)
                status: str = stream_info.get(STREAM_STATUS)

                message_parts = [""]

                if media_type == TMDB_MEDIA_TYPE_TV_SHOW:
                    season = stream_info.get(STREAM_SEASON)
                    episode = stream_info.get(STREAM_EPISODE)
                    additional_info = f"Season {season}, Episode {episode}"

                    message_parts.append(additional_info)

                message = " ".join(message_parts)

                _LOGGER.info(
                    f"{status.capitalize()} {media_type}: {title} [{imdb_id}]{message}"
                )

            stream_info[STREAM_STATUS] = STREAM_STATUS_EXISTS

        except Exception as ex:
            exc_type, exc_obj, exc_tb = sys.exc_info()

            _LOGGER.error(
                f"Failed to update stream file, ID: {stream_id}, Error: {ex}, Line: {exc_tb.tb_lineno}"
            )

        self._semaphore_no_io.release()

    def _fault_report(self):
        for reported_stream_id in self._reported_as_fault:
            reported_stream_info = self._streams_data.get(reported_stream_id)
            reported_stream_status = reported_stream_info.get(STREAM_STATUS)

            if reported_stream_status != STREAM_STATUS_FAULT:
                self._reported_as_fault.remove(reported_stream_id)

        relevant_streams = [
            stream_id
            for stream_id in self._streams_data
            if self._is_fault_stream(stream_id)
        ]

        for stream_id in relevant_streams:
            stream_info = self._streams_data.get(stream_id)

            self._reported_as_fault.append(stream_id)

            _LOGGER.warning(
                f"Stream {stream_id} was ignored due to invalid data, Data: {stream_info}"
            )

    def _is_fault_stream(self, stream_id):
        stream_info = self._streams_data[stream_id]

        stream_status = stream_info.get(STREAM_STATUS, STREAM_STATUS_NEW)

        is_fault = stream_status == STREAM_STATUS_FAULT
        reported = stream_id in self._reported_as_fault

        return is_fault and not reported

    @staticmethod
    def _get_stream_key(stream_info) -> str:
        parts = [stream_info[key] for key in stream_info if key != STREAM_STATUS]

        return "_".join(parts)

    @staticmethod
    def _get_stream_info(stream_info) -> dict:
        info_parts = stream_info.split(" ")
        data = {STREAM_STATUS: STREAM_STATUS_NEW}

        for info_part in info_parts:
            if '="' in info_part:
                data_item_parts = info_part.split("=")
                key = data_item_parts[0]
                value = data_item_parts[1].replace('"', "")

                if key in EXTRACT_KEYS:
                    data[key] = value

        for key in STREAM_TV_VALIDATION_POSITIONS:
            position = STREAM_TV_VALIDATION_POSITIONS[key]
            validation = STREAM_TV_VALIDATIONS[key]

            value = info_parts[len(info_parts) + position]

            if re.compile(validation).search(value):
                data[key] = value

        return data

    @staticmethod
    def _verify_url(line):
        match = re.compile("://").search(line)
        if match:
            return True

        return

    @staticmethod
    def _clean_name(title) -> str:
        for key in CLEAN_CHARS:
            if key in title:
                title = title.replace(key, CLEAN_CHARS[key])

        return title

    def _save_streams_file(self):
        self._save_file(STREAMS_FILE, json.dumps(self._streams_data, indent=4))

    def _save_tmdb_file(self):
        self._save_file(STREAMS_FILE, json.dumps(self._tmdb_data, indent=4))

    def _save_agtv_file(self):
        self._save_file(AGTV_FILE, json.dumps(self._agtv_data, indent=4))

    def _load_streams_file(self):
        if os.path.exists(STREAMS_FILE):
            with open(STREAMS_FILE, encoding="UTF-8") as f:
                self._streams_data = json.loads(f.read())

                self._has_cache = True

    def _load_tmdb_file(self):
        if os.path.exists(TMDB_FILE):
            with open(TMDB_FILE, encoding="UTF-8") as f:
                self._tmdb_data = json.loads(f.read())

    @staticmethod
    def _prepare_directory(directory_path):
        if not os.path.exists(directory_path):
            directory_path_parts = directory_path.split("/")
            current_path = "."

            for directory_path_part in directory_path_parts:
                current_path = f"{current_path}/{directory_path_part}"

                if not os.path.exists(current_path):
                    os.mkdir(current_path)

    def _save_file(self, file_path, content):
        file_path_parts = file_path.split("/")
        directory_path = "/".join(file_path_parts[:-1])

        self._prepare_directory(directory_path)

        with open(file_path, "w+", encoding="UTF-8") as f:
            f.write(content)


manager = MediaSyncManager()
manager.initialize()
