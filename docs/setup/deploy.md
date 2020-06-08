### Manual deploy

simple way for manual deploy,  
just place this code in .bash_profile or .bashrc

```bash
jobupdate() {
    sshpass -p "password" ssh root@172.104.145.11 "cd /opt/selfmarket; bash update.sh"
}
```

just run `jobupdate` cmd on terminal




