import os

# Tests must never call an online service because a developer's .env happens to hold a key.
os.environ["CLEANUP"] = "off"
