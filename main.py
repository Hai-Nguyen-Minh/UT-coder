"""
main.py
-------
UTcoder entry point.
Reads server config from config.json and launches the Gradio app.

Usage:
    python main.py
"""

import logging
import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH when run directly
sys.path.insert(0, str(Path(__file__).parent))

from core.config import get_config
from ui.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("utcoder")


def main() -> None:
    cfg    = get_config()
    server = cfg["server"]

    host  = server.get("host",  "0.0.0.0")
    port  = int(server.get("port",  7860))
    share = bool(server.get("share", False))
    debug = bool(server.get("debug", False))

    logger.info("Starting UTcoder on http://%s:%d  (share=%s)", host, port, share)

    demo, theme, css = create_app()
    demo.launch(
        server_name=host,
        server_port=port,
        share=share,
        debug=debug,
        show_error=True,
        theme=theme,
        css=css,
    )


if __name__ == "__main__":
    main()
