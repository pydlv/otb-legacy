# Block list
blocklist = []

try:
    with open(".blocklist", "r") as f:
        data = f.read()
except IOError:
    data = ""

parts = data.split(",")
for part in parts:
    if part != "":
        blocklist.append(int(part))


def add_block(user_id):
    blocklist.append(user_id)

    compiled_str = ""
    for anId in blocklist:
        compiled_str += ",%i" % anId

    with open(".blocklist", "w") as f:
        f.write(compiled_str)


def get():
    return blocklist
