"""
获取飞书用户 open_id 的小工具
用法：python get_openid.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from feishu import FeishuClient

client = FeishuClient()
token = client._get_token()

# 尝试通过 /users/me 获取当前用户信息
import requests

headers = {"Authorization": f"Bearer {token}"}

# 方式1：获取机器人自身信息
resp = requests.get(
    "https://open.feishu.cn/open-apis/contact/v3/users/me",
    headers=headers,
    timeout=10,
)
data = resp.json()
if data.get("code") == 0:
    user = data.get("data", {}).get("user", {})
    print(f"✅ 你的用户信息：")
    print(f"   open_id: {user.get('open_id', 'N/A')}")
    print(f"   user_id: {user.get('user_id', 'N/A')}")
    print(f"   姓名: {user.get('name', 'N/A')}")
else:
    print(f"⚠️ 方式1失败: [{data.get('code')}] {data.get('msg')}")
    print("可能需要开通 contact:user.employee_id:readonly 权限")
    print()
    print("尝试方式2：通过机器人发消息给自己...")

    # 方式2：先尝试通过 /im/v1/messages 发一条测试消息，从响应中获取 open_id
    # 但发消息需要知道 open_id... 死循环了。

    print()
    print("=" * 50)
    print("请手动获取 open_id：")
    print("1. 访问 https://open.feishu.cn/api-explorer/")
    print("2. 左侧选「获取用户信息」-> /open-apis/contact/v3/users/me")
    print("3. 点「调试」复制返回中的 open_id")
