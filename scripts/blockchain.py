import json
import urllib2

BLOCKCHAIN_TICKER_ENDPOINT = 'https://blockchain.info/ticker'


def address_balance(address):
    # TODO: set confirmations number to 6
    resp = urllib2.urlopen('https://blockchain.info/q/addressbalance/%s?confirmations=2' % address).read()
    confirmed_balance = long(resp)
    if confirmed_balance > 0:
        return confirmed_balance, confirmed_balance

    resp = urllib2.urlopen('https://blockchain.info/q/addressbalance/%s' % address).read()
    unconfirmed_balance = long(resp)
    return confirmed_balance, unconfirmed_balance


def request_exchange_rate():
    resp = json.load(urllib2.urlopen(BLOCKCHAIN_TICKER_ENDPOINT))
    rate = float(resp['USD']['last'])

    return rate
