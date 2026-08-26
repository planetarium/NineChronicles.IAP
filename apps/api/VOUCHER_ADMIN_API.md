# Voucher(복권) Admin API — IAP

IAP 결제 상품에 붙는 **복권 티켓 매핑**(`product_voucher_grant`)의 관리자 CRUD와 CSV 일괄 임포트.
상금표(확률/NCG) **정책 자체는 포탈**(`voucher_policy`)이 보유하고, IAP는 "어떤 상품이 어떤 티켓을 몇 개 준다"만 저장한다. 발급 실행은 워커가 포탈 grant로 위임한다.

관련 코드:
- 엔드포인트: `app/api/admin.py`
- 설정시점 검증(순수): `app/voucher_validation.py`
- CSV import: `app/utils/import_utils.py`
- 발급 워커: `../worker/app/tasks/voucher_grant_task.py`
- 운영/직접호출: 백오피스 repo `.claude/skills/voucher-ops/`

## 인증
모든 admin 엔드포인트는 `verify_token` (Bearer JWT):
- 알고리즘 `HS256`, `aud="iap"`, `iat`는 과거, 수명 ≤ 1h (`exp - iat < 1h`), `exp`는 미래.
- 서명 시크릿 = `config.backoffice_jwt_secret` (env `API_BACKOFFICE_JWT_SECRET`). 백오피스가 이 키로 서명해 호출.
- 실패 시 401.

```python
now = datetime.now(tz=timezone.utc)
token = jwt.encode({"iat": now, "exp": now + timedelta(minutes=10), "aud": "iap"},
                   API_BACKOFFICE_JWT_SECRET, algorithm="HS256")
# Authorization: Bearer <token>
```

## 관련 config (env `API_` prefix)
| config | env | 용도 |
|---|---|---|
| `backoffice_jwt_secret` | `API_BACKOFFICE_JWT_SECRET` | admin JWT 검증 |
| `portal_prize_tables_url` | `API_PORTAL_PRIZE_TABLES_URL` | C1 검증용 포탈 **라이브 상금표** read (fail-closed) |
| `voucher_grant_max_ncg_per_grant` | `API_VOUCHER_GRANT_MAX_NCG_PER_GRANT` | C3-lite cap (optional; **prod은 필수**) |

## 엔드포인트

### `GET /api/admin/product-voucher-grants`
매핑 전체(상품명 조인). 백오피스 표시 + C5 `base_updated_at` 획득용.
```json
[{"id":2,"product_id":111,"product_name":"Daily Free Package LV200",
  "ticket_type":"STANDARD","count":2,"active":true,
  "updated_at":"2026-08-05T09:58:45.355670+00:00"}]
```

### `PUT /api/admin/product-voucher-grants`
`(product_id, ticket_type)` upsert.
```json
{"product_id":5, "ticket_type":"PREMIUM", "count":1, "active":true, "base_updated_at":null}
```
- `active=true`일 때만 정책 검증(C1 + C3-lite). **끄는 것/placeholder는 미검증**.
- `active=true` + prod + cap 미설정 → **400**(fail-open 방지).
- `active=true` + **결제 상품이 아닌 상품**(`product.product_type != IAP`) → **400**(C6). 무료 클레임도 VALID+SUCCESS 영수증을 만들어 결제 0원 발급이 되고, MILEAGE 는 그 무료 클레임으로 적립한 마일리지로 사는 상품이라 같은 사슬이다. `active=false` 저장은 허용(placeholder), 켜는 순간 막힌다.
- **C5**: `base_updated_at` 제공 시 현재 행 `updated_at`과 대조(행 잠금 하). 불일치 → **409** "stale — reload before save". 신규인데 base 제공 → 409 "mapping gone".
- 신규 삽입 레이스는 `UNIQUE(product_id, ticket_type)`가 최종 가드.
- 응답 `{"id":.., "action":"created"|"updated"}`.

### `DELETE /api/admin/product-voucher-grants/{grant_id}`
하드 삭제. 응답 `{"deleted":true,"id":..}` / 없으면 404.
> ⚠️ 삭제·`active=false` 모두 **이미 enroll된 in-flight 결제**는 dispatch 시 "no active mapping (retry)"로 PENDING stall될 수 있음(운영 인지 필요). 발급 제외만 원하면 삭제보다 `active=false`.

