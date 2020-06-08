import copy
import random
from datetime import datetime, timedelta
from blinker import Namespace
from math import ceil

from app import app, es


signals = Namespace()
product_created = signals.signal('product_created')
product_updated = signals.signal('product_updated')
product_deleted = signals.signal('product_deleted')
seller_online = signals.signal('seller_online')


class DocumentTypes:
    USER = 'user'
    PRODUCT = 'product'


class ProductSorting:
    RECOMMENDED = 0
    DATE_DESC = 1
    PRICE_ASC = 2
    PRICE_DESC = 3
    ORDERS_DESC = 4
    RATING_DESC = 5
    RANDOM = 6


def create_index():
    settings = {
        "mappings": {
            DocumentTypes.USER: {},
            DocumentTypes.PRODUCT: {
                "_parent": {
                    "type": DocumentTypes.USER
                }
            }
        }
    }

    es.create_index(app.config['ELASTICSEARCH_INDEX'], settings)


def delete_index():
    es.delete_index(app.config['ELASTICSEARCH_INDEX'])


def add_seller_to_index(seller):
    if seller.is_deleted or not seller.seller_fee_paid:
        # Do not add deleted users or users who are not sellers
        return

    es.index(app.config['ELASTICSEARCH_INDEX'], DocumentTypes.USER, {
        'last_logged_on': seller.last_logged_on,
        '_seller': True
    }, seller.id)

def add_seller_to_index_handler(sender, seller):
    add_seller_to_index(seller)


def add_product_to_index(product):
    if not product.is_approved or product.is_deleted or product.published_on is None:
        # Do not add not approved and deleted products
        return

    rating = product.get_statistics()['feedbacks_rating']

    es.index(app.config['ELASTICSEARCH_INDEX'], DocumentTypes.PRODUCT, {
        'title': product.title,
        'description': product.description,
        'category_id': product.category_id,
        'seller_id': product.seller_id,
        'is_private': product.is_private,
        'is_highlighted': product.is_highlighted,
        'published_on': product.published_on,
        'price': product.price_offer if product.active_offer_id else product.price,
        'price_base': product.price,
        'tags': product.get_data('tags') or [],
        '_orders_count': product.get_completed_orders_count(),
        '_feedbacks_rating': rating,
        '_feedbacks_rating_int': int(round(rating))
    }, product.id, parent=product.seller_id)

def add_product_to_index_handler(sender, product):
    add_product_to_index(product)


def delete_product_from_index(product):
    try:
        es.delete(app.config['ELASTICSEARCH_INDEX'], DocumentTypes.PRODUCT, product.id, routing=product.seller.id)
    except:
        # Do not do anything in case there is no such document
        pass

def delete_product_from_index_handler(sender, product):
    delete_product_from_index(product)


