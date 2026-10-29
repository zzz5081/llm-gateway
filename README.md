# LLM 调用网关 + 用量统计

一个基于 **FastAPI** 的大模型统一调用服务：给内部多个应用提供「统一调大模型」的后端能力 ——
**集中管理调用、记录 token 与费用、查询用量**。

> 个人学习项目（进行中）。技术栈与项目结构按生产后端的方式组织：鉴权、记账、异常分支、接口测试、数据库索引设计。

---

## 这是什么

在公司里，如果 10 个业务应用各自去调大模型，会有三个问题：

1. **密钥散落**：API Key 存在 10 个地方，泄露了不知道是哪个
2. **成本不可见**：月底账单一来，不知道钱花在谁身上
3. **没有统一治理**：限流、重试、模型切换各写各的

所以需要一个网关：**所有调用都经过它，它负责转发、记账、统计。**

本项目实现了其中的 MVP：

| 接口 | 作用 |
|---|---|
| `POST /auth/register` | 注册（密码 bcrypt 加盐哈希） |
| `POST /auth/login` | 登录，签发 JWT |
| `GET /auth/me` | 查当前用户 |
| `POST /v1/chat` | **转发到 LLM，并把 token / 费用落库记账** |
| `GET /v1/usage` | **查用量：今日/本月 × 成功/失败 + 总 token + 总花费** |

---

## 技术栈

```
Python 3.12        FastAPI 0.141      Pydantic 2.13
SQLAlchemy 2.0     MySQL 8.0          PyMySQL
PyJWT 2.15         bcrypt 5.0         python-dotenv
pytest 9.1         httpx（TestClient）
```

---

## 三个值得说的设计决策

### 1. LLM 调用层可切换：`LLM_MODE=mock|real`

```python
# llm_client.py
LLM_MODE = os.environ.get("LLM_MODE", "mock")

def chat_completion(prompt, model=DEFAULT_MODEL, temperature=0.0) -> dict:
    result = _mock_call(prompt) if LLM_MODE == "mock" else _real_call(...)
    result["model"] = model
    result["cost"] = calc_cost(model, result["prompt_tokens"], result["completion_tokens"])
    return result
```

**为什么要这样分层：**

- **测试不依赖外部 API**：pytest 全程跑 mock，不需要真实 Key、不花钱、不会因为网络抖动而红
- **计费逻辑独立可测**：`calc_cost()` 是纯函数，可以单独测
- **mock 与 real 返回同一形状**：切换上下层时，上面的路由代码一行都不用改

> 细节：mock 的回复带 `[mock]` 前缀（`f"[mock] 你说的是: {prompt}"`），
> 让「假数据」自带指纹 —— 如果哪天误把用户输入当成 LLM 回复返回，一眼就能看出来。

### 2. 金额用 `Decimal`，不用 `float`

```python
PRICE = {"gpt-4o-mini": {"prompt": Decimal("0.15"), "completion": Decimal("0.60")}}
cost = mapped_column(Numeric(10, 6))
```

**实测差异：**

```
Decimal 累加 1000 次  → 0.45000         ✅
float   累加 1000 次  → 0.450000000000005  ❌
```

金额计算一旦用 float，误差会随着调用量累积，最后对不上账。

### 3. `api_calls` 表的联合索引按「最左前缀」设计

```python
Index("ix_api_calls_user_created", "user_id", "created_at")
```

用量查询几乎都是「**某个用户的、某个时间段内的**」记录 —— 所以**等值字段（user_id）在前，范围字段（created_at）在后**。

```
WHERE user_id = ?                        → key_len = 4   （只用第 1 列）
WHERE user_id = ? AND created_at >= ?    → key_len = 9   （两列都用上）
WHERE created_at >= ?                    → 跳过第 1 列，索引失效
```

---

## 记账的失败分支

`POST /v1/chat` 失败时**也要记一笔账**：

```python
try:
    result = chat_completion(...)
except Exception:
    db.add(ApiCall(user_id=current_user.id, model=body.model, status="failed"))
    db.commit()
    raise HTTPException(502, "上游服务暂时不可用")
```

**三个考虑：**

1. **成本可观测**：失败的调用也要能在报表里看见，否则「有人拿错误请求刷接口」这件事在数据上隐身
2. **`try` 只包住 LLM 调用那一行**：写库失败不是「上游挂了」，不该报 502
3. **`detail` 只写人话**：不把异常原文返回给客户端（避免泄露内部信息），

另外 `/v1/usage` 把 **成功和失败分开统计**，而不是混成一个数 —— 双方都能看到真相。

---

## 用量统计：一条 SQL 算 7 个指标

```sql
SELECT
  COUNT(CASE WHEN created_at >= CURDATE() AND status='success' THEN 1 END) AS today_success,
  COUNT(CASE WHEN created_at >= CURDATE() AND status='failed'  THEN 1 END) AS today_failed,
  COUNT(CASE WHEN created_at >= DATE_FORMAT(CURDATE(),'%Y-%m-01') AND status='success' THEN 1 END) AS month_success,
  COUNT(CASE WHEN created_at >= DATE_FORMAT(CURDATE(),'%Y-%m-01') AND status='failed'  THEN 1 END) AS month_failed,
  COALESCE(SUM(prompt_tokens),0)     AS total_prompt_tokens,
  COALESCE(SUM(completion_tokens),0) AS total_completion_tokens,
  COALESCE(SUM(cost),0)              AS total_cost
FROM api_calls
WHERE user_id = :uid
```

**两个踩过的坑：**

