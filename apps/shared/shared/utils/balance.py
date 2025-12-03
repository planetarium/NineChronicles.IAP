"""
Balance query utilities for IAP Garage stock reporting.

This module provides a common GraphQL query for checking token balances
across different currencies used in the IAP system.
"""

# Default IAP Garage address
DEFAULT_IAP_GARAGE_ADDRESS = "0xCb75C84D76A6f97A2d55882Aea4436674c288673"

# Balance query for all supported currencies
BALANCE_QUERY = """
query balanceQuery(
  $address: Address! = "0xCb75C84D76A6f97A2d55882Aea4436674c288673"
) {
  stateQuery {
    BlackCat: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1001", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    RedDongle: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1002", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    Valkyrie: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1003", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    LilFenrir: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1004", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    ThorRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_GOLDENTHOR", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenMeat: balance (
      address: $address,
      currency: {ticker: "Item_NT_800202", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    CriRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_CRI", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    EmeraldDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600203", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    Crystal: balance (
      address: $address,
      currency: {ticker: "FAV__CRYSTAL", decimalPlaces: 18, minters: [], }
    ) { currency {ticker} quantity }
    hourglass: balance (
      address: $address,
      currency: {ticker: "Item_NT_400000", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    APPotion: balance (
      address: $address,
      currency: {ticker: "Item_NT_500000", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenLeafRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNE_GOLDENLEAF", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600201", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    RubyDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600202", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    SapphireDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600206", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    SilverDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_800201", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    SacredHammer: balance (
      address: $address,
      currency: {ticker: "Item_NT_600306", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    HPRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_HP", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
  }
}"""
