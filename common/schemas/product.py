from dataclasses import dataclass
from typing import Optional, Dict, Union


@dataclass
class GooglePriceSchema:
    currency: str
    priceMicros: str
    price: Optional[float] = None

    def __post_init__(self):
        self.price = float(self.priceMicros) / 1_000_000


@dataclass
class GoogleIAPProductSchema:
    packageName: str
    sku: str
    status: str
    defaultPrice: Union[Dict[str, str], GooglePriceSchema]
    prices: Union[Dict[str, Dict[str, str]], Dict[str, GooglePriceSchema]]
    purchaseType: str
    ###
    defaultLanguage: str
    listings: Dict
    managedProductTaxesAndComplianceSettings: Dict

    def __post_init__(self):
        self.defaultPrice = GooglePriceSchema(**self.defaultPrice)
        self.prices = {key: GooglePriceSchema(**value) for key, value in self.prices.items()}
