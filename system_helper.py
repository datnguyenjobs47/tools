import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
os.sys.path.append(root_dir)
os.chdir(root_dir)

import json
import traceback
import shutil
from loguru import logger
import csv


import datetime
from datetime import timedelta, datetime
import threading
single_thread = threading.Lock()


def delete_file(file_path, export_error=False):
    """
    Deletes a file at the specified path.

    Args:
        file_path (str): The path to the file to be deleted.
        export_error (bool): If True, prints the error message when deletion fails.

    """
    try:
        os.remove(file_path)
    except:
        if export_error == True:
            logger.error(f"Error deleting file {file_path}")
            logger.error(traceback.format_exc())

def delete_folder(folder_path, export_error=False):
    """
    Deletes a folder at the specified path.

    Args:
        folder_path (str): The path to the folder to be deleted.
        export_error (bool): If True, prints the error message when deletion fails.

    """
    try:
        shutil.rmtree(folder_path)
    except:
        if export_error == True:
            logger.error(f"Error deleting folder {folder_path}")
            logger.error(traceback.format_exc())

def save_file(file_name, raw_data, file_extension='json', save_mode='w', data_folder='./data/', export_error=False):
    """
    Saves data to a file with the specified name and extension.

    Args:
        file_name (str): The name of the file to save.
        raw_data (dict/str): The data to save.
        file_extension (str): The file extension (default is 'json').
        save_mode (str): The mode to open the file ('w' by default).
        data_folder (str): The folder to save the file in (default is './data/').

    Returns:
        str: The path to the saved file.
    """
    file_path = os.path.join(data_folder, f'{file_name}.{file_extension}')
    try:
        if not os.path.exists(data_folder):
            os.makedirs(data_folder)
        with open(file_path, save_mode, encoding='utf-8') as f:
            if file_extension == 'json':
                json.dump(raw_data, f, indent=4, ensure_ascii=False)
            else:
                f.write(str(raw_data))
    except Exception as e:
        if export_error == True:
            logger.error(f"Error saving file {file_name}: {e}")
            logger.error(traceback.format_exc())

    return file_path

def read_file(file_path, file_extension='json', export_error=False):
    """
    Reads data from a file.

    Args:
        file_path (str): The path to the file to read.
        file_extension (str): The file extension (default is 'json').

    Returns:
        str/dict: The data read from the file (either as a string or a JSON object).
    """
    data = ''
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_extension == 'json':
                data = json.load(f)
            elif file_extension == 'csv':
                data = list(csv.reader(f))
            elif file_extension == 'jsonl':
                data = [json.loads(line) for line in f]
            elif file_extension == 'log':
                data = f.readlines()
            else:
                data = f.read()
    except Exception as e:
        if export_error == True:
            logger.error(f"Error reading file {file_path}: {e}")
            logger.error(traceback.format_exc())

    return data

def get_last_weekday(weekday):
    """
    get date of last weekday
    Args:
        weekday (int): last weekday to get (range from monday=0 to sunday=6)
    Example:
        input weekday=3 means get date of last thursday
    Returns:
        str: date in format "YYYY-MM-DD"
    """
    # Get the current date
    current_date = datetime.datetime.now()
    # Calculate the days since the last weekday
    days_since_last_weekday = (current_date.weekday() - weekday + 7) % 7

    # Calculate the last weekday date
    last_weekday = current_date - timedelta(days=days_since_last_weekday)

    # Print the result
    logger.debug(f"Last weekday {weekday} was on: {last_weekday.strftime('%Y-%m-%d')}")
    return last_weekday.strftime("%Y-%m-%d")

def get_folder_list(folder_path, export_error=False):
    """
    Get a list of subfolders in the given local folder path.

    Args:
        folder_path (str): Path to the local folder to list subfolders from

    Returns:
        List[str] | None: List of subfolder names
    """
    folder_list = None
    try:
        with os.scandir(folder_path) as entries:
            folder_list = [entry.name for entry in entries if entry.is_dir()]
    except Exception as e:
        if export_error == True:
            logger.error(f"Something wrong when listing folder: {e}")

    return folder_list

def get_file_list(folder_path, export_error=False):
    """
    Get a list of files in the given local folder path.

    Args:
        folder_path (str): Path to the local folder to list files from

    Returns:
        List[str] | None: List of files names.
    """
    file_list = None
    try:
        with os.scandir(folder_path) as entries:
            file_list = [entry.name for entry in entries if entry.is_file()]
    except Exception as e:
        if export_error == True:
            logger.error(f"Something wrong when listing file: {e}")

    return file_list

def split_config(configs, batch_size, export_error=False):
    """
    Split a list of configs into smaller batches.

    Args:
        configs (List[Any]): List of configuration items to split
        batch_size (int): Maximum number of items in each batch
        export_error (bool, optional): If True, log errors when splitting fails. Defaults to False

    Returns:
        List[List[Any]] | None: List of config batches, or None
    """
    result = []
    try:        
        for i in range(0, len(configs), batch_size):
            result.append(configs[i : i + batch_size])

    except Exception as e:
        if export_error == True:
            logger.error(f"Something wrong when spliting config: {e}")
        pass

    return result

def split_config_for_concurrent(max_workers, configs, export_error=False):
    """
    Split a list of configs into smaller batches for concurrent processing.

    Args:
        configs (List[Any]): List of configuration items to split
        max_workers (int): Maximum number of concurrent workers
        export_error (bool, optional): If True, log errors when splitting fails. Defaults to False
    Returns:
        List[List[Any]] | None: List of config batches, or None
    """
    result = []
    try:
        batch_size = len(configs) // max_workers
        if len(configs) % max_workers != 0:
            batch_size += 1
        
        for i in range(0, len(configs), batch_size):
            result.append(configs[i : i + batch_size])

    except Exception as e:
        if export_error == True:
            logger.error(f"Something wrong when spliting config: {e}")
        pass

    return result   

def append_to_jsonl(file_path, data, export_error=False):
    """
    Append a new JSON object to a JSONL file.

    Args:
        file_path (str): Path to the JSONL file
        data (dict): Dictionary representing the JSON object to append
        export_error (bool, optional): If True, log errors when appending fails. Defaults to False
    """
    try:
        with single_thread:
            with open(file_path, 'a') as f:
                json.dump(data, f)
                f.write('\n')
    except Exception as e:
        if export_error == True:
            logger.error(f"Error appending to JSONL file {file_path}: {e}")
            logger.error(traceback.format_exc())

def reset_file(file_path):
    try:
        open(file_path, "w", encoding="utf-8").close()
    except Exception as e:
        logger.warning(f"Error resetting file: {e}")

def reset_folder(folder_path):
    shutil.rmtree(folder_path, ignore_errors=True)
    os.makedirs(folder_path, exist_ok=True)

def create_folder(folder_path):
    os.makedirs(folder_path, exist_ok=True)