- **`SUM` 在空集上返回 `NULL`，不是 0** —— 新用户零调用时，`SUM(cost)` 返回 NULL，
  直接塞进 Pydantic 的 `Decimal` 字段会抛 `ValidationError` → 接口 500。
  所以 `SUM/AVG/MAX/MIN` 必须包 `COALESCE(..., 0)`；而 `COUNT` 返回 0，不用包。
  （即使写 `SUM(CASE WHEN ... ELSE 0 END)` 也没用 —— 零行时 CASE 从未被求值）
- **日期边界交给数据库算**（`CURDATE()`），不在 Python 里算 ——
  否则 Python 的时区和 MySQL 的时区不一致，凌晨 0–8 点的调用会被算进「昨天」

---

## 安全设计

| 机制 | 实现 |
|---|---|
| 密码存储 | bcrypt 加盐哈希（实测比 sha256 慢约 33 万倍） |
| 身份认证 | JWT（HS256），`Authorization: Bearer <token>` |
| 鉴权 | FastAPI `Depends` + `HTTPBearer` 注入当前用户 |
| **防越权（IDOR）** | **`user_id` 只从 JWT 解出的 `current_user.id` 取，绝不信请求体** |
| 输入校验 | Pydantic 模型约束 + 模型白名单（不在价格表 → 422） |
| 错误信息 | 5xx 只返回人话，异常原文不返回给客户端 |

---

## 怎么跑起来

### 1. 建库和账号

```sql
CREATE DATABASE llm_gateway_db CHARACTER SET utf8mb4;
CREATE USER 'dev'@'localhost' IDENTIFIED BY '换成你自己的密码';
GRANT ALL ON llm_gateway_db.* TO 'dev'@'localhost';
```

### 2. 装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，填入：

```
APP_SECRET=<随机字符串，用于签发 JWT>
DATABASE_URL=mysql+pymysql://dev:你的密码@localhost/llm_gateway_db?charset=utf8mb4
LLM_MODE=mock
```

> `.env` 已在 `.gitignore` 里，不会被提交。

### 4. 建表并起服务

```bash
python reset_db.py                 # 建表（开发期：DROP + 重建，会要求输入 yes 确认）
python -m uvicorn main:app --reload
```

打开 http://127.0.0.1:8000/docs

### 5. 手动试一遍

```bash
python try_chat.py                              # 调一次 /v1/chat
python try_chat.py --usage                      # 查自己的用量
python try_chat.py --usage --user 用户名:密码     # 查指定用户的用量
```

> `try_chat.py` 是手测工具，用 httpx 直接打接口。
> 不用 PowerShell 的 `Invoke-RestMethod` 是因为它在 Windows PowerShell 5.1 下
> 会把请求体里的中文编码成 `?`（数据不可逆丢失），响应也按错误的编码解码。

---

## 测试

```bash
python -m pytest -v
```

```
tests/test_smoke.py    3 个  健康检查 / 响应头 / 404
tests/test_auth.py     5 个  注册 / 重复注册 409 / 登录 / 密码错 401 / 无 token 401
tests/test_chat.py     2 个  chat 成功落库 / LLM 挂掉返回 502 且记 status='failed'
                      ─────
                      10 个  全绿
```

**测试的几个做法：**

- **fixture 里也断言**：注册/登录失败时直接报出真实原因，而不是在后面抛出一个看不懂的 `KeyError: 'access_token'`
- **用 `monkeypatch` 注入故障**：mock 模式永远不会失败，所以测试里把 `routers.chat.chat_completion` 换成会抛异常的函数
  （注意要打 `routers.chat` 这份，因为 `from x import f` 是把名字复制进当前模块）
- **断言看内容，不只看状态码**：
  ```python
  assert "[mock]" in r.json()["reply"]        # 只 assert 非空抓不到"回显用户输入"的 bug
  assert len(rows) == 1                        # 同时抓「漏写」和「重复记账」
  assert "RuntimeError" not in r.text          # 锁住"别把异常原文吐给客户端"
  ```
- **跑完查库**：`pytest` 全绿不代表数据库干净，清理失效是静默的 —— 每次跑完对一下 `COUNT(*)`

---

## 目录结构

```
.
├── main.py            应用入口：路由挂载 / CORS / 请求耗时中间件
├── db.py              ORM 模型（users / api_calls）+ 引擎 + Session
├── security.py        bcrypt 哈希 + JWT 签发与校验
├── deps.py            get_current_user 依赖（HTTPBearer）
├── schemas.py         Pydantic 请求/响应模型
├── llm_client.py      LLM 调用层（mock / real 可切换）+ 计费
├── routers/
│   ├── auth.py        注册 / 登录 / me
│   ├── chat.py        POST /v1/chat
│   └── usage.py       GET  /v1/usage
├── tests/             pytest 接口测试
├── conftest.py        fixture：client / cleanup / temp_user / auth_user / make_user
├── reset_db.py        开发工具：重建表
└── try_chat.py        手测工具（CLI）
```

---

## 还没做的

- [ ] 真实 LLM 调用（`_real_call` 目前抛 `NotImplementedError`，计划接 OpenAI 兼容接口）
- [ ] Redis：限流 + 结果缓存（`temperature == 0` 时才能缓存，否则会改变语义）
- [ ] Docker 化 + 部署上线
- [ ] Alembic 迁移（目前用 `reset_db.py` 重建，生产环境必须用迁移工具）
- [ ] 金额精度口径统一（接口返回 7 位小数，数据库 `NUMERIC(10,6)` 存 6 位，需要对账策略）

---

## 备注

这个项目是学习过程中做的，代码里有不少注释是给自己看的。
如果发现任何问题，欢迎指出。
