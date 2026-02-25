import traceback
import json
import logging
import sys
import threading
import time
import bl
import cooldowns
import mycolors
import proxy
import trading
from log import log
from session import session
from settings import settings

#################################################
RELEASE = True

VERSION = 57
#################################################

if RELEASE:
    settings["Debugging"]["easy_debug"] = "false"
    settings["Debugging"]["memory_debugging"] = "false"

if settings["Debugging"]["easy_debug"] == "true":
    log("DEBUG IS ON!!!", mycolors.WARNING)

proxy.start_proxy_loop()

# Overrides
settings["Trading"]["minimum_value_for_rbx_rocks"] = "-1"


log("Starting Olympian trading bot.", no_print=True, post_to_webhook=True)
log("Welcome to Olympian trading bot version %i!" % VERSION, mycolors.OKGREEN)

# Log trading settings
log("Trading settings: %s" % settings["Trading"], no_print=True)


def fetch_userid_and_name():
    """
    Gets info on the current account to self class
    """
    auth_response = session.get("https://users.roblox.com/v1/users/authenticated")

    if auth_response.status_code == 200:
        return str(auth_response.json()["id"]), auth_response.json()["name"]
    else:
        raise ValueError("Couldnt login with cookie")


def get_is_logged_in_and_run_privacy_checks():
    """
    Checks if the user is logged in, and exits if their settings will not allow trading.
    :return: None
    """

    response = session.get("https://www.roblox.com/my/settings/json")

    if "application/json" in response.headers["content-type"].lower():
        data = json.loads(response.text)

        user_above_13 = data["UserAbove13"]
        is_premium = data["IsPremium"]
        can_trade = data["CanTrade"]

        if not user_above_13:
            log(
                "Olympian can only be run on a Roblox account that is marked as being 13+ years old. Exiting.",
                mycolors.FAIL,
            )
            sys.exit(0)
        if not is_premium:
            log(
                "A Roblox Premium subscription is required to trade. Exiting.",
                mycolors.FAIL,
            )
            sys.exit(0)
        if not can_trade:
            log(
                "User is not able to trade. Please check your privacy settings.",
                mycolors.FAIL,
            )
            sys.exit(0)

        response = session.get("https://accountsettings.roblox.com/v1/trade-privacy")
        data = json.loads(response.text)
        if data["tradePrivacy"] != "All":
            log(
                "Trade privacy setting is not set to everyone. Please fix this before running again. Exiting.",
                mycolors.FAIL,
            )
            sys.exit(0)

        # NOTE: Store in cookies, because I cant be bothered adding classes to this source code
        USERID, USERNAME = fetch_userid_and_name()
        session.cookies["user_id"] = USERID
        session.cookies["username"] = USERNAME

        return True
    else:
        # User is not logged in.
        return False


# Login to Roblox account
log("Logging into account...", mycolors.OKBLUE)

session.cookies.set(
    ".ROBLOSECURITY", settings["General"]["roblosecurity"].strip(), domain="roblox.com"
)
if get_is_logged_in_and_run_privacy_checks():
    log("Login successful with .ROBLOSECURITY.", mycolors.OKBLUE)
else:
    log(
        "Failed to login with .ROBLOSECURITY.\n\nMake sure your cookie isnt expired.",
        mycolors.FAIL,
    )
    sys.exit(0)


def continuously_verify_logged_in():
    """
    Continuously checks to make sure we are still logged in every 60 seconds.
    :return: None
    """
    while True:
        time.sleep(60)
        if not get_is_logged_in_and_run_privacy_checks():
            log(
                "We are no longer logged into the Roblox account. Please fix this before running again.",
                mycolors.FAIL,
            )
            sys.exit(0)


login_verifier_thread = threading.Thread(target=continuously_verify_logged_in)
login_verifier_thread.daemon = True
login_verifier_thread.start()


