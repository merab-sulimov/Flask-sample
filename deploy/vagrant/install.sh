#!/bin/bash

DATABASE=simpleflask
STATISTIC_DATABASE=simpleflask_statistic
PROJECT_PATH=/vagrant

locale-gen en_US.UTF-8
dpkg-reconfigure locales

apt-get update -y
apt-get install -y build-essential python python-dev python-setuptools

# Python setuptools
wget https://bitbucket.org/pypa/setuptools/raw/bootstrap/ez_setup.py -O - | python

# Dependencies for Pillow
apt-get install -y libjpeg-dev libtiff-dev zlib1g-dev libfreetype6-dev liblcms2-dev

# Install pip
easy_install -U pip

# Install MySQL server (root password is empty!)
export DEBIAN_FRONTEND=noninteractive
apt-get -q -y install mysql-server libmysqlclient-dev

# configure mysql to work with HOST
create user 'root'@'10.0.2.2' identified by '';
grant all privileges on *.* to 'root'@'10.0.2.2' with grant option;
flush privileges;

# Install Redis
apt-get install redis-server -y
sed -i "s/^bind /#bind /" /etc/redis/redis.conf
service redis-server restart

# Install ElasticSearch
apt-get install openjdk-7-jre -y
wget https://download.elastic.co/elasticsearch/release/org/elasticsearch/distribution/deb/elasticsearch/2.4.3/elasticsearch-2.4.3.deb
dpkg -i elasticsearch-2.4.3.deb
echo "network.host: 0.0.0.0" >> /etc/elasticsearch/elasticsearch.yml # allow connections from host machine
service elasticsearch restart

#######################################

# Install requirements
pip install -r $PROJECT_PATH/requirements.txt

# Allow remote access to MySQL server
sed -i "s/^bind-address/#bind-address/" /etc/mysql/my.cnf
service mysql restart

# Create database
mysql -u root -e "create database $DATABASE character set utf8 collate utf8_general_ci;"
mysql -u root -e "create database $STATISTIC_DATABASE character set utf8 collate utf8_general_ci;"
mysql -u root -e "create database $DATABASE""_testing character set utf8 collate utf8_general_ci;"
mysql -u root -e "create user 'simpleflask'@'%' identified by '';"
mysql -u root -e "grant all privileges on *.* to 'simpleflask'@'%' with grant option;"
mysql -u root -e "flush privileges;"

# Apply migrations and add some test data
cd $PROJECT_PATH
chmod a+x manage.py
./manage.py db upgrade
