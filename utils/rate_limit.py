# utils/rate_limit.py
import os
from time import time

RATE_LIMIT = int(os.getenv("RATE_LIMIT", 60))  # requests per minute
rate_store = {}

def check_rate_limit(ip):
    now = int(time())
    window = now // 60
    key = f"{ip}:{window}"
    count = rate_store.get(key, 0)
    if count >= RATE_LIMIT:
        return False
    rate_store[key] = count + 1
    if len(rate_store) > 10000:
        rate_store.clear()
    return True
