# 시즌패스 SKU 고정 — 구성품은 시즌 정의에서 읽는다

- 작성일: 2026-09-18
- 상태: 설계 확정, 구현 미착수
- 관련 저장소: `NineChronicles.IAP`, `NineChronicles.SeasonPass`, `NineChronicles`, `NineChronicles.Backoffice`

## 1. 문제

시즌 하나를 열려면 사람이 네 번 움직인다.

1. **스토어** — SKU 에 시즌 번호가 박혀 있어(`g_pkg_couragepass34premium`) 매 시즌 구글·애플·애플K·원스토어에 상품을 새로 만들고 심사를 받는다
2. **IAP DB** — 그 시즌 상품 행을 CSV import 로 새로 넣는다 (이름·구성품·가격)
3. **IAP 카테고리** — `NoShow` 카테고리 연결을 새 시즌 상품으로 갈아끼운다 (이게 실질적인 시즌 전환 스위치다)
4. **season-pass DB** — 시즌 정의(기간·경험치 곡선·레벨별 보상)를 따로 등록한다

같은 "이번 달 시즌"이라는 사실을 네 번 적고 있다.

### 실측 (2026-09-18, mainnet)

`GET /api/product/all` 과 `GET /api/product` 로 확인했다.

- 전체 상품 365개 중 패스 관련 **83개가 누적**되어 있고 지워지지 않는다
- CouragePass 는 시즌 34, AdventureBossPass 는 22, WorldClearPass 는 1 까지 존재
- **83개 전부 `open_timestamp`/`close_timestamp` 가 null 이고 `active=true`** — 기간 기반 전환을 아무도 쓰지 않는다
- 클라에 실제 노출되는 건 `NoShow` 카테고리에 연결된 **현재 시즌 3개뿐**

| 상품 | google_sku | account_limit | mileage |
|---|---|---|---|
| `COURAGEPASS34Premium` | `g_pkg_couragepass34premium` | 3 | 1440 |
| `ADVENTUREBOSSPASS22Premium` | `g_pkg_adventurebosspass22premium` | 3 | 720 |
| `WORLDCLEARPASS1Premium` | `g_pkg_worldclearpass1premium` | 3 | 1440 |

시즌 기간 (`GET /api/season-pass/current`):

| 패스 | 시즌 | 기간 |
|---|---|---|
| CouragePass | 34 | 2026-09-01 09:00 ~ 2026-10-01 09:00 KST |
| AdventureBossPass | 22 | 동일 |
| WorldClearPass | 1 | 2024-12-01 시작, **종료 없음** |

초기 `SeasonPass1~12` 시절엔 Premium/Premiumplus/PremiumAll 3종이었으나, `COURAGEPASS13` 부터는 **패스당 Premium 1종만** 운영한다.

## 2. 목표

- 스토어 상품 등록·심사를 시즌마다 하지 않는다
- IAP DB 상품 등록·카테고리 연결 교체를 시즌마다 하지 않는다
- 사람이 매 시즌 손대는 곳을 **season-pass 시즌 등록 한 곳**으로 줄인다

### 비목표

- `NoShow` 가 카테고리 자리에 플래그로 들어앉아 있는 구조 정리 (클라 4파일 5곳이 문자열로 물고 있어 별건 — `IAPStoreManager.cs:101`·`:185`, `MobileShop.cs:199`, `ShopListPopup.cs:388`, `Game.cs:311`)
- 마일리지를 시즌 정의로 옮기는 것 (현재 시즌마다 바뀌지 않는다 — 상품에 고정으로 둔다)
- 과거 시즌 상품 83개 정리 (과거 영수증이 참조한다 — 그대로 둔다)

## 3. 설계

**상품은 영구히 하나로 두고, "이번 달에 뭘 주는지"는 IAP 에 저장하지 않는다.**

- 스토어에 시즌 번호 없는 SKU 를 **패스당 1개, 총 3개** 등록하고 그 뒤로 건드리지 않는다
- IAP DB 에도 그 상품 행 3개만 영구히 둔다. `NoShow` 연결도 영구
- 그 상품이 지금 무엇을 주는지는 **판매 시점과 목록 응답 시점에 season-pass 의 시즌 정의에서 읽는다**

### 왜 복사해두지 않는가

