import os
import sys
import valuemanager

os.chdir(os.path.dirname(os.path.realpath(__file__)))

sys.path.append("./Lib")
sys.path.append("./DLLs")
sys.path.append("./Lib/plat-win")
sys.path.append("./Lib/lib-tk")
sys.path.append("./Lib/site-packages")
sys.path.append("./Lib/site-packages/requests/packages")
sys.path.append("C:/Python27/Lib/site-packages")


def calculate_volume(value, volume):
    return volume / ((43951.2 / value) + (-0.00000484931 * value) + 2.43184)


while True:
    theId = input("Enter ID: ")

    item = valuemanager.generate_value(int(theId))
    try:
        item["ModifiedVolume"] = calculate_volume(
            item["value"], item["volume"])
    except ZeroDivisionError:
        item["ModifiedVolume"] = 0.0

    print(item)