log("Loading current inventory...", mycolors.OKBLUE)
tries = 0
while True:
    try:
        tradable_items = [
            item["name"]
            for item in [
                item
                for item in trading.get_inventory(session.cookies["user_id"])
                if item["itemId"] not in trading.safeItems
                and item["itemId"] not in trading.do_not_trade_away
            ]
        ]

        log(f"Tradable inventory: {tradable_items}", mycolors.OKBLUE)

        if len(tradable_items) >= 0:
            raise trading.AllSelfItemsHoldException
        break
    except trading.FailedToLoadInventoryException:
        logging.exception("Caught exception while trying to load user inventory.")
        log(
            "Failed to load inventory of current user (probably due to Roblox throttling). Trying again soon.",
            mycolors.FAIL,
        )
        time.sleep(10)
        tries += 1
        if tries >= 10:
            log("Failed to load inventory. Exiting.", mycolors.FAIL)
            sys.exit(0)
    except trading.AllSelfItemsHoldException:
        log("All items are on hold, waiting 30 minutes", mycolors.FAIL)
        logging.exception("All items are on hold, waiting 30 minutes.")
        time.sleep(1800)


log("Item IDs not to trade: %s" % str(trading.safeItems), mycolors.OKBLUE)

item_reseller_ids = set()
item_owner_ids = set()
trade_ad_ids = set()
trade_group_ids = set()

try:
    with open(".tradequeue", "r") as f:
        data = f.read()
    queueIds = data.split(",")
    log(
        "Recovered %i IDs from last session's trade queue." % len(queueIds),
        mycolors.OKBLUE,
    )
    for queueId in queueIds:
        if queueId != "":
            try:
                trade_ad_ids.add(
                    int(queueId)
                )  # just add it to trade_ad_ids because idc
            except ValueError:
                continue
except IOError:
    pass


last_rolimons_trade_ads_fetch = time.time() - 120


