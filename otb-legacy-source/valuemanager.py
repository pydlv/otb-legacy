from datetime import datetime
import sys
import json
import time
import mycolors
from log import log
from session import session
from settings import settings

values = {}

try:
    with open("values", "r") as f:
        data = f.read()
except IOError:
    data = None

identifier = (
    "old" if settings["Trading"]["use_old_value_algorithm"] == "true" else "new"
)

if data:
    lines = data.split("\n")
    if lines[0] != identifier:
        data = None
    else:
        for line in lines:
            parts = line.split(":")
            if len(parts) == 5:
                # Value, Average volume, Last updated timestamp
                values[int(parts[0])] = {
                    "value": float(parts[1]),
                    "volume": float(parts[2]),
                    "timestamp": int(parts[3]),
                    "age": float(parts[4]),
                }


def median(lst):
    n = len(lst)
    if n < 1:
        return None
    if n % 2 == 1:
        return sorted(lst)[n // 2]
    else:
        return sum(sorted(lst)[n // 2 - 1 : n // 2 + 1]) / 2.0


def write_value(item_id, value, volume, age):
    values[item_id] = {
        "value": float(value),
        "volume": float(volume),
        "timestamp": int(time.time()),
        "age": age,
    }

    compiled_str = "%s\n" % identifier
    for key in values:
        value = values[key]
        compiled_str += "\n%i:%i:%f:%i:%f" % (
            key,
            value["value"],
            value["volume"],
            value["timestamp"],
            value["age"],
        )

    with open("values", "w") as f:
        f.write(compiled_str)


# NOTE: More dynamic for parsing dates, because the v1 and v2 API dates are different formats? (goodjob roblox)
def parse_date(date_str):
    # Define the possible time formats
    time_formats = [
        "%Y-%m-%dT%H:%M:%SZ",  # Format with 'Z' (UTC indicator)
        "%Y-%m-%dT%H:%M:%S.%fZ",  # Format with fractional seconds and 'Z'
        "%Y-%m-%dT%H:%M:%S.%f",  # Format with fractional seconds, no 'Z'
    ]

    # Check if there is a '.' to handle microsecond truncation
    if "." in date_str:
        date_str = (
            date_str.split(".")[0] + "." + date_str.split(".")[1][:6]
        )  # Ensures only 6 digits for microseconds

    for time_format in time_formats:
        try:
            return datetime.strptime(date_str, time_format)
        except ValueError:
            continue

    # Return None if all formats fail

    return None


def generate_value(item_id):
    log("Generating value for %i..." % item_id)

    decoded = None

    # NOTE: these are set so we can use both V1 and V2 APIs without changing item id or url
    url = None
    resale_id = item_id
    while True:
        # NOTE: Assume the URL is the v1 API (all older items)
        if url is None:
            url = f"https://economy.roblox.com/v1/assets/{resale_id}/resale-data"

        response = session.get(url)
        if response.status_code == 429:
            log(
                "Got too many requests on resale-data, Waiting 15s and trying again.",
                mycolors.WARNING,
            )
            time.sleep(15)
            continue
        # NOTE: Handle new items that use the v2 API
        elif response.status_code == 400:
            log("Item uses new API retrying..", mycolors.WARNING)
            item_details = session.get(
                f"https://catalog.roblox.com/v1/catalog/items/{item_id}/details?itemType=asset"
            )
            if item_details.status_code == 429:
                log(
                    "Got too many on item details requests. Waiting 15s and trying again.",
                    mycolors.WARNING,
                )
                time.sleep(15)
                continue

            if item_details.status_code != 200:
                print(item_details.status_code)
                log("Failed to load item details. Exiting.", mycolors.FAIL)
                sys.exit(0)

            detail_data = item_details.json()
            if "collectibleItemId" in detail_data:
                resale_id = detail_data["collectibleItemId"]
                url = f"https://apis.roblox.com/marketplace-sales/v1/item/{resale_id}/resale-data"

            continue

        decoded = json.loads(response.text)
        break

    def api_data_to_list(items):
        result = []
        for item in items:
            dt = parse_date(item["date"])
            if not dt:
                log(f"got unexpected date from {item}")
                return None
            timestamp = time.mktime(dt.timetuple())
            value = item["value"]

            result.append(
                (
                    int(timestamp),
                    value,
                )
            )

        return result

    sales_data = api_data_to_list(decoded["priceDataPoints"])
    volume_data = api_data_to_list(decoded["volumeDataPoints"])
    if not sales_data is None or volume_data is None:
        log(f"Failed to parse_date of {item_id}, skipping it")
        return None

    now = time.time()

    # 10368000 is 4 months (1/3 of a year)
    # sales_data = [item for item in sales_data if now - item[0] <= 10368000]
    # volume_data = [item for item in volume_data if now - item[0] <= 10368000]

    # Make sure the oldest values are first
    sales_data.sort(key=lambda item: item[0])
    volume_data.sort(key=lambda item: item[0])

    def new_algorithm():
        volume_length = len(volume_data)

        if len(sales_data):
            age = now - sales_data[0][0]
        else:
            age = 0

        if not len(sales_data) or not len(volume_data):
            values[item_id] = {
                "value": 0.0,
                "volume": 0.0,
                "timestamp": now,
                "age": age,
            }
            write_value(item_id, 0.0, 0.0, age)
            return values[item_id]

        sales_median = median(map(lambda x: x[1], sales_data))
        volume_median = median(map(lambda x: x[1], volume_data))

        final_volume = (volume_median * volume_length) / 119

        values[item_id] = {
            "value": float(sales_median),
            "volume": float(final_volume),
            "timestamp": now,
            "age": age,
        }

        write_value(item_id, float(sales_median), float(final_volume), age)

        return values[item_id]

    # noinspection DuplicatedCode
    def old_algorithm():
        if len(sales_data) > 0:
            age = time.time() - sales_data[0][0]
        else:
            age = 0

        sales_lows = []
        sales_highs = []

        for i, item in enumerate(sales_data):
            # We don't know whether the end points are lows or highs or inbetween
            if i == 0 or i == len(sales_data) - 1:
                continue

            previous_item = sales_data[i - 1]
            next_item = sales_data[i + 1]

            if previous_item[1] > item[1] and next_item[1] > item[1]:
                sales_lows.append(item)
            elif previous_item[1] < item[1] and next_item[1] < item[1]:
                sales_highs.append(item)

        volume_lows = []
        volume_highs = []
        volume_candles = []

        for i, item in enumerate(volume_data):
            # We don't know whether the end points are lows or highs or inbetween
            if i == 0 or i == len(volume_data) - 1:
                continue

            volume_candles.append(item)

            previous_item = volume_data[i - 1]
            next_item = volume_data[i + 1]

            if previous_item[1] > item[1] and next_item[1] > item[1]:
                volume_lows.append(item)
            elif previous_item[1] < item[1] and next_item[1] < item[1]:
                volume_highs.append(item)

        # Order by date
        sales_lows.sort(key=lambda item: item[0])
        volume_candles.sort(key=lambda item: item[0])

        sale_thirds = []
        for i in range(3):
            sale_thirds.append([])

        if len(sales_lows) > 0:
            sales_time_range = sales_lows[len(sales_lows) - 1][0] - sales_lows[0][0]

            one_third = sales_time_range / 3.0
            first_start = sales_lows[0][0]
            second_start = sales_lows[0][0] + one_third
            third_start = sales_lows[0][0] + one_third * 2

            for item in sales_lows:
                if item[0] >= third_start:
                    sale_thirds[2].append(item)
                elif item[0] >= second_start:
                    sale_thirds[1].append(item)
                elif item[0] >= first_start:
                    sale_thirds[0].append(item)

            averages = []
            for third in sale_thirds:
                total = 0
                for item in third:
                    total += item[1]
                try:
                    averages.append(total / float(len(third)))
                except ZeroDivisionError:
                    averages.append(0)
        else:
            averages = [0, 0, 0]

        avg1 = (averages[0] + averages[1]) / 2.0
        avg2 = (averages[1] + averages[2]) / 2.0
        avg3 = (averages[0] + averages[2]) / 2.0

        if (
            abs(averages[2] - avg1) > avg1
            and abs(averages[0] - avg2) > avg2
            and abs(averages[1] - avg3) > avg3
        ):
            sales_lows = []
        elif abs(averages[2] - avg1) > avg1:
            sales_lows = sale_thirds[0] + sale_thirds[1]
        elif abs(averages[0] - avg2) > avg2:
            sales_lows = sale_thirds[1] + sale_thirds[2]
        elif abs(averages[1] - avg3) > avg3:
            sales_lows = sale_thirds[0] + sale_thirds[2]
        else:
            sales_lows = sale_thirds[0] + sale_thirds[1] + sale_thirds[2]

        # Volume
        volume_thirds = []
        for i in range(3):
            volume_thirds.append([])

        if len(volume_candles) > 0:
            volume_time_range = (
                volume_candles[len(volume_candles) - 1][0] - volume_candles[0][0]
            )

            one_third = volume_time_range / 3.0
            first_start = volume_candles[0][0]
            second_start = volume_candles[0][0] + one_third
            third_start = volume_candles[0][0] + one_third * 2

            for item in volume_candles:
                if item[0] >= third_start:
                    volume_thirds[2].append(item)
                elif item[0] >= second_start:
                    volume_thirds[1].append(item)
                elif item[0] >= first_start:
                    volume_thirds[0].append(item)

            averages = []
            for third in volume_thirds:
                total = 0
                for item in third:
                    total += item[1]
                try:
                    averages.append(total / float(len(third)))
                except ZeroDivisionError:
                    averages.append(0)
        else:
            averages = [0, 0, 0]

        avg1 = (averages[0] + averages[1]) / 2.0
        avg2 = (averages[1] + averages[2]) / 2.0
        avg3 = (averages[0] + averages[2]) / 2.0

        # Number of days that we divide by
        if (
            abs(averages[2] - avg1) > avg1
            and abs(averages[0] - avg2) > avg2
            and abs(averages[1] - avg3) > avg3
        ):
            divisor = 0.0
            volume_candles = []
        elif abs(averages[2] - avg1) > avg1:
            divisor = 80.0
            volume_candles = volume_thirds[0] + volume_thirds[1]
        elif abs(averages[0] - avg2) > avg2:
            divisor = 80.0
            volume_candles = volume_thirds[1] + volume_thirds[2]
        elif abs(averages[1] - avg3) > avg3:
            divisor = 80.0
            volume_candles = volume_thirds[0] + volume_thirds[2]
        else:
            volume_candles = volume_thirds[0] + volume_thirds[1] + volume_thirds[2]
            divisor = 120.0

        # Calculate low average, that's our value
        total = 0
        for item in sales_lows:
            total += item[1]

        try:
            low_average = total / float(len(sales_lows))
        except ZeroDivisionError:
            low_average = 0

        total = 0
        for item in volume_candles:
            total += item[1]

        try:
            volume_average = float(total) / divisor
        except ZeroDivisionError:
            volume_average = 0

        values[item_id] = {
            "value": float(low_average),
            "volume": float(volume_average),
            "timestamp": now,
            "age": age,
        }

        write_value(item_id, float(low_average), float(volume_average), age)

        return values[item_id]

    if identifier == "old":
        return old_algorithm()
    else:
        return new_algorithm()


def get_value(item_id):
    """
    Returns a generated value, will return NONE if it fails to parse the item date
    """

    if item_id in values:
        data = values[item_id]
        # Force regeneration of value every day
        if time.time() - data["timestamp"] >= 86400:
            item_value = generate_value(item_id)
        else:
            item_value = data
    else:
        item_value = generate_value(item_id)

    return item_value
