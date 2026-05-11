import requests
import os
import base64

with open('/home/.z/chat-images/image (1).png', 'rb') as f:
    img_b64 = base64.b64encode(f.read()).decode('utf-8')

response = requests.post(
    "https://api.zo.computer/zo/ask",
    headers={
        "authorization": os.environ["ZO_CLIENT_IDENTITY_TOKEN"],
        "content-type": "application/json"
    },
    json={
        "input": "Transcribe the text shown in the terminal output area in the image.",
        "model_name": "byok:3df13045-245b-450d-a69d-9c630618f5f6",
        "attachments": [{"type": "image/png", "data": img_b64}]
    }
)
print(response.json())
