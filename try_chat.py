"""
手测工具：一行命令调 /v1/chat 或 /v1/usage，并查库对账。

用法：
    python try_chat.py                              # 默认 prompt 调 /v1/chat
    python try_chat.py "随便一句话"                   # 自定义 prompt
    python try_chat.py "hi" --db                    # 顺带把最近 5 条账查出来
    python try_chat.py --usage                      # 查 /v1/usage（用 zhong）
    python try_chat.py --usage --user a:b           # 用指定账号查 usage
    python try_chat.py --register --user a:b        # 先注册这个账号（造空用户）
    python try_chat.py --usage --user a:b --register # 注册完立刻查（空用户用例）

为什么不用 PowerShell 的 Invoke-WebRequest 测中文：
    Windows PowerShell 5.1 发字符串 body 时不按 UTF-8 编码，
    中文会变成 '?'（数据不可逆丢失）；收响应时又按 ISO-8859-1 解码，
    即使数据是对的也显示成乱码。
    → 测接口一律用这个脚本（或浏览器 /docs）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx

BASE = "http://127.0.0.1:8000"
DEFAULT_USER = ("zhong", "12345678")


def pick_user(argv: list[str]) -> tuple[str, str]:
    """从 --user name:pass 里取账号，没有就用默认的。"""
    if "--user" in argv:
        raw = argv[argv.index("--user") + 1]
        name, _, pwd = raw.partition(":")
        return name, pwd
    return DEFAULT_USER


def register(user: tuple[str, str]) -> None:
    name, pwd = user
    r = httpx.post(f"{BASE}/auth/register", json={"username": name, "password": pwd})
    if r.status_code == 201:
        print(f"注册成功: {name} (id={r.json()['id']})")
    elif r.status_code == 409:
        print(f"用户已存在: {name}")
    else:
        sys.exit(f"注册失败 {r.status_code}: {r.text}")


def login(user: tuple[str, str]) -> str:
    name, pwd = user
    r = httpx.post(f"{BASE}/auth/login", json={"username": name, "password": pwd})
    if r.status_code != 200:
        sys.exit(f"登录失败 {r.status_code}: {r.text}")
    return r.json()["access_token"]


def auth_headers(user: tuple[str, str]) -> dict:
    return {"Authorization": f"Bearer {login(user)}"}


def chat(prompt: str, user: tuple[str, str]) -> dict:
    r = httpx.post(f"{BASE}/v1/chat", json={"prompt": prompt}, headers=auth_headers(user))
    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text)
        sys.exit(1)
    return r.json()


def show_usage(user: tuple[str, str]) -> None:
    name, _ = user
    r = httpx.get(f"{BASE}/v1/usage", headers=auth_headers(user))
    print(f"HTTP {r.status_code}   (用户 {name})")
    if r.status_code != 200:
        print(r.text)
        sys.exit(1)
    j = r.json()
    print("\n--- /v1/usage ---")
    for k, v in j.items():
        print(f"  {k:<26} {v!r}")
    print("\n  ⚠️ 检查：所有数字都应该是 0（空用户），cost 是字符串 '0.000000' 不是 None")


def show_db(n: int = 5) -> None:
    from db import SessionLocal, ApiCall
    from sqlalchemy import select

    with SessionLocal() as s:
        rows = s.scalars(select(ApiCall).order_by(ApiCall.id.desc()).limit(n)).all()
        print(f"\n--- 最近 {len(rows)} 条账 ---")
        print(f"{'id':>3} {'user_id':>7} {'p_tok':>6} {'c_tok':>6} {'cost':>12} "
              f"{'status':>8}  created_at")
        for row in rows:
            print(f"{row.id:>3} {row.user_id:>7} {row.prompt_tokens:>6} "
                  f"{row.completion_tokens:>6} {str(row.cost):>12} "
                  f"{row.status:>8}  {row.created_at}")


def main() -> None:
    argv = sys.argv[1:]
    user = pick_user(argv)

    # 把 --user 后面那个值、以及各种开关都剔掉，剩下的才算 prompt
    flags = {"--db", "--usage", "--register", "--user"}
    positional = []
    skip_next = False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a == "--user":
            skip_next = True
            continue
        if a in flags:
            continue
        positional.append(a)

    if "--register" in argv:
        register(user)
        if "--usage" not in argv:
            return

    if "--usage" in argv:
        show_usage(user)
        return

    prompt = positional[0] if positional else "你好，介绍一下你自己"
    print(f"prompt = {prompt!r}  (长度 {len(prompt)})")
    j = chat(prompt, user)
    print(f"  reply           = {j['reply']}")
    print(f"  model           = {j['model']}")
    print(f"  prompt_tokens   = {j['prompt_tokens']}")
    print(f"  completion_tokens = {j['completion_tokens']}")
    print(f"  cost            = {j['cost']}   (类型: {type(j['cost']).__name__})")

    if "--db" in argv:
        show_db()


if __name__ == "__main__":
    main()
