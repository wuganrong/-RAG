import os

# common/__001__path/path_utils.py → 仓库根目录
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_file_path(relative_path: str) -> str:
    return os.path.join(root_dir, relative_path)


def _data_dir(relative_path: str) -> str:
    path = get_file_path(relative_path)
    os.makedirs(path, exist_ok=True)
    return path


def page_relpath(image: str) -> str:
    return (image or "").replace("\\", "/").removeprefix("images/").lstrip("/")


def page_abs_path(image: str) -> str:
    return os.path.join(PAGE_IMAGE_DIR, page_relpath(image))


DATA_DIR = get_file_path("data")
os.makedirs(DATA_DIR, exist_ok=True)

# 会话/知识库/文档元数据：SQLite，不再用 sessions/*.json
SESSION_DB_PATH = os.path.join(DATA_DIR, "rag.sqlite3")

# 原始文件主存 MinIO；本地只作建索工作副本
UPLOAD_DIR = _data_dir("data/uploads")

# 检索页图工作副本，Web 走 /media/pages
PAGE_IMAGE_DIR = _data_dir("data/page_images")

# 文本向量（ES 不可用时的本地回退）
VECTOR_DIR = _data_dir("data/vectors")

# ColPali / Byaldi 视觉索引工作副本
BYALDI_DIR = _data_dir("data/byaldi")


if __name__ == "__main__":
    print(get_file_path("data/rag.sqlite3"))