대안(IAP 가 시즌 시작 시 상품 행을 자동 파생)은 같은 데이터를 두 DB 에 두게 되어 생성·갱신·삭제·드리프트 감지 코드를 영구히 안고 가야 한다. 게다가 그 방식이 기대는 `open/close_timestamp` 자동 전환은 **실제로 쓰이지 않고 있어**(§1 실측) 카테고리 연결 자동 교체까지 만들어야 한다.

읽어오는 쪽은 캐시를 쓰지만 캐시는 소유권이 없다 — 만료되면 알아서 원천을 따라가므로 동기화 코드가 필요 없다.

### 구매 경로의 통신은 늘지 않는다

지금도 시즌패스가 팔리면 IAP 가 `POST {season_pass_host}/api/user/upgrade` 를 호출해 프리미엄을 활성화한다. 지금은 IAP 가 **자기 DB 에서 꺼낸 구성품을 `reward_list` 로 실어서** 보낸다.

이 설계에서는 그 `reward_list` 를 **뺀다.** 구성품이 season-pass 에 있으니 season-pass 가 자기 시즌 정의에서 꺼내 쓴다. 호출 횟수는 1회 그대로고, 페이로드와 IAP 코드가 줄어든다.

새로 생기는 통신은 `GET /api/product` 응답을 만들 때의 조회 하나뿐이고, 여기엔 캐시가 붙는다.

## 4. 핵심 설계 결정

### 4.1 시즌은 "결제 시각" 기준으로 고정한다

지금은 SKU 에 시즌 번호가 박혀 있어서, 시즌 33 결제가 시즌 34 에 처리되면 season-pass 가 `get_pass(season_index=33, validate_current=True)` → `None` → `SeasonNotFound` 로 거부한다. 시즌 번호를 빼면 이 방어가 사라지므로, `/api/user/upgrade` 에 `purchased_at` 을 실어 보내고 season-pass 가 **그 시각에 유효했던 시즌**을 고르게 한다.

**보호 대상은 "재시도"가 아니라 "지연 제출"이다.** 이 문서의 이전 판은 재시도 경로가 시즌패스 분기를 다시 탄다고 적었는데 **틀렸다.** `/api/purchase/retry` 는 `request_product` 로 위임하고, 그 함수의 자체 중복검사가 기존 영수증을 그대로 돌려준다 — 거절하는 건 `INVALID` 뿐이고 시즌패스는 `status=VALID, tx_status=NULL` 이라 `return prev_receipt` 로 끝난다(`purchase.py` 의 중복검사 게이트). 회귀 테스트가 이를 고정하고 있다(`tests/api/test_purchase_retry.py` — "위임은 기존 영수증을 되돌려줄 뿐 재지급을 트리거하지 않는다", `scalar_calls == 2`).

실제로 위험한 경로는 **order_id 가 처음 제출되는 시점이 결제 시점보다 늦은 시즌인 경우**다. 클라가 오프라인이거나 앱을 껐다 켜서 다음 회수에 올리면 기존 영수증이 없으므로 전체 처리가 돌고 시즌패스 분기에 도달한다. 이때 시즌 번호가 없으면 **지난 시즌 결제가 이번 시즌 패스로 들어간다.**

**어느 시각을 쓸지 못박아야 한다.** `receipt.purchased_at` 의 출처가 스토어마다 다르다 — Google 은 `purchaseTime`, **Apple 은 `originalPurchaseDate`**, WEB 은 Stripe `purchaseDate`, `/free`·`/mileage` 는 `datetime.now()`. Apple 의 `originalPurchaseDate` 를 그대로 쓰면 복원(restore) 트랜잭션이 지난 시즌으로 떨어진다. 구현 시 Apple 경로만 별도 필드를 쓸지 결정할 것.

### 4.2 구매 제한을 시즌 범위로 좁힌다

세 상품 모두 `account_limit = 3` 이다. 고정 1행이 되면 카운트 창이 없으므로 **평생 3회**가 되어 4번째 시즌부터 영영 못 산다. `get_purchase_count()` 에 기간 창 인자를 추가해 `daily`/`weekly`/`account` 와 같은 축으로 `season` 을 넣는다. 창은 그 결제 시각이 속한 시즌의 `start_timestamp`~`end_timestamp`.

