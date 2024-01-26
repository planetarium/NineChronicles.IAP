from typing import Dict, Any, Union

import bencodex

class Currency():
    
    @staticmethod
    def to_currency(ticker: str) -> Dict[str, Union[str, int, None]]:
        if ticker.lower() == "crystal":
            return {
                "decimalPlaces": b'\x12',
                "minters": None,
                "ticker": "CRYSTAL",
            }
        elif ticker.lower() == "garage":
            return {
                "decimalPlaces": b'\x12',
                "minters": None,
                "ticker": "GARAGE",
                "totalSupplyTrackable": True,
            }
        else:
            return {
                "decimalPlaces": b'\x00',
                "minters": None,
                "ticker": ticker.upper(),
            }
        
    @staticmethod
    def serialize(currency: Dict[str, Union[str, int, None]]) -> bytes:
        return bencodex.dumps(currency)