### `POST /api/admin/products/import`
CSV로 상품 정보 + 바우처 매핑 일괄. body `{"environment":"internal"|"mainnet", "csv_content":"<csv>"}`.
- 바우처 컬럼(아래)에 **실제 값이 있는 행**이 하나라도 있을 때만 포탈 라이브 정책을 fetch(C1). voucher 없는 일반 import은 포탈 미의존.
- prod + voucher 값 있음 + cap 미설정 → 400.
- voucher 값 있음 + 그 행의 `product_type != IAP` → 400(C6). 같은 import 에서 타입을 바꾸는 경우도 포함 — 검사는 **CSV 가 쓰려는 타입** 기준이다. 위반 1행이면 import 전체 롤백. 단 `-`(전체 비활성)과 빈칸은 검사 대상이 아니다 — 잘못 붙은 매핑을 CSV 로 되돌릴 수 있어야 한다.
- 위반 행 하나라도 → **import 전체 롤백**(원자적). 에러엔 상품 컨텍스트 포함.
- 응답 `{"message":..,"processed_count":N,"updated_count":M}`.
> ⚠️ 상품 행 **전체 upsert**다. `path`/`l10n_key`는 코드상 무조건 `"="`로 세팅되고, 빈 CSV 셀은 해당 필드를 null화한다. 기존 상품 필드를 덮을 수 있으니, **매핑만** 바꿀 목적이면 `PUT`을 써라.

#### CSV 바우처 컬럼 — 3쌍 고정 슬롯
`voucher_ticket_type_1..3` / `voucher_count_1..3` (타입·개수 쌍 3개).
| 입력 | 의미 |
|---|---|
| 전 슬롯 빈칸 | **유지**(그 상품 매핑 변경 안 함) |
| `_1`에 `-` 단독 | **전체 비활성**(그 상품 모든 티켓 active=false) |
| 값들 | **REPLACE**: 나열된 티켓만 active, 나열 안 된 기존 티켓 active=false(삭제 아님). count 빈칸=1 |
- `-`를 다른 종류와 섞으면 거부(400). 중복 ticket_type 거부(400). voucher 행은 product id 필수(빈칸이면 신규 autoincrement라 FK 불가 → 거부).

## 설정시점 가드 (`voucher_validation.py`)
- **C6** — 바우처 매핑은 **결제 상품(IAP)만**(얼로우리스트). admin PUT(active=true)·CSV import 양쪽에서 400. 워커도 enroll·dispatch 양쪽에서 같은 조건을 본다(`grantable_product_ids()` / `tickets_for_product`) — enroll 이후 상품유형이 바뀌는 경로까지 덮는 2선 방어. IAP 아닌 상품에 active 매핑이 남아 있으면 매 회차 경고 로그.
- **C1** — `ticket_type`이 포탈 라이브 상금표(`prizeTables`)에 실재(빈 표도 거부). **fail-closed**: url 미설정→503, 도달불가/비200→502, `temporary`(placeholder 정책)→409. → 활성 정책 없는데 매핑 저장해 발급 미스매치 만드는 것 차단.
- **count** — 1 이상 정수.
- **C3-lite** — cap 설정 시 `count × 최대상금(NCG) ≤ cap`. 가격/환율 무관 머니펌프 방어. cap None이면 스킵.

## 발급 흐름 (워커, 참고)
`../worker/app/tasks/voucher_grant_task.py` beat(~2분): 컷오프 이후 결제 enroll → active 매핑 있는 상품에 대해 포탈 grant 호출.
- 포탈 호출: `POST config.portal_grant_url`, `Authorization: Bearer <jwt>` — 이 JWT는 **`portal_iap_jwt_secret`(기존 IAP 키 재사용)**, `iss="iap"`, 수명 1분. (admin의 `voucher-admin` JWT와 다름)
- 응답 분류: 200/기수령/소액=종단 GRANTED · 5xx/401/403/429/408/'voucher disabled'/`body.retryable==true`(**R2**, 예: 409 ERR-TICKET-TYPE-UNKNOWN=정책 전파 지연)=transient(PENDING 재시도, self-heal) · 그 외 4xx=FAILED.

