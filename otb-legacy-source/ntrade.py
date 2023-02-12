# No trade list
noTrade = []

try:
    with open(".notrade", "r") as f:
        data = f.read()
except IOError:
    data = ""

parts = data.split(",")
for part in parts:
    if part != "":
        noTrade.append(int(part))


def add_no_trade(user_id):
    noTrade.append(user_id)

    compiled_str = ""
    for anId in noTrade:
        compiled_str += ",%i" % anId

    with open(".notrade", "w") as f:
        f.write(compiled_str)


def clear():
    global noTrade

    noTrade = []

    with open(".notrade", "w") as f:
        f.write("")


def get():
    return noTrade
