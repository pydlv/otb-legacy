import copy
import sys
import itertools
import json
import logging
import math
import random
import re
import threading
import time

import requests
from cachetools import cached, TTLCache

import bl
import cooldowns
import mycolors
import typevalues
import valuemanager
from log import log
from session import session
from settings import settings
from authenticator import AuthHandler

safeItems = []

tradeSendQueue = []

try:
    with open("safeitems", "r") as safe_items_file:
        safe_items_data = safe_items_file.read()
except IOError:
    safe_items_data = ""

parts = safe_items_data.split(",")
for part in parts:
    if part != "":
        safeItems.append(int(part))

parts = settings["Trading"]["not_for_trade"].split(",")
for part in parts:
    if part != "":
        try:
            safeItems.append(int(part))
        except ValueError:
            pass

do_not_trade_away = []
parts = settings["Trading"]["do_not_trade_away"].split(",")
for part in parts:
    if part != "":
        try:
            do_not_trade_away.append(int(part))
        except ValueError:
            pass

do_not_trade_for = []
parts = settings["Trading"]["do_not_trade_for"].split(",")
for part in parts:
    if part != "":
        try:
            do_not_trade_for.append(int(part))
        except ValueError:
            pass

Authenticator = AuthHandler(settings["General"]["authenticator_code"])

trade_cooldown_time = float(settings["Trading"]["minimum_time_between_trades"])
auto_adjust_time_between_trades = (
    settings["Trading"]["auto_adjust_time_between_trades"] == "true"
)

if settings["Trading"]["max_weighted_item_volume_slippage_allowance"] != "none":
    MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE = float(
        settings["Trading"]["max_weighted_item_volume_slippage_allowance"]
    )
    assert 0 <= MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE
else:
    MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE = None

WEIGHTED_ITEM_VOLUME_HIGH_VALUE_BIAS = float(
    settings["Trading"]["weighted_item_volume_high_value_bias"]
)

ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED = settings["Trading"][
    "additional_minimum_value_gain_per_item_downgraded"
]

if ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED == "none":
    ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED = 0
else:
    ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED = float(
        ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED
    )

# TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET = settings["Trading"]["trades_queue_growth_per_minute_target"]
# if TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET == "none":
#     TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET = None
# else:
#     TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET = float(TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET)

TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET = None

score_threshold = float(settings["Trading"]["score_threshold"])

testing = settings["Trading"]["testing"] != "false"

if testing:
    log("WE ARE TESTING!", mycolors.WARNING)

clock = trade_cooldown_time


def countdown():
    global clock
    while True:
        clock -= 1
        time.sleep(1)


clockThread = threading.Thread(target=countdown)
clockThread.daemon = True
clockThread.start()


def calculate_volume(value, volume):
    return volume / ((43951.2 / value) + (-0.00000484931 * value) + 2.43184)


def get_xsrf():
    response = session.get("https://www.roblox.com/upgrades/robux?ctx=nav")
    match = re.findall(
        r'<meta name="csrf-token" data-token="?([^>"]+)"? />', response.text
    )

    return match[0]


def add_extra_info(item):
    # New method for outbound trades
    if "Name" not in item:
        item_name_encoded = item["name"].encode("utf-8")
        item["Name"] = item_name_encoded  # For compatibility
        item["name"] = item_name_encoded
        item["itemId"] = int(item["assetId"])

        item["ImageLink"] = (
            "https://www.roblox.com/asset-thumbnail/image?assetId=%i&height=110&width=110"
            % (item["assetId"])
        )
        item["ItemLink"] = "https://www.roblox.com/catalog/%i/--" % item["assetId"]
        item["SerialNumber"] = item["serialNumber"]
        item["SerialNumberTotal"] = item[
            "assetStock"
        ]  # I think this is correct but not entirely sure
        item["OriginalPrice"] = item["originalPrice"]
        item["userAssetID"] = item["assetId"]
        item["UserAssetID"] = item["assetId"]

        membership_type = (
            item["buildersClubMembershipType"]
            if "buildersClubMembershipType" in item
            else item["membershipType"]
        )
        item["buildersClubMembershipType"] = membership_type
        item["MembershipLevel"] = membership_type
        item["AveragePrice"] = int(item["recentAveragePrice"])
    else:
        # Old method for inbound trades
        item["name"] = item["Name"]

        item["itemId"] = int(re.match(r".*/(\d+)/.*", item["ItemLink"]).group(1))

        item["AveragePrice"] = int(item["AveragePrice"])

    item_data = valuemanager.get_value(item["itemId"])
    item["value"] = item_data["value"]
    item["OriginalVolume"] = item_data["volume"]
    try:
        item["volume"] = calculate_volume(item["value"], item_data["volume"])
    except ZeroDivisionError:
        item["volume"] = 0
    item["age"] = item_data["age"]

    return item


class FailedToLoadInventoryException(Exception):
    pass


class AllSelfItemsHoldException(Exception):
    pass


