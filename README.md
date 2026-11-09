# LLM 调用网关 + 用量统计

一个基于 **FastAPI** 的大模型统一调用服务：给内部多个应用提供「统一调大模型」的后端能力 ——
**集中管理调用、记录 token 与费用、查询用量**。

🌐 **线上演示**：<http://162.14.105.155:8000/docs> （腾讯云轻量 · Docker 三容器编排）

> 个人学习项目。技术栈与项目结构按生产后端的方式组织：鉴权、记账、限流、缓存、异常分支、接口测试、容器化部署。
>
> ⚠️ 演示环境跑的是 `LLM_MODE=mock`（不调真实 API、不产生费用），里面是测试数据。

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
Redis 8.1          PyJWT 2.15         bcrypt 5.0
python-dotenv      pytest 9.1         httpx（TestClient）

容器化：Dockerfile（python:3.12-slim）+ docker-compose（app / mysql / redis 三服务）
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
| **限流** | Redis 固定窗口计数器，`10 次 / 60 秒`，超限 429（**在调 LLM 之前拦截**） |

---

## 限流 + 缓存（Redis）

两个都落在 Redis 上，但解决的问题相反：**限流是省「下游的钱」**（别让一个用户把额度刷爆），
**缓存是省「上游的钱」**（同样的确定性请求不重复付费）。

### 限流：固定窗口计数器

```python
# ratelimit.py
bucket = int(time.time()) // window     # 按 window 对齐的窗口号
key = f"rl:{user_id},{bucket}"
n = r.incr(key)                          # 原子自增
if n == 1:
    r.expire(key, window)                # 只在窗口第一次设过期
return (n <= limit, n)
```

**三个设计点：**

1. **为什么用 Redis 而不是 MySQL** —— MySQL 每次要 `UPDATE` 一行，高频下会把数据库打爆；
   Redis 的 `INCR` 是内存里的原子操作，几乎零成本
2. **窗口推进只能靠一个机制** —— 桶号已经进了 key 名，所以 `EXPIRE` 只是兜底清理。
   如果既靠桶号又靠 TTL 做窗口推进，两者会打架
3. **限流必须在调 LLM 之前** —— 放在后面的话，钱已经花了再返回 429，等于没限流

**已知缺陷（写出来是因为知道它存在）：**

```
固定窗口的「边界双倍」：
用户在 t=59s 打满 10 次，t=61s 再过 2 秒又打满 10 次
→ 2 秒内实际通过了 20 次，是本该允许速率的 2 倍
解法：滑动窗口（ZSET 存时间戳）或令牌桶 —— 本项目暂不做
```

实测：第 1–10 次返回 200，第 11 次起返回 429。
**注意：被拒绝的请求也会 `INCR`**，所以超限后计数器只涨不跌，要等窗口翻页才恢复 ——
这是刻意的（防止在窗口末尾反复试探），代价是一旦超限，剩余窗口内会被彻底锁死。

### 缓存：只缓存 `temperature == 0`

```python
if body.temperature == 0:                       # ★ 只有确定性请求才缓存
    ck = "cache:" + sha256(json({"prompt": ..., "model": ...}))
    hit = r.get(ck)
    if hit:
        return {...,
                "prompt_tokens": 0, "completion_tokens": 0,
                "cost": Decimal("0"), "cached": True}   # ★ 命中不记账
```

**两个关键取舍：**

1. **`temperature > 0` 绝不缓存** —— 采样本来就是「每次不一样」，缓存会改变语义
   （用户要的就是多样性，你给他同一句回复就是 bug）
2. **命中不写 `api_calls`** —— 命中时没有产生真实成本，记账就错了；
   但接口仍返回 `cached: true`，让调用方能区分「这次是不是真的花钱了」

实测对比：

```
第 1 次   {"prompt_tokens":4,"completion_tokens":20,"cost":"0.000013","cached":false}
第 2 次   {"prompt_tokens":0,"completion_tokens":0,"cost":"0","cached":true}
```

### 顺带踩到的测试坑：缓存会污染测试

`monkeypatch` 把 LLM 换成「必抛异常」的函数之后，测试仍然绿 ——
因为请求命中了上一次测试留下的缓存，**根本没走到 LLM 那一行**。

