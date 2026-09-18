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

- `NoShow` 가 카테고리 자리에 플래그로 들어앉아 있는 구조 정리 (클라 3곳이 문자열로 물고 있어 별건)
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

지금은 SKU 에 시즌 번호가 박혀 있어서, 시즌 33 결제가 시즌 34 에 재시도되면 season-pass 가 `get_pass(season_index=33, validate_current=True)` → `None` → `SeasonNotFound` 로 거부한다. **안전장치가 SKU 덕에 공짜로 있었다.**

시즌 번호를 빼면 이게 사라져 지연된 재시도가 엉뚱한 시즌에 붙는다. 그래서 `/api/user/upgrade` 에 `purchased_at` 을 실어 보내고, season-pass 가 **그 시각에 유효했던 시즌**을 고른다. 이미 종료된 시즌이면 지금처럼 거부된다.

재시도 경로가 이 분기를 다시 탄다는 점이 중요하다 — 시즌패스 영수증은 `tx_status` 가 영구히 `NULL` 이라(`send_product` 큐를 타지 않는다) `/api/purchase/retry` 의 "이미 처리됨" early return 에 걸리지 않는다.

### 4.2 구매 제한을 시즌 범위로 좁힌다

세 상품 모두 `account_limit = 3` 이다. 지금은 상품이 시즌마다 바뀌니 사실상 "시즌당 3회"지만, **고정 1행이 되는 순간 평생 3회가 되어 4번째 시즌부터 영영 못 산다.**

`get_purchase_count()` 에 기간 창 인자를 추가해 `daily`/`weekly` 와 같은 축으로 `season` 을 넣는다. 창은 그 결제 시각이 속한 시즌의 `start_timestamp`~`end_timestamp`.

무기한 시즌(WorldClearPass, `end=None`)은 창이 `2024-12-01~∞` 가 되어 현재의 평생 제한과 동일하게 동작한다 — 동작 변화 없음.

### 4.3 표시 = 지급 불변식을 지킨다

`/api/product` 응답은 THOR 행성에서 아이템·FAV·마일리지를 2배로 부풀려 표시하고, 지급도 구매 경로에서 2배로 나간다. 이 저장소는 이 불변식을 여러 주석에서 명시적으로 지키고 있다(복권 티켓·가챠 풀은 표시만 부풀리면 안 되므로 2배 대상에서 제외).

**Thor 배수는 IAP 에 남긴다.** 구성품 원천만 옮기고, 구매 행성에 따른 곱셈은 지금처럼 IAP 가 한다. season-pass 쪽 `reward_coef` 는 현재 1로 하드코딩돼 있고 건드리지 않는다. `/api/user/upgrade` 에는 배수를 숫자로만 넘긴다.

### 4.4 캐시

구성품은 한 달에 한 번, 매월 1일 09:00 KST 에만 바뀐다. `(pass_type, season_pass_id)` 키로 캐싱하면 시즌당 조회 1회면 된다.

⚠️ `apps/api/app/api/product.py` 의 기존 `@cache(expire=3600)` 은 **실제로 동작하지 않는다.** fastapi-cache 기본 key_builder 가 요청마다 새로 생기는 `sess` 를 키에 넣어 매번 MISS 다(코드 주석에 실측 기록 있음). 이 캐시는 그 데코레이터에 기대지 말고 별도로 만든다.

조회 실패 시 **만료된 값을 계속 쓴다.** 최악의 경우도 "시즌 경계에서 잠깐 지난 달 구성품이 표시됨"이고, 지급은 구매 시점에 season-pass 가 결정하므로 틀린 걸 주지는 않는다.

### 4.5 WorldClearPass 도 편입한다

시즌이 돌지 않아 무인화 이득은 0 이지만, 빼면 "구성품을 season-pass 에서 읽는 패스"와 "IAP DB 에서 읽는 패스"라는 분기가 §5 의 네 지점에 영구히 남는다. 편입 비용은 스토어 SKU 1개 등록과 구성품 1회 복사뿐이다.

무기한 시즌은 `get_pass` 가 이미 "시작만 있고 끝 없는 시즌" 케이스로 처리한다.

## 5. 변경 목록

### A. NineChronicles.SeasonPass

