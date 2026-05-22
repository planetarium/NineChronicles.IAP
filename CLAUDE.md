# NineChronicles.IAP

Nine Chronicles 인앱결제(IAP) 백엔드. 스토어 영수증을 검증하고, 결제된 상품을 온체인 `grant_items` 트랜잭션으로 유저에게 지급한다. 마일리지/리딤코드/Web 결제(Stripe)도 함께 처리.

- **배포 도메인:**
  - 운영(mainnet, 9c-main): `iap-api.9c.gg` · 백오피스 `iap-backoffice.9c.gg`
  - 사내(internal, 9c-internal): `iap-internal-api.9c.gg` · 백오피스 `iap-internal-backoffice.9c.gg`
  - 배포 도메인의 진실 소스는 `9c-infra` 레포의 `9c-main/external-services/values.yaml` · `9c-internal/external-services/values.yaml`.

> ⚠️ README.md 는 과거 AWS Lambda/CDK 시절 구조(`common/`, `iap/`, `worker/`) 기준이라 현재와 다르다. **이 문서가 현재 구조 기준의 진입점.**

## 스택

- Python 3.11 · FastAPI · SQLAlchemy 2.0 · Alembic
- Celery (큐: `product_queue`) · 브로커: RabbitMQ · 결과 백엔드: Redis
- PostgreSQL
- Frontend: SvelteKit + Vite + Tailwind (백오피스/영수증 조회)
- AWS KMS (TX 서명), S3 / Cloudflare R2 (상품 이미지)
- 헤드리스 GraphQL (TX staging, 잔액/논스 조회)

## 구조 (`apps/` 모노레포)

| 컴포넌트 | 진입점 | 역할 |
|---|---|---|
| [apps/api](apps/api) | FastAPI | 영수증 검증, 상품/가격 조회, 구매 요청, 관리자 API. `Dockerfile.Api` |
| [apps/worker](apps/worker) | Celery worker | `grant_items` TX 작성/서명/스테이징, nonce 관리, Tx 상태 모니터링, 환불 추적. `Dockerfile.Worker` |
| [apps/shared](apps/shared) | 라이브러리 | DB 모델, enum(PlanetID/Store/PackageName), 스토어 검증기, lib9c 헬퍼, GraphQL/KMS 유틸 |
| [apps/frontend](apps/frontend) | SvelteKit | 영수증 조회 백오피스 UI |

로컬은 `docker-compose.yml` 로 postgres + rabbitmq + redis + api + worker 한 번에 띄움.

## 핵심 DB 모델 ([apps/shared/shared/models/](apps/shared/shared/models/))

- `Product` ([product.py](apps/shared/shared/models/product.py)) — 상품 마스터. `apple_sku` / `apple_sku_k` / `google_sku`, 일/주/계정 구매 제한, 오픈/마감 시각, 마일리지 보상, 카테고리·가격 관계. `fav_list` (FungibleAssetProduct), `fungible_item_list` (FungibleItemProduct) 로 지급 내용 정의
- `Receipt` ([receipt.py](apps/shared/shared/models/receipt.py)) — 영수증/주문. `store` (Apple/Google/Web/Redeem ±Test), `status` (INIT → VALIDATION_REQUEST → VALID), `tx_status` (CREATED → STAGED → SUCCESS), `planet_id`, `agent_addr`/`avatar_addr`, `mileage_change`. `get_user_receipts_by_month` 헬퍼
- `Mileage` ([mileage.py](apps/shared/shared/models/mileage.py)) — 유저 누적 마일리지
- `Voucher` ([voucher.py](apps/shared/shared/models/voucher.py)) — 리딤 코드
- `Category`, `Price` — 상품 분류/가격 (스토어·통화별)
- `FungibleAssetProduct` — 상품에 묶인 FAV (NCG, CRYSTAL, SOULSTONE 등). `ticker` 컬럼에 온체인 포맷(`FAV__CRYSTAL` 등)을 그대로 저장 (런타임 변환 아님)
- `FungibleItemProduct` — 상품에 묶인 아이템. `fungible_item_id` 컬럼에 `Item_NT_{...}` 형태를 그대로 저장. `sheet_item_id`는 별도 메타데이터

## 주요 API ([apps/api/app/api/](apps/api/app/api/))

### Product ([product.py](apps/api/app/api/product.py))
- `GET /api/product` — 카테고리별 상품. `planet_id`, `agent_addr` 기준 구매 제한 적용
- `GET /api/product/all` — 전체 상품 (캐시 1h)

### Purchase ([purchase.py](apps/api/app/api/purchase.py))
- `POST /api/purchase/request` — 결제 영수증 받아 `Receipt` 생성 + 큐 발행
- `POST /api/purchase/free` — 무료 상품 지급
- `POST /api/purchase/retry` — 실패 구매 재시도
- `GET /api/purchase/log` — 유저 구매 이력
- `GET /api/purchase/invalid-receipt-count` — 검증 실패 영수증 수

### Validate ([validate.py](apps/api/app/api/validate.py))
- `POST /api/validate` — 영수증 검증 (Apple/Google/Stripe 라우팅)

### Redeem ([redeem.py](apps/api/app/api/redeem.py))
- `POST /api/redeem-codes/redeem` — 리딤 코드 사용

### Mileage / L10n
- 마일리지 잔액·사용, 다국어 문자열 조회

