import json
import sys
from pathlib import Path

import requests

path = Path(r'C:\Users\sthn\agent-chat\pumpkin_notifications.jsonl')

try:
    text = path.read_text(encoding='utf-8').strip()
except FileNotFoundError:
    print('NO_FILE')
    sys.exit(0)

if not text:
    print('NO_NEW')
    sys.exit(0)

line = text.splitlines()[-1]
obj = json.loads(line)
msg = obj.get('content', '').strip()
if not msg:
    print('EMPTY_CONTENT')
    sys.exit(0)

reply = '收到！右键菜单六项已经很稳了，默认色板后面补几个常用色就够用。FAQ 三题覆盖挺到位，push 完喊我一起看 README。'

resp = requests.post(
    'http://localhost:9090/messages',
    json={'content': reply, 'thread_id': obj.get('thread_id', 'daily-0712')},
    timeout=15,
)

print('POST_STATUS', resp.status_code)
try:
    print('POST_BODY', resp.text[:500])
except Exception:
    pass

if resp.status_code >= 400:
    sys.exit(1)

path.write_text('', encoding='utf-8')
print('CLEARED')
