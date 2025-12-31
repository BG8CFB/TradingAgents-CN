#!/usr/bin/env python3
"""
股票筛选 API 测试脚本
"""
import requests
import json

BASE_URL = "http://localhost:3000"
auth_token = None

def print_section(title):
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")

def print_test(name, passed, details=""):
    status = "✓ 通过" if passed else "✗ 失败"
    print(f"{status}: {name}")
    if details:
        print(f"  详情: {details}")

def api_request(endpoint, method="GET", data=None):
    """发送 API 请求"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=120)

        return {
            "success": response.ok,
            "status": response.status_code,
            "data": response.json() if response.content else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# 测试 1: 登录
print_section("测试 1: 用户登录")

result = api_request("/api/auth/login", "POST", {
    "username": "admin",
    "password": "admin123"
})

if result["success"] and result["data"].get("success"):
    auth_token = result["data"]["data"]["token"]
    print_test("用户登录", True, f"Token: {auth_token[:30]}...")
else:
    print_test("用户登录", False, result.get("error", "未知错误"))
    exit(1)

# 测试 2: 获取字段配置
print_section("测试 2: 获取筛选字段配置")

result = api_request("/api/screening/fields")

if result["success"]:
    fields = result["data"].get("fields", {})
    categories = result["data"].get("categories", {})
    print_test("获取字段配置", True, f"共 {len(fields)} 个字段，{len(categories)} 个分类")

    print("  字段示例:")
    for name, info in list(fields.items())[:3]:
        print(f"    - {name}: {info.get('display_name')} ({info.get('field_type')})")
else:
    print_test("获取字段配置", False, result.get("data", {}).get("detail", "未知错误"))

# 测试 3: 获取行业列表
print_section("测试 3: 获取行业列表")

result = api_request("/api/screening/industries")

if result["success"]:
    industries = result["data"].get("industries", [])
    total = result["data"].get("total", 0)
    source = result["data"].get("source", "未知")

    print_test("获取行业列表", True, f"共 {total} 个行业，来源: {source}")

    if industries:
        print("  行业示例 (前5个):")
        for ind in industries[:5]:
            print(f"    - {ind['label']} ({ind['count']} 只股票)")
    else:
        print("  警告: 行业列表为空，需要先同步股票数据")
else:
    print_test("获取行业列表", False, result.get("data", {}).get("detail", "未知错误"))

# 测试 4: 简单筛选
print_section("测试 4: 简单筛选（无条件）")

payload = {
    "market": "CN",
    "date": None,
    "adj": "qfq",
    "conditions": {
        "logic": "AND",
        "children": []
    },
    "order_by": [{"field": "total_mv", "direction": "desc"}],
    "limit": 10,
    "offset": 0
}

result = api_request("/api/screening/run", "POST", payload)

if result["success"]:
    total = result["data"].get("total", 0)
    items = result["data"].get("items", [])

    print_test("简单筛选", True, f"返回 {total} 只股票，显示前 {len(items)} 只")

    if items:
        print("  筛选结果示例 (前3只):")
        for item in items[:3]:
            market_cap = f"{item.get('total_mv', 0):.2f}亿" if item.get('total_mv') else "N/A"
            print(f"    - {item.get('code')} {item.get('name', 'N/A')}: 市值 {market_cap}")
    else:
        print("  警告: 没有筛选到任何股票，需要先同步股票数据")
else:
    print_test("简单筛选", False, result.get("data", {}).get("detail", "未知错误"))
    if result.get("data"):
        print(f"  完整响应: {json.dumps(result['data'], indent=2, ensure_ascii=False)[:500]}")

print_section("测试总结")
print("提示: 如果筛选没有返回数据，请访问 http://localhost:3000/settings/sync 同步股票数据")
