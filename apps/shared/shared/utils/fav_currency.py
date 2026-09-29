"""FAV 티커 → 그 통화의 **진짜 자릿수**. lib9c 가 정한 값을 그대로 옮겨 놓은 표다.

## 왜 이 파일이 필요한가

`GrantItems` 는 우리가 보낸 값을 이렇게 쓴다(Lib9c/Action/GrantItems.cs:209-214):

    var currency = Currencies.GetUnwrappedCurrency(tokenCurrency);
    var granted  = FungibleAssetValue.FromRawValue(currency, requestedToken.RawValue);

**통화의 자릿수는 lib9c 가 정하고, 발행량(raw)은 우리가 정한다.** 우리가 보내는 raw 는
`amount × 10**decimal_places` 이므로, 우리 쪽 `decimal_places` 가 그 통화의 실제 자릿수와
다르면 그 차이가 **그대로 배율**이 된다. 룬스톤(실제 0)에 18 을 적으면 1 개가 10^18 개로
나간다. 체인에 올라간 발행은 되돌릴 수 없다.

그런데 지금까지의 검사는 전부 "0 이상" 또는 "0~18" 이었다 — **티커를 보지 않는 상한**이라
이 사고를 하나도 막지 못한다. 옳은 불변식은 `dp <= 18` 이 아니라 `dp == 그 통화의 dp` 다.

## 티커 오타도 같은 자리에서 막는다

`Currencies.GetRune` / `GetSoulStone` 은 **접두어만 맞으면 어떤 티커든 새 통화를 즉석에서
만들어 준다.** 즉 `RUNESTONE_HPP` 같은 오타는 tx 가 SUCCESS 로 끝나고, 유저는 시트에 없는
쓸모없는 잔고를 받고, 포탈은 GRANTED 로 확정한다. 아무도 모른다. 그래서 여기서 접두어
규칙까지 같이 본다(존재하는 룬인지까지는 시트가 있어야 알 수 있어 범위 밖이다).

## 검사 위치

**등록 시점**(CSV 임포트·상품 CRUD)에 건다. 추첨 시점이 아니다 — 추첨 뒤에 거절하면
"당첨될수록 실패하는" 분포가 되고 재추첨 문제가 돌아온다. 등록 시점이면 그 비용이 없다.
`claim_from_result` 에도 같은 표를 걸어 직접 INSERT 경로를 닫는다(이중 방어).

근거: Lib9c/Currencies.cs — Crystal/Garage 는 `Currency.Legacy/Uncapped(_, 18, …)`,
`GetRune`/`GetSoulStone` 은 `Currency.Legacy(ticker, 0, …)`. NCG 는 minter 가 있어
`GetMinterlessCurrency` 가 아예 거절하므로(= 발행 불가) 이 표에 없다.
"""

#: lib9c 가 wrapped currency 를 알아보는 접두어. `Currencies.IsWrappedCurrency` 는
#: 실제로 `StartsWith("FAV")` 지만, 우리가 만들어 보내는 건 항상 `FAV__` 다.
FAV_PREFIX = "FAV__"

#: 고정 자릿수 티커 (Lib9c/Currencies.cs 의 Crystal·Garage)
_FIXED_DECIMALS = {
    "CRYSTAL": 18,
    "GARAGE": 18,
}

#: 접두어로 판별하는 계열. 전부 `Currency.Legacy(ticker, 0)` 이라 자릿수가 0 이다.
#: lib9c 는 소문자로 내려 비교하지만 우리는 **대문자만** 받는다 — 아래 `decimal_places_of` 주석 참고.
_ZERO_DECIMAL_PREFIXES = ("RUNE_", "RUNESTONE_", "SOULSTONE_")


class FavCurrencyError(ValueError):
    """FAV 티커·자릿수가 lib9c 가 아는 통화와 맞지 않는다."""


def strip_fav_prefix(ticker: str) -> str:
    """`FAV__CRYSTAL` → `CRYSTAL`. 접두어가 없으면 그대로 돌려준다."""
    return ticker[len(FAV_PREFIX):] if ticker.startswith(FAV_PREFIX) else ticker


