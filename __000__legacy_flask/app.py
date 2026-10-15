"""项目入口。在仓库根目录执行：python app.py"""

from __009__flask.app import app

if __name__ == "__main__":
    app.run(port=5050, debug=True, use_reloader=False)
