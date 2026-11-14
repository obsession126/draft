"""Запуск report сервера: python -m report"""

import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("REPORT_PORT", "8001"))
    uvicorn.run("report.server:app", host="0.0.0.0", port=port, reload=True)