@cached(cache=TTLCache(maxsize=4096, ttl=300))
def get_inventory(user_id):
    user_id = int(user_id)

    inventory_raw = []

    # NOTE: I don't like the original approach because you get ratelimited every user you scan -Flaried

    # Good job tardblox, now I get to send EVEN MORE http requests to your server :DDDDD
    # Wasting resources is fun! 8x more to be exact :-)
    # accessory_asset_type_ids = [8, 41, 42, 43, 44, 45, 46, 47]
    # other_asset_type_ids = [19, 18]
    # asset_type_ids = (accessory_asset_type_ids + other_asset_type_ids
    #                   if settings["Trading"]["only_trade_accessories"] != "true"
    #                   else accessory_asset_type_ids[:])

    cursor = ""
    while cursor is not None:  # Continue until we've loaded all of this asset type
        data = None

        for i in range(5):  # Up to 5 attempts
            url = (
                "https://inventory.roblox.com/v1/users/%(userId)i/assets/collectibles?"
                "cursor=%(cursor)s&sortOrder=Desc&limit=100"
                % {  # &assetType=%(assetTypeId)i" % {
                    "userId": int(user_id),
                    "cursor": cursor,
                }
            )  # , "assetTypeId": assetTypeId}
            response = session.get(url)

            data = json.loads(response.text)

            if response.status_code == 503:
                log("Inventory request failed. Trying again.", mycolors.WARNING)
                time.sleep(1)
                continue

            if response.status_code == 429:
                log("Loading Inventory throttled retrying.", mycolors.WARNING)
                time.sleep(10)
                if i >= 5:
                    log("Failed to load inventory. Exiting.", mycolors.FAIL)
                    sys.exit(0)
                continue

            if "errors" in data:
                for err in data["errors"]:
                    logging.warning("Failed to load inventory: %s" % (err["message"]))
                raise FailedToLoadInventoryException

            break

        cursor = data["nextPageCursor"]
        inventory_raw += data["data"]

    inventory = []
    for item in inventory_raw:
        new_item = add_extra_info(item)
        # Only do this for our inventory
        if (
            settings["Trading"]["value_op_items_at_rap"] == "true"
            and int(session.cookies["user_id"]) == user_id
        ):
            if new_item["AveragePrice"] > new_item["value"]:
                new_item["value"] = new_item["AveragePrice"]
        inventory.append(new_item)

    inventory = [item for item in inventory if item["value"] > 0]
    inventory = [
        item
        for item in inventory
        if item["value"] <= int(settings["Trading"]["maximum_item_value"])
        and not item["isOnHold"]
    ]

    return inventory


# noinspection PyBroadException
def sale_manager():
    reseller_position = int(settings["Trading"]["constant_reseller_list_position"])

    while True:
        try:
            my_inventory = get_inventory(session.cookies["user_id"])
            filtered_inventory = []
            for item in my_inventory:
                if (
                    item["itemId"] not in safeItems
                    and item["itemId"] not in do_not_trade_away
                    and not item["value"]
                    > int(settings["Trading"]["maximum_item_value"])
                ):
                    filtered_inventory.append(item)
            for item in filtered_inventory:
                try:
                    item_info = json.loads(
                        session.get(
                            "https://api.roblox.com/Marketplace/ProductInfo?assetId=%i"
                            % item["itemId"]
                        ).text
                    )

                    response = session.get(
                        "https://economy.roblox.com/v1/assets/%i/resellers?limit=10&cursor="
                        % item_info["AssetId"]
                    )
                    decoded_json = json.loads(response.text)

                    sellers = decoded_json["data"]

                    price = (
                        max(item["AveragePrice"], item["value"])
                        / 0.7
                        * float(settings["Trading"]["sale_price_multiplier"])
                    )
                    place_on_sale = False
                    if 1 <= reseller_position <= 9:
                        for i in range(reseller_position, 10):
                            if len(sellers) >= i:
                                competitor = sellers[i - 1]
                                if (
                                    competitor["seller"]["id"]
                                    != int(session.cookies["user_id"])
                                    or competitor["userAssetId"] == item["userAssetId"]
                                ):
                                    if competitor["userAssetId"] == item["userAssetId"]:
                                        price = competitor["price"]
                                    else:
                                        price = competitor["price"] - 1
                                    try:
                                        if i > 1 and (price <= sellers[i - 2]["price"]):
                                            continue
                                        else:
                                            place_on_sale = True
                                            break
                                    except IndexError:
                                        continue
                    else:
                        if len(sellers) > 0:
                            cheapest_price = sellers[0]["price"]
                            price = max(price, cheapest_price - 1)
                        place_on_sale = True

                    price = int(math.ceil(price))

                    xsrf = get_xsrf()

                    if max(item["value"], item["AveragePrice"]) > int(
                        settings["Trading"]["maximum_item_value_for_resale"]
                    ):
                        place_on_sale = False

                    if place_on_sale:
                        log(
                            "Placing %s (%i) for sale at price %i."
                            % (item["Name"], item["itemId"], price),
                            mycolors.OKBLUE,
                            post_to_webhook=True,
                        )
                        data = {
                            "assetId": item["itemId"],
                            "userAssetId": item["userAssetId"],
                            "price": price,
                            "sell": True,
                        }
                    else:
                        log(
                            "Taking item off sale %s (%i)."
                            % (item["Name"], item["itemId"]),
                            mycolors.OKBLUE,
                            post_to_webhook=True,
                        )
                        data = {
                            "assetId": item["itemId"],
                            "userAssetId": item["userAssetId"],
                            "price": 0,
                            "sell": False,
                        }

                    if settings["Debugging"]["easy_debug"] == "false" and not testing:
                        response = session.post(
                            "https://www.roblox.com/asset/toggle-sale",
                            headers={"X-CSRF-TOKEN": xsrf},
                            data=data,
                        )
                        if response.status_code != 200:
                            raise Exception

                    time.sleep(
                        float(
                            settings["Trading"][
                                "interval_between_placing_items_on_sale"
                            ]
                        )
                    )
                except Exception:
                    log("Caught exception in sale manager.", mycolors.FAIL)
                    logging.exception("Caught exception in sale manager.")
                    time.sleep(
                        float(
                            settings["Trading"][
                                "interval_between_placing_items_on_sale"
                            ]
                        )
                    )
                    continue

        except Exception:
            log("Caught exception in sale manager.", mycolors.FAIL)
            logging.exception("Caught exception in sale manager.")
            time.sleep(
                float(settings["Trading"]["interval_between_placing_items_on_sale"])
            )
            continue


