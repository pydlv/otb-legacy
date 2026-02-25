import time
from settings import settings

cooldowns = {}


def load_cooldowns():
    global cooldowns

    try:
        with open(".cooldowns", "r") as f:
            data = f.read()
    except IOError:
        with open(".cooldowns", "w") as f:
            f.write("")
        data = ""

    lines = data.split("\n")
    for line in lines:
        parts = line.split(":")
        if len(parts) == 2:
            try:
                int(parts[0])
                int(parts[1])
            except ValueError:
                continue
            if parts[0] != "" and parts[1] != "":
                cooldowns[int(parts[0])] = int(parts[1])


load_cooldowns()


def is_user_ready(user_id):
    global cooldowns
    if user_id not in cooldowns:
        return True

    if (
        cooldowns[user_id] + int(settings["Trading"]["minimum_trade_partner_cooldown"])
        <= time.time()
    ):
        del cooldowns[user_id]
        return True
    else:
        return False


def add_cooldown(user_id):
    global cooldowns

    now = time.time()
    # Perform some cleanup to prevent data size from bloating
    for key in cooldowns.keys():
        if (
            cooldowns[key] + int(settings["Trading"]["minimum_trade_partner_cooldown"])
            <= now
        ):
            del cooldowns[key]

    cooldowns[user_id] = now

    j = ""

    for key in cooldowns.keys():
        j += "%i:%i\n" % (key, cooldowns[key])

    with open(".cooldowns", "w") as f:
        f.write(j)


def remove_cooldown(user_id):
    global cooldowns
    if user_id in cooldowns:
        del cooldowns[user_id]
        add_cooldown(1)  # Do this to force the cooldown file to update
