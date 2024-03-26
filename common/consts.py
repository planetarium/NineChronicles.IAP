import os

HOST_LIST = {
    "development": [
        os.environ.get("HEADLESS", "http://localhost")
    ],
    "internal": [
        "https://9c-internal-rpc-1.nine-chronicles.com",
    ],
    "preview": [
        "http://k8s-9codinli-remotehe-55686c889c-fbbfdb2f7f6d58ec.elb.us-east-2.amazonaws.com"
    ],
    "mainnet": [
        "https://9c-main-full-state.nine-chronicles.com",
        "https://9c-main-rpc-1.nine-chronicles.com",
        "https://9c-main-rpc-2.nine-chronicles.com",
        "https://9c-main-rpc-3.nine-chronicles.com",
        # "https://9c-main-rpc-4.nine-chronicles.com",
        # "https://9c-main-rpc-5.nine-chronicles.com",
    ],
}

CURRENCY_LIST = ("NCG", "CRYSTAL", "GARAGE")

AVATAR_BOUND_TICKER = (
    "RUNE_GOLDENLEAF",
    "SOULSTONE_1001",  # D:CC Blackcat
    "SOULSTONE_1002",  # Red Dongle
    "SOULSTONE_1003",  # Valkyrie of Light
    "SOULSTONE_1004",  # Lil' Fenrir
)
