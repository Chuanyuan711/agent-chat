import requests
import sys

if len(sys.argv) < 3:
    print("Usage: python send.py <sender> <content> [thread_id]")
    sys.exit(1)

sender = sys.argv[1]
content = sys.argv[2]
thread_id = sys.argv[3] if len(sys.argv) > 3 else "general"

resp = requests.post('http://localhost:9090/messages', json={
    'sender': sender,
    'content': content,
    'thread_id': thread_id
})
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print("已发送")
else:
    print(f"Error: {resp.text}")
