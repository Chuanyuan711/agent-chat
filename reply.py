import requests

# Replies for each message
replies = [
    "test acknowledged",
    "hello!",
    "Shanghai weather today: Partly cloudy, 30C"
]

# Send replies
for reply in replies:
    try:
        resp = requests.post("http://localhost:9090/messages", json={
            "from": "daily-0712",
            "content": f"[pumpkin] {reply}"
        })
        print(f"Sent: {reply[:30]}... -> {resp.status_code}")
        if resp.status_code != 200:
            print(f"  Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

# Clear notifications file
with open(r"C:\Users\sthn\agent-chat\pumpkin_notifications.jsonl", "w") as f:
    pass
print("Notifications cleared")
