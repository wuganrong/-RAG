#!/usr/bin/env python
"""Django 管理命令行工具，用于执行管理任务。"""
import os
import sys


def main():
    """运行管理任务。"""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__000__django.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "无法导入 Django。请确认是否已安装并可从 PYTHONPATH 环境变量访问？"
            "是否忘记了激活虚拟环境？"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
