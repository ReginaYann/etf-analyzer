"""启动 Web：python run_web.py"""

from __future__ import annotations

import uvicorn

from etf_analyzer.config import default_settings
from etf_analyzer.web.app import create_app

if __name__ == "__main__":
    app = create_app(default_settings())
    uvicorn.run(app, host="127.0.0.1", port=8000)
