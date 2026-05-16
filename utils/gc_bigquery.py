from __future__ import annotations
import os
import sys

src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_dir = os.path.dirname(src_dir)
sys.path.append(project_dir)

import io
import pathlib
import polars as pl

from google.cloud import bigquery
# from utils.helper import read_file, FileFormat
from loguru import logger
from google.auth import exceptions

class GCBigquery:
    def __init__(self, json_credentials_path: str = "") -> None:
        self.client = bigquery.Client.from_service_account_json(json_credentials_path)

    def execute_query(self, query) -> pl.DataFrame:
        query_job = self.client.query(query)
        df = pl.from_arrow(query_job.result().to_arrow())
        if isinstance(df, pl.Series):
            df = df.to_frame()
        return df

    def update_with_dml(self, query):
        query_job = self.client.query(query)
        # Wait for query job to finish.
        query_job.result()

        assert query_job.num_dml_affected_rows is not None

        print(f"DML query modified {query_job.num_dml_affected_rows} rows.")
        return query_job.num_dml_affected_rows

    def upload_dataframe(
        self, df, project: str, destination: str, format: str, mode: str, schema=None, use_legacy=True
    ):
        print("Uploading dataframe to BigQuery...")
        print(df)
        if mode == "append":
            mode = bigquery.WriteDisposition.WRITE_APPEND
        elif mode == "overwrite":
            mode = bigquery.WriteDisposition.WRITE_TRUNCATE
        else:
            mode = bigquery.WriteDisposition.WRITE_EMPTY

        with io.BytesIO() as stream:
            if format == "parquet":
                df.write_parquet(stream)
            elif format == "csv":
                df.write_csv(stream)
            elif format == "json":
                df.write_json(stream)
            else:
                raise ValueError(f"Unsupported format: {format}")

            stream.seek(0)

            if use_legacy:
                job = self.client.load_table_from_file(
                    stream,
                    destination=destination,
                    project=project,
                    job_config=bigquery.LoadJobConfig(
                        source_format=format.upper(),
                        write_disposition=mode,
                    ),
                )
            else:
                ### Needs solve conflict with exist table using this before replace with new approach
                if schema:
                    job = self.client.load_table_from_file(
                        stream,
                        destination=destination,
                        project=project,
                        job_config=bigquery.LoadJobConfig(
                            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                            write_disposition=mode,
                            schema=schema,
                            autodetect=False,
                        ),
                    )
                else:
                    job = self.client.load_table_from_file(
                        stream,
                        destination=destination,
                        project=project,
                        job_config=bigquery.LoadJobConfig(
                            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                            write_disposition=mode,
                            autodetect=True,
                        ),
                    )
        job.result()  # Waits for the job to complete
        
    def upload_to_bigquery(self, df, project_id, dataset_id, table_id):
        bq_client = self.client
        if isinstance(df, pl.DataFrame):
            df = df.to_pandas()
        try:
            table_ref = bq_client.dataset(dataset_id).table(table_id)
        except:
            table_ref = f"{project_id}.{dataset_id}.{table_id}"

        job_config = bigquery.LoadJobConfig()
        job_config.autodetect = True  
        
        try:
            job = bq_client.load_table_from_dataframe(df, table_ref, job_config=job_config)
            job.result()  # Wait for the job to complete
            print('BQ upload is done: ' + project_id + '/' + dataset_id + '/' + table_id)
        except exceptions.GoogleAuthError as e:
            print('Failed to upload to BigQuery. Error:', e)
        except Exception as e:
            print('An error occurred:', e)
            pass