def trade_side_to_str(side):
    data = []
    for item in side:
        data.append(item["Name"])
    return str(data)


def create_offer(user_id, items, robux):
    return {
        "userId": user_id,
        "userAssetIds": [item["userAssetId"] for item in items],
        "robux": robux,
    }


def remove_trades_with_invalid_items_from_queue():
    global trade_queue_insertion_timestamps
    my_inventory = get_inventory(session.cookies["user_id"])
    my_uaids = [item["userAssetId"] for item in my_inventory]

    for trade in tradeSendQueue:
        offer = trade[1][1]
        for item in offer:
            if item["userAssetId"] not in my_uaids:
                tradeSendQueue.remove(trade)

    trade_queue_insertion_timestamps = []


on_trade_hold = False


def send_trade(
    user_id, trade, skip_clock=False, trade_id=0, their_robux=0, is_repeat=False
):
    global clock

    offer_nice = trade_side_to_str(trade[1])
    ask_nice = trade_side_to_str(trade[2])

    log(
        "Offering %s (%i)[%i]\tRequesting %s (%i)[%i]. {%f} (%i left in queue)..."
        % (
            offer_nice,
            trade[0][1],
            trade[0][3],
            ask_nice,
            trade[0][2],
            trade[0][4],
            trade[0][0],
            len(tradeSendQueue),
        ),
        mycolors.OKGREEN,
        post_to_webhook=(not is_repeat),
    )

    offers = [
        create_offer(session.cookies["user_id"], trade[1], 0),
        create_offer(user_id, trade[2], their_robux),
    ]

    if not skip_clock:
        while clock > 0:
            time.sleep(0.5)

    cooldowns.add_cooldown(user_id)

    if settings["Debugging"]["easy_debug"] != "true" and not testing:
        response = session.post(
            "https://trades.roblox.com/v1/trades/send",
            headers={"X-CSRF-TOKEN": get_xsrf()},
            json={"offers": offers},
        )

        data = json.loads(response.text)
    else:
        log("TESTING IS ON SO NOT ACTUALLY SENDING!!!", mycolors.WARNING)
        return

    global trade_cooldown_time

    if response.status_code != 200:
        # if response["msg"] == "That user has blocked this form of contact." \
        #         or response["msg"] == "You are not authorized to make this trade!" \
        #         or response["msg"] == "You are not authorized to alter this trade!":
        #     # Block the user here
        #     bl.add_block(user_id)
        #     log("Trade with %i: \"%s\", moving to next partner..." % (user_id, response["msg"]), mycolors.WARNING)

        errors = data["errors"]
        error_output_text = " ".join([error["message"] for error in errors])

        if response.status_code == 429:
            if "errors" in response.json():
                if (
                    "you are sending too many trade requests"
                    in response.json()["errors"][0]["message"].lower()
                ):
                    cooldowns.items_on_hold_event.set()
                    log(
                        f"{session.cookies['username']} has hit the daily 100 trade limit waiting 3 hours, then retrying",
                        mycolors.WARNING,
                        post_to_webhook=True,
                    )
                    time.sleep(10800)
                    cooldowns.items_on_hold_event.clear()
                    return
            log(
                "Trade with %i: Roblox is throttling us, waiting and trying again. Current cooldown is at %i."
                % (user_id, trade_cooldown_time),
                mycolors.WARNING,
            )

            if auto_adjust_time_between_trades:
                trade_cooldown_time += 1
            clock = trade_cooldown_time
            send_trade(
                user_id, trade, skip_clock, trade_id, their_robux, is_repeat=True
            )
        else:
            log("Failed to send trade. %s" % error_output_text, mycolors.FAIL)
            if "Challenge is required to authorize the request" in error_output_text:
                ok = Authenticator.validate_2fa(response, session)
                log(f"response from 2fa: {ok}", no_print=True)
                send_trade(
                    user_id, trade, skip_clock, trade_id, their_robux, is_repeat=True
                )
            if "userAssets are invalid" in error_output_text:
                remove_trades_with_invalid_items_from_queue()
            if "One or more UserAssets are on hold" in error_output_text:
                # Set the hold_event to stop the searching for players to pause
                cooldowns.items_on_hold_event.set()

                while True:
                    remove_trades_with_invalid_items_from_queue()
                    if len(get_inventory(session.cookies["user_id"])) > 0:
                        # stop the on_hold event
                        cooldowns.items_on_hold_event.clear()
                        break
                    log(
                        "All items on hold, waiting 30 minutes, then refreshing...",
                        post_to_webhook=True,
                    )
                    time.sleep(1800)
    else:
        log("Trade sent successfully.", mycolors.OKGREEN)

        if auto_adjust_time_between_trades:
            trade_cooldown_time = max(trade_cooldown_time - 1, 0)
        clock = trade_cooldown_time


