import configparser
import io
import sys

# Default config.ini file
contents = """
[General]
# https://www.youtube.com/watch?v=2SdEivsw8yA (This video shows how to get the Authenticator Secret at 0:25)
Authenticator Code = enter auth code here


colors = false

archive_trade_messages = true
message_check_interval = 60

# Change to a new proxy every n minutes
switch_proxy_every_minutes = 10

# You can put a discord webhook here and the bot will post when it sends a trade, accepts, or declines one.
webhook_url = none

[Authentication]
# This is required. Please make sure you enter your Roblox user ID at https://olympian.xyz/ or else whitelist 
# authentication will fail.
userid = 1234567890

# you can use either username/password auth or .roblosecurity
# both are not required
# you can leave 2fa enabled if you use .roblosecurity

username = roblox username
password = roblox password

ROBLOSECURITY = put your .roblosecurity here

[Trading]
# If not set to false, then the bot will not send/accept/decline any trades or sell items.
testing = false

###################### BOT VALUES ######################
# A lot of people say the new one doesn't work as well, so you can use the old one if you'd like
use_old_value_algorithm = true

# Tells the bot to not trade items above this value
maximum_item_value = 27500

#If this setting is true, it will value overpriced/projected items at their RAP if RAP is higher than value
# This can make it send ridiculous trades if a lot of items have RAP higher than value, which is often true.
value_op_items_at_rap = false


###################### ITEMS ######################
# You can put the IDs of items that you don't want traded here, separated by commas

# Items on this list will not be traded away nor traded for
not_for_trade = 0

# Items on this list will not be traded away
do_not_trade_away = 0

# Items on this list will not be traded for
do_not_trade_for = 0

#change to true if you only want to trade accessories
only_trade_accessories = false

#in seconds
minimum_item_age = 5184000

# The bot will only trade items with a volume above this number
# .15 should evaluate to approximately average-high volume
# You can think of this as demand
minimum_volume = .15

# If this setting is true, then the value of the ask has to always be greater than value of the offer.
safety = true



###################### ITEM RESELLING ######################
# Bot will sell items in catalog for RAP/.7
# Excludes items in not for trade list, and items above maximum_item_value
keep_items_on_sale = false
sale_price_multiplier = 1

maximum_item_value_for_resale = 15000

# In seconds
interval_between_placing_items_on_sale = 10

# Set this to -1 to disable it. When set to 1-9, it will constantly update the sale price 
# to keep the item at a certian position in the reseller list. Warning: Overrides all price settings
# Please note that it can take a lot of time for it to update the price for an item depending on 
# how many items are in your inventory and your interval_between_placing_items_on_sale setting
constant_reseller_list_position = -1



###################### INBOUND TRADES ######################
#Set this to false if you don't want it to handle inbound trades
handle_inbound_trades = true

# The bot won't accept or decline inbound trades with a total value that is greater than this setting.
ignore_inbound_above_value = 15000

interval_between_checking_inbound = 60

# If set to true, then the bot is able to accept inbound trades but not decline them.
accept_but_dont_decline = false



###################### OUTBOUND TRADES ######################
# Minimum time required to wait between sending a trade. Default 30. Setting too low will cause Roblox to temporarily 
# throttle your account.
minimum_time_between_trades = 30
auto_adjust_time_between_trades = true

# Controls how much its allowed to upgrade/downgrade in each trade
maximum_xv1 = 4
maximum_1vx = 4

# If set to true then it will try and vary the grades randomly.
# For example, if you are getting a lot of 4v1s and you don't like that, then you can try and enable this setting.
vary_trade_grades = true

# Maximum amount of time that can be spent searching for trades with a single partner (in seconds)
maximum_time_searching_with_partner = 10

# This setting controls the minimum time that is required to trade with a user twice
# in seconds
minimum_trade_partner_cooldown = 86400

# This used to be a hard-coded value. You can think of it as the likelihood a trade will be accepted.
# Score is a function of the difference in RAP between the offer and the ask.
# Typically ranges from 0.0 - 0.3
score_threshold = .1123

# This setting determines whether the item's RAP or calculated value will be used when calculating
# the trade's attractiveness score.
score_function_of_rap_or_value = rap

# If less than one, it will be treated as a percent. If more than or equal to 1, it will be treated as an constant
# Set to 'none' to disable
minimum_value_gain = 1
apply_minimum_value_to_inbound = true
additional_minimum_value_gain_per_item_downgraded = 0.05

# If less than one, it will be treated as a percent. If more than or equal to 1, it will be treated as an constant
# Set to 'none' to disable
minimum_rap_gain = none
apply_minimum_rap_to_inbound = true

# The minimum trade value to send the trade. It is the sum of the value of all items from both sides. 
# Does not take Robux into account.
minimum_trade_value = 100

# If the calculated weighted volume average that is lost in a trade is greater than this allowance, then the trade will not be executed.
# Valid values: none, any positive decimal
# Example: 0.2 = allow up to 20% weighted average volume lost per trade
# weighted_item_volume = sum(volume * value^bias)/(value^bias)
max_weighted_item_volume_slippage_allowance = none
# Not used if max_weighted_item_volume_slippage_allowance is set to none
weighted_item_volume_high_value_bias = 1.5

# Determines which trades in the queue are sent first
# 1 = highest score
# 2 = highest value gain
# 3 = highest rap gain
# 4 = highest total trade value (sum of all items in the trade)
trade_priority = 2



[Debugging]
easy_debug = false
memory_debugging = false
"""



try:
    with open("config.ini", "r") as f:
        f.read()
except IOError:
    # File doesn't exist, let's create it with the default
    with open("config.ini", "w") as f:
        f.write(contents)
    print("Created config.ini. Please edit it, and then rerun.")
    sys.exit(0)

# Write default settings to example file
with open("config.example.ini", "w") as f:
    f.write(contents)

# Read config
config = configparser.ConfigParser()
config.read("config.ini")
sections = config.sections()

def config_section_map(c, section):
    dict1 = {}
    options = c.options(section)
    for option in options:
        try:
            dict1[option] = c.get(section, option)
            if dict1[option] == -1:
                pass
        except (ValueError, TypeError):
            dict1[option] = None
    return dict1

settings = {}

for section in sections:
    settings[section] = config_section_map(config, section)

config2 = configparser.ConfigParser()
buf = io.StringIO(contents)
config2.read_file(buf)

defaultSettings = {}

sections = config2.sections()
for section in sections:
    defaultSettings[section] = config_section_map(config2, section)

updated = False
for section in sections:
    if section not in settings:
        config.add_section(section)
        settings[section] = {}
        updated = True
    for k in defaultSettings[section]:
        if k not in settings[section]:
            config.set(section, k, defaultSettings[section][k])
            settings[section][k] = defaultSettings[section][k]
            updated = True

if updated:
    with open("config.ini", "w") as f:
        config.write(f)