| # | 작업 |
|---|---|
| A1 | `SeasonPass` 에 `purchase_reward_list` JSON 컬럼 추가 + Alembic 마이그레이션 |
| A2 | 시즌 CRUD API·스키마에 필드 추가 (`POST/PUT /api/admin/season-passes`, `CreateSeasonPassSchema`) |
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

**티커 변환 계층은 필요 없다.** season-pass 의 `reward_list` 와 IAP 의 `fungible_item_id` 가 이미 같은 온체인 표기(`Item_NT_600201`, `FAV__RUNESTONE_HP`)를 쓴다. 클라 아이콘용 `sheet_item_id` 는 `Item_NT_` 뒤 숫자라 파생 가능하다.

Alembic 은 `cd apps/shared && alembic revision --autogenerate` (`apps/shared/alembic.ini` 의 `script_location = tool/migrations` → 리비전은 `apps/shared/tool/migrations/versions/`).

### B. NineChronicles.IAP

| # | 작업 |
|---|---|
| B1 | SKU→상품 조회를 고정 SKU 1행 기준으로 정리 — `purchase.py` 의 google/onestore·apple·`/free`·`/mileage` 경로와 `redeem.py` |
| B2 | SKU 문자열에서 시즌 숫자를 뽑는 파싱 제거. pass_type 판정만 남긴다 |
| B3 | 구매 처리 시 `reward_list` 를 싣지 않고 `purchased_at`·`reward_multiplier` 만 보낸다 |
| B4 | 구매 제한에 시즌 범위 축 추가 (`check_purchase_limit` / `get_purchase_count`) |
| B5 | `/api/product` 응답에 현재 시즌 구성품 주입 (+ 캐시). Thor 2배 블록 **앞**에 넣어 표시=지급 불변식 유지 |
| B6 | 이행기 별칭 — `NoShow` 응답에 현재 시즌 이름(`COURAGEPASS34Premium`)의 복제 항목을 함께 싣는다 |

시즌패스 판별은 기존 `is_season_pass_product()` 한 곳을 계속 쓴다(바우처 발급 워커도 같은 집합을 알아야 한다).

### C. NineChronicles (클라)

`SeasonPassPremiumPopup.GetProductKey()` 에서 시즌 인덱스를 빼고, 못 찾으면 기존 키로 폴백한다. `SeasonIndex == 12` 예외 분기도 이때 정리한다.

상품 조회 키가 `product.Name` 이라는 점은 그대로다(`IAPStoreManager` 가 `NoShow` 카테고리 상품을 `SeasonPassProduct[product.Name]` 으로 담는다).

### D. NineChronicles.Backoffice

시즌 편집 화면에 구성품 입력 UI. 티커 + 수량 행 추가/삭제 수준.

### E. 스토어 / 운영

- 고정 SKU 3개를 구글·애플·애플K·원스토어에 신규 등록. 가격은 현행과 동일(§6 전제)
- 원스토어는 일괄등록 파일 추출 API 로 내보낸다
- 상품 이미지·L10n 키를 시즌 무관 이름으로 1벌 준비

## 6. 전제

- **시즌패스 가격은 시즌과 무관하게 고정이다.** 시즌패스 팝업은 가격을 IAP DB 가 아니라 스토어에서 받은 값으로 직접 표시하고, 스토어 가격은 SKU 에 귀속되므로 SKU 를 고정하면 가격도 고정된다. 특정 시즌에 할인을 걸어야 하면 별도 프로모션 SKU 를 하나 더 두는 방식으로 푼다
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

## 9. 알려진 충돌면

`yang/grant-pointshop-gacha`(PR #493, 22커밋)가 `/api/product` 의 상품 루프에 포인트 카탈로그 필터와 가챠 풀 주입을 추가한다. B5 도 같은 루프에 들어간다. 파일 단위로 겹치지만 로직 충돌은 아니라 기계적으로 풀린다.

## 10. 미결

- 고정 SKU 의 정확한 문자열 (`g_pkg_couragepasspremium` 형태 제안, 스토어 정책 확인 필요)
- 스토어 상품 설명 문구 — 시즌 무관하게 정확해야 한다(애플은 설명이 실제와 어긋나면 리젝 사유)
- B6 별칭 제거 시점의 구버전 비중 기준