**단, `account_limit=3` 은 지금까지 한 번도 구속한 적이 없다.** (이 문서의 이전 판은 "사실상 시즌당 3회"라고 적었는데 틀렸다.) 같은 시즌 두 번째 구매는 IAP 한도에 닿기 전에 season-pass 가 먼저 거절한다 — 현재 SKU 접미사 `premium` 은 `is_premium` 과 `is_premium_plus` 를 **둘 다** 세우므로 두 번째 구매는 항상 "already purchased same or inclusive product" 에 걸린다. 즉 **실효 한도는 시즌당 1회**다.

그러니 시즌 창을 넣을 때 "3" 을 그대로 가져갈지 다시 정해야 한다 — 그대로 두면 여전히 죽은 손잡이다.

관련해서 같이 정할 것이 둘 있다.

- **`InvalidUpgradeRequestError` 가 season-pass 예외 매핑에 없어 500 으로 나간다.** 중복 구매는 유저 입력 오류지 서버 오류가 아니다. 매핑에 추가할 것
- **실패한 구매가 한도를 먹는다.** season-pass 가 non-200 이면 IAP 는 `raise_error` 로 끝내는데, `receipt.status` 는 이미 `VALID` 로 세팅된 채 커밋된다. `get_purchase_count` 는 VALID 를 세므로 중복 시도나 season-pass 장애가 한도를 소모한다

무기한 시즌(WorldClearPass, `end=None`)은 창이 `2024-12-01~∞` 가 되어 현재와 동일하게 동작한다 — 동작 변화 없음.

### 4.3 표시 = 지급 불변식을 지킨다

`/api/product` 응답은 THOR 행성에서 아이템·FAV·마일리지를 2배로 부풀려 표시하고, 지급도 구매 경로에서 2배로 나간다. 이 저장소는 이 불변식을 여러 주석에서 명시적으로 지키고 있다(복권 티켓·가챠 풀은 표시만 부풀리면 안 되므로 2배 대상에서 제외).

**배수는 IAP 가 결정하고 season-pass 가 적용한다.** 구성품을 안 보내므로 IAP 에는 곱할 대상이 없다 — `/api/user/upgrade` 에 `reward_multiplier` 를 숫자로 넘기고 season-pass 가 자기 시즌 정의에 곱한다. season-pass 의 `reward_coef` 하드코딩 1 은 이 값으로 대체된다.

⚠️ **대가를 분명히 하자.** 지금은 표시 2배와 지급 2배가 둘 다 IAP 안에 있어 한 파일만 보면 불변식을 확인할 수 있다. 이 설계 후에는 **표시는 IAP, 지급은 season-pass** 로 갈라진다. 두 곳이 같은 배수를 쓰는지 감시하는 비용이 새로 생기므로, 배수 계산을 한 곳(공유 상수/함수)에 두고 양쪽이 그것만 참조하게 할 것.

### 4.4 캐시

구성품은 한 달에 한 번, 매월 1일 09:00 KST 에만 바뀐다. `(pass_type, season_pass_id)` 키로 캐싱하면 시즌당 조회 1회면 된다.

⚠️ **B5 가 건드리는 `GET /api/product` 에는 캐시가 아예 없다.** 같은 파일의 `@cache(expire=3600)` 은 `/api/product/all` 에 붙어 있고, 그나마 fastapi-cache 기본 key_builder 가 요청마다 새로 생기는 `sess` 를 키에 넣어 매번 MISS 다(코드 주석에 실측 기록 있음). 즉 기존 캐시를 고쳐 쓰는 게 아니라 **새로 만드는** 것이다.

조회 실패 시 **만료된 값을 계속 쓴다.** 최악의 경우도 "시즌 경계에서 잠깐 지난 달 구성품이 표시됨"이고, 지급은 구매 시점에 season-pass 가 결정하므로 틀린 걸 주지는 않는다.

### 4.5 WorldClearPass 도 편입한다

시즌이 돌지 않아 무인화 이득은 0 이지만, 빼면 "구성품을 season-pass 에서 읽는 패스"와 "IAP DB 에서 읽는 패스"라는 분기가 §5 의 네 지점에 영구히 남는다. 편입 비용은 스토어 SKU 1개 등록과 구성품 1회 복사뿐이다.

무기한 시즌은 `get_pass` 가 이미 "시작만 있고 끝 없는 시즌" 케이스로 처리한다.

## 5. 변경 목록

### A. NineChronicles.SeasonPass

