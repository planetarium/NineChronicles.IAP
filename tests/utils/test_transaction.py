import datetime

import bencodex
import pytest
from common.utils.actions import create_unload_my_garages_action_plain_value

from common.utils.receipt import PlanetID
from common.utils.transaction import append_signature_to_unsigned_tx, create_unsigned_tx, get_genesis_block_hash


def test_get_same_byteshex():
    value = {
        b'a': [
            {
                'type_id': 'claim_items',
                'values': {
                    'cd': [[b"\xe2u`\xfc.\x0c\xd9 c>\xdd\xbc\xbf\t\xe7\x03\xa7X'I", [[{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 1]]]],
                    'id': b'9y\xab\xa1c\x1d%C\x8c\x8b\xf9>\xed2\x8e\xff',
                    'm': '{"season_pass": {"n": [1], "p": [], "t": "claim"}}'
                }
            }
        ],
        b'g': b'E\x82%\r\r\xa3;\x06w\x9a\x84u\xd2\x83\xd5\xdd!\x0ch;\x9b\x99\x9dt\xd0?\xacOX\xfak\xce',
        b'l': 1,
        b'm': [{'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'Mead'}, 10_000_000_000_000],
        b'n': 11,
        b'p': b'\x04\x97\x0c\x06QVU|O#\xa0\x89E\xed6\xe5\x1f`4\x14\xd5K\x98\xa6\xd0\x1akpC\xb96\xc9\xef\xa9\xea4dsa\x02\x02\x89|\xa6\xa8u\xc3\xcf\x0b\xe8\x8aV4\xdd(Lx\xed\x1bM\x95\x8c\xf6HV', 
        b's': b'\x0e\x19\xa9\x92\xad\x97kI\x86\t\x88\x13\xdf\xcd$\xb0wZ\xc0\xaa', 
        b't': '2023-11-22T01:56:33.194530Z', 
        b'u': []
    }

    expected = "64313a616c6475373a747970655f69647531313a636c61696d5f6974656d7375363a76616c7565736475323a63646c6c32303ae27560fc2e0cd920633eddbcbf09e703a75827496c6c647531333a646563696d616c506c61636573313a0075373a6d696e746572736e75363a7469636b65727531343a4974656d5f4e545f353030303030656931656565656575323a696431363a3979aba1631d25438c8bf93eed328eff75313a6d7535303a7b22736561736f6e5f70617373223a207b226e223a205b315d2c202270223a205b5d2c202274223a2022636c61696d227d7d656565313a6733323a4582250d0da33b06779a8475d283d5dd210c683b9b999d74d03fac4f58fa6bce313a6c693165313a6d6c647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275343a4d656164656931303030303030303030303030306565313a6e69313165313a7036353a04970c065156557c4f23a08945ed36e51f603414d54b98a6d01a6b7043b936c9efa9ea346473610202897ca6a875c3cf0be88a5634dd284c78ed1b4d958cf64856313a7332303a0e19a992ad976b4986098813dfcd24b0775ac0aa313a747532373a323032332d31312d32325430313a35363a33332e3139343533305a313a756c6565"

    assert expected == bencodex.dumps(value).hex()

def test_append_signature_to_unsinged_tx():
    unsigned_tx = "64313a616c6475373a747970655f69647531313a636c61696d5f6974656d7375363a76616c7565736475323a63646c6c32303ae27560fc2e0cd920633eddbcbf09e703a75827496c6c647531333a646563696d616c506c61636573313a0075373a6d696e746572736e75363a7469636b65727531343a4974656d5f4e545f353030303030656931656565656575323a696431363a3979aba1631d25438c8bf93eed328eff75313a6d7535303a7b22736561736f6e5f70617373223a207b226e223a205b315d2c202270223a205b5d2c202274223a2022636c61696d227d7d656565313a6733323a4582250d0da33b06779a8475d283d5dd210c683b9b999d74d03fac4f58fa6bce313a6c693165313a6d6c647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275343a4d6561646569313030303030303030303030303030303030306565313a6e69313165313a7036353a04970c065156557c4f23a08945ed36e51f603414d54b98a6d01a6b7043b936c9efa9ea346473610202897ca6a875c3cf0be88a5634dd284c78ed1b4d958cf64856313a7332303a0e19a992ad976b4986098813dfcd24b0775ac0aa313a747532373a323032332d31312d32325430313a35363a33332e3139343533305a313a756c6565"
    expected_tx = "64313a5337313a3045022100e1a9ed1ee1589ffb766812502357c160e1911caee44f74d2936f814a85f9979e022028696abf20424b4229d0ad3e8a41f4b7533c5af9ad142f26b958d03797673c68313a616c6475373a747970655f69647531313a636c61696d5f6974656d7375363a76616c7565736475323a63646c6c32303ae27560fc2e0cd920633eddbcbf09e703a75827496c6c647531333a646563696d616c506c61636573313a0075373a6d696e746572736e75363a7469636b65727531343a4974656d5f4e545f353030303030656931656565656575323a696431363a3979aba1631d25438c8bf93eed328eff75313a6d7535303a7b22736561736f6e5f70617373223a207b226e223a205b315d2c202270223a205b5d2c202274223a2022636c61696d227d7d656565313a6733323a4582250d0da33b06779a8475d283d5dd210c683b9b999d74d03fac4f58fa6bce313a6c693165313a6d6c647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275343a4d6561646569313030303030303030303030303030303030306565313a6e69313165313a7036353a04970c065156557c4f23a08945ed36e51f603414d54b98a6d01a6b7043b936c9efa9ea346473610202897ca6a875c3cf0be88a5634dd284c78ed1b4d958cf64856313a7332303a0e19a992ad976b4986098813dfcd24b0775ac0aa313a747532373a323032332d31312d32325430313a35363a33332e3139343533305a313a756c6565"
    signature = b"0E\x02!\x00\xe1\xa9\xed\x1e\xe1X\x9f\xfbvh\x12P#W\xc1`\xe1\x91\x1c\xae\xe4Ot\xd2\x93o\x81J\x85\xf9\x97\x9e\x02 (ij\xbf BKB)\xd0\xad>\x8aA\xf4\xb7S<Z\xf9\xad\x14/&\xb9X\xd07\x97g<h"
    signed_tx = append_signature_to_unsigned_tx(bytes.fromhex(unsigned_tx), signature)

    assert expected_tx == signed_tx.hex()

def test_create_unsigned_tx():
    plain_value_dict = {
                "type_id": "claim_items",
                "values": {
                    "cd": [
                        [
                            b"\xe2u`\xfc.\x0c\xd9 c>\xdd\xbc\xbf\t\xe7\x03\xa7X'I",
                            [
                                [
                                    {
                                        "decimalPlaces": b"\x00",
                                        "minters": None,
                                        "ticker": "Item_NT_500000",
                                    },
                                    1,
                                ]
                            ],
                        ]
                    ],
                    "id": b"9y\xab\xa1c\x1d%C\x8c\x8b\xf9>\xed2\x8e\xff",
                    "m": '{"season_pass": {"n": [1], "p": [], "t": "claim"}}',
                },
            }
    plain_value = plain_value_dict
    unsigned_tx = create_unsigned_tx(
        PlanetID.ODIN,
        "024007a3342b03083e7c87e80b6daa9be6f7e1caae66c368fb32ca43994394ef3e",
        "0x8bA11bEf1DB41F3118f7478cCfcbE7f1Af4650fa",
        0,
        plain_value,
        datetime.datetime(2021, 10, 1, 5, 36, 33, 194530)
    )

    expected_tx = "64313a616c6475373a747970655f69647531313a636c61696d5f6974656d7375363a76616c7565736475323a63646c6c32303ae27560fc2e0cd920633eddbcbf09e703a75827496c6c647531333a646563696d616c506c61636573313a0075373a6d696e746572736e75363a7469636b65727531343a4974656d5f4e545f353030303030656931656565656575323a696431363a3979aba1631d25438c8bf93eed328eff75313a6d7535303a7b22736561736f6e5f70617373223a207b226e223a205b315d2c202270223a205b5d2c202274223a2022636c61696d227d7d656565313a6733323a4582250d0da33b06779a8475d283d5dd210c683b9b999d74d03fac4f58fa6bce313a6c693465313a6d6c647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275343a4d656164656931303030303030303030303030306565313a6e693065313a7033333a024007a3342b03083e7c87e80b6daa9be6f7e1caae66c368fb32ca43994394ef3e313a7332303a8ba11bef1db41f3118f7478ccfcbe7f1af4650fa313a747532373a323032312d31302d30315430353a33363a33332e3139343533305a313a756c6565"
    loaded_tx = bencodex.loads(unsigned_tx)

    assert expected_tx == unsigned_tx.hex()
    assert loaded_tx[b'a'][0]['values']['cd'][0][0] == plain_value_dict['values']['cd'][0][0]
    assert loaded_tx[b'a'][0]['values']['cd'][0][1] == plain_value_dict['values']['cd'][0][1]
    assert loaded_tx[b'a'][0]['values']['id'] == plain_value_dict['values']['id']
    assert loaded_tx[b'a'][0]['values']['m'] == plain_value_dict['values']['m']
    assert loaded_tx[b'a'][0]['type_id'] == plain_value_dict['type_id']
    assert loaded_tx[b'g'] == get_genesis_block_hash(PlanetID.ODIN)
