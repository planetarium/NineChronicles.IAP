# 원스토어(ONE Store) IAP 서버 연동 — 인수인계

클라이언트(NineChronicles Unity) 쪽 원스토어 결제 연동은 **실기기에서 연결·상품조회까지 확인 완료**했다.
남은 것은 이 저장소(IAP 서버)에서 원스토어 영수증을 검증하고 지급하는 부분이다.

작성 시점: 2026-09-02

---

## 1. 지금 어디까지 됐나

**클라이언트 (확인 완료)**

실기기(SM-F966N, Android 16)에서 ONE Billing Lab 환경으로 확인한 로그:

```
[OneStoreIAP] Initialize. products=54
[OneStoreIAP] QueryProductDetails. count=54
[OneStoreIAP] QueryPurchases
[OneStoreIAP] connected.
[OneStoreIAP] product details fetched. count=1 ids=[g_pkg_worldclearpass1premium]
```

- 원스토어 SDK 연결 성공
- 상품 조회 성공 (개발자센터에 등록한 1개가 잡힘)
- 상품이 개발자센터에서 `등록중` 상태여도 **Sandbox 조회는 된다** (문서에는 "등록중: 테스트 불가"로 되어 있으나 실제로는 조회됨)

**서버 (1~6단계 완료 — 2026-09-02)**

영수증 파싱부터 원스토어 서버 검증·지급 경로·바우처 분류까지 다 들어갔다. 남은 건 **설정 주입**
(개발자센터 값을 시크릿에 넣기)과 **클라이언트 `_store` 정리**, 그리고 아래 "안 한 것" 두 가지다.

`config.onestore_*` 가 비어 있으면 **영수증을 만들기 전에** 거절한다(fail-closed). 시크릿을 안 넣은
배포에 이 이미지를 올려도 기존 결제엔 영향이 없고, 원스토어 결제만 400 으로 끝난다 — 아무것도
저장하지 않으므로 나중에 시크릿을 넣으면 그 구매들이 **다음 회수 때 정상 지급된다**.
(영수증을 먼저 만들면 검증 실패가 `INVALID` 로 굳고, dedup 게이트가 INVALID 를 종단 취급해서
그 구매는 영영 지급되지 않는다. 그래서 순서를 뒤집어 뒀다.)

**지급 뒤 서버가 acknowledge 한다.** 원스토어는 3일 안에 소비/승인되지 않은 구매를 자동 환불하는데,
클라이언트가 consume 을 안 하면(앱을 죽이거나 호출만 막으면) **지급은 나갔는데 결제만 사라진다** —
재현 가능한 무료 경로다. Google 은 `ack_google` 이 검증 직후에 이 창을 닫아 막고 있었다. 원스토어는
검증 직후가 아니라 **배송을 내보낸 뒤**에 친다: 지급이 막힌 건(TIME_LIMIT·구매제한·시즌패스 실패)은
그 앞에서 빠져나가므로 창이 열린 채 남아 자동 환불된다. ack 실패는 `[ONESTORE_ACK_FAILED]` 로만
남기고 진행한다(지급은 이미 나갔다).

**여전히 남는 실패 모드**: 원스토어 서버 장애·타임아웃으로 검증이 두 번 다 실패하면 그 영수증은
INVALID 로 굳는다. 돈은 3일 뒤 자동 환불되지만 **그 구매를 나중에 살려 지급할 수는 없다.**

**안 한 것 (의도적)**

- **`/api/validate` 엔드포인트** — 손대지 않았다. **애초에 앱에 등록되지 않는 라우터다**
  (`app/api/__init__.py` 의 `__all__` 에 없다). 게다가 코드 자체가 깨져 있다: `ReceiptSchema` 에
  `.id` 가 없고, `Receipt` 모델에 `receipt_id`/`receipt_data` 컬럼이 없으며, Google 분기는
  `ReceiptDetailSchema` 를 돌려주는데 다음 줄이 `resp.status_code` 를 읽는다. 그 분기는 무조건
  `valid=True` 를 주는 스텁이라, ONESTORE 를 끼우면 "원스토어 영수증은 언제나 유효" 스텁이 하나
  더 생긴다.
