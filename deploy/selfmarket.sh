
#INSTALARE RAPIDA SELFMARKET

SELFDIR=/opt/master

crontab -l | { cat; echo "*/30 * * * * python $SELFDIR/manage.py generate_sitemap"; } | crontab -
crontab -l | { cat; echo "*/5 * * * * python $SELFDIR/manage.py update_exchange_rate"; } | crontab -
crontab -l | { cat; echo "*/30 * * * * python $SELFDIR/manage.py update_favorite_searches"; } | crontab -
crontab -l | { cat; echo "*/5 * * * * python $SELFDIR/manage.py check_addresses"; } | crontab -
crontab -l | { cat; echo "*/30 * * * * python $SELFDIR/manage.py check_orders"; } | crontab -