def find_people():
    global last_rolimons_trade_ads_fetch

    # Try to load state of previous session
    try:
        with open(".page", "r") as f:
            cursor = int(f.read())
    except (IOError, ValueError):
        cursor = ""
        with open(".page", "w") as f:
            f.write("")

    while True:
        # Catalog
        try:
            # Search catalog for collectables
            response = session.get(
                f"https://catalog.roblox.com/v2/search/items/details?taxonomy=wNYJso48d1XnhMyFWT3oX3&creatorName=ROBLOX&salesTypeFilter=2&sortType=1&limit=10&cursor={cursor}"
            )
            if response.status_code == 429:
                log(
                    "Ratelimited getting collectables from catalog waiting 60 seconds and retrying"
                )
                time.sleep(60)
                continue

            if response.status_code == 400 and "Invalid cursor" in response.text:
                cursor = ""
                with open(".page", "w") as f:
                    f.write(str(cursor))
                continue

            decoded_response = json.loads(response.text)

            if (
                "nextPageCursor" not in decoded_response
                or decoded_response["nextPageCursor"] == ""
            ):
                cursor = ""
                with open(".page", "w") as f:
                    f.write(str(cursor))
                continue

            cursor = decoded_response["nextPageCursor"]
            with open(".page", "w") as f:
                f.write(str(cursor))

            for item in decoded_response["data"]:
                item_id = item["collectibleItemId"]
                response = session.get(
                    f"https://apis.roblox.com/marketplace-sales/v1/item/{item_id}/resellers?cursor=&limit=100&cursor="
                )
                if response.status_code == 429:
                    print("ratelimited trying to get resellers")
                else:
                    decoded_json = json.loads(response.text)

                    if "data" not in decoded_json:
                        log(
                            "Could not get resellers of asset ID %i. Got status code %i"
                            % (item_id, response.status_code),
                            mycolors.WARNING,
                        )
                        if (
                            "errors" in decoded_json
                            and "message" in decoded_json["errors"]
                        ):
                            log(
                                "Message from Roblox: %s"
                                % decoded_json["errors"]["message"]
                            )
                    else:
                        seller_ids = [
                            result["seller"]["sellerId"]
                            for result in decoded_json["data"]
                        ]

                        for sellerId in seller_ids:
                            if (
                                sellerId not in bl.get()
                                and sellerId not in item_reseller_ids
                                and cooldowns.is_user_ready(sellerId)
                            ):
                                item_reseller_ids.add(sellerId)

                # Find IDs from item owners
                response = session.get(
                    f"https://inventory.roblox.com/v2/assets/{item_id}/owners?sortOrder=Desc&limit=100"
                )
                if response.status_code == 429 or response.status_code == 503:
                    log(
                        "Got TOO MANY REQUESTS from Roblox in catalog searcher.",
                        mycolors.WARNING,
                    )
                    break
                if response.status_code != 200:
                    # Something went wrong with this item. Skip it.
                    logging.warning(
                        "Roblox had internal server error while fetching item owners."
                    )
                    break
                item_owners = [
                    item["owner"]["id"]
                    for item in json.loads(response.text)["data"]
                    if item["owner"]
                ]
                for ownerId in item_owners:
                    if (
                        ownerId not in bl.get()
                        and ownerId not in item_owner_ids
                        and cooldowns.is_user_ready(ownerId)
                    ):
                        item_owner_ids.add(ownerId)
        except Exception as error:
            log(f"Caught exception while searching catalog. {error}", mycolors.FAIL)
            logging.exception(f"Caught exception while searching catalog. {error}")

        # Get from rolimon trade ads
        # We are rate limiting to once per two minutes. Per rolimons devs this page contains ads from the last 3 minutes
        try:
            if time.time() - last_rolimons_trade_ads_fetch >= 120:
                # It has been at least two minutes, we are safe to fetch
                response = session.get(
                    "https://api.rolimons.com/tradeads/v1/getrecentads"
                )
                decoded = json.loads(response.text)

                ids = [int(ad[2]) for ad in decoded["trade_ads"]]

                for i in ids:
                    if i not in trade_ad_ids:
                        trade_ad_ids.add(i)

                last_rolimons_trade_ads_fetch = time.time()
        except Exception as error:
            log(f"Caught exception while doing thing. {error}", mycolors.FAIL)
            logging.exception(f"Caught exception while doing thing. {error}")

        # Trade group
        # NOTE: This is now scans a knock-off trade group as group walls got removed.
        try:
            response = session.get(
                "https://groups.roblox.com/v1/groups/598411/forums/6877cf36-b844-488a-bb4d-32abccbf3d7e/posts?includeCommentCount=true&limit=10"
            )

            if response.status_code == 429 or response.status_code == 403:
                # We're sending too many requests, so just skip this one for now
                pass
            else:
                found_ids = [
                    datum["firstComment"]["createdBy"]
                    for datum in json.loads(response.text)["data"]
                ]

                for found_id in found_ids:
                    if (
                        found_id not in bl.get()
                        and found_id not in trade_group_ids
                        and cooldowns.is_user_ready(found_id)
                    ):
                        trade_group_ids.add(found_id)
        except Exception as error:
            log(
                f"Caught exception while searching Trade. group for trade partners. {error}",
                mycolors.FAIL,
            )
            logging.exception(
                f"Caught exception while searching Trade. group for trade partners. {error}"
            )

        while True:
            # Sleep until one of our ID queues has less than 100 people in it
            min_id_set_size = min(
                len(trade_ad_ids),
                len(trade_group_ids),
                len(item_reseller_ids),
                len(item_owner_ids),
            )
            if min_id_set_size < 100:
                break
            time.sleep(1)

        time.sleep(20)