def search_products(q='', sorting=ProductSorting.RECOMMENDED, include_private=False, since=None, start=0, limit=20, **kwargs):
    query = {
        'query': {
            'filtered': {
                'filter': {
                    'bool': {
                        'must': []
                    }
                }
            }
        },
        'sort': [],
        'fields': ['_feedbacks_rating_int'],
        'aggs': {
            'tags': {
                'terms': { 'field': 'tags' }
            }
        }
    }

    def push_filter(f):
        # Shortcut for adding filters to the query
        query['query']['filtered']['filter']['bool']['must'].append(f)

    if 'online' in kwargs and kwargs['online']:
        push_filter({
            'has_parent': {
                'type': DocumentTypes.USER,
                'query': {
                    'range': {
                        'last_logged_on': {
                            'gte': (datetime.utcnow() - timedelta(seconds=15 * 60))
                        }
                    }
                }
            }
        })

    if since:
        push_filter({
            'range': {
                'published_on': {
                    'gte': since
                }
            }
        })

    if 'seller_id' in kwargs:
        # Filter by seller ID
        push_filter({
            'term': {
                'seller_id': kwargs['seller_id']
            }
        })

    if 'category_id' in kwargs:
        # Filter by category ID
        push_filter({
            'term': {
                'category_id': kwargs['category_id']
            }
        })

    if 'category_ids' in kwargs:
        # Filter by multiple category IDs
        push_filter({
            'terms': {
                'category_id': kwargs['category_ids']
            }
        })

    if 'min_rating_int' in kwargs:
        push_filter({
            'range': {
                '_feedbacks_rating_int': {
                    'gte': kwargs['min_rating_int']
                }
            }
        })

    if 'rating_int' in kwargs:
        rating = kwargs['rating_int']

        # Convert rating from INT form to FLOAT, like 4 stars rating is actually range (3.5 - 4.5)

        push_filter({
            'range': {
                '_feedbacks_rating': {
                    'gte': rating - 0.5,
                    'lt': rating + 0.5
                }
            }
        })

    if 'price' in kwargs:
        # Filter by min/max price
        price_range = dict()
        if kwargs['price'][0]:
            price_range['gte'] = kwargs['price'][0]

        if kwargs['price'][1]:
            price_range['lte'] = kwargs['price'][1]

        if price_range:
            push_filter({
                'range': {
                    'price': price_range
                }
            })

    if 'tags' in kwargs and kwargs['tags']:
        # Filter by tags
        for tag in kwargs['tags']:
            push_filter({
                'term': {
                    'tags': tag
                }
            })

    if not include_private:
        # Do not include private products
        push_filter({
            'term': {
                'is_private': False
            }
        })

    if q:
        # Include full-text match by query
        query['query']['filtered']['query'] = {
            'multi_match': {
                'query': q,
                'fields': ['title^10', 'description']
            }
        }

    sorting_key, sorting_order = None, None

    if sorting == ProductSorting.PRICE_ASC:
        sorting_key, sorting_order = 'price', 'asc'
    elif sorting == ProductSorting.PRICE_DESC:
        sorting_key, sorting_order = 'price', 'desc'
    elif sorting == ProductSorting.ORDERS_DESC:
        sorting_key, sorting_order = '_orders_count', 'desc'
    elif sorting == ProductSorting.DATE_DESC:
        sorting_key, sorting_order = 'published_on', 'desc'
    elif sorting in (ProductSorting.RATING_DESC, ProductSorting.RECOMMENDED):
        # This is used by recommended search to return random results, grouped by rating value (integer)

        query_part = query['query']

        query['query'] = {
            'function_score': {
                'query': query_part,
                'functions': [{
                    'random_score': {
                        'seed': kwargs['random_seed'] if 'random_seed' in kwargs else random.randint(0, 10000000000),
                    },
                    'weight': 1
                }, {
                    'field_value_factor': {
                        'field': '_feedbacks_rating_int',
                        'factor': 1,
                        'missing': 0
                    },
                    'weight': 10
                }, {
                    'field_value_factor': {
                        'field': 'is_highlighted',
                        'factor': 1,
                        'missing': 0
                    },
                    'weight': 100
                }],
                'score_mode': 'sum'
            }
        }

        del query['sort']
        
        if sorting == ProductSorting.RECOMMENDED:
            # Include _feedbacks_rating to the fields so we will have an access to them later
            query['fields'].append('_feedbacks_rating')

            # Include MAX aggregation on _feedback_rating
            query['aggs']['_max_feedbacks_rating'] = { 'max': { 'field' : '_feedbacks_rating' } }
    else:
        # Random sorting
        query_part = query['query']

        query['query'] = {
            'function_score': {
                'query': query_part,
                'functions': [{
                    'random_score': {
                        'seed': kwargs['random_seed'] if 'random_seed' in kwargs else random.randint(0, 10000000000)
                    }
                }]
            }
        }

        del query['sort']

    if sorting_key and sorting_order:
        query['sort'].append({ sorting_key: { 'order': sorting_order } })

    try:
        products = es.search(query,
                             index=app.config['ELASTICSEARCH_INDEX'],
                             doc_type=DocumentTypes.PRODUCT,
                             size=limit,
                             es_from=start)

        total = products['hits']['total']
        tags = products['aggregations']['tags']['buckets']
        ids = [product['_id'] for product in products['hits']['hits']]
    except:
        return ([], 0, [])

    # print '------------'
    # for product in products['hits']['hits']:
    #     print '[%s] %d - %d' % ('X' if product['fields'].get('is_highlighted') else ' ', product['fields']['_feedbacks_rating_int'][0], product['_score'])

    # print '------------'

    tags = map(lambda item: dict(tag=item['key'], count=item['doc_count']), tags)

    if sorting == ProductSorting.RECOMMENDED:
        rating = round(products['aggregations']['_max_feedbacks_rating']['value']) if type(products['aggregations']['_max_feedbacks_rating']['value']) is float else 0
        if rating:
            search_kwargs = copy.deepcopy(kwargs)
            search_kwargs['rating_int'] = rating
            count_top_products = count_search_products(q, include_private=include_private, since=since, **search_kwargs)
            
            # print "Top products count: ", count_top_products

            since_new = datetime.now() - timedelta(days=app.config['NEW_SERVICE_DAYS'])
            count_new_products = count_search_products(q, include_private=include_private, since=since_new, **kwargs)

            # print "New products count: ", count_new_products

            max_new_products = min((count_top_products + 1) / 3, count_new_products)

            # print "Max new. products: ", max_new_products

            total += max_new_products

            # print "New total:", total

            new_products_injected = min(start / limit * (limit / 3), max_new_products)

            # print "New products already injected in previous pages: ", new_products_injected

            new_product_ids = []
            new_products_this_page = 0

            if new_products_injected < max_new_products:
                # Perform search on new products

                top_products_this_page = 0
                for product in products['hits']['hits']:
                    if product['fields']['_feedbacks_rating'] >= (rating - 0.5):
                        top_products_this_page += 1

                new_products_this_page = min((top_products_this_page + 1) / 3, max_new_products - new_products_injected)

                # print "Requesting new products to inject into current page: ", new_products_this_page
                new_product_ids, _, _ = search_products(q, sorting=ProductSorting.RANDOM, include_private=include_private, since=since_new, start=new_products_injected, limit=new_products_this_page, **kwargs)

                # print "New product IDs: ", new_product_ids

            corrected_products_limit = limit - new_products_this_page

            # print "Corrected products limit: ", corrected_products_limit

            corrected_products_start = start - new_products_injected

            # print "Corrected products start: ", corrected_products_start

            corrected_product_ids, _, _ = search_products(q, sorting=ProductSorting.RATING_DESC, include_private=include_private, since=since, start=corrected_products_start, limit=corrected_products_limit, **kwargs)

            # print "Corrected product IDs: ", corrected_product_ids

            ids = []
            new_idx = 0
            corrected_idx = 0

            for i in range(start, start + limit):
                if i % 3 == 2 and len(new_product_ids) > new_idx:
                    ids.append(new_product_ids[new_idx])
                    new_idx += 1
                elif len(corrected_product_ids) > corrected_idx:
                    ids.append(corrected_product_ids[corrected_idx])
                    corrected_idx += 1

            # print "Resulting IDs: ", ids

            return (ids, total, tags)

    return (ids, total, tags)


