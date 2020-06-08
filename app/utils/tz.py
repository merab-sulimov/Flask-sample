import pytz
import datetime


def get_names_list():
    return pytz.common_timezones


def get_list():
    result = list()

    for tz in pytz.common_timezones:
        offset = datetime.datetime.now(pytz.timezone(tz)).strftime('%z')

        result.append((
            tz,
            '(%s:%s) %s' % (offset[:-2], offset[-2:], tz),
            offset,
        ))

    return sorted(result, key=lambda x: int(x[2]))


def get_local_datetime(dt, tz=None):
    tz_object_utc = pytz.timezone('UTC')

    if tz is None:
        tz = 'UTC'

    try:
        tz_object = pytz.timezone(tz)
    except:
        tz_object = tz_object_utc

    dt = dt.replace(tzinfo=tz_object_utc)

    return dt.astimezone(tz_object)


def get_utc_datetime(dt):
    tz_object_utc = pytz.timezone('UTC')
    return dt.astimezone(tz_object_utc).replace(tzinfo=None)
