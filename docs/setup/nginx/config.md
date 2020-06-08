#nginx configs


## example nginx default config

```
server {
    listen 80;
    server_name static.jobdone.net;

    location ~* \.(eot|otf|ttf|woff|woff2)$ {
        add_header Access-Control-Allow-Origin *;
    }

    root /opt/selfmarket/app/static/;

    location /static/assets/ {
        alias /opt/jobdone-fontend/build/;
        autoindex off;
    }
}


server {
    listen 80 default_server;
    server_name  jobdone.net;

    # Serve bundles from frontend project
    location /static/assets/ {
        alias /opt/jobdone-fontend/build/;
        autoindex off;
    }

    # Serve static files and uploads
    location ^~ /static/ {
        root /opt/selfmarket/app/;
    }

    proxy_read_timeout 90s;
    client_max_body_size 150M;

    if ($http_cf_connecting_ip) {
        set   $real_remote_addr $http_cf_connecting_ip;
    }
    if ($http_cf_connecting_ip = "") {
        set   $real_remote_addr $remote_addr;
    }

    location / {
        proxy_pass "http://127.0.0.1:8080/";
        proxy_redirect     off;
        proxy_cookie_domain localhost jobdone.net;
        proxy_set_header   X-Real-IP $real_remote_addr;
        proxy_pass_header Set-Cookie;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Host $server_name;
    }
}


server {
    listen 80;
    server_name www.jobdone.net;

    return 301 http://jobdone.net$request_uri;
}


server {
    listen 80;
    server_name messaging.jobdone.net;

    client_max_body_size 5M;

    location /ws/ {
        proxy_pass "http://127.0.0.1:8081/ws/";
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        proxy_pass "http://127.0.0.1:8081/";
        proxy_redirect     off;
        proxy_cookie_domain localhost messaging.jobdone.net;
        proxy_pass_header Set-Cookie;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Host $server_name;
    }
}
```