def cubic_root(x):
    return x ** (1 / 3.0) if x >= 0 else -(abs(x) ** (1 / 3.0))


def calculate_score(x):
    return (0.200844 * cubic_root(x - 0.995808)) + (0.0237571 * x**7) + 0.192809


def pull_trade(session_id):
    response = session.get("https://trades.roblox.com/v1/trades/%i" % session_id)

    data = json.loads(response.text)

    return data


def calculate_weighted_volume_average(items):
    assert len(items) > 0

    total = 0.0
    divisor = 0.0
    for item in items:
        effective_value = (
            item["value"] ** WEIGHTED_ITEM_VOLUME_HIGH_VALUE_BIAS
        )  # Apply high value bias to our value
        total += effective_value * item["volume"]
        divisor += effective_value

    return total / divisor


def listen_for_inbound_trades():
    # noinspection PyUnresolvedReferences
    while ".ROBLOSECURITY" not in requests.utils.dict_from_cookiejar(session.cookies):
        time.sleep(1)
    while True:
        # noinspection PyBroadException
        try:
            # Load inbound trades
            inbound = []

            cursor = None
            while True:
                response = session.get(
                    "https://trades.roblox.com/v1/trades/inbound?%s" % "cursor="
                    + (cursor if cursor else "")
                )

                if response.status_code == 429:
                    logging.info(
                        "Inbound checker getting throttled. Waiting and trying again."
                    )
                    time.sleep(30)
                    continue

                data = json.loads(response.text)

                for trade in data["data"]:
                    inbound.append(trade)

                if data["nextPageCursor"]:
                    cursor = data["nextPageCursor"]
                else:
                    break

            good_trades = []

            max_handle_value = int(settings["Trading"]["ignore_inbound_above_value"])

            for tradeInfo in inbound:
                trade_data = pull_trade(tradeInfo["id"])

                my_offer = None
                their_offer = None

                for offer in trade_data["offers"]:
                    if int(offer["user"]["id"]) == int(session.cookies["user_id"]):
                        my_offer = copy.deepcopy(offer)
                    else:
                        their_offer = copy.deepcopy(offer)

                assert my_offer is not None
                assert their_offer is not None

                my_items = [add_extra_info(item) for item in my_offer["userAssets"]]
                their_items = [
                    add_extra_info(item) for item in their_offer["userAssets"]
                ]

                my_items_original = copy.deepcopy(my_items)
                their_items_original = copy.deepcopy(their_items)

                my_robux = my_offer["robux"]

                max_item_value = int(settings["Trading"]["maximum_item_value"])

                their_filtered_items = []
                for item in their_items:
                    include = True
                    reason = ""

                    if item["value"] <= 0:
                        include = False
                        reason = "Item value is 0."

                    if (
                        settings["Trading"]["only_trade_accessories"] == "true"
                        and typevalues.get_type(item["itemId"]) != 1
                    ):
                        include = False
                        reason = "Item is not an accessory."

                    if item["volume"] < float(settings["Trading"]["minimum_volume"]):
                        include = False
                        reason = "Item volume is too low."

                    if item["age"] < int(settings["Trading"]["minimum_item_age"]):
                        include = False
                        reason = "Item age is too low."

                    if int(item["AveragePrice"]) > max_item_value:
                        include = False
                        reason = "Item RAP is too high."

                    if int(item["value"]) > max_item_value:
                        include = False
                        reason = "Item value is too high."

                    if item["itemId"] in safeItems:
                        include = False
                        reason = "Item is in safe items."

                    if item["itemId"] in do_not_trade_for:
                        include = False
                        reason = "Item is marked as do not trade for."

                    if not include:
                        log("Excluding item %s because: %s" % (item["Name"], reason))
                    else:
                        their_filtered_items.append(item)

                # FLAG TRADE AS BAD IF IT REQUESTS AN ITEM THATS IN OUR SAFE LIST
                contains_bad_item = False
                for item in my_items:
                    if item["itemId"] in safeItems or item["value"] <= 0:
                        contains_bad_item = True
                    if item["itemId"] in do_not_trade_away:
                        contains_bad_item = True
                    if (
                        item["value"] > max_item_value
                        or item["AveragePrice"] > max_item_value
                    ):
                        contains_bad_item = True
                    if settings["Trading"]["only_trade_accessories"] == "true":
                        item_type = typevalues.get_type(item["itemId"])
                        if item_type != 1:
                            contains_bad_item = True

                my_total = 0
                for item in my_items:
                    my_total += item["value"]

                their_total = 0
                for item in their_filtered_items:
                    their_total += item["value"]

                my_total_rap = 0
                for item in my_items:
                    my_total_rap += item["AveragePrice"]

                their_total_rap = 0
                for item in their_filtered_items:
                    their_total_rap += item["AveragePrice"]

                if settings["Trading"]["minimum_value_gain"] != "none":
                    minimum_value_gain = float(
                        settings["Trading"]["minimum_value_gain"]
                    )
                else:
                    minimum_value_gain = None

                if settings["Trading"]["apply_minimum_value_to_inbound"] == "false":
                    minimum_value_gain = None

                if settings["Trading"]["minimum_rap_gain"] != "none":
                    minimum_rap_gain = float(settings["Trading"]["minimum_rap_gain"])
                else:
                    minimum_rap_gain = None

                if settings["Trading"]["apply_minimum_rap_to_inbound"] == "false":
                    minimum_rap_gain = None

                if minimum_value_gain is not None:
                    if 1 > minimum_value_gain >= 0:
                        their_value_requirement = my_total * (1 + minimum_value_gain)
                    else:
                        their_value_requirement = my_total + minimum_value_gain

                    my_num = len(my_items)
                    their_num = len(their_filtered_items)

                    num_downgraded = max(0, their_num - my_num)

                    if (
                        num_downgraded > 0
                        and ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED > 0
                    ):
                        if 1 > ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED > 0:
                            their_value_requirement += (
                                my_total
                                * ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED
                                * num_downgraded
                            )
                        else:
                            their_value_requirement += (
                                ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED
                                * num_downgraded
                            )
                    meets_value_requirement = their_total >= their_value_requirement
                else:
                    if settings["Trading"]["safety"] != "false":
                        meets_value_requirement = their_total > my_total
                    else:
                        meets_value_requirement = True

                meets_rap_requirement = False
                if minimum_rap_gain is not None:
                    if 1 > minimum_rap_gain >= 0:
                        meets_rap_requirement = their_total_rap >= my_total_rap * (
                            1 + minimum_rap_gain
                        )
                    elif minimum_rap_gain >= 1:
                        meets_rap_requirement = (
                            their_total_rap >= my_total_rap + minimum_rap_gain
                        )
                else:
                    meets_rap_requirement = True

                if (
                    max(my_total_rap, their_total_rap, my_total, their_total)
                    > max_handle_value
                ):
                    # Ignore the trade
                    continue

                # Check if it meets the max_weighted_item_volume_slippage_allowance
                meets_volume_slippage_allowance = True
                if MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE is not None:
                    our_weighted_volume_average = calculate_weighted_volume_average(
                        my_items
                    )
                    partner_weighted_volume_average = calculate_weighted_volume_average(
                        their_items
                    )
                    calculated_minimum_weighted_volume_average = (
                        our_weighted_volume_average
                        * (1 - MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE)
                    )
                    meets_volume_slippage_allowance = (
                        partner_weighted_volume_average
                        >= calculated_minimum_weighted_volume_average
                    )

                if not meets_volume_slippage_allowance:
                    log("Trade fails to meet maximum volume slippage allowance.")

                if (
                    meets_value_requirement
                    and meets_rap_requirement
                    and my_robux == 0
                    and not contains_bad_item
                    and meets_volume_slippage_allowance
                ):
                    # It's a good trade
                    score = their_total - my_total

                    good_trades.append(
                        [
                            [
                                score,
                                my_total,
                                their_total,
                                my_total_rap,
                                their_total_rap,
                            ],
                            my_items_original,
                            their_items_original,
                            tradeInfo,
                        ]
                    )
                elif settings["Trading"]["accept_but_dont_decline"] != "true":
                    my_side_nice_data = []
                    for item in my_items:
                        my_side_nice_data.append(item["Name"])
                    my_side_nice = str(my_side_nice_data)

                    their_side_nice_data = []
                    for item in their_items:
                        their_side_nice_data.append(item["Name"])
                    their_side_nice = str(their_side_nice_data)

                    log(
                        "Declining trade: %s (%i)[%i]\tfor %s (%i)[%i]..."
                        % (
                            my_side_nice,
                            my_total,
                            my_total_rap,
                            their_side_nice,
                            their_total,
                            their_total_rap,
                        ),
                        mycolors.OKBLUE,
                        post_to_webhook=True,
                    )
                    if settings["Debugging"]["easy_debug"] == "false" and not testing:
                        session.post(
                            "https://trades.roblox.com/v1/trades/%i/decline"
                            % int(tradeInfo["id"]),
                            headers={"X-CSRF-TOKEN": get_xsrf()},
                        )

            # Sort good trades based on score
            good_trades.sort(key=lambda x: -x[0][0])

            for trade in good_trades:
                offer_nice = trade_side_to_str(trade[1])
                ask_nice = trade_side_to_str(trade[2])

                log(
                    "Accepting trade: %s (%i)[%i]\tfor %s (%i)[%i]..."
                    % (
                        offer_nice,
                        trade[0][1],
                        trade[0][3],
                        ask_nice,
                        trade[0][2],
                        trade[0][4],
                    ),
                    mycolors.OKGREEN,
                    post_to_webhook=True,
                )

                session.post(
                    "https://trades.roblox.com/v1/trades/%i/accept"
                    % int(trade[3]["id"]),
                    headers={"X-CSRF-TOKEN": get_xsrf()},
                )
        except Exception:
            logging.exception("Caught exception in inbound trading loop.")
            log(
                "Found exception in inbound trading loop. Check log for more details.",
                mycolors.FAIL,
            )
            time.sleep(30)
            continue

        time.sleep(float(settings["Trading"]["interval_between_checking_inbound"]))