```python
# conftest.py —— 每个测试前清 cache:* 和 rl:*
@pytest.fixture(autouse=True)
def clean_redis():
    ...
```

这是「测试的外部状态」的**第四类：缓存残留**（前三类：数据残留 / 顺序依赖 / 环境残留）。
不清的话，测试名和它实际验证的行为对不上 —— 属于最难发现的一种「假通过」。

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
tests/test_chat.py     3 个  chat 成功落库 / LLM 挂掉返回 502 且记 status='failed' / 接口 cost 与库一致
tests/test_usage.py    3 个  空用户全 0 / 一次成功后的数字 / 失败调用只算 failed
tests/test_cache.py    2 个  命中缓存不记账 / temperature>0 不缓存
                      ─────
                      16 个  全绿
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
  assert Decimal(j["total_cost"]) == 0         # 断言值，不断言字面格式
  ```
- **断言用 `j["key"]`，不用 `j.get("key", 0)`**：
  键名写错时，`[...]` 会抛 `KeyError`（响亮地失败），`.get()` 会静默返回默认值（假通过）
- **跑完查库**：`pytest` 全绿不代表数据库干净，清理失效是静默的 —— 每次跑完对一下 `COUNT(*)`

### 变异测试：证明测试有牙齿

测试写完不代表有效，要**故意把代码改坏，看测试会不会红**。

```
正常代码                        13 passed
变异 1：COALESCE(SUM(cost),0)  只有 test_usage_for_new_user 变红
        → SUM(cost)                 （空集返回 NULL → total_cost 是 None → 500）
