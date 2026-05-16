from __future__ import annotations
import sys
import os
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_dir = os.path.dirname(src_dir)
sys.path.append(project_dir)

import datetime as dt
import io
import json
import mimetypes
import pathlib

import pandas as pd
import requests
import yaml
from google.cloud import storage
from google.cloud.exceptions import Conflict, ServerError
from google.cloud.storage import transfer_manager

# from loguru import logger
# from source.utils.common_helper import read_file, FileFormat, regex_extract_date

STORAGE_CLASSES = ("STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE")


class GCStorageException(Exception):
    pass


import os
class GCStorage:
    def __init__(self, json_credentials_path: str = "") -> None:
        # if not json_credentials_path:
        #     gcp_config = read_file("configs/secrets.yaml", FileFormat.YAML)
        #     json_credentials_path = f"{(pathlib.Path().resolve())}/{gcp_config['credentials_file']}"
        self.client = storage.Client.from_service_account_json(json_credentials_path)

    def create_bucket(
        self,
        bucket_name,
        storage_class=STORAGE_CLASSES[0],
        bucket_location="ASIA-SOUTHEAST1",
    ):
        bucket = self.client.bucket(bucket_name)
        bucket.storage_class = storage_class
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        bucket.iam_configuration.public_access_prevention = "enforced"
        try:
            return self.client.create_bucket(bucket, location=bucket_location)
        except Conflict:
            print(f"Conflict: [Warning] >>> Bucket already exists: {bucket_name}")

    def get_bucket(self, bucket_name):
        return self.client.get_bucket(bucket_name)

    def list_buckets(self):
        buckets = self.client.list_buckets()

        return [bucket.name for bucket in buckets]

    def upload_file(self, bucket, blob_destination, file_path, format):
        blob = bucket.blob(blob_destination)

        if format == "json":
            content_type = "application/json"
        elif format == "parquet":
            content_type = "application/octet-stream"
        else:
            content_type = mimetypes.guess_type(file_path)[0]

        blob.upload_from_filename(file_path, content_type=content_type)

    def upload_many_blobs_with_transfer_manager(self, bucket_name, prefix, filenames, source_directory="", workers=8):
        """Upload every file in a list to a bucket, concurrently in a process pool.

        Each blob name is derived from the filename, not including the
        `source_directory` parameter. For complete control of the blob name for each
        file (and other aspects of individual blob metadata), use
        transfer_manager.upload_many() instead.
        """

        # The ID of your GCS bucket
        # bucket_name = "your-bucket-name"

        # A list (or other iterable) of filenames to upload.
        # filenames = ["file_1.txt", "file_2.txt"]

        # The directory on your computer that is the root of all of the files in the
        # list of filenames. This string is prepended (with os.path.join()) to each
        # filename to get the full path to the file. Relative paths and absolute
        # paths are both accepted. This string is not included in the name of the
        # uploaded blob; it is only used to find the source files. An empty string
        # means "the current working directory". Note that this parameter allows
        # directory traversal (e.g. "/", "../") and is not intended for unsanitized
        # end user input.
        # source_directory=""

        # The maximum number of processes to use for the operation. The performance
        # impact of this value depends on the use case, but smaller files usually
        # benefit from a higher number of processes. Each additional process occupies
        # some CPU and memory resources until finished. Threads can be used instead
        # of processes by passing `worker_type=transfer_manager.THREAD`.
        # workers=8

        bucket = self.client.bucket(bucket_name)

        results = transfer_manager.upload_many_from_filenames(
            bucket, filenames, blob_name_prefix=prefix, source_directory=source_directory, max_workers=workers, worker_type=transfer_manager.THREAD
        )
        print(f"Uploaded {len(filenames)}/{len(results)} to bucket `{bucket.name}` at prefix `{prefix}`.")
        for name, result in zip(filenames, results):
            # The results list is either `None` or an exception for each filename in
            # the input list, in order.

            if isinstance(result, Exception):
                print(f"Failed to upload {name} due to exception: {result}")
            else:
                # print(f"Uploaded {name} to bucket `{bucket.name}` at prefix `{prefix}`.")
                pass

    def upload_data(self, bucket, prefix, file_name, data, format="json", add_date_folder=False):
        try:
            if add_date_folder:
                date_folder = dt.datetime.now().strftime("%Y-%m-%d")
                prefix = pathlib.Path(prefix).joinpath(date_folder)
            if prefix is not None:
                blob_destination = pathlib.Path(prefix).joinpath(f"{file_name}.{format}").as_posix()
            else:
                blob_destination = pathlib.Path(f"{file_name}.{format}").as_posix()
            blob = bucket.blob(blob_destination)

            if format == "json":
                blob.upload_from_string(json.dumps(data, ensure_ascii=False), "application/json", timeout=6000)
            elif format == "parquet":
                if isinstance(data, dict):
                    df = pd.DataFrame([data])
                elif isinstance(data, list):
                    df = pd.DataFrame(data)
                else:
                    raise TypeError(f"Invalid data type for parquet format: {type(data)}")
                blob.upload_from_string(df.to_parquet(), "application/octet-stream")
            elif format == "jpg":
                blob.upload_from_string(data, content_type="image/jpeg")
                return blob.public_url
            else:
                raise ValueError(f"Unsupported format: {format}")

            # logger.info(f"Uploaded file ➡ GCS: {blob_destination}")
            print(f"Uploaded file ➡ GCS: {blob_destination}")
        except ServerError as e:
            print(f"Server error when uploading file {file_name}: {e}")
        except Exception as e:
            print(f"Something wrong when upload data: {e}")
            
    def list_blobs(self, bucket):
        return self.client.list_blobs(bucket)

    def get_latest_folder(self, bucket, prefix):
        blobs = bucket.list_blobs(prefix=prefix)
        sub_folders = []
        for blob in blobs:
            sub_folder = blob.name.split("/")[-2]
            if sub_folder not in sub_folders:
                try:
                    dt.datetime.strptime(sub_folder, "%Y-%m-%d")
                    sub_folders.append(sub_folder)
                except Exception:
                    pass
        # sub_folders.pop(0)
        if len(sub_folders) > 0:
            sub_folders.sort(reverse=False)
            return sub_folders[-1]
        print(f"Do not have latest folder in: {prefix}")
        return None

    def get_file(self, bucket, prefix, file_name, format="json"):
        """
        Download a file from a Google Cloud Storage bucket as a string.

        Parameters:
        bucket (Bucket): The Google Cloud Storage bucket.
        path (str): The path to the file within the bucket.

        Returns:
        str: The contents of the file as a string.
        """
        if isinstance(bucket, str):
            bucket = self.client.get_bucket(bucket)

        blob_name = f"{pathlib.Path(prefix).joinpath(file_name)}"
        try:
            blob = bucket.blob(blob_name)
            data = blob.download_as_string().decode("utf-8")
            if format == "json":
                data = json.loads(data)
            elif format == "yaml":
                data = yaml.safe_load(data)
            else:
                raise ValueError(f"Unsupported format: {format}")
            return data
        except Exception as e:
            print(f"Error at get_file: {e}")

    def fetch_data(self, bucket, prefix, format, return_type="dataframe"):
        print(isinstance(bucket, str))
        if isinstance(bucket, str):
            bucket = self.client.get_bucket(bucket)
        blobs = bucket.list_blobs(prefix=prefix)

        datas = []
        for blob in blobs:
            if blob.name in prefix or blob.name[:-1] in prefix:
                continue
            if format == "json":
                # first way
                data = blob.download_as_string()
                if return_type == "dataframe":
                    datas.append(pd.DataFrame(json.loads(data)))
                else:
                    datas.append(json.loads(data))
               
            elif format == "parquet":
                data = blob.download_as_bytes()
                pq_data = io.BytesIO(data)
                datas.append(pd.read_parquet(pq_data))

        if return_type == "dataframe":
            return pd.concat(datas)
        else:
            if len(datas) == 1:
                return datas[0]
            return datas

    def list_date_prefixes(self, bucket, prefix, start_date="2023-01-01", end_date="2099-01-01"):
        destination_bucket = self.client.get_bucket(bucket)
        destination_blobs = destination_bucket.list_blobs(prefix=prefix, delimiter="/")

        for _ in destination_blobs:
            pass

        destination_prefixes = [blob.replace(prefix, "") for blob in destination_blobs.prefixes]

        folders = sorted([dprefix for dprefix in destination_prefixes if dprefix[:7] >= "2023-10"])
        inter_paths = []
        for folder in folders:
            date_folder = regex_extract_date(folder)
            if date_folder and date_folder >= start_date and date_folder <= end_date:
                inter_paths.append(f"gs://{bucket}/{prefix}{folder}")

        return inter_paths

    def find_unexist_folders(self, bucket_src, bucket_dest, prefix_src, prefix_dest, start_date="2023-10-01"):
        source_bucket = self.client.get_bucket(bucket_src)
        source_blobs = source_bucket.list_blobs(prefix=prefix_src, delimiter="/")

        destination_bucket = self.client.get_bucket(bucket_dest)
        destination_blobs = destination_bucket.list_blobs(prefix=prefix_dest, delimiter="/")

        for _ in source_blobs:
            pass

        for _ in destination_blobs:
            pass
        source_prefixes = [blob.replace(prefix_src, "") for blob in source_blobs.prefixes]
        destination_prefixes = [blob.replace(prefix_dest, "") for blob in destination_blobs.prefixes]

        unexist_folders = sorted(
            [prefix for prefix in source_prefixes if prefix[:10] >= start_date and prefix not in destination_prefixes]
        )

        return unexist_folders

    def download_file(self, bucket_name: str, blob_path: str, local_path: str) -> dict:
        """
        Download 1 file từ GCS về local.

        Returns:
            dict: {
                "status": "success" | "not_found" | "error",
                "bucket": bucket_name,
                "blob": blob_path,
                "local": local_path,
                "error": None hoặc lỗi
            }
        """
        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            if not blob.exists():
                return {
                    "status": "not_found",
                    "bucket": bucket_name,
                    "blob": blob_path,
                    "local": local_path,
                    "error": None
                }

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            blob.download_to_filename(local_path)

            return {
                "status": "success",
                "bucket": bucket_name,
                "blob": blob_path,
                "local": local_path,
                "error": None
            }

        except Exception as e:
            return {
                "status": "error",
                "bucket": bucket_name,
                "blob": blob_path,
                "local": local_path,
                "error": str(e)
            }



