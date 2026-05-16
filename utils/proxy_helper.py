import os
import sys

# current_dir = os.path.dirname(os.path.abspath(__file__))
# root_dir = os.path.dirname(os.path.dirname(current_dir))
# os.sys.path.append(root_dir)
# os.chdir(root_dir)

import time
import requests
import traceback
import re
from loguru import logger
import threading
single_thread = threading.Lock()

def change_zing_proxy_ip(access_key, retries=80):
    """
    Using the ZingProxy API to change the IP address of a ZingProxy proxy.
    
    Args:
        access_key (str): The access key for API authentication.
        retries (int, optional): Number of attempts to change the IP. Default is 80.

    Raises:
        RuntimeError: If unable to change the IP after the specified number of retries.
    """
    
    change_ip_status = False
    reset_link = f'https://api.zingproxy.com/open/change-ip/{access_key}'

    for _ in range(retries):
        # back-up for networt error
        try:
            change_ip_info = requests.get(reset_link).json()
        except Exception as e:

            logger.error(f'Network error: {e}')
            logger.error(traceback.format_exc())
            logger.debug('Wait for 20 seconds and try again')
            time.sleep(20)
            continue
        
        try:
            # succeed in changing IP
            if 'status' in change_ip_info and change_ip_info['status'] == 'success':

                logger.debug(f'Change IP success with ip: {change_ip_info.get("message", "Not have ip info")}')
                change_ip_status = True
                break
            # Change IP too frequently
            elif change_ip_info['warningSpam'] is not None:
                error_message = change_ip_info.get('error', '')
                match = re.search(r'\d+', error_message)
                wait_time = 61
                if match:
                    wait_time = int(match.group()) + 1
                logger.debug(change_ip_info)
                logger.debug(f'Change IP too frequently, wait for {wait_time} seconds')
                time.sleep(wait_time)
        
        except Exception as e:

            logger.error(f'Error occurred: {e}, response: {change_ip_info}')
            logger.error(traceback.format_exc())
            logger.debug('Wait for 20 seconds and try again')
            time.sleep(20)
    
    if not change_ip_status:
        raise RuntimeError(f'Failed to change Proxy IP after {retries} retries')

def check_proxy(proxy):
    """
    Checks if the provided proxy is working by making requests to several IP-checking services.

    Args:
        proxy (dict): A dictionary containing 'http' and 'https' proxy URLs.

    Example input:
        proxy = {
            'http': 'http://username:password@ip:port',
            'https': 'http://username:password@ip:port'
        }           
        or
        proxy = {
            'http': 'http://ip:port',
            'https': 'http://ip:port'
        }
    Returns:
        bool: True if the proxy is working, False otherwise.
    """

    checking_status = False
    checking_url_list = [
        ( "https://api.ipify.org?format=json" , "ip" ),
        ( "https://jsonip.com/" , "ip" ),
        ( "http://httpbin.org/ip" , "origin" )
    ]

    # Try each URL in the list until one succeeds
    for check in checking_url_list:
        checking_url = check[0]
        response_id_field = check[1]
        try:
            ip_info = requests.get(checking_url, proxies=proxy, timeout=4).json()
            if ip_info[response_id_field]:
                logger.debug(f'Proxy checking done, IP: {ip_info[response_id_field]}, check_url: {checking_url}')
                checking_status = True
                break
            
        except Exception as e:
            logger.warning(f'Error get ip info from {checking_url}: {e}')
            logger.warning(traceback.format_exc())
    
    return checking_status
    
def set_zing_proxy(access_key, ip, port, username=None, password=None, reset=False, retries=80):
    """
    Sets up a ZingProxy proxy using provided credentials and optionally resets the proxy IP.

    Args:
        access_key (str): The access key for API authentication.
        ip (str): The proxy IP address.
        port (str): Port number.
        username (str): Username.
        password (str): Password.
        uid (str): uId from ZingProxy.
        reset (bool): Change proxy IP. Default is False.
        retries (int): Max retries for checking proxy. Default is 80.

    Returns:
        dict: proxy as http format.
    """
    # Define the proxy dictionary
    proxy = {
        'http': f'http://{username}:{password}@{ip}:{port}',
        'https': f'http://{username}:{password}@{ip}:{port}'
    }

    # If no authentication is needed
    if username is None or password is None:
        proxy = {
            'http': f'http://{ip}:{port}',
            'https': f'http://{ip}:{port}'
        }

    set_zing_proxy_status = False

    # Change IP if reset is True
    if reset == True:
        change_zing_proxy_ip(access_key, retries)

    # Check if the proxy is working
    for let_try in range(1,retries):
        logger.debug(f'Trying proxy, attempt {let_try}/{retries}')
        if let_try % 10 == 0:
            logger.debug('Since proxy not working after 10 tries, changing IP')
            change_zing_proxy_ip(access_key, retries)

        if check_proxy(proxy) == True:
            logger.debug(f'Proxy is working in attempt {let_try}')
            set_zing_proxy_status = True
            break
        else:
            logger.warning('Proxy not working')
            time.sleep(2)
        
    # If the proxy is not working after all retries, return a default invalid proxy
    if set_zing_proxy_status == False:
        logger.error(f'Proxy is not working after {retries} retries')
        proxy = {
            'http': 'http://undefined:undefined@undefined:undefined',
            'https': 'http://undefined:undefined@undefined:undefined'
        }
    else:
        logger.debug('Proxy is set successfully')

    return proxy

def get_proxy(proxy_auth, reset=False, retries=80):
    # with single_thread:
    proxy = set_zing_proxy(
        access_key=proxy_auth['access_key'], 
        ip=proxy_auth['ip'], 
        port=proxy_auth['port'], 
        username=proxy_auth['username'], 
        password=proxy_auth['password'],
        reset=reset
    )
    return proxy

def scale_proxies(proxy_auths, max_workers):
    """
    Scale the list of proxy configurations to match the number of workers.
    """
    if not proxy_auths:
        raise ValueError("proxy_auths list is empty")
    n = len(proxy_auths)
    if n >= max_workers:
        return proxy_auths[:max_workers]
    else:
        # round-robin fill
        result = []
        for i in range(max_workers):
            result.append(proxy_auths[i % n].copy()) 
        return result