def decimal_places_of(ticker: str) -> int:
    """이 FAV 티커의 **진짜** 자릿수. 모르는 티커면 `FavCurrencyError`.

    `FAV__` 접두어는 붙어 있어도 없어도 된다.
    """
    bare = strip_fav_prefix(ticker or "")
    if not bare:
        raise FavCurrencyError("FAV 티커가 비었다")
    if bare in _FIXED_DECIMALS:
        return _FIXED_DECIMALS[bare]
    # **대문자로 못박는다.** lib9c 의 `IsRuneTicker` 는 `ToLower()` 후 판정하지만
    #   `GetRune(ticker)` 는 **원래 대소문자 그대로** `Currency.Legacy(ticker, 0)` 을 만든다.
    #   즉 `runestone_hp` 는 `RUNESTONE_HP` 와 **다른 통화**이고, tx 는 SUCCESS 로 끝나고
    #   유저는 아무 데서도 안 쓰이는 잔고를 받는다 — 이 모듈이 막겠다고 한 바로 그 부류다.
    #   lib9c 판정을 그대로 흉내 내면(소문자 비교) 그 오타가 통과하므로 일부러 좁힌다.
    #   라이브 티커는 전부 대문자다(CRYSTAL / RUNE_GOLDENLEAF / RUNESTONE_* 실측).
    for prefix in _ZERO_DECIMAL_PREFIXES:
        if bare.startswith(prefix) and len(bare) > len(prefix):
            return 0
    raise FavCurrencyError(
        f"lib9c 가 모르는 FAV 티커다: {ticker!r} — "
        f"CRYSTAL / GARAGE / RUNE_* / RUNESTONE_* / SOULSTONE_* 만 발행할 수 있다"
        " (NCG 는 minter 가 있어 GrantItems 로 발행 자체가 불가능하다)"
    )


def assert_fav_decimal_places(ticker: str, decimal_places: int, where: str = "") -> None:
    """티커와 자릿수가 맞는지. 안 맞으면 `FavCurrencyError`.

    `where` 는 어느 행이 틀렸는지 운영이 찾을 수 있게 붙이는 꼬리표다.
    """
    suffix = f" ({where})" if where else ""
    expected = decimal_places_of(ticker)
    if isinstance(decimal_places, bool) or not isinstance(decimal_places, int):
        raise FavCurrencyError(
            f"decimal_places 는 정수여야 한다: {decimal_places!r}{suffix}"
        )
    if decimal_places != expected:
        raise FavCurrencyError(
            f"{ticker} 의 자릿수는 {expected} 인데 {decimal_places} 로 적혀 있다{suffix} — "
            f"그 차이가 그대로 발행 배율이 된다(10^{abs(decimal_places - expected)} 배). "
            "체인 발행은 되돌릴 수 없다"
        )


def assert_product_favs_mintable(product, where: str = "") -> None:
    """고정 상품의 `fav_list` 전체가 발행 가능한 티커·자릿수인지.

    **가챠의 `claim_from_result` 에 대응하는 고정 상품 쪽 이중 방어다.** 등록 시점 CSV 검증만
    있으면 충분해 보이지만 우회로가 실재한다:

      · `CLAUDE.md` 가 상품 추가 경로로 "관리자 CSV 임포트, **또는 직접 DB**" 를 적어 뒀다
      · `scripts/fungible_asset.py` 는 `process_fungible_asset_row` 의 **복사본**인데 검증이
        한 줄도 없다 — `DATABASE_URL` 만 있으면 돈다

    그리고 이 PR 이 여는 것이 바로 그 고정 상품의 **무상** 지급이다. 고정 상품엔 추첨이
    없으므로 "당첨될수록 실패하는 분포" 비용도 없다 — 요청 시점에 400 으로 끊으면 된다.

    유상 결제 경로(`send_product_task`)는 일부러 건드리지 않는다. 그쪽은 이 PR 이 여는 것이
    아니고, 레거시 행 하나로 기존 결제를 깨뜨릴 위험이 이득보다 크다. 대신 배포 전에
    `fungible_asset_product` 를 실제로 훑어 위반 행이 있는지 확인해야 한다(있다면 그 상품은
    지금까지 잘못된 배율로 지급돼 온 것이므로 **별건의 사고**다).
    """
    for fav in getattr(product, "fav_list", None) or []:
        assert_fav_decimal_places(
            fav.ticker, fav.decimal_places, where or f"product {product.id}"
        )
