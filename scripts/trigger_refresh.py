import sys
import requests

def trigger_refresh(shop_id):
    """
    Manually triggers a real-time refresh of the Levix Dashboard 
    for the specified shop_id using the SSE broadcast system.
    """
    url = f"http://127.0.0.1:8000/admin/force-refresh/{shop_id}"
    try:
        response = requests.post(url)
        if response.status_code == 200:
            print(f"✅ Successfully triggered refresh for Shop ID: {shop_id}")
        else:
            print(f"❌ Failed to trigger refresh. Server returned: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"❌ Error connecting to server: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python trigger_refresh.py <shop_id>")
        sys.exit(1)
    
    target_shop_id = sys.argv[1]
    trigger_refresh(target_shop_id)