## 클라 노출 (상품 조회 API, PLD-1472)
`GET /api/product` · `GET /api/product/all` 응답의 각 상품에 **`voucher_ticket_list`** 가 실린다 — 게임 샵이 "이 상품을 사면 복권 N장"을 표시하는 용도. `mileage` 와 같은 결.
```json
"voucher_ticket_list": [{"ticket_type": "GOLD", "count": 1}, {"ticket_type": "STANDARD", "count": 2}]
```
- **상금·확률은 싣지 않는다.** IAP 는 발급까지만 알고 상금표는 포탈 소유(기획 소유권 원칙).
- 노출 조건 = `active=true` + `count>0` + 상품유형 `IAP`(C6). 매핑이 없거나 조건에 안 맞으면 `[]` — **구버전 클라(필드를 모름)와 같은 모양**이라 하위호환.
- 정렬 `ticket_type` 오름차순 고정. 구현: [`app/voucher_display.py`](app/voucher_display.py).
- `GET /api/product/all` 은 `@cache(expire=3600)` 선언이 붙어 있으나 **현재 캐시 키에 요청별 세션이 섞여 사실상 미스**라 지연이 없다. 캐시를 살리면 그때 매핑 변경이 최대 1h 늦게 반영되므로 무효화 전략을 함께 정할 것(엔드포인트 주석에 선택지 정리).
- ⚠️ 영수증 조회(`FullReceiptSchema.product`)에도 같은 스키마가 쓰여 `voucher_ticket_list` 가 보이지만 **거긴 항상 `[]`** 다. 매핑 진실은 `GET /api/admin/product-voucher-grants`.

### 롤아웃 순서 (중요)
**표시 킬스위치(`active` 컬럼)와 발급 킬스위치(워커 env)는 서로 다른 스위치다.** 매핑만 켜면 클라는 즉시 광고하는데 워커가 안 주는 구간이 생기고, 그 구간 유료 결제는 나중에 컷오프를 런칭 시각으로 잡는 순간 되돌릴 수 없이 미지급으로 굳는다. 그래서 **켤 때는 워커 먼저, 끌 때는 매핑 먼저.**
1. **(worker)** `WORKER_PORTAL_GRANT_URL` · `WORKER_PORTAL_IAP_JWT_SECRET` · `WORKER_STAGE` 배선
2. **(worker)** `WORKER_VOUCHER_GRANT_CUTOFF` 를 **5번을 실행할 시각 직전으로 정확히** 설정
   > 🔴 enroll 의 시간 하한은 이 값 **하나뿐**이고 **기본값은 `None`(하한 없음)** 이다. 미설정이거나 넉넉히 과거로 잡으면, 5번에서 매핑을 켜는 순간 그 상품의 **과거 전체** VALID+SUCCESS 실스토어 영수증이 enroll 대상이 된다(2분마다 500건씩). 실제 NCG 대량 소급 발급이고 되돌릴 수 없다.
3. **(worker)** `WORKER_VOUCHER_GRANT_ENABLED=true` (기본값 false)
4. **(api)** `API_VOUCHER_GRANT_MAX_NCG_PER_GRANT`(C3-lite cap) — prod 에서 이게 없으면 5번의 `active=true` 요청이 **400** 으로 거부된다
5. 마지막에 매핑 `active=true` (= 이 순간부터 클라에 보이고 발급도 된다)

1~3 은 워커 프로세스, 4 는 API 프로세스 env 라 배포 대상이 다르다.

## 상태코드 요약
| code | 상황 |
|---|---|
| 200 | 정상 |
| 400 | count/파싱/C3-lite/CSV 위반, prod cap 미설정 활성, **C6 비IAP 상품 매핑** |
| 401 | JWT 실패 |
| 404 | product/grant 없음 |
| 409 | C1(unknown ticket_type) / C5(stale) / 정책 temporary |
| 502/503 | 포탈 정책 fetch 실패 / url 미설정 |
