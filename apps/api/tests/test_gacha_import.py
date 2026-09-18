"""
(PLD-1562) 뽑기 풀 CSV 임포트.

이 파일이 생긴 이유는 리뷰의 뮤테이션 테스트다: 임포트 경로를 부르는 테스트가 리포에
**0건**이라, 이 커밋이 넣은 검증을 전부 지워도 299건이 초록이었다. 살아남은 변이들:
  · FAV 를 아이템 상한으로 재기      (커밋 메시지가 "사고" 라고 부른 바로 그것)
  · 모르는 kind 를 ITEM 으로 흡수
  · FAV 에 sheet_item_id 허용
  · ITEM 에 decimal_places != 0 허용
  · 옛 컬럼명 폴백 제거
가드 쪽은 엔드포인트 테스트가 촘촘한데 **등록 경로만 무방비**였다. 등록 시점 검증은
"지급 시점에만 걸리면 유저가 포인트를 쓴 뒤에 실패한다"는 이유로 넣은 것이라, 그게
지워져도 조용한 건 원래 목적을 잃는 것이다.
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.utils.import_utils import (
    import_gacha_entries_from_csv,
    import_products_from_csv,
)
from shared.enums import ProductAssetUISize, ProductRarity, ProductType
from shared.models.base import Base
from shared.models.product import FungibleItemProduct, Product, ProductGachaEntry

_TABLES = (
    "product",
    "fungible_asset_product",
    "fungible_item_product",
    "product_gacha_entry",
)

HEADER = "product_id,name,weight,kind,ticker,amount,sheet_item_id,decimal_places"


@pytest.fixture
def sess():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng, tables=[Base.metadata.tables[t] for t in _TABLES])
    session = Session(eng)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def product(sess):
    p = Product(
        id=900,
        name="gacha",
        order=1,
        google_sku="g",
        apple_sku="a",
        apple_sku_k="ak",
        product_type=ProductType.FREE,
        active=True,
        rarity=ProductRarity.NORMAL,
        size=ProductAssetUISize.ONE_BY_ONE,
        path="p.png",
        l10n_key="L",
        mileage=0,
        discount=0,
    )
    sess.add(p)
    sess.commit()
    return p


def run_import(sess, rows, **kwargs):
    """CSV 문자열을 임시 파일로 넘긴다(엔드포인트까지 안 가도 검증은 전부 지난다)."""
    content = HEADER + "\n" + "\n".join(rows) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
        f.write(content)
        path = f.name
    try:
        return import_gacha_entries_from_csv(sess, path, **kwargs)
    finally:
        os.unlink(path)


def entries(sess):
    return sess.scalars(select(ProductGachaEntry)).all()


ITEM_ROW = "900,Hourglass,100,ITEM,Item_NT_400000,30,400000,0"
FAV_ROW = "900,HP Rune,100,FAV,FAV__RUNESTONE_HP,200,,0"
ALLOW_HP = frozenset({"FAV__RUNESTONE_HP"})


class TestBasics:
    def test_아이템과_FAV_를_같이_넣는다(self, sess, product):
        processed, changed = run_import(
            sess, [ITEM_ROW, FAV_ROW], allowed_fav_tickers=ALLOW_HP
        )
        assert (processed, changed) == (2, 2)
        by_kind = {e.kind: e for e in entries(sess)}
        assert by_kind["ITEM"].ticker == "Item_NT_400000"
        assert by_kind["ITEM"].sheet_item_id == 400000
        assert by_kind["FAV"].ticker == "FAV__RUNESTONE_HP"
        assert by_kind["FAV"].sheet_item_id is None

    def test_재임포트는_멱등이다(self, sess, product):
        run_import(sess, [ITEM_ROW], allowed_fav_tickers=ALLOW_HP)
        processed, changed = run_import(sess, [ITEM_ROW], allowed_fav_tickers=ALLOW_HP)
        assert (processed, changed) == (1, 0)
        assert len(entries(sess)) == 1

    def test_옛_컬럼명_fungible_item_id_도_읽는다(self, sess, product):
        # kind 컬럼이 없던 시절 시트가 그대로 돌아야 한다.
        content = "product_id,name,weight,fungible_item_id,amount,sheet_item_id\n"
        content += "900,Hourglass,100,Item_NT_400000,30,400000\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
            f.write(content)
            path = f.name
        try:
            import_gacha_entries_from_csv(sess, path)
        finally:
            os.unlink(path)
        assert entries(sess)[0].ticker == "Item_NT_400000"
        assert entries(sess)[0].kind == "ITEM"

    def test_ticker_와_옛_컬럼이_다르면_거절(self, sess, product):
        content = HEADER + ",fungible_item_id\n"
        content += "900,X,100,ITEM,Item_NT_400000,1,400000,0,Item_NT_999999\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
            f.write(content)
            path = f.name
        try:
            with pytest.raises(ValueError, match="다르다"):
                import_gacha_entries_from_csv(sess, path)
        finally:
            os.unlink(path)


class TestKindIsThreeState:
    """
    `kind` 는 머니 플래그다 — 빈칸/컬럼 부재는 **"변경 없음"**이지 ITEM 이 아니다.
    2상태로 읽으면 옛 시트 재임포트가 기존 FAV 칸을 ITEM 으로 내려앉히고, 그 칸은 그 뒤로
    얼로우리스트를 안 지난다(닫은 구멍이 임포트로 다시 열린다).
    """

    def test_빈칸은_기존_FAV_를_ITEM_으로_뒤집지_않는다(self, sess, product):
        run_import(sess, [FAV_ROW], allowed_fav_tickers=ALLOW_HP)
        # kind 를 비운 같은 티커 행 재임포트 (sheet_item_id 도 비워야 FAV 로 성립)
        run_import(
            sess,
            ["900,HP Rune,150,,FAV__RUNESTONE_HP,200,,0"],
            allowed_fav_tickers=ALLOW_HP,
        )
        row = entries(sess)[0]
        assert row.kind == "FAV", "빈칸이 기존 FAV 를 ITEM 으로 뒤집으면 안 된다"
        assert row.weight == 150, "나머지 값은 정상적으로 갱신돼야 한다"

    def test_신규_행의_빈칸은_ITEM(self, sess, product):
        run_import(sess, ["900,Hourglass,100,,Item_NT_400000,30,400000,0"])
        assert entries(sess)[0].kind == "ITEM"

    def test_모르는_kind_는_거절(self, sess, product):
        with pytest.raises(ValueError, match="kind"):
            run_import(sess, ["900,X,100,COIN,Item_NT_400000,1,400000,0"])
        assert entries(sess) == []


class TestShapeValidation:
    def test_ITEM_에_sheet_item_id_가_없으면_거절(self, sess, product):
        with pytest.raises(ValueError, match="sheet_item_id"):
            run_import(sess, ["900,X,100,ITEM,Item_NT_400000,1,,0"])

    def test_FAV_에_sheet_item_id_가_있으면_거절(self, sess, product):
        # 두면 화면이 없는 아이콘을 그린다.
        with pytest.raises(ValueError, match="sheet_item_id"):
            run_import(
                sess,
                ["900,X,100,FAV,FAV__RUNESTONE_HP,1,400000,0"],
                allowed_fav_tickers=ALLOW_HP,
            )

    def test_ITEM_의_decimal_places_는_0_이어야_한다(self, sess, product):
        # 0 이 아니면 amount * 10**places 로 부풀려 발행된다.
        with pytest.raises(ValueError, match="decimal_places"):
            run_import(sess, ["900,X,100,ITEM,Item_NT_400000,1,400000,18"])

    @pytest.mark.parametrize("weight", ["0", "-1", ""])
    def test_가중치는_양의_정수(self, sess, product, weight):
        with pytest.raises(ValueError, match="weight"):
            run_import(sess, [f"900,X,{weight},ITEM,Item_NT_400000,1,400000,0"])

    @pytest.mark.parametrize("amount", ["0", "-5", ""])
    def test_수량은_양의_정수(self, sess, product, amount):
        with pytest.raises(ValueError, match="amount"):
            run_import(sess, [f"900,X,100,ITEM,Item_NT_400000,{amount},400000,0"])


class TestCapsAreMeasuredPerAxis:
    """합치면 FAV 상한이 아이템 상한에 흡수된다 — 등록 시점에도 같은 규칙이어야 한다."""

    def test_FAV_는_FAV_상한으로_잰다(self, sess, product):
        with pytest.raises(ValueError, match="상한"):
            run_import(
                sess,
                [FAV_ROW],  # amount=200
                max_item_units=10_000,  # 아이템 상한은 넉넉
                max_fav_units=50,  # FAV 상한은 빡빡
                allowed_fav_tickers=ALLOW_HP,
            )
        assert entries(sess) == [], "거절이면 전체 롤백이어야 한다"

    def test_아이템은_아이템_상한으로_잰다(self, sess, product):
        with pytest.raises(ValueError, match="상한"):
            run_import(sess, [ITEM_ROW], max_item_units=10, max_fav_units=10_000)

    def test_상한_미설정이면_검사하지_않는다(self, sess, product):
        run_import(sess, [ITEM_ROW, FAV_ROW], allowed_fav_tickers=ALLOW_HP)
        assert len(entries(sess)) == 2


class TestFavAllowlistAtRegistration:
    """
    닫힌 티커가 등록되면 그 칸에 당첨된 주문이 503 이 되는데, 그 503 은 "그 주문만 멈춤"이
    아니라 **조용한 재추첨**이다(추첨이 아웃박스 행보다 먼저라 거절 시 행이 없고, 재시도가
    멱등에 안 걸린다). 그래서 등록 자체를 막는다.
    """

    def test_허용목록_밖_티커는_등록되지_않는다(self, sess, product):
        with pytest.raises(ValueError, match="허용목록 밖"):
            run_import(
                sess, [FAV_ROW], allowed_fav_tickers=frozenset({"FAV__CRYSTAL"})
            )
        assert entries(sess) == []

    def test_허용목록이_비어_있으면_FAV_등록을_막는다(self, sess, product):
        with pytest.raises(ValueError, match="비어 있다"):
            run_import(sess, [FAV_ROW], allowed_fav_tickers=frozenset())
        assert entries(sess) == []

    def test_아이템만_있으면_허용목록과_무관하다(self, sess, product):
        run_import(sess, [ITEM_ROW], allowed_fav_tickers=frozenset())
        assert len(entries(sess)) == 1


class TestMixedComponents:
    def test_고정_구성품이_있는_상품에는_풀을_못_넣는다(self, sess, product):
        sess.add(
            FungibleItemProduct(
                product_id=product.id,
                sheet_item_id=500000,
                name="AP",
                fungible_item_id="Item_NT_500000",
                amount=1,
            )
        )
        sess.commit()

        with pytest.raises(ValueError, match="동시에 가질 수 없다"):
            run_import(sess, [ITEM_ROW])
        assert entries(sess) == []

    def test_없는_상품은_거절(self, sess):
        with pytest.raises(ValueError, match="존재하지 않는다"):
            run_import(sess, ["999,X,100,ITEM,Item_NT_400000,1,400000,0"])


# ── 10연: 상한은 1 요청 단위다 ────────────────────────────────────────────────
PRODUCT_HEADER = (
    "id,name,google_sku,apple_sku,apple_sku_k,daily_limit,weekly_limit,account_limit,"
    "order,active,open_timestamp,close_timestamp,discount,rarity,size,popup_path_key,"
    "required_level,product_type,mileage,mileage_price,gacha_draw_count"
)


def run_product_import(sess, rows, **kwargs):
    content = PRODUCT_HEADER + "\n" + "\n".join(rows) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
        f.write(content)
        path = f.name
    try:
        return import_products_from_csv(
            sess, path, "internal", interactive=False, **kwargs
        )
    finally:
        os.unlink(path)


def product_row(draws):
    return (
        f"900,gacha,g,a,ak,,,,1,TRUE,,,0.0,NORMAL,ONE_BY_ONE,,,FREE,0,,{draws}"
    )


class TestDrawCountCaps:
    """
    상한은 **1 요청** 단위인데 10연은 한 요청이 10회 지급이다. 회차당으로 재면 10연이
    상한을 10배 우회하고, 반대로 재검증을 빠뜨리면 "운 좋은 10연만 400" 이 된다 —
    그 400 은 그 주문만 멈추는 게 아니라 **조용한 재추첨**이다(행이 안 생겨 포탈 재시도가
    멱등에 안 걸린다).
    """

    def test_최악의_10연_합계로_잰다(self, sess, product):
        # amount=30 × 10연 = 300 > 100 → 등록 시점에 막혀야 한다.
        product.gacha_draw_count = 10
        sess.commit()
        with pytest.raises(ValueError, match="상한"):
            run_import(sess, [ITEM_ROW], max_item_units=100)
        assert entries(sess) == []

    def test_단연이면_같은_칸이_통과한다(self, sess, product):
        # 회차당으로 재는 회귀를 가른다 — draws=1 이면 30 ≤ 100 이라 통과다.
        run_import(sess, [ITEM_ROW], max_item_units=100)
        assert len(entries(sess)) == 1

    def test_상품_CSV_로_10연을_켜면_풀_상한을_다시_잰다(self, sess, product):
        # 🔴 이 경로가 없으면 상한 검사가 **한 번도 안 돌고**, 그 뒤 큰 칸이 뽑힌 10연만
        #    지급 시점에 400 이 된다(= 재추첨).
        run_import(sess, [ITEM_ROW], max_item_units=100)  # draws=1 이라 통과
        with pytest.raises(ValueError, match="상한"):
            run_product_import(sess, [product_row(10)], max_item_units=100)

    def test_상품_CSV_로_켠_10연이_상한_안이면_통과한다(self, sess, product):
        run_import(sess, [ITEM_ROW], max_item_units=1000)
        run_product_import(sess, [product_row(10)], max_item_units=1000)
        sess.refresh(product)
        assert product.gacha_draw_count == 10

    def test_풀이_없는_상품은_재검증하지_않는다(self, sess, product):
        # 뽑기와 무관한 상품 임포트마다 풀을 조회할 이유가 없다.
        run_product_import(sess, [product_row(10)], max_item_units=1)
        sess.refresh(product)
        assert product.gacha_draw_count == 10


class TestDrawCountColumn:
    def test_헤더가_없으면_기존_값을_유지한다(self, sess, product):
        # 2상태로 읽으면 옛 시트 재임포트가 10연을 조용히 단연으로 되돌린다.
        product.gacha_draw_count = 10
        sess.commit()
        header_no_draws = PRODUCT_HEADER.replace(",gacha_draw_count", "")
        content = header_no_draws + "\n" + product_row(10).rsplit(",", 1)[0] + "\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
            f.write(content)
            path = f.name
        try:
            import_products_from_csv(sess, path, "internal", interactive=False)
        finally:
            os.unlink(path)
        sess.refresh(product)
        assert product.gacha_draw_count == 10

    def test_빈칸도_기존_값을_유지한다(self, sess, product):
        product.gacha_draw_count = 10
        sess.commit()
        run_product_import(sess, [product_row("")])
        sess.refresh(product)
        assert product.gacha_draw_count == 10

    @pytest.mark.parametrize("draws", ["0", "-1", "101", "100000"])
    def test_범위_밖은_거절(self, sess, product, draws):
        # 상한이 필요한 이유: 추첨이 전역 advisory lock 안에서 돈다(큰 값 = 지급 처리량 정지).
        with pytest.raises(ValueError, match="gacha_draw_count"):
            run_product_import(sess, [product_row(draws)])

    def test_경계값_1_과_100_은_통과한다(self, sess, product):
        for draws in (1, 100):
            run_product_import(sess, [product_row(draws)])
            sess.refresh(product)
            assert product.gacha_draw_count == draws


# ── (PLD-1564) 결제 가능 포인트 종류 ─────────────────────────────────────────
#
# 기획이 "가챠·확정교환 = PP-X 전용" 을 **확률보다 강한 가드**로 쓴다(상품표 v0.9 부록 C.5):
# 가챠를 현금화 가능 포인트로만 살 수 있게 두면 체크인 적립만 하는 층(봇 주 서식지)이
# 가챠에 아예 못 닿는다. 그래서 이 값이 조용히 풀리는 경로가 없어야 한다.
class TestPointPayableKinds:
    def test_기본은_ANY_다(self, sess, product):
        run_product_import(sess, [product_row(1)])
        sess.refresh(product)
        assert product.point_payable_kinds == 'ANY'

    def test_NCG_전용으로_켤_수_있다(self, sess, product):
        content = PRODUCT_HEADER + ',point_payable_kinds\n' + product_row(1) + ',NCG\n'
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.csv') as f:
            f.write(content)
            path = f.name
        try:
            import_products_from_csv(sess, path, 'internal', interactive=False)
        finally:
            os.unlink(path)
        sess.refresh(product)
        assert product.point_payable_kinds == 'NCG'

    def test_헤더가_없으면_기존_값을_유지한다(self, sess, product):
        # ⚠️ 2상태로 읽으면 이 컬럼 없는 기존 시트 재임포트가 가챠의 NCG 제약을 조용히
        #    'ANY' 로 푼다 — 봇이 무상 포인트로 가챠를 도는 문이 열린다.
        product.point_payable_kinds = 'NCG'
        sess.commit()
        run_product_import(sess, [product_row(1)])  # 컬럼 없는 시트
        sess.refresh(product)
        assert product.point_payable_kinds == 'NCG'

    def test_빈칸도_기존_값을_유지한다(self, sess, product):
        product.point_payable_kinds = 'NCG'
        sess.commit()
        content = PRODUCT_HEADER + ',point_payable_kinds\n' + product_row(1) + ',\n'
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.csv') as f:
            f.write(content)
            path = f.name
        try:
            import_products_from_csv(sess, path, 'internal', interactive=False)
        finally:
            os.unlink(path)
        sess.refresh(product)
        assert product.point_payable_kinds == 'NCG'

    @pytest.mark.parametrize('alias', ['PP_X', 'PP-X', 'PPX', 'pp_x'])
    def test_문서_어휘_PP_X_도_받는다(self, sess, product, alias):
        # 값을 넣는 사람은 기획 문서(PP-S/PP-X)를 본다. 번역이 필요한 경계가 실수의 자리다.
        content = PRODUCT_HEADER + ',point_payable_kinds\n' + product_row(1) + f',{alias}\n'
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.csv') as f:
            f.write(content)
            path = f.name
        try:
            import_products_from_csv(sess, path, 'internal', interactive=False)
        finally:
            os.unlink(path)
        sess.refresh(product)
        assert product.point_payable_kinds == 'NCG', '저장은 코드 어휘 하나로'

    def test_BOTH_은_ANY_로_저장된다(self, sess, product):
        content = PRODUCT_HEADER + ',point_payable_kinds\n' + product_row(1) + ',BOTH\n'
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.csv') as f:
            f.write(content)
            path = f.name
        try:
            import_products_from_csv(sess, path, 'internal', interactive=False)
        finally:
            os.unlink(path)
        sess.refresh(product)
        assert product.point_payable_kinds == 'ANY'

    @pytest.mark.parametrize('bad', ['PP_S', 'ncg2', 'X', 'CASH'])
    def test_모르는_값은_거절(self, sess, product, bad):
        content = PRODUCT_HEADER + ',point_payable_kinds\n' + product_row(1) + f',{bad}\n'
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.csv') as f:
            f.write(content)
            path = f.name
        try:
            with pytest.raises(ValueError, match='point_payable_kinds'):
                import_products_from_csv(sess, path, 'internal', interactive=False)
        finally:
            os.unlink(path)

    def test_소문자도_받는다(self, sess, product):
        content = PRODUCT_HEADER + ',point_payable_kinds\n' + product_row(1) + ',ncg\n'
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.csv') as f:
            f.write(content)
            path = f.name
        try:
            import_products_from_csv(sess, path, 'internal', interactive=False)
        finally:
            os.unlink(path)
        sess.refresh(product)
        assert product.point_payable_kinds == 'NCG'