def main():
    # Initialize instance
    json_credentials_path = "/path/to/GCPKey.json"
    gcs = GCStorage(json_credentials_path)

    # List bucket
    print(gcs.list_buckets())

    # Create bucket
    bucket_name = "0_test_class"
    if bucket_name not in gcs.list_buckets():
        bucket = gcs.create_bucket(bucket_name)

    # WARNING: Conflict, bucket already existed
    # bucket = gcs.create_bucket(bucket_name)

    # Get bucket
    bucket = gcs.get_bucket("0_test_zone")
    print(bucket.name)

    # Upload file
    files_folder = pathlib.Path("/path/to/data/folder")

    for file_path in files_folder.glob("*.*"):
        format = str(file_path.name.split(".")[-1])
        gcs.upload_file(bucket, f"sub_folder/{file_path.name}", str(file_path), format)
        gcs.upload_file(bucket, file_path.name, str(file_path), format)

    # Upload data object
    format = "parquet"
    for i in range(1, 10):
        r = requests.get(f"https://jsonplaceholder.typicode.com/posts/{i}")

        json_data = r.json()
        gcs.upload_data(bucket, f"sub_test/{i}_post.{format}", json_data, format)

    # List blobs in bucket
    for blob in gcs.list_blobs(bucket):
        print(blob.name)

    base_folder = "6_thanh/6_thanh_raw_data/shopee_platform/sales_data/VN"
    # Get newest folder
    latest_folder = gcs.get_latest_folder(bucket, base_folder)
    print(latest_folder)

    prefix = f"{base_folder}/{latest_folder}"
    # Fetch data
    df = gcs.fetch_data(bucket, prefix, format="json")
    print(df.shape, list(df))


def test():
    json_credentials_path = "configs/scraper/shopee/GCPKey.json"
    gcs = GCStorage(json_credentials_path)

    bucket = gcs.get_bucket("0_test_zone")
    data = {"sd": "sdsd"}
    gcs.upload_data(
        bucket,
        "7_tai/7_tai_raw-data/test",
        "test.json",
        data,
        "json",
        add_date_folder=True,
    )


if __name__ == "__main__":
    test()