import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('179.43.123.220', port=5375, username='root', password='Willy.48462800')

cmds = [
    'cd /var/www/enviobot-full && git pull origin main',
    'grep -q ML_SHARED_CLIENT_ID /var/www/enviobot-full/.env || echo ML_SHARED_CLIENT_ID=1845856849463362 >> /var/www/enviobot-full/.env',
    'grep -q ML_CLIENT_SECRET /var/www/enviobot-full/.env || echo ML_CLIENT_SECRET=2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q >> /var/www/enviobot-full/.env',
    'sed -i "s/^ML_SHARED_CLIENT_ID=.*/ML_SHARED_CLIENT_ID=1845856849463362/" /var/www/enviobot-full/.env',
    'sed -i "s/^ML_CLIENT_SECRET=.*/ML_CLIENT_SECRET=2f2cg8ZGY4X9pLOFxgPUOAQefHQePf6q/" /var/www/enviobot-full/.env',
    'systemctl restart enviobot-full',
    'systemctl is-active enviobot-full'
]

for cmd in cmds:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    print(f'CMD: {cmd}')
    if out: print(out.strip())
    if err: print(err.strip())

ssh.close()
print('DONE')