- **원스토어 환불 회수 폴링** — `track_google_refund` 대응물이 없다. `voucher_reconcile_task` 의
  `_GOOGLE_STORES` 에 ONESTORE 를 넣는 건 **틀린 수정**이다(그 목록은 google void 폴링이 준
  order_id 를 받는 자리다). 영수증 `data` 에 purchaseToken 이 남아 있어 재조회는 가능하니,
  원스토어 취소 조회를 도는 별도 폴링을 붙이면 된다.
  그 전까지: 사용자가 환불받아도 **NCG 바우처가 자동 회수되지 않는다**(ONESTORE 를
  `_PROD_STORES` 에 넣었으므로 바우처는 나간다). 수동 경로는 열려 있다 — 운영자가 영수증을
  `REFUNDED_BY_ADMIN` 으로 바꾸면 회수 enroll 은 store 무관이라 그대로 돈다.

**오픈 전에 샌드박스에서 실측할 것 세 가지**

1. **상품 치환이 막히는지** — 서명을 검증하지 않으므로, 싼 상품 토큰에 비싼 `productId` 를 붙이는
   치환을 막는 건 "토큰과 안 맞는 productId 로 조회하면 404" 하나뿐이다. 상품 2개를 등록해
   A 토큰 + B productId 로 조회해 404 를 눈으로 확인하고 결과를 여기 적어라. 깨지면 열려 있는 것이다.
2. **401 강제 재발급이 진짜 새 토큰을 주는지** — 문서가 "600초 미만 남은 경우 신규 발급 가능"
   이라, 잔여가 많은데 401 을 맞으면 같은 죽은 토큰을 돌려받아 재시도가 무의미해질 수 있다.
3. **서버 ack 뒤에도 클라이언트 consume 이 정상인지** — 순서상 ack 가 먼저 나간다.

클라이언트는 **지급이 확정되지 않으면 소비(consume)하지 않도록** 되어 있어서, 실패해도 구매가
원스토어에 남고 다음 회수 때 재시도된다. 다만 **3일 안에 소비/승인하지 않으면 원스토어가 자동 환불**한다.

---

## 2. 클라이언트가 보내는 영수증 — 제일 중요

Google 경로의 Unity IAP 영수증과 **같은 모양으로 맞춰 두었다.** 그래서 서버는 `Store` 분기만 추가하면
기존 Google 파싱 로직을 그대로 재사용할 수 있다.

```json
{
  "Store": "OneStore",
  "TransactionID": "<PurchaseData.PurchaseId>",
  "Payload": "{\"json\":\"<원본 구매 JSON>\",\"signature\":\"<서명>\"}"
}
```

`Payload` 안이 `{json, signature}` 인 것도 Google 과 동일하다. 즉 아래 기존 코드가 그대로 먹는다:

```python
# apps/shared/shared/schemas/receipt.py:133-134
self.payload = json.loads(self.data["Payload"])
self.order = json.loads(self.payload["json"])
```

`order` 안에는 원스토어 구매 데이터가 들어간다 — `productId`, `purchaseToken`, `purchaseTime`,
`orderId`, `purchaseId`, `packageName`, `purchaseState`, `quantity`, `acknowledgeState`, `developerPayload`.

**생성 코드**: `nekoyume/Assets/_Scripts/IAPStore/IAPStoreManager.OneStore.cs` 의 `BuildOneStoreReceipt`

**호출**: 기존 `PurchaseRequestAsync(receipt, agentAddr, avatarAddr, planetId, transactionId, appleOriginalTransactionID)`
를 그대로 쓴다. `appleOriginalTransactionID` 는 빈 문자열, `transactionId` 는 `PurchaseId`.

---

## 3. 고쳐야 할 파일

줄 번호는 2026-09-02 기준.

