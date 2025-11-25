import requests
import json
from src.encryption_utils import encrypt_data

BASE_URL = "http://127.0.0.1:8000"

# ========== MANAGER CREDENTIALS ==========
# Update these with your actual manager credentials
MANAGER_EMAIL = "admin@example.com"  # Change this
MANAGER_PASSWORD = "admin123"       # Change this

print("=" * 60)
print("🔐 MANAGER LOGIN TESTS")
print("=" * 60)

# Test 1: Normal Manager Login (1 hour token)
print("\n=== Test 1: Manager Login (remember_me=False) ===")
login_data = {
    "email": MANAGER_EMAIL,
    "password": MANAGER_PASSWORD
}
encrypted = encrypt_data(json.dumps(login_data))

response = requests.post(
    f"{BASE_URL}/managers/login",
    json={"encrypted_data": encrypted, "remember_me": False}
)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    print(f"✅ Login successful!")
    print(f"   Role: {result.get('role')}")
    print(f"   Token expires in: {result.get('expires_in')}")
    print(f"   Remember me: {result.get('remember_me')}")
    token_1hour = result.get('access_token')
    print(f"   Token (first 50 chars): {token_1hour[:50]}...")
else:
    print(f"❌ Login failed: {response.json()}")
    exit()

# Test 2: Extended Manager Login (14 days token)
print("\n=== Test 2: Manager Login (remember_me=True) ===")
response = requests.post(
    f"{BASE_URL}/managers/login",
    json={"encrypted_data": encrypted, "remember_me": True}
)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    print(f"✅ Login successful!")
    print(f"   Role: {result.get('role')}")
    print(f"   Token expires in: {result.get('expires_in')}")
    print(f"   Remember me: {result.get('remember_me')}")
    token_14days = result.get('access_token')
    print(f"   Token (first 50 chars): {token_14days[:50]}...")
else:
    print(f"❌ Login failed: {response.json()}")

# Test 3: Check token info for 1-hour token
print("\n=== Test 3: Token Info (1-hour manager token) ===")
response = requests.post(
    f"{BASE_URL}/auth/token-info",
    json={"token": token_1hour}
)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    info = response.json()
    print(f"✅ Token info retrieved!")
    print(f"   Email: {info.get('email')}")
    print(f"   Role: {info.get('role')}")
    print(f"   User ID: {info.get('user_id')}")
    print(f"   Issued at: {info.get('issued_at')}")
    print(f"   Expires at: {info.get('expires_at')}")
    print(f"   Time remaining: {info.get('time_remaining_minutes'):.2f} minutes")
else:
    print(f"❌ Failed: {response.json()}")

# Test 4: Check token info for 14-day token
print("\n=== Test 4: Token Info (14-day manager token) ===")
response = requests.post(
    f"{BASE_URL}/auth/token-info",
    json={"token": token_14days}
)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    info = response.json()
    print(f"✅ Token info retrieved!")
    print(f"   Email: {info.get('email')}")
    print(f"   Role: {info.get('role')}")
    print(f"   Time remaining: {info.get('time_remaining_minutes'):.2f} minutes")
    print(f"   Time remaining (hours): {info.get('time_remaining_minutes') / 60:.2f} hours")
    print(f"   Time remaining (days): {info.get('time_remaining_minutes') / 1440:.2f} days")
else:
    print(f"❌ Failed: {response.json()}")

# Test 5: Extend the 1-hour token
print("\n=== Test 5: Extend Manager Token ===")
response = requests.post(
    f"{BASE_URL}/auth/extend-token",
    json={"token": token_1hour}
)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    print(f"✅ Token extended!")
    print(f"   Message: {result.get('message')}")
    print(f"   Extended by: {result.get('extended_minutes')} minutes")
    print(f"   New expiration: {result.get('new_expiration')}")
    extended_token = result.get('new_token')
    print(f"   New token (first 50 chars): {extended_token[:50]}...")
else:
    print(f"❌ Failed: {response.json()}")

# Test 6: Use token to access protected endpoint
print("\n=== Test 6: Access Protected Endpoint with Token ===")
response = requests.get(
    f"{BASE_URL}/profile/me",
    headers={"Authorization": f"Bearer {token_1hour}"}
)
print(f"Status: {response.status_code}")

if response.status_code == 200:
    profile = response.json()
    print(f"✅ Profile accessed!")
    print(f"   Full name: {profile.get('full_name')}")
    print(f"   Email: {profile.get('email')}")
    print(f"   Role: {profile.get('role')}")
else:
    print(f"❌ Failed: {response.json()}")

print("\n" + "=" * 60)
print("✅ ALL MANAGER LOGIN TESTS COMPLETED!")
print("=" * 60)