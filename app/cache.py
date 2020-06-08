import cPickle as pickle

from app import redis


class TokenType:
    PASSWORD_RECOVERY = 'recovery'
    VARIABLE = 'variable'
    ENDORSEMENT = 'endorsement'


class SharedCache:
    FRONTEND_CATEGORY_TREE = 'frontend_category_tree'
    FRONTEND_MAX_PRICE = 'frontend_max_price'
    FRONTEND_CATEGORY_STATISTICS = 'frontend_category_statistics:%d'
    FRONTEND_CATEGORY_STATISTICS_INCL_PRIVATE = 'frontend_category_statistics_incl_private:%d'
    FRONTEND_SERVICE_STATISTICS = 'frontend_service_statistics:%d'
    STATISTIC_SERVICE_IMPRESSION = 'stat_service_impression:%d'
    AFFILIATE_STATISTIC = 'affiliate_statistic:%d:%s:%s'


USER_ONLINE_EXPIRE = 15*60


def add_token(token, token_type, data, expire=3600):
    key = 'token:%s:%s' % (token_type, token)
    redis.set(key, data)
    redis.expire(key, expire)


def search_token(token, token_type, destroy_token=True):
    key = 'token:%s:%s' % (token_type, token)
    value = redis.get(key)

    if destroy_token:
        redis.delete(key)

    return value


def set_user_online(user_id):
    key = 'user_online:%d' % user_id
    redis.setex(key, 1, USER_ONLINE_EXPIRE)


def is_user_online(user_id, ttl_threshold=USER_ONLINE_EXPIRE / 2):
    # Check if user_online key is present and have ttl > 1/2
    key = 'user_online:%d' % user_id
    ttl = redis.ttl(key)
    return ttl > ttl_threshold


def is_user_online_multiple(user_ids):
    keys = redis.mget(map(lambda user_id: 'user_online:%d' % user_id, user_ids))

    result = dict()

    for idx, user_id in enumerate(user_ids):
        result[user_id] = int(bool(keys[idx]))
    
    return result


def get_cached_object(key):
    serialized = redis.get('cache:%s' % key)
    if not serialized:
        return None

    try:
        object = pickle.loads(serialized)
    except:
        return None

    return object


def put_cached_object(key, object, expire=600):
    try:
        serialized = pickle.dumps(object)
    except:
        return

    redis.set('cache:%s' % key, serialized)
    redis.expire('cache:%s' % key, expire)
