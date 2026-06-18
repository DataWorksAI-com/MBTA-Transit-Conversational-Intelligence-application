#!/usr/bin/env python
"""
Restart Auth NS via supervisorctl and then register fares agents + test /resolve.
"""
import paramiko
import time
import json

HOST = "96.126.111.107"
PORT = 22
USER = "root"
PASSWORD = "aN09lBKu0cqo6GAiBgTOrbkcz"

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)
    return client

def run_cmd(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, out, err

def main():
    print("Connecting to agents server...")
    client = ssh_connect()
    print("Connected!")

    # Check supervisor status
    code, out, err = run_cmd(client, "supervisorctl status mbta-auth-ns")
    print(f"Current supervisor status:\n{out}")

    # Restart via supervisorctl
    print("\nRestarting mbta-auth-ns via supervisorctl...")
    code, out, err = run_cmd(client, "supervisorctl restart mbta-auth-ns")
    print(f"Restart result: code={code}\n{out}\n{err}")

    time.sleep(3)

    # Verify it's running
    code, out, err = run_cmd(client, "supervisorctl status mbta-auth-ns")
    print(f"Status after restart:\n{out}")

    # Check it responds
    print("\nTesting /health endpoint...")
    code, out, err = run_cmd(client, "curl -s http://localhost:8300/health")
    print(f"Health: {out}")

    # Register Boston fares agent
    print("\nRegistering Boston fares agent...")
    boston_cmd = """curl -s -X POST http://localhost:8300/register_agent \
  -H "Content-Type: application/json" \
  -d '{"label":"fares","endpoint":"http://50.116.57.161:50054","agent_id":"mbta-fares-boston","region":"us-east","region_label":"Boston, MA","flag":"\U0001f1fa\U0001f1f8"}'"""
    code, out, err = run_cmd(client, boston_cmd)
    print(f"Boston registration: {out}")

    # Register Frankfurt fares agent
    print("\nRegistering Frankfurt fares agent...")
    frankfurt_cmd = """curl -s -X POST http://localhost:8300/register_agent \
  -H "Content-Type: application/json" \
  -d '{"label":"fares","endpoint":"http://85.90.246.180:50054","agent_id":"mbta-fares-frankfurt","region":"eu-central","region_label":"Frankfurt, DE","flag":"\U0001f1e9\U0001f1ea"}'"""
    code, out, err = run_cmd(client, frankfurt_cmd)
    print(f"Frankfurt registration: {out}")

    # Check /agents to confirm both are registered
    print("\nChecking /agents endpoint...")
    code, out, err = run_cmd(client, "curl -s http://localhost:8300/agents")
    print(f"Agents: {out}")

    # Test /resolve
    print("\nTesting /resolve for 'fares'...")
    resolve_cmd = """curl -s -X POST http://localhost:8300/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent":"fares","requester_context":{}}'"""
    code, out, err = run_cmd(client, resolve_cmd, timeout=30)
    print(f"Resolve result:\n{out}")
    if err:
        print(f"Stderr: {err}")

    client.close()

if __name__ == "__main__":
    main()