| # | 작업 |
|---|---|
| A1 | `SeasonPass` 에 `purchase_reward_list` JSON 컬럼 추가 + Alembic 마이그레이션 |
| A2 | 시즌 CRUD API·스키마에 필드 추가 (`POST/PUT /api/admin/season-passes`). ⚠️ `CreateSeasonPassSchema`·`SeasonPassDetailSchema` 가 **두 곳에 중복 정의**돼 있다 — 라우트가 실제로 쓰는 건 `apps/api/app/api/admin.py` 안의 것이고 `schemas/season_pass.py` 쪽이 아니다 |
| A3 | 신규 서버간 API `GET /api/season-pass/purchase-reward?pass_type=&at=` — 주어진 시각에 유효한 시즌의 구성품 반환. 인증은 `/api/user/upgrade` 와 같은 `verify_token` 재사용 (새 라우터 모듈은 만들지 않는다). **표시 경로 전용** — 지급은 A4 로 season-pass 가 스스로 해결하므로 이 API 를 타지 않는다 |
| A4 | `UpgradeRequestSchema` — `season_index` 를 `int \| None = None` 으로, `purchased_at` 추가. `reward_list` 미전달 시 시즌 정의에서 꺼내 쓰고 `reward_multiplier` 를 곱한다 |

`purchase_reward_list` 형식:

```json
{
  "premium":      [{"ticker": "Item_NT_600201", "amount": 2000, "decimal_places": 0}],
  "premium_plus": [{"ticker": "FAV__CRYSTAL", "amount": 5000, "decimal_places": 18}],
  "premium_all":  []
}
```

- 키는 상품 종류. 클라의 `PassPremiumType`(`Premium`/`Premiumplus`/`PremiumAll`)과 1:1
- `premium_all` 이 비면 `premium + premium_plus` 합산으로 해석한다
- 기존 `reward_list`(레벨별 보상)와 **의미가 다르므로 별도 컬럼**이다

**티커 변환 계층은 (패스 상품에 한해) 필요 없다.** season-pass 의 `reward_list` 와 IAP 의 `fungible_item_id` 가 같은 온체인 표기(`Item_NT_600201`, `FAV__RUNESTONE_HP`)를 쓴다. 클라 아이콘용 `sheet_item_id` 는 `Item_NT_` 뒤 숫자라 파생 가능하고, season-pass 에 이미 같은 파생식이 있다(`ticker.split("_")[-1]` / `split("__")[-1]`).

⚠️ 단, `fungible_item_id` 에는 **raw hex(64자) 형태도 담긴다**(상품 스키마 테스트가 Golden Dust 를 양쪽으로 파라미터화한다). 파생식은 그 형태에 적용되지 않는다. 패스 상품은 `Item_NT_` 만 쓰는 것으로 보이지만, 주입 시 접두어를 확인하고 아니면 실패시킬 것.

Alembic 은 `cd apps/shared && alembic revision --autogenerate` (`apps/shared/alembic.ini` 의 `script_location = tool/migrations` → 리비전은 `apps/shared/tool/migrations/versions/`).

### B. NineChronicles.IAP

| # | 작업 |
|---|---|
| B1 | SKU→상품 조회를 고정 SKU 1행 기준으로 정리 — `purchase.py` 의 google/onestore·apple·`/free`·`/mileage` 경로와 `redeem.py` |
| B2 | SKU 문자열에서 시즌 숫자를 뽑는 파싱 제거. pass_type 판정만 남긴다 |
| B3 | 구매 처리 시 `reward_list` 를 싣지 않고 `purchased_at`·`reward_multiplier` 만 보낸다 |
| B4 | 구매 제한에 시즌 범위 축 추가 — 집행 경로(`check_purchase_limit` / `get_purchase_count`) **와 표시 경로(`get_purchase_history`)를 둘 다**. 아래 ⚠️ 참조 |
| B5 | `/api/product` 응답에 현재 시즌 구성품 주입 (+ 캐시). Thor 2배 블록 **앞**에 넣어 표시=지급 불변식 유지. `/api/product/all` 도 같이 — 안 하면 백오피스에서 고정 상품이 구성품 0개로 보인다 |
| B6 | 이행기 별칭 — `NoShow` 응답에 현재 시즌 이름(`COURAGEPASS34Premium`)의 복제 항목을 함께 싣는다 |
| B7 | 복권 티켓 매핑(`ProductVoucherGrant`, 키가 `product_id`)을 고정 상품 id 로 이전. 안 하면 패스 구매자에게 **조용히 티켓이 안 나간다** |

시즌패스 판별은 기존 `is_season_pass_product()` 한 곳을 계속 쓴다(바우처 발급 워커도 같은 집합을 알아야 한다).

