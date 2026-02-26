import logging
import os
import time

import mycolors
from session import session
from settings import settings

if not os.path.exists("logs"):
    os.makedirs("logs")

logging.basicConfig(filename="logs/%f.log" % time.time(), level=logging.INFO)

colors = True if settings["General"]["colors"] == "true" else False


def post_to_webhook_if_enabled(msg):
    url = settings["General"]["webhook_url"]
    if url != "none":
        # Webhook url is enabled, post to it
        try:
            session.post(url, {"content": msg})
        except Exception:
            logging.exception("Failed to post to webhook URL.")


# There's no colors in Windows command prompt :(((
def log(msg, log_color="\033[0m", no_print=False, post_to_webhook=False):
    colored_msg = (
        (mycolors.OKBLUE if colors else "")
        + str(time.time())
        + ": "
        + ("\033[0m" if colors else "")
        + (log_color if colors else "")
        + str(msg)
        + (mycolors.ENDC if colors else "")
    )
    if not no_print:
        print(colored_msg)
    logging.info(str(time.time()) + ": " + str(msg))

    if post_to_webhook:
        post_to_webhook_if_enabled(msg)