def update_trade_queue_save():
    with open(".tradequeue", "w") as f:
        f.write(",".join([str(trade[0]) for trade in tradeSendQueue]))


trade_queue_insertion_timestamps = [(time.time(), 0)]


def update_score_threshold():
    global trade_queue_insertion_timestamps, score_threshold
    if TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET is not None:
        delta = 0.01

        now = time.time()

        # Calculate the average over the last 10 minutes
        ten_minutes_ago = now - 10 * 60

        # Filter out all the timestamps that are too old
        trade_queue_insertion_timestamps = [
            stamp
            for stamp in trade_queue_insertion_timestamps
            if stamp[0] >= ten_minutes_ago
        ]

        if len(trade_queue_insertion_timestamps) == 0:
            average_growth = 0
        elif len(trade_queue_insertion_timestamps) == 1:
            net_growth = trade_queue_insertion_timestamps[0][1]
            start = trade_queue_insertion_timestamps[0][0]
            end = now
            seconds_elapsed = end - start
            minutes_elapsed = seconds_elapsed / 60.0

            try:
                average_growth = net_growth / minutes_elapsed
            except ZeroDivisionError:
                average_growth = 999
        else:
            net_growth = (
                trade_queue_insertion_timestamps[-1][1]
                - trade_queue_insertion_timestamps[0][1]
            )
            start = trade_queue_insertion_timestamps[0][0]
            end = trade_queue_insertion_timestamps[-1][0]
            seconds_elapsed = end - start
            minutes_elapsed = seconds_elapsed / 60.0

            try:
                average_growth = net_growth / minutes_elapsed
            except ZeroDivisionError:
                return

        clamp = lambda x: max(x, 0.001)

        try:
            percent_diff = abs(
                (TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET - average_growth) / average_growth
            )
            needs_adjusting = percent_diff >= 0.01
        except ZeroDivisionError:
            percent_diff = 0.2
            needs_adjusting = True

        # delta = min(math.sqrt(percent_diff), 0.1)  # Maximum of 10% adjustment each time
        delta = 0.00167

        if needs_adjusting:
            if average_growth < TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET:
                score_threshold = clamp(score_threshold - delta)
            elif average_growth > TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET:
                score_threshold = clamp(score_threshold + delta)

        log(
            "Score threshold is now at %f, Average: %f"
            % (score_threshold, average_growth)
        )