变异 2：COUNT(CASE WHEN ...    只有 test_usage_counts_failed 变红
        → COUNT(*)                  （失败的调用被算进了 success → assert 1 == 0）
```

**三个测试各管一段，没有一个多余**；两个变异都被杀掉，说明覆盖到了关键行为。
测试「红了」叫**杀死变异**，「还是绿」叫**存活变异** —— 存活越多，测试越虚。


---

## Docker 部署：三个容器

线上跑的是 `docker-compose.yml` 里的三个服务：

```
app（本项目镜像，:8000）──→ mysql  (8.0，数据落在 mysql_data 卷)
                        └──→ redis  (7-alpine，限流 + 缓存)
```

**compose 里的几个关键点：**

| 配置 | 为什么这么写 |
|---|---|
| `depends_on: mysql: condition: service_healthy` | 等 mysql **真的能接受连接**才起 app，不是「容器启动了」就算 |
| `DATABASE_URL` 里写 `@mysql:3306` | **服务名当主机名** —— 容器里的 `localhost` 指的是容器自己，不是别的容器 |
| `REDIS_HOST: redis` | 同上 |
| `mysql` / `redis` **不写 `ports`** | 不暴露到宿主机，只有 compose 内部网络能访问（最小暴露面） |
| `restart: unless-stopped` | 宿主机重启后自动拉起 |
| `mysql_data` 卷 | 容器删了数据还在（但卷仍绑在这台机器上，换机器要 `mysqldump`） |

### 镜像怎么交付到服务器

**不在服务器上 build**，而是在本地构建好、导出成 tar 传过去：

```bash
# 本地
docker build -t llm-gateway:v2 .
docker save llm-gateway:v2 -o llm-gateway-v2.tar      # 63.7 MB
scp llm-gateway-v2.tar ubuntu@<公网IP>:/home/ubuntu/

# 服务器
docker load -i llm-gateway-v2.tar
docker compose up -d            # compose 里 app 用 image: 而不是 build:
```

**为什么不直接在 2核2G 的服务器上 `build`：**

- 服务器 build 要重新下载 10 个依赖包（国内源慢，还可能撞 `THESE PACKAGES DO NOT MATCH THE HASHES`）
- 2G 内存下 pip 装包的内存尖峰会导致 OOM

至于 `mysql:8.0` / `redis:7-alpine` 这类标准镜像，仍然由服务器自己 `pull` ——
镜像加速器有缓存，比自己传文件快得多。
**分工原则：标准镜像走 registry，自定义镜像走文件。**

### 三个真踩过的坑

**① 镜像比代码旧（最坑的一个）**

改了 `ratelimit.py` 但没重新 build，服务器上 `/v1/chat` 返回 500：

```
redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379. Connection refused.
```

镜像里还是 `host="localhost"` 的旧代码。
→ **镜像 = 某一刻的快照**，改完代码必须 rebuild + 重新分发，改磁盘上的 `.py` 对容器没有任何影响。
→ 诊断动作（不用启动容器就能看镜像里是哪一版）：
`docker run --rm <镜像名> grep -n "关键字" /app/xxx.py`

**② 新 MySQL 容器是空库**

三个容器都 Up，但注册接口 500 —— 因为新数据库里一张表都没有。
首次必须建表：

```bash
docker compose exec app python -c "from db import init_db; init_db()"
```

**③「服务 Up」≠「服务能用」**

`docker compose ps` 显示 Up、`/health` 返回 200，但一发请求就 500 ——
因为 SQLAlchemy 的 `create_engine()` 是**惰性**的，启动时根本不去连数据库。

→ 验收必须发一个**真的会碰数据库**的请求（比如注册），不能只看健康检查和端口。

### 部署后怎么验

```bash
curl localhost:8000/health                        # {"status":"ok"}
curl -X POST localhost:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{"username":"demo","password":"abc12345"}'   # 201，拿到 id
```

最后**用手机流量访问** `http://<公网IP>:8000/docs` ——
手机能打开才是真的公网可访问（在自己电脑上访问 `localhost` 不算）。

> 💡 不需要 ICP 备案：用的是 `8000` 端口而不是 `80/443`，直接 IP 访问。
> 备案只在「用域名走 80/443」时才需要。

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
├── ratelimit.py       Redis 固定窗口限流（INCR + 桶号进 key）
├── routers/
│   ├── auth.py        注册 / 登录 / me
│   ├── chat.py        POST /v1/chat（限流 → 缓存 → LLM → 记账）
│   └── usage.py       GET  /v1/usage
├── tests/             pytest 接口测试（5 个文件，16 个用例）
├── conftest.py        fixture：client / cleanup / temp_user / auth_user / make_user
│                      + autouse 的 clean_redis（清缓存和限流计数器）
├── Dockerfile         6 条指令；requirements.txt 单独 COPY 以利用层缓存
├── .dockerignore      排除 .env（密钥不进镜像）/ tests / __pycache__
├── docker-compose.yml app + mysql + redis 三服务编排
├── requirements.txt   运行依赖（不含 pytest / httpx —— 那是开发依赖）
├── redis_demo.py      Redis 五组验证脚本（String / Hash / List / Set / ZSet）
├── reset_db.py        开发工具：重建表
└── try_chat.py        手测工具（CLI）
```

---

## 还没做的

- [ ] 真实 LLM 调用（`_real_call` 目前抛 `NotImplementedError`，计划接 OpenAI 兼容接口）
- [ ] **`/health` 现在是「假健康检查」** —— 它不检查 MySQL / Redis，数据库挂了照样返回 200。
      要做成真探活：ping 一下 MySQL 和 Redis 再返回
- [ ] 限流补测试（窗口传小 + `sleep`，或用 `monkeypatch` 固定 `time.time`）
- [ ] 429 响应加 `Retry-After` 头，让客户端知道要等多久
- [ ] `ratelimit.py` 的 key 改成冒号分层（现在是 `rl:1,12345678`，`KEYS rl:1:*` 匹配不到）
- [ ] 滑动窗口 / 令牌桶（解决固定窗口的「边界双倍」）
- [ ] 镜像统一成一个 tag（现在 `v1` / `v2` 并存，容易拿错 —— 这个坑实际踩过）
- [ ] Alembic 迁移（目前用 `reset_db.py` 重建，生产环境必须用迁移工具）
- [ ] 金额精度口径统一（接口返回 7 位小数，数据库 `NUMERIC(10,6)` 存 6 位，需要对账策略）
- [ ] CI/CD：push 到 GitHub 自动构建镜像并部署

---

## 备注

这个项目是学习过程中做的，代码里有不少注释是给自己看的。
如果发现任何问题，欢迎指出。
