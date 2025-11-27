# utils/cache.py
import os
import logging

REDIS_URL = os.getenv("REDIS_URL")
redis_client = None
logger = logging.getLogger("agrovista")

try:
    if REDIS_URL:
        import redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
except Exception as e:
    logger.warning("Redis not available: %s", e)
    redis_client = None

def cache_get(key):
    try:
        if redis_client:
            return redis_client.get(key)
    except Exception as e:
        logger.debug("redis get error: %s", e)
    return None

def cache_set(key, value, expire=300):
    try:
        if redis_client:
            redis_client.set(key, value, ex=expire)
    except Exception as e:
        logger.debug("redis set error: %s", e)