def update_score_threshold_loop():
    if TRADE_QUEUE_GROWTH_PER_MINUTE_TARGET is not None:
        while True:
            trade_queue_insertion_timestamps.append((time.time(), len(tradeSendQueue)))
            update_score_threshold()
            time.sleep(10)


update_score_threshold_thread = threading.Thread(target=update_score_threshold_loop)
update_score_threshold_thread.daemon = True
update_score_threshold_thread.start()


def trade_send_queue_runner():
    global tradeSendQueue

    try:
        trade_priority = int(settings["Trading"]["trade_priority"])
        if trade_priority < 1 or trade_priority > 4:
            raise ValueError
    except (TypeError, ValueError):
        log("Invalid setting for trade priority.", mycolors.WARNING)
        trade_priority = 1

    while True:
        # noinspection PyBroadException
        try:
            while len(tradeSendQueue) > 0:
                # Sort the queue according to the settings
                if trade_priority == 1:
                    tradeSendQueue.sort(key=lambda trade: -trade[1][0][0])
                elif trade_priority == 2:
                    tradeSendQueue.sort(
                        key=lambda trade: -(trade[1][0][2] - trade[1][0][1])
                    )
                elif trade_priority == 3:
                    tradeSendQueue.sort(
                        key=lambda trade: -(trade[1][0][4] - trade[1][0][3])
                    )
                elif trade_priority == 4:
                    tradeSendQueue.sort(key=lambda trade: -trade[1][0][5])

                trade = tradeSendQueue.pop(0)

                update_trade_queue_save()

                send_trade(trade[0], trade[1])

            time.sleep(1)
        except Exception as error:
            log(f"Caught exception in trade sending loop: {error}", mycolors.FAIL)
            logging.exception("Caught exception in trade sending loop.")
            continue


tradeSendQueueRunnerThread = threading.Thread(target=trade_send_queue_runner)
tradeSendQueueRunnerThread.daemon = True
tradeSendQueueRunnerThread.start()


