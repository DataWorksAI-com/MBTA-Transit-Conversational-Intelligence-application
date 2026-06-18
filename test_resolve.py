#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import paramiko
HOST = '96.126.111.107'
PASSWORD = 'aN09lBKu0cqo6GAiBgTOrbkcz'
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=22, username='root', password=PASSWORD, timeout=30)

def run(cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, out, err

# Test resolve
code, out, err = run('curl -s -X POST http://localhost:8300/resolve -H "Content-Type: application/json" -d \'{"agent":"fares","requester_context":{}}\'', timeout=30)
print('RESOLVE RESULT:')
print(out)
if err:
    print('STDERR:', err)

# Also test /agents
code2, out2, err2 = run('curl -s http://localhost:8300/agents', timeout=10)
print('\nAGENTS RESULT:')
print(out2)

client.close()