def count_search_products(q, include_private=False, since=None, **kwargs):
    query = {
        'query': {
            'filtered': {
                'filter': {
                    'bool': {
                        'must': []
                    }
                }
            }
        },
        'sort': [],
        'fields': []
    }

    def push_filter(f):
        # Shortcut for adding filters to the query
        query['query']['filtered']['filter']['bool']['must'].append(f)

    if 'online' in kwargs and kwargs['online']:
        push_filter({
            'has_parent': {
                'type': DocumentTypes.USER,
                'query': {
                    'range': {
                        'last_logged_on': {
                            'gte': (datetime.utcnow() - timedelta(seconds=15 * 60))
                        }
                    }
                }
            }
        })

    if since:
        push_filter({
            'range': {
                'published_on': {
                    'gte': since
                }
            }
        })

    if 'seller_id' in kwargs:
        # Filter by seller ID
        push_filter({
            'term': {
                'seller_id': kwargs['seller_id']
            }
        })

    if 'category_id' in kwargs:
        # Filter by category ID
        push_filter({
            'term': {
                'category_id': kwargs['category_id']
            }
        })

    if 'category_ids' in kwargs:
        # Filter by multiple category IDs
        push_filter({
            'terms': {
                'category_id': kwargs['category_ids']
            }
        })

    if 'min_rating_int' in kwargs:
        push_filter({
            'range': {
                '_feedbacks_rating_int': {
                    'gte': kwargs['min_rating_int']
                }
            }
        })

    if 'rating_int' in kwargs:
        rating = kwargs['rating_int']

        # Convert rating from INT form to FLOAT, like 4 stars rating is actually range (3.5 - 4.5)

        push_filter({
            'range': {
                '_feedbacks_rating': {
                    'gte': rating - 0.5,
                    'lt': rating + 0.5
                }
            }
        })

    if 'price' in kwargs:
        # Filter by min/max price
        price_range = dict()
        if kwargs['price'][0]:
            price_range['gte'] = kwargs['price'][0]

        if kwargs['price'][1]:
            price_range['lte'] = kwargs['price'][1]

        if price_range:
            push_filter({
                'range': {
                    'price': price_range
                }
            })

    if 'tags' in kwargs and kwargs['tags']:
        # Filter by tags
        for tag in kwargs['tags']:
            push_filter({
                    'term': {
                        'tags': tag
                    }
                })

    if not include_private:
        # Do not include private products
        push_filter({
            'term': {
                'is_private': False
            }
        })

    if q:
        # Include full-text match by query
        query['query']['filtered']['query'] = {
            'multi_match': {
                'query': q,
                'fields': ['title^10', 'description']
            }
        }

    count = 0

    try:
        es_count = es.count(query,
                            index=app.config['ELASTICSEARCH_INDEX'],
                            doc_type=DocumentTypes.PRODUCT)

        count = es_count['count']
    except:
        count = 0

    return count


