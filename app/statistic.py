import json
import peewee
from playhouse import db_url
from playhouse.pool import PooledMySQLDatabase
from datetime import datetime, timedelta

from app import app
from app.utils.tz import get_utc_datetime


db_options = db_url.parse(app.config['STATISTIC_DATABASE_URI'])
db = PooledMySQLDatabase(db_options.pop('database'), **db_options)


def with_database(f):
    def overridden(*args, **kwargs):
        db.connect()
        try:
            retval = f(*args, **kwargs)
        finally:
            db.close()

        return retval

    return overridden


class JSONField(peewee.TextField):
    def db_value(self, value):
        return value if value is None else json.dumps(value)

    def python_value(self, value):
        return value if value is None else json.loads(value)


class AffiliateImpressionModel(peewee.Model):
    client_id = peewee.CharField(max_length=32, primary_key=True)
    ip = peewee.CharField(max_length=46)
    event_date = peewee.DateTimeField(index=True, default=datetime.utcnow)

    class Meta:
        db_table = 'affiliate_impression'
        database = db


class BaseStatisticRecordModel(peewee.Model):
    key_id = peewee.IntegerField(index=True)
    key_value = peewee.IntegerField(default=None, null=True)
    event_date = peewee.DateTimeField(index=True, default=datetime.utcnow)
    data = JSONField(default=None, null=True)


class AffiliateImpression:
    class NotUniqueException(Exception):
        pass

    @staticmethod
    @with_database
    def initialize():
        print "Initializing affiliate data layer..."
        db.create_tables([AffiliateImpressionModel], safe=True)

    @staticmethod
    @with_database
    def try_save_unique(client_id, ip):
        """
        Try to save unique impression.
        In case client ID (fingerprint) already exists - throw error
        In case clinet IP address has been recorded
            in the last 24 hours - throw error as well
        """

        # TODO: first check for IP in cache

        existing_impression = None

        try:
            existing_impression = AffiliateImpressionModel.get(
                AffiliateImpressionModel.client_id == client_id
            )
        except peewee.DoesNotExist:
            pass

        if existing_impression:
            raise AffiliateImpression.NotUniqueException()

        try:
            existing_impression = AffiliateImpressionModel.get(
                AffiliateImpressionModel.ip == ip,
                AffiliateImpressionModel.event_date > (datetime.utcnow() - timedelta(days=1))
            )
        except peewee.DoesNotExist:
            pass

        if existing_impression:
            raise AffiliateImpression.NotUniqueException()

        AffiliateImpressionModel.create(client_id=client_id, ip=ip)


class StatisticRecord:
    model_classes = dict()

    class Types:
        SERVICE_IMPRESSION = 'service_impression'
        SERVICE_ORDER_COMPLETED = 'service_order_completed'
        USER_LOGIN = 'user_login'
        USER_REGISTER = 'user_register'
        USER_SELLER_ORDER_COMPLETED = 'user_seller_order_completed'
        USER_AFFILIATE_IMPRESSION = 'user_affiliate_impression'
        USER_AFFILIATE_REGISTER = 'user_affiliate_register'
        USER_AFFILIATE_BECOME_SELLER = 'user_affiliate_become_seller'
        USER_AFFILIATE_SALE = 'user_affiliate_sale'

    @classmethod
    def types(cls):
        return (
            getattr(cls.Types, value)
            for value in dir(cls.Types)
            if not value.startswith('__')
        )

    @classmethod
    @with_database
    def initialize(cls):
        print "Initializing statistic data layer..."
        for record_type in cls.types():
            Meta = type(
                'Meta',
                (object,),
                dict(database=db, db_table='stat_%s' % record_type)
            )

            cls.model_classes[record_type] = type(
                'Record_%s' % record_type,
                (BaseStatisticRecordModel,),
                dict(Meta=Meta)
            )

        db.create_tables(cls.model_classes.values(), safe=True)

    @classmethod
    @with_database
    def record(cls, record_type, key_id, key_value=None, **kwargs):
        """
        Record statistic item.
        Keyword args will be unpacked into data JSON object
        """

        if record_type not in cls.model_classes:
            raise Exception('No such record type')

        Model = cls.model_classes[record_type]

        record = Model(
            key_id=key_id,
            key_value=key_value,
            data=kwargs if kwargs else None
        )

        record.save()

    @classmethod
    def record_silent(cls, *args, **kwargs):
        """
        Record statistic item. The same as record() but fails silently
        """
        try:
            cls.record(*args, **kwargs)
        except Exception, e:
            print "Exception while saving statistic record (%s): %s" % (args[0], e.message)

    @classmethod
    @with_database
    def count(cls, record_type, key_id, date_range_utc=None):
        """
        Get count of records of specified type
        """
        if record_type not in cls.model_classes:
            raise Exception('No such record type')

        Model = cls.model_classes[record_type]

        query = Model.select().where(Model.key_id == key_id)

        if date_range_utc and date_range_utc[0]:
            query = query.where(Model.event_date >= date_range_utc[0].isoformat())

        if date_range_utc and date_range_utc[1]:
            query = query.where(Model.event_date <= date_range_utc[1])

        return query.count()

    @classmethod
    @with_database
    def count_per_day(cls, record_type, key_id, date_range_local):
        """
        Get count of records of specified type
        """
        if record_type not in cls.model_classes:
            raise Exception('No such record type')

        Model = cls.model_classes[record_type]

        local_offset = date_range_local[0].tzinfo.tzname(date_range_local[0])

        query = Model \
            .select(
                peewee.fn.count(Model.id).alias('count'),
                peewee.fn.DATE_FORMAT(peewee.fn.CONVERT_TZ(Model.event_date, 'SYSTEM', local_offset), '%Y-%m-%d').alias('date_local')
            ) \
            .where(
                Model.key_id == key_id,
                Model.event_date >= get_utc_datetime(date_range_local[0]),
                Model.event_date <= get_utc_datetime(date_range_local[1])
            ) \
            .group_by(peewee.SQL('date_local')) \
            .dicts()

        counts_dict = {item['date_local']: item['count'] for item in query}

        result = list()
        total = 0

        for date in (date_range_local[0] + timedelta(days=i) for i in range((date_range_local[1] - date_range_local[0]).days + 1)):
            key = date.strftime('%Y-%m-%d')
            count = counts_dict[key] if key in counts_dict else 0
            total += count

            result.append(dict(
                count=count,
                date=key
            ))

        return result, total

    @classmethod
    @with_database
    def sum(cls, record_type, key_id, date_range_utc=None):
        """
        Get sum of values for records of specified type
        """
        if record_type not in cls.model_classes:
            raise Exception('No such record type')

        Model = cls.model_classes[record_type]

        query = Model \
            .select(peewee.fn.SUM(Model.key_value)) \
            .where(Model.key_id == key_id)

        if date_range_utc and date_range_utc[0]:
            query = query.where(Model.event_date >= date_range_utc[0])

        if date_range_utc and date_range_utc[1]:
            query = query.where(Model.event_date <= date_range_utc[1])

        result = query.scalar()
        return float(query.scalar()) if result else 0.0


StatisticRecord.initialize()
AffiliateImpression.initialize()