⚠️ **B4 — 표시 경로가 집행 경로와 다른 함수다.** 버튼 활성화(`buyable`/`purchase_count`)는 `get_purchase_history()` 가 정하고 이건 `get_purchase_count()` 와 별개다. 집행만 고치면 **4번째 시즌부터 구매는 되는데 버튼이 꺼진다.** 게다가 표시는 `agent_addr` 기준인데 시즌패스 집행은 `avatar_addr` 기준이라 지금도 축이 어긋나 있다 — 어느 쪽으로 맞출지 정할 것.

⚠️ **B5 — FAV 티커가 스키마에서 정규화된다.** 상품 스키마의 `make_ticker_to_name` 이 `FAV__` 접두어를 **벗기고**, 클라는 그 값을 그대로 아이콘 조회에 쓴다(`SpriteHelper.GetFavIcon(ticker)`). season-pass 의 `FAV__CRYSTAL` 을 스키마 검증 **뒤에** 주입하면 접두어가 살아남아 아이콘·툴팁이 깨진다. 주입 지점이 정규화 앞이어야 한다.

⚠️ **B6 — 별칭 이름이 겹치면 전면 장애다.** 클라의 `SeasonPassProduct.Add(product.Name, ...)` 는 `TryAdd` 가 아니라 `Add` 라, 키 중복 시 `ArgumentException` 으로 **IAP 초기화 전체가 죽는다**(바로 위 SKU 딕셔너리는 `TryAdd` 라 안전). `product.name` 에 유니크 제약이 없으므로 NoShow 안에서 이름이 겹치지 않도록 코드로 막을 것.

⚠️ **redeem 경로엔 시즌패스 분기가 없다.** `redeem.py` 는 SKU 로 상품을 찾은 뒤 무조건 `send_product` 로 보낸다 — 온체인 지급만 되고 프리미엄 활성화는 안 된다. SKU 가 영구화되면 리딤 코드가 참조하는 패스 SKU 도 영구 유효해진다(지금은 시즌마다 자연 소멸). 패스 SKU 를 리딤에서 거절할지 정할 것.

### C. NineChronicles (클라)

`SeasonPassPremiumPopup.GetProductKey()` 에서 시즌 인덱스를 빼고, 못 찾으면 기존 키로 폴백한다. `SeasonIndex == 12` 예외 분기도 이때 정리한다.

상품 조회 키가 `product.Name` 이라는 점은 그대로다(`IAPStoreManager` 가 `NoShow` 카테고리 상품을 `SeasonPassProduct[product.Name]` 으로 담는다).

### D. NineChronicles.Backoffice

시즌 편집 화면에 구성품 입력 UI. 티커 + 수량 행 추가/삭제 수준.

그리고 `SeasonPassBalanceService.ExtractCurrenciesFromRewardList` 가 레벨 `reward_list` 의 `normal`/`premium` 키만 판다. 새 `purchase_reward_list`(키 `premium`/`premium_plus`/`premium_all`)를 안 보면 **잔고 점검이 계속 과소집계**된다 — 구매보상 Claim 도 season-pass 지갑이 지급한다.

### E. 스토어 / 운영

- 고정 SKU 3개를 구글·애플·애플K·원스토어에 신규 등록. 가격은 현행과 동일(§6 전제)
- 원스토어는 일괄등록 파일 추출 API 로 내보낸다
- 상품 이미지·L10n 키를 시즌 무관 이름으로 1벌 준비

## 6. 전제

- **시즌패스 가격은 시즌과 무관하게 고정이다.** 시즌패스 팝업은 가격을 IAP DB 가 아니라 스토어에서 받은 값으로 직접 표시하고, 스토어 가격은 SKU 에 귀속되므로 SKU 를 고정하면 가격도 고정된다. 특정 시즌에 할인을 걸어야 하면 별도 프로모션 SKU 를 하나 더 두는 방식으로 푼다
  - ⚠️ **이 전제는 모바일 스토어 한정이다.** WEB(Stripe) 결제는 SKU 가 아니라 `Product.id` 로 상품을 찾고 **가격을 IAP DB 의 `price` 테이블에서 읽어** Stripe 금액 검증에 쓴다. 웹샵/포탈에서 패스를 판다면 가격 원천이 다르므로 고정 상품의 `price` 행도 같이 관리해야 한다
