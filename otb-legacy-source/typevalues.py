from bs4 import BeautifulSoup

import mycolors
from log import log
from session import session

# 1 = hat
# 2 = face
# 3 = gear

typeValues = {}

try:
    with open(".itemtypes", "r") as f:
        data = f.read()
except IOError:
    data = ""

for line in data.split("\n"):
    parts = line.split(":")
    if len(parts) == 2:
        typeValues[int(parts[0])] = int(parts[1])


def generate_type(item_id):
    response = session.get("https://www.roblox.com/item.aspx?id=%i" % item_id)

    soup = BeautifulSoup(str(response.text.encode("UTF-8")), "html.parser")

    the_type = None

    for elem in soup.find_all(id="type-content"):
        hat_types = [
            "Hat",
            "Accessory | Hat",
            "Accessory | Hair",
            "Accessory | Face",
            "Accessory | Neck",
            "Accessory | Shoulder",
            "Accessory | Front",
            "Accessory | Back",
            "Accessory | Waist"
        ]
        if elem.text in hat_types:
            the_type = 1
            break
        elif elem.text == "Face":
            # Not to be confused with Accessory | Face
            the_type = 2
            break
        elif elem.text == "Gear":
            the_type = 3
            break

    if not the_type:
        log("Failed to find type of %i" % item_id, log_color=mycolors.FAIL)
        raise ValueError

    typeValues[item_id] = the_type

    compiled = ""
    for key in typeValues:
        val = typeValues[key]
        compiled += "\n%i:%i" % (key, val)

    with open(".itemtypes", "w") as f:
        f.write(compiled)

    return the_type


def get_type(item_id):
    if item_id not in typeValues:
        return generate_type(item_id)
    else:
        return typeValues[item_id]
