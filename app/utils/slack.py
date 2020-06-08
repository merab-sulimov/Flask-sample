import requests
import json

from app import app


DEFAULT_CHANNEL = '#selfmarket-backend'
SALES_CHANNEL = '#sales'

class Icons:
    SUCCESS = ':+1:'
    DANGER = ':sos:'
    MONEY = ':moneybag:'


def notification(message, icon=Icons.SUCCESS, channel=DEFAULT_CHANNEL):
    if app.config.get('DEVELOPMENT') or app.config.get('LOCAL_DEVELOPMENT'):
        # Do not send any notification for dev servers
        return

    payload = {
        'text': '`%s` %s' % (app.config.get('SERVER_NAME'), message),
        'channel': channel,
        'username': 'backend',
        'icon_emoji': icon
    }

    try:
        requests.post(
            app.config.get('SLACK_WEBHOOK_URL'),
            data=json.dumps(payload)
        )

        return True
    except:
        return False


def notification_sale(message):
    return notification(message, icon=Icons.MONEY, channel=SALES_CHANNEL)
