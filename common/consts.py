import os

from common.utils.receipt import PlanetID

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

ITEM_FUNGIBLE_ID_DICT = {
    "400000": "3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a",
    "500000": "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe",
    "600201": "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0",
    "600202": "08f566bb43570aad34c1790901f824dd5609db880afebd5382fcec054203d92a",
    "600203": "",
    "800201": "1a755098a2bc0659a063107df62e2ff9b3cdaba34d96b79519f504b996f53820",
    "CRYSTAL": "FAV__CRYSTAL",
    "RUNE_GOLDENLEAF": "FAV__RUNE_GOLDENLEAF",
}

GQL_DICT = {
    PlanetID.ODIN: os.environ.get("ODIN_GQL_URL"),
    PlanetID.ODIN_INTERNAL: os.environ.get("ODIN_GQL_URL"),
    PlanetID.HEIMDALL: os.environ.get("HEIMDALL_GQL_URL"),
    PlanetID.HEIMDALL_INTERNAL: os.environ.get("HEIMDALL_GQL_URL"),
}
