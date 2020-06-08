import json
import urllib2

BITSTAMP_TICKER_ENDPOINT = 'https://www.bitstamp.net/api/ticker/'


def request_exchange_rate():
    resp = json.load(urllib2.urlopen(BITSTAMP_TICKER_ENDPOINT))
    rate = float(resp['last'])

    return rate
