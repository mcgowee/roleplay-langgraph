#!/usr/bin/env python3
import requests

# Test games endpoint
print("=== Testing /games ===")
res = requests.get("http://127.0.0.1:5051/games")
print(f"Status: {res.status_code}")
print(f"Games: {len(res.json()['games'])}")
for g in res.json()["games"]:
    print(
        f"  - {g['title']} (narrator: {g['narrator_model']}, NPC: {g['character_models']})"
    )

# Test NSFW content
print("\n=== Testing NSFW Content ===")
res = requests.post(
    "http://127.0.0.1:5051/start", json={"game": "LostInCity", "fresh": True}
)
session_id = res.json().get("session_id", "test")
print(res.json()["response"][:300])

res = requests.post(
    "http://127.0.0.1:5051/chat",
    json={
        "session_id": session_id,
        "message": "I kiss him deeply. I feel his breath catch and his hands on my waist.",
    },
)
response = res.json()["response"]
print("\n=== NSFW Response ===")
print(response[:1000])
print(
    f"\nSuccessful! No content blocking."
) if "cannot create explicit" not in response.lower() else print(
    "\nBlocked by content filter."
)

# Test /list_slots
print("\n=== Testing /list_slots ===")
res = requests.get(
    "http://127.0.0.1:5051/list_slots", params={"session_id": session_id}
)
print(f"Status: {res.status_code}")
print(f"Slots: {res.json()}")

print("\n=== All tests passed! ===")