| 파일 | 줄 | 할 일 |
|---|---|---|
| ~~`apps/shared/shared/enums.py`~~ | ~~40~~ | ✅ `ONESTORE = 4` (샌드박스 쌍둥이는 없다 — 아래 참조) |
| ~~`apps/shared/shared/schemas/receipt.py`~~ | ~~123-127~~ | ✅ `"OneStore"` 추론 분기 |
| ~~`apps/shared/shared/schemas/receipt.py`~~ | ~~132-134~~ | ✅ payload 파싱을 Google 분기와 공유 |
| ~~`apps/shared/tool/migrations/.../a5f3c8d21b7e`~~ | ~~신규~~ | ✅ PG `store` 타입에 라벨 추가 (**적용은 수동**, 아래 참조) |
| ~~`apps/frontend/src/const.js`~~ | ~~23~~ | ✅ `STORE_MAP` 동기화 |
| ~~`apps/shared/shared/validator/common.py`~~ | ~~19~~ | ✅ order_id=`purchaseId`, product_id, purchased_at |
| ~~`apps/shared/shared/validator/onestore.py`~~ | ~~신규~~ | ✅ 토큰 발급·캐시 + 구매 조회 |
| ~~`apps/api/app/config.py`~~ | ~~39~~ | ✅ `onestore_client_id`/`_secret`/`_host` (Optional, 미배선=거절) |
| ~~`apps/api/app/api/purchase.py`~~ | ~~394, 463~~ | ✅ 상품 조회(google_sku 공유) + 검증 분기 |
| ~~`apps/worker/app/tasks/voucher_grant_task.py`~~ | ~~55-56~~ | ✅ `_PROD_STORES`/`_MOBILE_STORES` |
| `apps/api/app/api/validate.py` | 103 | ❌ 안 함 — 죽은 코드(위 "안 한 것") |
| `apps/worker/app/tasks/voucher_reconcile_task.py` | 55 | ❌ 넣으면 안 됨 — 별도 폴링 필요(위 "안 한 것") |
| `NineChronicles` `ApiClients.cs` | 71-76 | 클라이언트 `_store` 를 ONESTORE 로 (아래 참조) |
| `NineChronicles` `InAppPurchaseServiceClient.cs` | 980, 994 | 생성 enum + `StoreTypeConverter.InvalidEnumMapping` 에 `4` |

**3~6단계 진입 전 유의사항** (1~2단계 리뷰에서 나왔다)

1. **`ONESTORE_TEST` 는 안 만든다 — 결정됨(2026-09-02).** 세팅할 주체가 없다: `/purchase/request`
   는 클라이언트가 store 를 안 보내고 봉투 문자열은 두 환경이 같아서 서버가 구분할 수 없다.
   **환경 분리는 배포별 호스트로 한다** — 인터널은 `sbpp.onestore.net`, 메인넷은
   `iap-apis.onestore.net`. client_id/secret 은 앱 단위 한 벌이라 양쪽이 같다(4장). 이렇게 하면
   fail-closed 이기도 하다: 샌드박스 구매는 상용 호스트에 **기록 자체가 없어서** 메인넷에서
   검증이 실패하고 `INVALID` 로 끝난다(= 바우처·지급 안 나간다). Google 이
   `GOOGLE_TEST` 를 따로 둔 건 라이선스 테스터 구매를 **같은** 상용 credential 이 통과시켜 버리기
   때문이고, 원스토어는 그 상황이 아니다.

   되살려야 하는 유일한 조건: **검증환경 구매를 메인넷 IAP 서버로 보내 테스트해야 할 때.** 그땐
   `ONESTORE_TEST = 95` 를 다시 넣고(94 는 REDEEM 이 씀) 클라이언트가 95 를 실어보내게 해야 한다.
2. **클라이언트 `_store` 가 아직 `Store.GOOGLE` 이다.** `ApiClients.cs` 의 `#if UNITY_IOS / #else`
   가 안드로이드를 전부 GOOGLE 로 잡고 `ONESTORE` define 이 여기엔 안 걸린다. `/purchase/retry` ·
   `/free` · `/mileage` 는 이 값을 **명시로** 보내고, 명시 store 가 있으면 서버는 추론을 건너뛴다.
   `/retry` 는 원스토어에서 안 불린다 — 유일한 호출부 `IAPStoreManager.OnlyTxRetryPurchaseAsync`
   가 Unity IAP 의 `Product` 를 받는 Google/Apple 전용 경로다. 반면 **`/free` · `/mileage` 는
   원스토어 빌드에서도 불린다**(`ShopListPopup` → `OnPurchaseFreeAsync`/`OnPurchaseMileageAsync`
   는 스토어 중립). 그래서 4단계 뒤 `Receipt.store` 가 request=ONESTORE / free·mileage=GOOGLE 로
   갈린다. 구매 제한(`get_purchase_count`)은 store 로 안 거르니 영향 없고, 지금 당장의 피해는
   집계·`platform_for_store` 분류가 어긋나는 정도다. 다만 나중에 retry 가 원스토어까지 열리면
   `Receipt.store == GOOGLE AND order_id == <원스토어 orderId>` 로 조회하게 되고, dedup 키
   `(store, order_id)` 에 unique index 가 없다는 것(`purchase.py:309-329`)까지 겹치면 이중 지급으로
   자란다. **원스토어 오픈 전에 정리해 둘 것.**