- 마일리지는 시즌마다 바뀌지 않는다 (상품에 고정)

## 7. 이행 계획

1. **season-pass 배포 (A)** — 하위 호환이라 단독 배포 무해
2. **스토어에 고정 SKU 3개 등록** + 심사 통과 대기
3. **IAP 배포 (B)** — 이 시점부터 고정 SKU 구매가 동작. 구버전 클라는 B6 별칭으로 계속 동작
4. **클라 배포 (C)** — 신버전은 고정 이름으로 조회
5. 구버전 비중이 충분히 내려가면 **B6 별칭 제거**

시즌 전환이 매월 1일 09:00 KST 이므로 **시즌 경계 전후로는 배포하지 않는다.**

과거 시즌 상품 83개는 건드리지 않는다. `NoShow` 연결만 새 고정 상품으로 바꾼다.

## 8. 리스크

| 리스크 | 완화 |
|---|---|
| season-pass 장애 시 상품 목록에 구성품이 안 실림 | stale 캐시 허용. 구매 경로는 어차피 지금도 season-pass 의존이라 결합도 증가 없음 |
| 시즌 경계 재시도가 엉뚱한 시즌에 적용 | §4.1 결제 시각 기준 시즌 고정 |
| 고정 1행의 `account_limit` 이 평생 제한이 됨 | §4.2 시즌 범위 제한 |
| 구버전 클라가 상품을 못 찾아 시즌패스 매출 정지 | §5 B6 별칭 + 구버전 비중 확인 후 제거 |
| 시즌별 매출 분리가 `product_id` 로 안 됨 | `purchased_at` 기준 집계. 지급 내역은 season-pass `Claim.reward_list` 에 시점 스냅샷으로 남는다 |
| 실패한 구매가 시즌 한도를 소모 | §4.2 — 실패 시 `receipt.status` 를 VALID 로 두지 않거나, 카운트에서 제외 |
| 복권 티켓이 조용히 미지급 | §5 B7 매핑 이전. 표시/발급 조건이 `voucher_display.py` 와 `voucher_grant_task.py` 에 중복 정의돼 있으니 둘 다 확인 |
| 별칭 이름 충돌로 클라 IAP 초기화 전면 사망 | §5 B6 — `Add` 가 `TryAdd` 가 아니다 |

## 9. 알려진 충돌면

`yang/grant-pointshop-gacha`(PR #493, 22커밋)가 `/api/product` 의 상품 루프에 포인트 카탈로그 필터와 가챠 풀 주입을 추가한다. B5 도 같은 루프에 들어간다. 파일 단위로 겹치지만 로직 충돌은 아니라 기계적으로 풀린다.

## 10. 미결

- 고정 SKU 의 정확한 문자열 (`g_pkg_couragepasspremium` 형태 제안, 스토어 정책 확인 필요)
  - **제약 1**: `google_sku` 안에 `pass` 가 **대소문자 구분으로** 들어 있어야 시즌패스로 판별된다(`SEASON_PASS_SKU_TOKEN`)
  - **제약 2**: 현재 `product.google_sku.split("pass")` 가 `try` **밖**이라 `pass` 가 정확히 1회 등장해야 한다(2회면 ValueError → 500). B2 가 이 줄을 손보더라도 SKU 네이밍 제약으로 남겨둘 것
  - **제약 3**: `pass` 를 유지해야 다른 3곳의 필터가 현 동작을 보존한다 — 월간 매출/토큰 집계 제외(`admin.py`), 자동 재시도 제외(`retryer.py`), invalid-receipt-count 알람 제외(`purchase.py`, 여기만 상수 대신 `"%pass%"` 하드코딩)
- **고정 상품의 `name` 규약** — C 가 `GetProductKey` 에서 시즌을 빼면 조회 키가 `$"{PASSTYPE}{PremiumType}"` = `COURAGEPASSPremium` 이 된다. IAP 고정 상품의 `name` 이 **정확히 그 문자열**이어야 한다
- 스토어 상품 설명 문구 — 시즌 무관하게 정확해야 한다(애플은 설명이 실제와 어긋나면 리젝 사유)
- B6 별칭 제거 시점의 구버전 비중 기준
- §4.1 Apple 의 시즌 판정 기준 시각 (`originalPurchaseDate` 를 그대로 쓸지)
- §4.2 시즌 창을 넣을 때 `account_limit` 을 3 으로 둘지 1 로 맞출지