def search_for_trades(user_id, guarantee_trade=False):
    log("Searching for trades with %i..." % user_id)

    # If precheck is set to false in the lines following, then we will not look for trades with this user.
    precheck = True

    # Check if we are allowed to trade with the user
    response = session.get(
        "https://trades.roblox.com/v1/users/%i/can-trade-with" % user_id
    )
    # Sometimes Roblox will throttle this,
    # so in that case just don't bother with checking if we can trade with the user.
    if response.status_code == 200:
        data = json.loads(response.text)
        can_trade_with = data["canTrade"]
        if not can_trade_with:
            precheck = False

    # Check that the user is not a Roblox administrator
    is_admin = False

    response = session.get(
        "https://accountinformation.roblox.com/v1/users/%i/roblox-badges" % user_id
    )

    data = json.loads(response.text)
    if (
        len(data) > 0
    ):  # Apparently Roblox returns a blank dictionary if the user has no badges.
        for item in data:
            if item["name"] == "Administrator":
                is_admin = True
                precheck = False

    if not precheck:
        if is_admin:
            # log("Skipping user because they're admin.")
            # Block the user
            bl.add_block(user_id)
        else:
            # log("Unable to trade with user, probably because user is NBC.")
            pass
        return

    my_inventory = get_inventory(session.cookies["user_id"])

    try:
        their_inventory = get_inventory(user_id)
    except FailedToLoadInventoryException:
        logging.warning("Skipping user...")
        return

    def highest_value_affordable(inventory, upper_limit_multiplier):
        inventory_sorted = sorted(inventory, key=lambda x: x["value"], reverse=True)

        total = 0.0

        for i, item in enumerate(inventory_sorted):
            if i <= 3:
                total += item["value"]

        return total * upper_limit_multiplier

    # Calculate the highest value either of us could reasonable trade for and then filter out items
    # above that limit (it will speed up calculations)
    my_highest_value_affordable = highest_value_affordable(my_inventory, 1.3)
    their_highest_value_affordable = highest_value_affordable(their_inventory, 1)

    my_inventory = [
        item for item in my_inventory if item["value"] <= their_highest_value_affordable
    ]
    their_inventory = [
        item
        for item in their_inventory
        if item["value"] <= my_highest_value_affordable
        and item["volume"] >= float(settings["Trading"]["minimum_volume"])
    ]

    # Protect items from our safe list and make sure the item is old enough
    my_inventory = [
        item
        for item in my_inventory
        if item["itemId"] not in safeItems
        and item["itemId"] not in do_not_trade_away
        and item["age"] >= float(settings["Trading"]["minimum_item_age"])
    ]
    their_inventory = [
        item
        for item in their_inventory
        if item["itemId"] not in safeItems
        and item["itemId"] not in do_not_trade_for
        and item["age"] >= float(settings["Trading"]["minimum_item_age"])
    ]

    if len(their_inventory) == 0:
        return

    # noinspection PyShadowingNames
    def limit_inventory(inventory, item_count=4):
        # If there's more than 4 of the same item in an inventory,
        # remove the extra since there are only 4 trading slots (should improve performance)
        counts = {}
        i = 0
        while i < len(inventory):
            if inventory[i]["itemId"] not in counts:
                counts[inventory[i]["itemId"]] = 1
            elif counts[inventory[i]["itemId"]] >= item_count:
                del inventory[i]
                continue
            else:
                counts[inventory[i]["itemId"]] += 1

            i += 1

        return inventory

    my_inventory = limit_inventory(
        my_inventory, int(settings["Trading"]["maximum_xv1"])
    )
    their_inventory = limit_inventory(
        their_inventory, int(settings["Trading"]["maximum_1vx"])
    )

    if len(my_inventory) == 0:
        log(
            "There are no tradable items or they have all been filtered out.",
            mycolors.WARNING,
        )
        return

    try:
        minimum_value_gain = float(settings["Trading"]["minimum_value_gain"])
    except (TypeError, ValueError):
        minimum_value_gain = None
    try:
        minimum_rap_gain = float(settings["Trading"]["minimum_rap_gain"])
    except (TypeError, ValueError):
        minimum_rap_gain = None

    max_run_time = float(settings["Trading"]["maximum_time_searching_with_partner"])

    deadline = max_run_time + time.time()

    # Use old trade finder
    random.shuffle(my_inventory)
    random.shuffle(their_inventory)

    def combos(inventory_length, max_combo_length):
        nums = list(range(inventory_length))
        lengths = list(range(max_combo_length, 0, -1))

        if settings["Trading"]["vary_trade_grades"] == "true":
            random.shuffle(nums)
            random.shuffle(lengths)

        for l in lengths:
            result = itertools.combinations(nums, l)
            for combo in result:
                yield combo

    def prod(a, b_factory):
        for x in a:
            for y in b_factory():
                yield x, y

    my_combos = combos(len(my_inventory), int(settings["Trading"]["maximum_xv1"]))
    their_combos_wrapper = lambda: combos(
        len(their_inventory), int(settings["Trading"]["maximum_1vx"])
    )

    combinations = prod(my_combos, their_combos_wrapper)

    good_combinations = []
    for i, indexCombo in enumerate(combinations):
        if i % 128 == 0 and time.time() > deadline:
            break

        my_num = len(indexCombo[0])
        their_num = len(indexCombo[1])

        offer = [my_inventory[index] for index in indexCombo[0]]

        ask = [their_inventory[index] for index in indexCombo[1]]

        my_total = float(sum([item["value"] for item in offer]))
        their_total = float(sum([item["value"] for item in ask]))

        my_total_rap = float(sum([item["AveragePrice"] for item in offer]))
        their_total_rap = float(sum([item["AveragePrice"] for item in ask]))

        # Check meets minimum value requirement
        if minimum_value_gain is None:
            meets_value_requirement = True
        else:
            if 1.0 > minimum_value_gain >= 0.0:
                their_value_requirement = my_total * (1.0 + minimum_value_gain)
            else:
                their_value_requirement = my_total + minimum_value_gain

            num_downgraded = max(0, their_num - my_num)
            if (
                num_downgraded > 0
                and ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED > 0
            ):
                if 1 > ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED > 0:
                    their_value_requirement += (
                        my_total
                        * ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED
                        * num_downgraded
                    )
                else:
                    their_value_requirement += (
                        ADDITIONAL_MINIMUM_VALUE_GAIN_PER_ITEM_DOWNGRADED
                        * num_downgraded
                    )

            meets_value_requirement = their_total >= their_value_requirement

        if not meets_value_requirement:
            continue

        # Check meets minimum rap requirement
        meets_rap_requirement = False

        if minimum_rap_gain is None:
            meets_rap_requirement = True
        if minimum_rap_gain is not None and 1.0 > minimum_rap_gain >= 0.0:
            meets_rap_requirement = their_total_rap > my_total_rap * (
                1.0 + minimum_rap_gain
            )
        elif minimum_rap_gain is not None and minimum_rap_gain >= 1:
            meets_rap_requirement = their_total_rap > my_total_rap + minimum_rap_gain

        if not meets_rap_requirement:
            continue

        try:
            if settings["Trading"]["score_function_of_rap_or_value"] == "value":
                score = calculate_score(float(my_total) / their_total)
            else:
                score = calculate_score(float(my_total_rap) / their_total_rap)
        except (ValueError, ZeroDivisionError):
            continue

        meets_score_requirement = score >= score_threshold

        if not meets_score_requirement:
            continue

        # Check if it meets the max_weighted_item_volume_slippage_allowance
        meets_volume_slippage_allowance = True
        if MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE is not None:
            our_weighted_volume_average = calculate_weighted_volume_average(offer)
            partner_weighted_volume_average = calculate_weighted_volume_average(ask)
            calculated_minimum_weighted_volume_average = our_weighted_volume_average * (
                1 - MAX_WEIGHTED_ITEM_VOLUME_SLIPPAGE_ALLOWANCE
            )
            meets_volume_slippage_allowance = (
                partner_weighted_volume_average
                >= calculated_minimum_weighted_volume_average
            )

        if not meets_volume_slippage_allowance:
            continue

        # Check meets minimum_trade_value
        trade_total_value = my_total + their_total
        minimum_trade_value = int(settings["Trading"]["minimum_trade_value"])

        meets_minimum_trade_value_requirement = trade_total_value >= minimum_trade_value

        if settings["Trading"]["safety"] != "false" and my_total >= their_total:
            meets_value_requirement = False

        if (
            meets_value_requirement
            and meets_rap_requirement
            and meets_minimum_trade_value_requirement
            and meets_volume_slippage_allowance
        ):
            # Don't send entirely stupid trades (such as asking for free items)
            my_names = [item["name"] for item in offer]
            their_names = [item["name"] for item in ask]

            contains_duplicate = False

            for aName in my_names:
                if aName in their_names:
                    contains_duplicate = True

            if contains_duplicate:
                continue

            if meets_score_requirement:
                # log("Found potential trade.", mycolors.WARNING);
                good_combinations.append(
                    [
                        [
                            score,  # 0
                            my_total,  # 1
                            their_total,  # 2
                            my_total_rap,  # 3
                            their_total_rap,  # 4
                            trade_total_value,  # 5
                        ],
                        offer,
                        ask,
                    ]
                )

    # LETS TRY SOMETHING NEW AGAIN XXDDDDDDDDD
    try:
        trade_priority = int(settings["Trading"]["trade_priority"])
        if trade_priority < 1 or trade_priority > 4:
            raise ValueError
    except (TypeError, ValueError):
        log("Invalid setting for trade priority.", mycolors.WARNING)
        trade_priority = 1

    if trade_priority == 1:
        good_combinations.sort(key=lambda trade: -trade[0][0])
    elif trade_priority == 2:
        good_combinations.sort(key=lambda trade: -(trade[0][2] - trade[0][1]))
    elif trade_priority == 3:
        good_combinations.sort(key=lambda trade: -(trade[0][4] - trade[0][3]))
    elif trade_priority == 4:
        good_combinations.sort(
            key=lambda trade: -trade[0][5]
        )  # Highest total trade value

    global tradeSendQueue

    if len(good_combinations) > 0:
        queue_length = len(tradeSendQueue)

        num = random.randint(0, int(calculate_score(1.2) * 1000)) / 1000.0

        # goodCombinations[0][0][0] is score
        add_trade = (
            True  # Always add trades, set False if you want to limit queue length
        )
        append = True  # Changed this from False to True since we are always adding found trades to queue
        if (
            num * (1.0 - (1.0 / (queue_length + 1))) - (0.11 - score_threshold)
            <= good_combinations[0][0][0]
            or guarantee_trade
            or queue_length == 0
        ):
            add_trade = True
            append = True
        elif (
            queue_length
            and good_combinations[0][0][0] > tradeSendQueue[queue_length - 1][1][0][0]
        ):
            add_trade = True

        if add_trade:
            offer_nice_data = []
            for item in good_combinations[0][1]:
                offer_nice_data.append(item["name"])
            offer_nice = str(offer_nice_data)

            ask_nice_data = []
            for item in good_combinations[0][2]:
                ask_nice_data.append(item["name"])
            ask_nice = str(ask_nice_data)

            log(
                "Adding trade to queue: %s (%i)[%i]\tfor %s (%i)[%i] {%f} (%i left in queue)..."
                % (
                    offer_nice,
                    good_combinations[0][0][1],
                    good_combinations[0][0][3],
                    ask_nice,
                    good_combinations[0][0][2],
                    good_combinations[0][0][4],
                    good_combinations[0][0][0],
                    len(tradeSendQueue),
                ),
                mycolors.OKBLUE,
            )

            if append:
                tradeSendQueue.append([user_id, good_combinations[0]])
            else:
                tradeSendQueue[queue_length - 1] = [user_id, good_combinations[0]]

            update_trade_queue_save()