def count_tags(q, include_private=False, **kwargs):
    query = {
        'query': {
            'filtered': {
                'filter': {
                    'bool': {
                        'must': []
                    }
                }
            }
        },
        'aggs': {
            'tags': {
                'terms': { 'field': 'tags' }
            }
        }
    }

    def push_filter(f):
        # Shortcut for adding filters to the query
        query['query']['filtered']['filter']['bool']['must'].append(f)

    if 'seller_id' in kwargs:
        # Filter by seller ID
        push_filter({
            'term': {
                'seller_id': kwargs['seller_id']
            }
        })

    if 'category_id' in kwargs:
        # Filter by category ID
        push_filter({
            'term': {
                'category_id': kwargs['category_id']
            }
        })

    if 'category_ids' in kwargs:
        # Filter by multiple category IDs
        push_filter({
            'terms': {
                'category_id': kwargs['category_ids']
            }
        })

    if 'price' in kwargs:
        # Filter by min/max price
        price_range = dict()
        if kwargs['price'][0]:
            price_range['gte'] = kwargs['price'][0]

        if kwargs['price'][1]:
            price_range['lte'] = kwargs['price'][1]

        if price_range:
            push_filter({
                'range': {
                    'price': price_range
                }
            })

    if not include_private:
        # Do not include private products
        push_filter({
            'term': {
                'is_private': False
            }
        })

    if q:
        # Include full-text match by query
        query['query']['filtered']['query'] = {
            'multi_match': {
                'query': q,
                'fields': ['title^10', 'description']
            }
        }

    es_result = es.search(query,
                          size=0,
                          index=app.config['ELASTICSEARCH_INDEX'],
                          doc_type=DocumentTypes.PRODUCT)

    return es_result


def search_best(product=None, seller=None, limit=3, start=0):
    """
    Search for best sellers of the product seller
    Returns IDs of the products except product ID used for search
    """
    if not product and not seller:
        raise Exception('Either product or seller is required to search for best sellers')

    seller_id = product.seller_id if product else seller.id

    query_best = {
        'query': {
            'filtered': {
                'filter': {
                    'bool': {
                        'must': [
                            { 'term': { 'seller_id': seller_id } },
                            { 'term': { 'is_private': False } } # TODO: search for private products for those who have access?
                        ]
                    }
                }
            }
        },
        'sort': [
            { '_orders_count': { 'order': 'desc' } }
        ],
        'fields': []
    }

    try:
        products = es.search(query_best,
                             index=app.config['ELASTICSEARCH_INDEX'],
                             doc_type=DocumentTypes.PRODUCT,
                             size=limit + 1,
                             es_from=start)

        total = products['hits']['total']
        products = [hit['_id'] for hit in products['hits']['hits'] if not product or (product and long(hit['_id']) != product.id)][:limit]
    except:
        total = 0
        products = list()

    return products, total


def search_similar(product, limit=3):
    """
    Search for best sellers of the product category
    Returns IDs of the products except product ID used for search
    """

    # Otherwise search for similiar products
    query_similar = {
        'query': {
            'filtered': {
                'filter': {
                    'bool': {
                        'must': [
                            {'term': {'category_id': product.category_id}},
                            {'term': {'is_private': False}}
                        ]
                    }
                }
            }
        },
        'sort': [
            {'_orders_count': {'order': 'desc'}}
        ],
        'fields': []
    }

    try:
        products = es.search(query_similar,
                             index=app.config['ELASTICSEARCH_INDEX'],
                             doc_type=DocumentTypes.PRODUCT,
                             size=limit + 1)

        products = [hit['_id'] for hit in products['hits']['hits'] if long(hit['_id']) != product.id][:limit]
    except:
        products = list()

    return products


product_created.connect(add_product_to_index_handler)
product_updated.connect(add_product_to_index_handler)
product_deleted.connect(delete_product_from_index_handler)
seller_online.connect(add_seller_to_index_handler)
