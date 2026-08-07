"""幂等回填：将已有的 type=3 按钮/接口权限 name 从英文动作后缀改为中文显示名。

与 app/core/rbac_seed._resolve_child_name 保持一致。仅更新「name 仍等于旧英文后缀」
的行，避免覆盖人工维护过的中文名；可重复执行。

运行：在 rail_monitor 目录下 `python scripts/fix_menu_names.py`（使用 .venv）。
"""

from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.rbac_seed import _resolve_child_name
from app.model.system import Permission


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(Permission).where(Permission.type == 3, Permission.is_deleted.is_(False))
        ).all()
        updated = 0
        for r in rows:
            suffix = r.code.split(":")[-1]
            # 仅处理旧式英文后缀名（已中文化或人工命名则跳过）
            if r.name == suffix:
                new_name = _resolve_child_name(r.code)
                if new_name != r.name:
                    r.name = new_name
                    updated += 1
        db.commit()
        print(f"菜单子项名称回填完成：更新 {updated} 条（共扫描 {len(rows)} 条 type=3）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
