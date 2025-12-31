import requests
import json

BASE_URL = "http://localhost:3000"

# 登录
login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
    "username": "admin",
    "password": "admin123"
})
print("登录状态:", login_resp.status_code)
token = login_resp.json()["data"]["token"]
print("Token:", token[:50] if token else "None")

# 测试字段配置
fields_resp = requests.get(f"{BASE_URL}/api/screening/fields")
print("\n字段配置:", fields_resp.status_code)
if fields_resp.ok:
    data = fields_resp.json()
    print(f"字段数量: {len(data.get('fields', {}))}")

# 测试行业列表
industries_resp = requests.get(f"{BASE_URL}/api/screening/industries")
print("\n行业列表:", industries_resp.status_code)
if industries_resp.ok:
    data = industries_resp.json()
    industries = data.get("industries", [])
    print(f"行业数量: {len(industries)}")
    if industries:
        print(f"第一个行业: {industries[0]}")

# 测试简单筛选
payload = {
    "market": "CN",
    "date": None,
    "adj": "qfq",
    "conditions": {"logic": "AND", "children": []},
    "order_by": [{"field": "total_mv", "direction": "desc"}],
    "limit": 10,
    "offset": 0
}
screen_resp = requests.post(
    f"{BASE_URL}/api/screening/run",
    json=payload,
    headers={"Authorization": f"Bearer {token}"}
)
print("\n筛选结果:", screen_resp.status_code)
if screen_resp.ok:
    data = screen_resp.json()
    print(f"总数: {data.get('total', 0)}")
    print(f"返回: {len(data.get('items', []))} 条")
    if data.get('items'):
        print(f"第一只股票: {data['items'][0]}")
else:
    print(f"错误: {screen_resp.text}")