def trade_message_archiver():
    while True:
        # noinspection PyBroadException
        try:
            ids_to_move = []

            response = session.get(
                "https://privatemessages.roblox.com/v1/messages?messageTab=inbox&pageNumber=0&pageSize=20"
            )

            messages = json.loads(response.text)["collection"]

            for message in messages:
                if message["isSystemMessage"]:
                    if message["sender"]["id"] == 1:
                        if "trade" in message["subject"].lower():
                            ids_to_move.append(message["id"])

            data = json.dumps({"messageIds": ids_to_move})

            xsrf = trading.get_xsrf()

            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.8",
                "Content-Type": "application/json;charset=UTF-8",
                "Referer": "https://www.roblox.com/my/messages/",
                "User-Agent": "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36",
                "X-CSRF-TOKEN": xsrf,
            }

            response = session.post(
                "https://privatemessages.roblox.com/v1/messages/mark-read",
                headers=headers,
                data=data,
            )
            if response.status_code != 200:
                raise Exception("Failed to mark trade message as read.")
            response = session.post(
                "https://privatemessages.roblox.com/v1/messages/archive",
                headers=headers,
                data=data,
            )
            if response.status_code != 200:
                raise Exception("Failed to archive trade message.")

            time.sleep(float(settings["General"]["message_check_interval"]))
        except Exception:
            log("Caught exception in trade message archiver.", mycolors.FAIL)
            logging.exception("Caught exception in trade message archiver.")
            time.sleep(10)
            continue


idFinderThread = threading.Thread(target=find_people)
idFinderThread.daemon = True
idFinderThread.start()

if settings["Trading"]["handle_inbound_trades"] != "false":
    inboundThread = threading.Thread(target=trading.listen_for_inbound_trades)
    inboundThread.daemon = True
    inboundThread.start()

if settings["Trading"]["keep_items_on_sale"] == "true":
    saleManagerThread = threading.Thread(target=trading.sale_manager)
    saleManagerThread.daemon = True
    saleManagerThread.start()

# NOTE: Roblox Changed this API pretty sure.
# if settings["General"]["archive_trade_messages"] != "false":
#     tradeArchiverThread = threading.Thread(target=trade_message_archiver)
#     tradeArchiverThread.daemon = True
#     tradeArchiverThread.start()

if settings["Debugging"]["memory_debugging"] == "true":

    def memory_debug():
        import typevalues
        import valuemanager

        while True:
            print(
                "ID queue bytes: %i, Type values: %i, Values: %i, Trade queue: %i"
                % (
                    sys.getsizeof(queueIds),
                    sys.getsizeof(typevalues.typeValues),
                    sys.getsizeof(valuemanager.values),
                    sys.getsizeof(trading.tradeSendQueue),
                )
            )
            time.sleep(5)

    memoryDebugger = threading.Thread(target=memory_debug)
    memoryDebugger.daemon = True
    memoryDebugger.start()

lastChecked = time.time()

numFails = 1


def iterate_id_sets():
    # if not item_reseller_ids:
    #     print("Item reseller ids is empty")
    yield item_reseller_ids

    # if not item_owner_ids:
    #     print("Item owner ids is empty")
    yield item_owner_ids

    # if not trade_ad_ids:
    #     print("trade ad ids is empty")
    yield trade_ad_ids

    # if not trade_group_ids:
    #     print("Trade group ids is empty")
    yield trade_group_ids


# Trade
while True:
    for current_id_set in iterate_id_sets():
        # noinspection PyBroadException
        try:
            # noinspection PyBroadException

            if len(current_id_set) > 0:
                nextUserId = current_id_set.pop()
                if (
                    nextUserId not in bl.get()
                    and cooldowns.is_user_ready(nextUserId)
                    and nextUserId not in [trade[0] for trade in trading.tradeSendQueue]
                ):
                    trading.search_for_trades(nextUserId)
            elif len(current_id_set) == 0:
                log("No users in current ID queue, continuing...", mycolors.WARNING)
                time.sleep(1)
            else:
                time.sleep(1)
        except Exception as error:
            tb = traceback.format_exc()
            log(f"Caught exception in main trading loop.\n{tb}", mycolors.FAIL)
            logging.exception(f"Caught exception in main trading loop. {error}")
            continue
