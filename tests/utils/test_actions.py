from common.utils.actions import create_unload_my_garages_action_plain_value

import bencodex


def test_create_unload_my_garages_action_plain_value():
    fav_data = [
        {
            "balanceAddr": "1c2ae97380cfb4f732049e454f6d9a25d4967c6f",
            "value": {
                "currencyTicker": "CRYSTAL",
                "value": 1500000,
                "decimalPlaces": 18,
            }
        }
    ]
    avatar_addr = "0x41aefe4cddfb57c9dffd490e17e571705c593ddc"
    item_data = [
        {
            "fungibleId": "3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a",
            "count": 8000
        },
        {
            "fungibleId": "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0",
            "count": 200
        }
    ]
    id = "6e747fecdc33374a81fdc42b99d0d4f3"
    memo = '["0x9eaac29af78f88f8dbb5fad976c683e92f25fdb3", "0x25b4ce744b7e0150ef9999b6eff5010b6d4a164a", "{\\"iap\\": {\\"g_sku\\": \\"g_pkg_launching1\\", \\"a_sku\\": \\"a_pkg_launching1\\"}}"]'
    plain_value = create_unload_my_garages_action_plain_value(id, fav_data, avatar_addr, item_data, memo)
    expected = {'type_id': 'unload_from_my_garages', 'values': {'id': b'nt\x7f\xec\xdc37J\x81\xfd\xc4+\x99\xd0\xd4\xf3', 'l': [b'A\xae\xfeL\xdd\xfbW\xc9\xdf\xfdI\x0e\x17\xe5qp\\Y=\xdc', [[b'\x1c*\xe9s\x80\xcf\xb4\xf72\x04\x9eEOm\x9a%\xd4\x96|o', [{'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'CRYSTAL'}, 1500000000000000000000000]]], [[b'9\x91\xe0M\xd8\x08\xdc\x0b\xc2K!\xf5\xad\xb7\xbf\x19\x971/\x87\x00\xda\xf13K\xf3I6\xe8\xa0\x81:', 8000], [b'\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0', 200]], '["0x9eaac29af78f88f8dbb5fad976c683e92f25fdb3", "0x25b4ce744b7e0150ef9999b6eff5010b6d4a164a", "{\\"iap\\": {\\"g_sku\\": \\"g_pkg_launching1\\", \\"a_sku\\": \\"a_pkg_launching1\\"}}"]']}}
    expected_hex = "6475373a747970655f69647532323a756e6c6f61645f66726f6d5f6d795f6761726167657375363a76616c7565736475323a696431363a6e747fecdc33374a81fdc42b99d0d4f375313a6c6c32303a41aefe4cddfb57c9dffd490e17e571705c593ddc6c6c32303a1c2ae97380cfb4f732049e454f6d9a25d4967c6f6c647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275373a4352595354414c656931353030303030303030303030303030303030303030303030656565656c6c33323a3991e04dd808dc0bc24b21f5adb7bf1997312f8700daf1334bf34936e8a0813a693830303065656c33323af8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e069323030656565753137333a5b22307839656161633239616637386638386638646262356661643937366336383365393266323566646233222c2022307832356234636537343462376530313530656639393939623665666635303130623664346131363461222c20227b5c226961705c223a207b5c22675f736b755c223a205c22675f706b675f6c61756e6368696e67315c222c205c22615f736b755c223a205c22615f706b675f6c61756e6368696e67315c227d7d225d656565"

    assert expected == plain_value
    assert expected_hex == bencodex.dumps(plain_value).hex()
