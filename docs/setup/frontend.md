### INSTALLING FRONTEND DEPS

```
npm install
npm run build

```

### Complete Install history from dev.jobdone.net

```
    1  apt-get update
    2  locale-gen en_US.UTF-8
    3  dpkg-reconfigure locales
    4  apt-get install -y build-essential python python-dev python-setuptools
    5  wget https://bitbucket.org/pypa/setuptools/raw/bootstrap/ez_setup.py -O - | python
    6  easy_install
    7  apt-get install -y libjpeg-dev libtiff-dev zlib1g-dev libfreetype6-dev liblcms2-dev
    8  apt-get -q -y install mysql-server libmysqlclient-dev
    9  apt-get install redis-server
   10  service redis-server restart
   11  apt-get install openjdk-7-jre
   12  apt-cache search openjdk
   13  apt-get install openjdk-9-jre
   14  wget https://download.elastic.co/elasticsearch/release/org/elasticsearch/distribution/deb/elasticsearch/2.4.6/elasticsearch-2.4.6.deb
   15  dpkg -i elasticsearch-2.4.6.deb 
   16  free -m
   17  service elasticsearch restart
   18  pip
   19  easy_install -U pip
   20  # SET UP FIREWALL!!!!
   21  apt-get install ufw
   22  ufw status
   23  vim /etc/default/ufw 
   24  ufw default deny incoming
   25  ufw default allow outgoing
   26  ufw allow ssh
   27  ufw allow 80
   28  ufw allow 443
   29  ufw enable
   30  cd /opt
   31  ls
   32  mkdir selfmarket
   33  cd selfmarket/
   34  ls
   35  git clone https://github.com/scaltro/selfmarket.git
   36  apt install git
   37  git clone https://github.com/scaltro/selfmarket.git
   38  git clone https://github.com/scaltro/selfmarket.git .
   39  ls
   40  pip install -r requirements.txt 
   41  mysql -uroot -p
   42  ls -la
   43  cat manage
   44  ./manage db upgrdade
   45  ./manage db upgrade
   46  ls
   47  cat config.py.save 
   48  ll
   49  cp config.py.save config.py
   50  vim config.py
   51  ./manage db upgrade
   52  apt-get install nginx
   53  cd /etc/nginx/
   54  ls
   55  cd sites-
   56  cd sites-enabled/
   57  ls
   58  vim default 
   59  service nginx restart
   60  service nginx status
   61  cd /opt/selfmarket/
   62  ls
   63  cd
   64  wget https://nodejs.org/dist/v6.11.1/node-v6.11.1-linux-x64.tar.xz
   65  ls
   66  rm node-v6.11.1-linux-x64.tar.xz
   67  mv node-v6.11.1-linux-x64.tar.xz.1 node-v6.11.1-linux-x64.tar.xz
   68  l
   69  tar xf node-v6.11.1-linux-x64.tar.xz 
   70  ls
   71  cd node-v6.11.1-linux-x64/
   72  ls
   73  rm CHANGELOG.md LICENSE README.md 
   74  ls
   75  mv * /usr/local
   76  mv -f * /usr/local
   77  cp -R * /usr/local
   78  ls
   79  cd ..
   80  ls
   81  node -v
   82  cd /opt/selfmarket/
   83  ls
   84  cd frontend/
   85  ls
   86  # INSTALLING FRONTEND DEPS
   87  npm install
   88  ls
   89  npm run build
   90  ls
   91  cd ..
   92  ls
   93  # INSTALLING PM2
   94  npm install -g pm2
   95  whereis gunicorn
   96  pm2 start /usr/local/bin/gunicorn --name="web" --interpreter=python -- app:app -b 127.0.0.1:8080 --chdir /opt/selfmarket -e SIMPLEFLASK_CONFIG="config.ProductionConfig"
   97  pm2 ls
   98  cd ..
   99  ls
  100  git clone https://github.com/scaltro/selfmarket-chat.git .
  101  git clone https://github.com/scaltro/selfmarket-chat.git 
  102  cd selfmarket-chat/
  103  ls
  104  npm install
  105  ls
  106  vim .env
  107  pm2 start server.js --name "messaging"
  108  pm2 logs
  109  pm2 stop messaging # FORGOT TO ADD MESSAGING DB
  110  mysql -uroot -p
  111  pm2 start messaging
  112  pm2 los
  113  pm2 logs
  114  # THAT'S IT
  115  ls
  116  pm2 ls
  117  pm2 stop all
  118  ls
  119  cd /opt/selfmarket
  120  git pull
  121  ./manage db upgrade
  122  ls
  123  cd
  124  ls
  125  scp root:139.162.158.229/root/main.sql .
  126  scp root@139.162.158.229/root/main.sql .
  127  scp 139.162.158.229/root/main.sql .
  128  ip a
  129  scp root@139.162.158.229:/root/main.sql .
  130  scp root@139.162.158.229:/root/messaging.sql .
  131  cd /opt/selfmarket
  132  ls
  133  vim config.py
  134  mysql -uroot -p
  135  cd 
  136  ls
  137  mysql -uroot -p selfmarket < main.sql 
  138  ip a
  139  mysql -uroot -p selfmarket
  140  cd /opt/selfmarket
  141  ./manage db upgrade
  142  mysql -uroot -p selfmarket
  143  mysql -uroot -p 
  144  ./manage db upgrade
  145  mysql -uroot -p 
  146  cd ../selfmarket-chat/
  147  ls
  148  npm run migrate
  149  mysql -uroot -p 
  150  cd ../selfmarket
  151  ls
  152  cd
  153  ls
  154  vim main.sql 
  155  mysql -uroot -p 
  156  scp root@139.162.158.229:/root/main.sql .
  157  ls
  158  vim main.sql 
  159  mysql -uroot -p 
  160  ls
  161  pm2 ls
  162  pm2 start web
  163  pm2 start messaging
  164  cd /opt/selfmarket
  165  ls
  166  ./manage rebuild_search_index
  167  service elasticsearch start
  168  service elasticsearch status
  169  chkconfig
  170  systemctl
  171  systemctl status elasticsearch
  172  systemctl enable elasticsearch
  173  service elasticsearch status
  174  cd /var/log/elasticsearch/
  175  ls
  176  vim elasticsearch
  177  vim elasticsearch.log
  178  apt-get search jre
  179  apt search jre
  180  apt remove openjdk-9-jre
  181  apt install openjdk-8-jre
  182  apt-get update
  183  apt install openjdk-8-jre
  184  service elasticsearch start
  185  service elasticsearch status
  186  java -version
  187  vim /etc/alternatives/
  188  update-java-alternatives
  189  update-java-alternatives -v
  190  update-java-alternatives -l
  191  update-java-alternatives java-1.8.0-openjdk-amd64
  192  update-java-alternatives -s java-1.8.0-openjdk-amd64
  193  vim /etc/alternatives/
  194  java -v
  195  java -version
  196  service elasticsearch status
  197  service elasticsearch start
  198  service elasticsearch status
  199  cd /opt/selfmarket
  200  ls
  201  ./manage rebuild_search_index
  202  vim /etc/nginx/de
  203  vim /etc/nginx/sites-enabled/
  204  pm2 logs web
  205  mysql --version
  206  cat requirements.txt 
  207  pip install SQLAlchemy
  208  pip install SQLAlchemy -U
  209  pip install Flask-SQLAlchemy -U
  210  pm2 restart web
  211  pm2 logs
  212  vim /etc/mysql/mysql.cnf 
  213  vim /etc/mysql/mysql.conf.d/mysqld
  214  vim /etc/mysql/mysql.conf.d/mysqld.cnf 
  215  service mysql restart
  216  service mysql status
  217  pm2 logs messages
  218  pm2 logs messaging
  219  pm2 restart messaging
  220  pm2 logs messaging
  221  vim /etc/nginx/sites-enabled/
  222  service nginx restart
  223  ls
  224  history > install_history.txt


```


