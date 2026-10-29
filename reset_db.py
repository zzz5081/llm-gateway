"""开发用：删表 + 重建。⚠️ 会丢数据，只在开发阶段用。

用法：
    cd C:\\Users\\zzz\\Desktop\\code-practice\\llm_gateway
    python reset_db.py

⚠️ 为什么需要它：
    Base.metadata.create_all() 只会创建"还不存在的表"，
    不会修改已经存在的表结构（加字段、改类型、加默认值都不生效）。
    → 改了模型之后，必须 DROP 再重建。
    → 生产环境不能这么做，要用迁移工具（Alembic）写 ALTER 脚本。
"""
import db
from sqlalchemy import text

# ⚠️ 删除顺序：先删有外键的子表，再删父表
DROP_ORDER = ["api_calls", "users"]


def reset():
    with db.engine.begin() as conn:
        for table in DROP_ORDER:
            conn.execute(text("DROP TABLE IF EXISTS %s" % table))
            print("  DROP %s" % table)

    db.init_db()
    print("  建表完成")

    with db.engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text("SHOW TABLES"))]
    print("  当前表:", tables)


if __name__ == "__main__":
    print("=" * 56)
    print("⚠️  这会删掉 llm_gateway_db 里的所有数据")
    print("=" * 56)
    answer = input("输入 yes 继续，其他任意键取消：").strip().lower()
    if answer == "yes":
        reset()
    else:
        print("已取消，什么都没做")