3. **마이그레이션 적용을 4단계 머지 조건에 넣을 것.** 이미지 기동에 alembic 단계가 없어서 수동이다.
   지금은 `get_order_data` 가 먼저 막아 INSERT 자체가 없으니 잊어도 티가 안 나고, 4단계가 나간 뒤
   **첫 원스토어 영수증**에서 `invalid input value for enum store: "ONESTORE"` 로 터진다 —
   결제가 이미 끝난 구매에서. 메인넷·인터널 양쪽 `alembic current` 확인을 못 박아라.

**본보기로 쓸 파일**

- `apps/shared/shared/validator/google.py` (49줄) — 구조가 가장 가깝다
- `apps/shared/shared/validator/web.py` (98줄) — **외부 결제 API 를 HTTP 로 호출하는 선례**.
  원스토어도 REST 라서 이쪽이 더 참고가 된다

---

## 4. 원스토어 서버 API

**인증정보**: 개발자센터 → 공통정보 → **라이선스 관리**. 이 화면에 `라이선스 키`(ALC용),
`Client ID`, `Client Secret` 이 함께 있다. **환경별로 값이 갈리지 않는다** — 앱 단위 한 벌이고,
화면에 검증/상용 탭이나 별도 발급 버튼이 없다(문서 확인).

**환경을 가르는 건 credential 이 아니라 호스트다.**

| | 호스트 |
|---|---|
| 검증(개발) | `https://sbpp.onestore.net` |
| 상용 | `https://iap-apis.onestore.net` |

두 환경은 구매 기록 자체가 분리돼 있고, 한쪽에서 발급한 AccessToken 은 다른 쪽에 안 먹는다.
그래서 **배포별 설정값은 호스트 하나면 된다** — 인터널은 sbpp, 메인넷은 iap-apis.
(구버전 문서에 보이는 `sbpp.onestore.co.kr` / `apis.onestore.co.kr` 은 v21 이전 표기다.)

**AccessToken 발급**

```
POST {호스트}/v7/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id={...}&client_secret={...}
```

유효기간 3600초. 문서상 "만료됐거나 **600초 미만** 남았을 때" 신규 발급 가능 → 캐시하고
잔여 600초 밑에서 갱신하는 형태로 짜면 된다.

**구매 조회(검증) 엔드포인트**

```
GET {호스트}/v7/apps/{clientId}/purchases/inapp/products/{productId}/{purchaseToken}
Authorization: Bearer <AccessToken>
```

- `clientId` 가 **예전의 `packageName` 자리**다 (2025-03-20 개편). 앱 식별자로 쓴다.

**환경 분리 (중요)**

> "검증(개발) 환경과 상용환경의 AccessToken은 독립적으로 관리되므로, 환경 별로 AccessToken을 분리하여 관리해야 합니다."

처음엔 이 문장을 근거로 `ONESTORE` / `ONESTORE_TEST` 를 나누려 했다. 확인해 보니 이건 **토큰**
이야기지 credential 이야기가 아니었다 — client_id/secret 은 한 벌이고 호스트가 갈릴 뿐이다.
그래서 enum 을 나누지 않고 **배포별 호스트 설정**으로 정리했다(3장 유의사항 1).

**문서**: https://onestore-dev.gitbook.io/dev/tools/billing/v21/serverapi

---

## 5. 이미 결정된 것

**SKU 는 Google Play 것을 그대로 쓴다**

원스토어 In-App ID 규칙(소문자·숫자·`_`·`.`, 소문자나 숫자로 시작, 136자)에 우리 `g_pkg_*` SKU 가
전부 맞는다. 확인된 실제 SKU 예:

```
g_pkg_worldclearpass1premium     ← 개발자센터에 등록해 테스트 중
g_pkg_couragepass33premium
g_pkg_adventurebosspass22premium
g_pkg_travel01
```

**그래서 `product` 테이블에 원스토어 SKU 컬럼을 추가하지 않는다.** 이유:

