import json
import threading
import time

import mycolors
from log import log
from session import session

noTrade = []


def add_no_trade(user_id):
    noTrade.append(user_id)


def populate_no_trade():
    global noTrade

    log("Loading outbound trade data...", mycolors.OKBLUE)

    start_index = 0
    while True:
        request = session.post(
            "https://www.roblox.com/my/money.aspx/getmyitemtrades",
            headers={"Content-Type": "application/json"},
            data='{"statustype":"outbound","startindex":%i}' % start_index,
        )
        response = request.text

        outbound_json_raw = json.loads(response)

        outbound_json = json.loads(outbound_json_raw["d"])

        outbound = []

        for tradeRaw in outbound_json["Data"]:
            outbound.append(json.loads(tradeRaw))

        if len(outbound) == 0:
            break
        else:
            noTrade += [int(aTrade["TradePartnerID"]) for aTrade in outbound]
            if start_index == 0:
                start_index = 19
            else:
                start_index += 20


def refresh_no_trade():
    global noTrade

    while True:
        time.sleep(7200)
        noTrade = []
        populate_no_trade()


refresher = threading.Thread(target=refresh_no_trade)
refresher.daemon = True
refresher.start()
