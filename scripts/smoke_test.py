import importlib

mods = [
    "fastapi",
    "uvicorn",
    "gunicorn",
    "sqlalchemy",
    "alembic",
    "psycopg2",
    "redis",
    "paho.mqtt",
    "minio",
    "dotenv",
    "pydantic",
    "pydantic_settings",
    "httpx",
    "jwt",
    "passlib",
    "PIL",
    "captcha",
    "shapely",
    "geopy",
    "celery",
    "cv2",
    "pytest",
    "pytest_asyncio",
    "locust",
    "prometheus_client",
]
ok, bad = [], []
for m in mods:
    try:
        importlib.import_module(m)
        ok.append(m)
    except Exception as e:  # noqa
        bad.append((m, str(e)))

print("OK count:", len(ok))
for m in ok:
    print("  -", m)
if bad:
    print("FAIL count:", len(bad))
    for m, e in bad:
        print("  -", m, "::", e)
else:
    print("ALL KEY PACKAGES IMPORT OK")