- `apps/shared/shared/models/product.py:243,248` 의 시즌패스 판별이 `google_sku` 기준
- `apps/shared/shared/models/receipt.py:189` 이 `receipt.product.google_sku` 를 상품 식별자로 사용

SKU 를 따로 두면 이 로직들을 전부 손봐야 한다. 접두사 `g_`(google) 가 이름상 어색하지만 그대로 둔다.

**지급 → 소비 순서**

클라이언트가 이렇게 동작한다. 서버 응답이 이 흐름을 결정한다.

```
구매/회수 수신 → PurchaseRequestAsync → IsDelivered(result) 확인
   → 배송 확정(VALID)이면 ConsumePurchase
   → 아니면 소비하지 않고 남김 → 다음 회수에서 재시도
```

**서버가 같은 영수증에 멱등하게 응답해야 한다.** 재시도가 전제된 설계다. (기존 `purchase.py` 의
`prev_receipt` 처리와 같은 성질)

---

## 6. 아직 안 풀린 것

**배포국가 ↔ 테스트 계정 국가 불일치**

- 앱 배포국가: **미국** (개발자센터 기본정보에서 선택됨)
- 만들어 둔 테스트 계정: **싱가포르**

원스토어는 "로그인한 원스토어 계정의 국가와 개발자센터에서 설정한 결제 환경을 기준으로" 결제 화면을
결정한다. 배포국가에 싱가포르를 추가하거나, 미국 계정을 새로 만들어야 실제 결제 테스트가 된다.

싱가포르는 문서상 **Crypto 지원 국가**로 명시된 곳이라 배포국가 추가가 더 쉬운 길일 수 있다.

**Crypto 적용 여부 신고**

개발자센터 기본정보의 `Crypto 적용 여부` = "블록체인을 활용한 '게임'인 경우 선택". m 빌드에는 지갑·
스테이킹·모험보스가 살아 있으므로 사실은 "예"다. 이걸 예로 하면 **배포국가가 Crypto 지원 국가로
제한**된다. 사업 판단이 필요한 항목이며 서버 작업과는 독립적이다.

---

## 7. 클라이언트 쪽 참고 파일

`~/projects/NineChronicles` 에 있다. 서버 작업 중 영수증 구조를 확인할 때 본다.

| 파일 | 내용 |
|---|---|
| `nekoyume/Assets/_Scripts/IAPStore/IAPStoreManager.OneStore.cs` | 원스토어 결제 경로 전체. `BuildOneStoreReceipt` 가 영수증 봉투를 만든다 |
| `nekoyume/Assets/_Scripts/IAPStore/OneStorePurchaseService.cs` | 원스토어 SDK 래퍼 |
| `nekoyume/Assets/_Scripts/IAPStore/IapProductInfo.cs` | 스토어 중립 상품 DTO |
| `nekoyume/Assets/_Scripts/ApiClient/IAPServiceManager.cs` | `PurchaseRequestAsync` 호출부 |

클라이언트는 `ONESTORE` 스크립팅 디파인 심볼로 갈린다. 기본값은 꺼짐이고, 켠 빌드만 원스토어 경로를
탄다. Unity 메뉴 `Build → OneStore → Enable ONESTORE define`.

---

## 8. 착수 순서 제안

1. ~~`Store` enum 에 `ONESTORE` 추가~~ ✅ (+ PG enum 마이그레이션 `a5f3c8d21b7e`)
2. ~~`receipt.py` 파싱 분기~~ ✅ (테스트: `apps/shared/tests/schemas/test_onestore_receipt.py`)
3. ~~`validator/onestore.py`~~ ✅
4. ~~`common.py` 추출 분기~~ ✅
5. ~~API·워커 분기~~ ✅
6. `client_id` / `client_secret` / `host` 시크릿 주입 — **남음**. 넣을 곳:
   AWS Secrets Manager `9c-internal-v2/external-services/iap-env`(인터널) ·
   `9c-main-v2/external-services/iap-env`(메인넷). 키 이름은 `env_prefix="API_"` 라
   `API_ONESTORE_CLIENT_ID` / `API_ONESTORE_CLIENT_SECRET` / `API_ONESTORE_HOST`.
   인터널 host = `https://sbpp.onestore.net`, 메인넷 = `https://iap-apis.onestore.net`.

1~2 만 해도 클라이언트에서 영수증이 서버에 도달해 파싱되는 것까지 로그로 확인할 수 있다.
