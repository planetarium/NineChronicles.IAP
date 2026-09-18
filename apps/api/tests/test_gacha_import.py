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
# 전환 테스트용 — 키 시트의 `mat_hourglass_s`(8,000) 와 **같은 수량**이라 그 행에 입양된다.
#   (수량이 다르면 "기존 칸이 이 파일에 없다" 로 거절된다 — 의도된 fail-closed)
ITEM_ROW_8000 = "900,Hourglass,100,ITEM,Item_NT_400000,8000,400000,0"
FAV_ROW = "900,HP Rune,100,FAV,FAV__RUNESTONE_HP,200,,0"


class TestBasics:
    def test_아이템과_FAV_를_같이_넣는다(self, sess, product):
        processed, changed = run_import(
            sess, [ITEM_ROW, FAV_ROW]
        )
        assert (processed, changed) == (2, 2)
        by_kind = {e.kind: e for e in entries(sess)}
        assert by_kind["ITEM"].ticker == "Item_NT_400000"
        assert by_kind["ITEM"].sheet_item_id == 400000
        assert by_kind["FAV"].ticker == "FAV__RUNESTONE_HP"
        assert by_kind["FAV"].sheet_item_id is None

    def test_재임포트는_멱등이다(self, sess, product):
        run_import(sess, [ITEM_ROW])
        processed, changed = run_import(sess, [ITEM_ROW])
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
        run_import(sess, [FAV_ROW])
        # kind 를 비운 같은 티커 행 재임포트 (sheet_item_id 도 비워야 FAV 로 성립)
        run_import(
            sess,
            ["900,HP Rune,150,,FAV__RUNESTONE_HP,200,,0"],
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


class TestSlotKey:
    """
    칸의 정체성은 **표에서의 자리**(`slot_key`)지 산출물(`ticker`)이 아니다.

    상품표 v0.9 §1.1 의 재료 티어가 "아이템 5종 × 수량 2단계 = 9칸"이라, 티커를 축으로
    두면 두 번째 행이 첫 번째를 **조용히 덮어써** 9칸 표가 5칸이 된다. 임포트는 성공하고
    확률만 기획과 달라지므로, 표현 자체가 되는지를 여기서 못 박는다.
    """

    def test_같은_아이템을_수량만_다르게_두_칸(self, sess, product):
        # 상품표의 모래시계 두 칸(8,000개 21% / 25,000개 6%) 그대로.
        header = HEADER + ",slot_key\n"
        content = header + "\n".join(
            [
                "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,mat_hourglass_s",
                "900,Hourglass,600,ITEM,Item_NT_400000,25000,400000,0,mat_hourglass_l",
            ]
        ) + "\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
            f.write(content)
            path = f.name
        try:
            processed, changed = import_gacha_entries_from_csv(sess, path)
        finally:
            os.unlink(path)

        assert (processed, changed) == (2, 2)
        rows = sorted(entries(sess), key=lambda e: e.weight)
        assert [(e.slot_key, e.amount, e.weight) for e in rows] == [
            ("mat_hourglass_l", 25000, 600),
            ("mat_hourglass_s", 8000, 2100),
        ]

    def test_slot_key_없는_시트는_티커가_키다(self, sess, product):
        run_import(sess, [ITEM_ROW])
        assert entries(sess)[0].slot_key == "Item_NT_400000"
        # 멱등 — 옛 시트를 다시 올려도 칸이 늘지 않는다.
        run_import(sess, [ITEM_ROW])
        assert len(entries(sess)) == 1

    def test_slot_key_를_처음_붙이면_기존_칸을_입양한다(self, sess, product):
        """옛 시트에 이름표를 붙이는 첫 재임포트가 **칸을 복제하면 안 된다.**

        그냥 INSERT 하면 22칸 표가 44칸이 되고 확률이 절반으로 어긋난다 — 이 변경이
        만들 수 있는 가장 흔한 사고라 여기서 막는다.
        """
        run_import(sess, [ITEM_ROW])  # slot_key = ticker 로 들어간다
        before = entries(sess)[0].id

        header = HEADER + ",slot_key\n"
        content = header + "900,Hourglass,100,ITEM,Item_NT_400000,30,400000,0,mat_hourglass_s\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
            f.write(content)
            path = f.name
        try:
            import_gacha_entries_from_csv(sess, path)
        finally:
            os.unlink(path)

        rows = entries(sess)
        assert len(rows) == 1, "칸이 복제됐다 — 확률이 절반으로 어긋난다"
        assert rows[0].id == before  # 같은 칸 그대로, 이름표만 바뀜
        assert rows[0].slot_key == "mat_hourglass_s"

    def test_입양은_한_번뿐이다(self, sess, product):
        """입양이 무제한이면 같은 티커의 **두 번째 칸을 영원히 못 만든다.**"""
        run_import(sess, [ITEM_ROW_8000])

        header = HEADER + ",slot_key\n"
        content = header + "\n".join(
            [
                "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,mat_hourglass_s",
                "900,Hourglass,600,ITEM,Item_NT_400000,25000,400000,0,mat_hourglass_l",
            ]
        ) + "\n"
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
            f.write(content)
            path = f.name
        try:
            import_gacha_entries_from_csv(sess, path)
        finally:
            os.unlink(path)

        rows = sorted(entries(sess), key=lambda e: e.weight)
        assert len(rows) == 2
        assert [e.slot_key for e in rows] == ["mat_hourglass_l", "mat_hourglass_s"]

    def test_같은_칸의_산출물_교체는_갱신이다(self, sess, product):
        """수량·티커를 바꿔도 **칸은 그대로** — 이게 안 A(UNIQUE 에 amount 추가)와의 차이다."""
        header = HEADER + ",slot_key\n"

        def run(row):
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
                f.write(header + row + "\n")
                path = f.name
            try:
                return import_gacha_entries_from_csv(sess, path)
            finally:
                os.unlink(path)

        run("900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,mat_slot_1")
        before = entries(sess)[0].id
        run("900,AP Stone,2100,ITEM,Item_NT_500000,25,500000,0,mat_slot_1")

        rows = entries(sess)
        assert len(rows) == 1
        assert rows[0].id == before
        assert (rows[0].ticker, rows[0].amount) == ("Item_NT_500000", 25)


def run_keyed(sess, rows, **kwargs):
    """`slot_key` 컬럼이 있는 CSV. rows 는 HEADER + ',slot_key' 순서의 문자열."""
    content = HEADER + ",slot_key\n" + "\n".join(rows) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv") as f:
        f.write(content)
        path = f.name
    try:
        return import_gacha_entries_from_csv(sess, path, **kwargs)
    finally:
        os.unlink(path)


HG_S = "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,mat_hourglass_s"
HG_L = "900,Hourglass,600,ITEM,Item_NT_400000,25000,400000,0,mat_hourglass_l"


class TestSlotKeyGuards:
    """
    선행 검사가 막는 것들. 전부 **임포트는 성공하고 확률만 틀어지는** 종류라, 하나라도
    빠지면 사고가 인터널이 아니라 유저 화면에서 처음 드러난다.

    풀 CSV 는 upsert-only(삭제가 없다)라 잘못 들어간 칸은 DB 를 직접 고쳐야 없어진다.
    """

    def test_이미_키잉된_상품에_옛_시트는_거절(self, sess, product):
        """전환 직후가 제일 위험하다 — 옛 시트 탭이 그대로 남아 있다."""
        run_keyed(sess, [HG_S, HG_L])
        before = {(e.slot_key, e.amount, e.weight) for e in entries(sess)}

        with pytest.raises(ValueError, match="옛 시트"):
            run_import(sess, [ITEM_ROW])

        assert {(e.slot_key, e.amount, e.weight) for e in entries(sess)} == before

    def test_한_상품_안에서_키가_섞이면_거절(self, sess, product):
        """무키 행이 레거시 칸을 갱신하고, 뒤 행이 그 칸을 또 입양해 둘이 한 칸이 된다."""
        run_import(sess, [ITEM_ROW])
        with pytest.raises(ValueError, match="전부"):
            run_keyed(
                sess,
                ["900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,", HG_L],
            )
        assert len(entries(sess)) == 1

    def test_파일_안_중복_키는_거절(self, sess, product):
        with pytest.raises(ValueError, match="두 번"):
            run_keyed(
                sess,
                [
                    "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,dup",
                    "900,AP Stone,600,ITEM,Item_NT_500000,25,500000,0,dup",
                ],
            )
        assert entries(sess) == []

    def test_레거시_칸을_덮지_않는_부분_시트는_거절(self, sess, product):
        """새 행만 올리면 남은 레거시 칸이 그 행으로 **변신**한다 — 추가가 아니다."""
        run_import(sess, [ITEM_ROW])  # Item_NT_400000 x30
        with pytest.raises(ValueError, match="전체"):
            run_keyed(sess, ["900,AP Stone,600,ITEM,Item_NT_500000,25,500000,0,mat_ap"])
        assert [(e.ticker, e.amount) for e in entries(sess)] == [
            ("Item_NT_400000", 30)
        ]

    def test_칸_이름을_남의_티커로_지으면_거절(self, sess, product):
        with pytest.raises(ValueError, match="티커 형태"):
            run_keyed(
                sess,
                ["900,Hourglass,100,ITEM,Item_NT_400000,30,400000,0,Item_NT_500000"],
            )

    def test_입양은_product_단위로_갇힌다(self, sess, product):
        """한 CSV 에 두 상품. 남의 상품 칸을 입양하면 두 상품의 확률이 동시에 틀어진다."""
        other = Product(
            id=901,
            name="gacha2",
            order=2,
            google_sku="g2",
            apple_sku="a2",
            apple_sku_k="ak2",
            product_type=ProductType.FREE,
            active=True,
            rarity=ProductRarity.NORMAL,
            size=ProductAssetUISize.ONE_BY_ONE,
            path="p.png",
            l10n_key="L",
            mileage=0,
            discount=0,
        )
        sess.add(other)
        sess.commit()
        run_import(sess, [ITEM_ROW_8000, ITEM_ROW_8000.replace("900,", "901,", 1)])
        assert len(entries(sess)) == 2

        run_keyed(
            sess,
            [HG_S, HG_L, HG_S.replace("900,", "901,", 1), HG_L.replace("900,", "901,", 1)],
        )
        by_product = {}
        for e in entries(sess):
            by_product.setdefault(e.product_id, []).append(e.slot_key)
        assert sorted(by_product[900]) == ["mat_hourglass_l", "mat_hourglass_s"]
        assert sorted(by_product[901]) == ["mat_hourglass_l", "mat_hourglass_s"]

    def test_행_순서를_뒤집어도_최종_풀은_같다(self, sess, product):
        run_import(sess, [ITEM_ROW_8000])
        run_keyed(sess, [HG_L, HG_S])  # 큰 칸 먼저
        assert {(e.slot_key, e.amount, e.weight) for e in entries(sess)} == {
            ("mat_hourglass_s", 8000, 2100),
            ("mat_hourglass_l", 25000, 600),
        }

    def test_무키_시트의_중복_티커도_거절(self, sess, product):
        """이 티켓의 **원래 사고** — 재료 9행을 쓰면서 slot_key 컬럼을 깜빡한 경우다.

        실효 키(티커 폴백) 기준으로 안 보면 3행이 2칸이 되고, 임포트는 (3, 3) 으로
        성공을 돌려준다.
        """
        with pytest.raises(ValueError, match="두 번"):
            run_import(
                sess,
                [
                    "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0",
                    "900,Hourglass,600,ITEM,Item_NT_400000,25000,400000,0",
                    "900,AP Stone,1800,ITEM,Item_NT_500000,25,500000,0",
                ],
            )
        assert entries(sess) == []

    def test_이번_임포트가_만든_칸은_입양당하지_않는다(self, sess, product):
        """"기존 칸은 이름을 티커 그대로 두고 새 칸만 이름 붙인다" 가 주 경로다.

        새로 INSERT 된 칸(slot_key == ticker)을 뒤 행이 입양하면 두 행이 한 칸으로
        합쳐진다 — 행 순서만 바꿔도 결과가 달라지는 종류의 버그다.
        """
        run_import(sess, ["900,AP Stone,1800,ITEM,Item_NT_500000,25,500000,0"])
        run_keyed(
            sess,
            [
                "900,AP Stone,1800,ITEM,Item_NT_500000,25,500000,0,mat_ap",
                # 칸 이름을 자기 티커로 둔 신규 행 — 폴백과 구분되지 않는다
                "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0,Item_NT_400000",
                "900,Hourglass,600,ITEM,Item_NT_400000,25000,400000,0,mat_hourglass_l",
            ],
        )
        rows = sorted(entries(sess), key=lambda e: e.slot_key)
        assert [(e.slot_key, e.amount) for e in rows] == [
            ("Item_NT_400000", 8000),
            ("mat_ap", 25),
            ("mat_hourglass_l", 25000),
        ], "칸이 합쳐졌다 — Σweight 가 줄어 확률이 통째로 바뀐다"
        assert sum(e.weight for e in rows) == 4500

    def test_티커는_다_덮지만_칸은_절반인_시트는_거절(self, sess, product):
        """커버를 티커로 재면 뚫린다 — 이 티켓의 전제가 "티커 하나가 수량별로 여러 칸" 이다.

        티커별 '큰 수량' 행만 담은 시트는 티커를 전부 덮지만, 작은 수량 칸들이 통째로
        큰 수량으로 **재정의**된다(10칸이 될 표가 5칸으로, Σweight 도 같이 줄어든다).
        """
        run_import(
            sess,
            [
                "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0",
                "900,AP Stone,1800,ITEM,Item_NT_500000,25,500000,0",
            ],
        )
        with pytest.raises(ValueError, match=r"Item_NT_400000 x8000"):
            run_keyed(
                sess,
                [
                    HG_L,
                    "900,AP Stone,500,ITEM,Item_NT_500000,80,500000,0,mat_ap_l",
                ],
            )
        assert {(e.ticker, e.amount) for e in entries(sess)} == {
            ("Item_NT_400000", 8000),
            ("Item_NT_500000", 25),
        }

    def test_작은_칸까지_담은_전체_시트는_통과(self, sess, product):
        """위와 **같은 상태에서 행만 온전하면** 정상적으로 4칸이 된다."""
        run_import(
            sess,
            [
                "900,Hourglass,2100,ITEM,Item_NT_400000,8000,400000,0",
                "900,AP Stone,1800,ITEM,Item_NT_500000,25,500000,0",
            ],
        )
        run_keyed(
            sess,
            [
                HG_S,
                HG_L,
                "900,AP Stone,1800,ITEM,Item_NT_500000,25,500000,0,mat_ap_s",
                "900,AP Stone,500,ITEM,Item_NT_500000,80,500000,0,mat_ap_l",
            ],
        )
        rows = sorted(entries(sess), key=lambda e: e.slot_key)
        assert [(e.slot_key, e.amount) for e in rows] == [
            ("mat_ap_l", 80),
            ("mat_ap_s", 25),
            ("mat_hourglass_l", 25000),
            ("mat_hourglass_s", 8000),
        ]
        assert sum(e.weight for e in rows) == 5000  # 2100+600+1800+500
