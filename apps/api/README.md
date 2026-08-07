# IAP API

로컬 실행:

```bash
uvicorn main:app --reload
```

## 문서
- [Voucher(복권) Admin API](./VOUCHER_ADMIN_API.md) — 상품→티켓 매핑 CRUD, CSV 3쌍 임포트, 설정시점 가드(C1/C3-lite/C5), 발급 워커 흐름. 운영/직접호출은 9c-backoffice `.claude/skills/voucher-ops/`.