### Admin ([admin.py](apps/api/app/api/admin.py))
> 상품/가격/재화 등록은 운영자가 `9C_IAP_list` 시트를 작성 → **NineChronicles.Backoffice** "IAP 상품 임포트" UI가 아래 import 엔드포인트들을 호출하는 흐름.
- `GET /api/admin/products` · `POST /api/admin/products/import` — 상품 일괄 CSV 임포트
- `POST /api/admin/products/categories/import` · `/api/admin/products/fungible-assets/import` · `/api/admin/products/fungible-items/import`
- `POST /api/admin/prices/import`
- `GET /api/admin/receipts` — 영수증 검색
- `GET /api/admin/user-receipts/courage-pass` — 용기 패스 구매 여부 확인 (SeasonPass 연계)
- `GET /api/admin/user-receipts/non-pass-amount`
- `GET /api/admin/stats/product-sales?year=YYYY&month=MM` — **월간 토큰 판매량 집계** (UTC 기준, mainnet 행성만). 응답: `{ planets: { odin: [TokenSales], heimdall: [...] } }`. 최근에 추가됨 (PR #466)
- `POST /api/admin/r2/product` · `POST /api/admin/s3/product` — 상품 이미지 업로드

### 기타
- `GET /api/balance/{planet}` — IAP Garage(지급용 지갑) 재고 (GraphQL 조회)

## 스토어 영수증 검증 ([apps/shared/shared/validator/](apps/shared/shared/validator/))

- [apple.py](apps/shared/shared/validator/apple.py) — App Store Server API (StoreKit 2), JWT 인증
- [google.py](apps/shared/shared/validator/google.py) — Play Developer API
- [web.py](apps/shared/shared/validator/web.py) — Stripe `payment_intent` 검증 + 가격 일치 확인

`Store` enum에 `*_TEST` 변종이 있어서 sandbox/실제 분기.

## Worker 처리 흐름 ([apps/worker/app/tasks/](apps/worker/app/tasks/))

대표: `send_product` (`send_product_task.py`)

1. `Receipt.product_id` → `Product` 로드 (`selectinload(fav_list, fungible_item_list)`)
2. lib9c 모델로 `FungibleAssetValue` / `FungibleItemValue` 변환
3. `grant_items` 액션 + unsigned TX 작성
4. **Nonce 결정**: DB `max(nonce)` vs 헤드리스 `next_nonce` 비교해서 동시성 처리
5. KMS 키로 서명
6. 헤드리스 GraphQL로 TX staging
7. `Receipt.tx_id` · `tx_status=STAGED` 저장

부가 태스크:
- `status_monitor` / `tracker` — 스테이징된 TX 상태 추적 (`STAGED → SUCCESS / FAILURE`)
- `track_google_refund` — Google Play 환불 폴링 후 상태 변경
- `retryer` — 실패 TX 재시도

## 멀티플래닛 ([apps/shared/shared/enums.py](apps/shared/shared/enums.py))

`PlanetID`: `ODIN`/`HEIMDALL`(mainnet) + `IDUN`/`THOR`(internal/test) + 각 `_INTERNAL`. planet hex → 헤드리스 GraphQL URL 매핑은 [apps/api/app/config.py](apps/api/app/config.py)의 `gql_url_map`.

`PackageName`: `NINE_CHRONICLES_M`(Android), `NINE_CHRONICLES_K`(KR 변형 — `apple_sku_k` 사용), `NINE_CHRONICLES_WEB`.

## 자주 쓰는 작업

| 목표 | 어디 보면 됨 |
|---|---|
| "이번 달 IAP 매출/토큰 지급량" | `GET /api/admin/stats/product-sales?year=&month=` |
| 특정 유저 구매 내역 | `GET /api/admin/receipts?...` 또는 `Receipt.get_user_receipts_by_month` |
| 신규 상품 추가 | 관리자 CSV 임포트 + 가격 임포트, 또는 직접 DB |
| TX 안 나가는 결제 디버깅 | `Receipt.tx_status` · 헤드리스 staging 결과 · `apps/worker/app/tasks/send_product_task.py` 로그 |
| 환불 처리 | Google: `track_google_refund` 워커가 자동. 수동은 `Receipt.status=REFUNDED_BY_ADMIN` |
| 새 스토어 추가 | `Store` enum + `apps/shared/shared/validator/`에 검증기 추가 + `validate.py` 라우팅 |

## 외부 의존성

- **헤드리스 GraphQL** — TX staging, nonce/잔액 조회 ([apps/shared/shared/utils/](apps/shared/shared/utils/))
- **lib9c** — `grant_items` 액션·`FungibleAssetValue` 등 도메인 모델 ([apps/shared/shared/lib9c/](apps/shared/shared/lib9c/))
- **Apple App Store Server API** · **Google Play Developer API** · **Stripe**
- **AWS KMS** — IAP 지갑 TX 서명
- **AWS S3** · **Cloudflare R2** — 상품 이미지 호스팅
- **RabbitMQ** · **Redis** · **PostgreSQL**

## 마이그레이션

`apps/shared/tool/migrations/versions/` — Alembic. `alembic upgrade head`는 `apps/shared`에서 실행. 마이그레이션 추가 시 `Receipt`·`Product` 같은 핵심 모델은 무중단 호환을 항상 고려 (라이브 결제 흐름이 바로 영향받음).
