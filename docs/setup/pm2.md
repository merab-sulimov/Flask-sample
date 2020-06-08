## Quick setup of PM2

### Installing and adding to startup

`npm install -g pm2` to install
`pm2 startup` to autostart PM2 after system boots

### Adding our workers

Starting `web` worker (which is the Flask application).

Worker timeout is increased from 30 to 90 seconds (uploading video to cloudinary can take more than 30 seconds in some cases).

In addition, python stdout/stderr buffering disabled by adding python interpreter argument `-u`. This allows to observe live logs via `pm2 logs` 

```bash
cd /opt/selfmarket
pm2 start /usr/local/bin/gunicorn --name="web" --interpreter=python --interpreter-args="-u" -- app:app -b 127.0.0.1:8080 --timeout 90 --chdir /opt/selfmarket -e SIMPLEFLASK_CONFIG="config.ProductionConfig"
```

Starting `background` worker (which is the script running periodic tasks)

```bash
cd /opt/selfmarket
SIMPLEFLASK_CONFIG="config.ProductionConfig" pm2 start ./manage.py --name="background" --interpreter=python -- runbackground
```

Starting `messaging` worker (which is the messaging application)

```bash
cd /opt/selfmarket-chat
pm2 start server.js --name "messaging"
```

### Saving process list

This is very important thing to do after adding all workers to the list

`pm2 save` to save process list so they will be resurrected after system startup
