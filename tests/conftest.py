"""测试环境基础配置。"""

from __future__ import annotations

import os


os.environ.setdefault("DJANGO_ENV", "test")
os.environ.setdefault("DB_ENGINE", "sqlite")
os.environ.setdefault("CACHE_BACKEND", "locmem")
os.environ.setdefault("REQUIRE_AUTH", "0")
