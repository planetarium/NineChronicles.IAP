#!/usr/bin/env python3
"""원스토어 일괄등록 파일 만들기 — CLI.

변환 로직은 전부 `shared/utils/onestore_export.py` 에 있다. 이 스크립트는 그 위의
얇은 껍데기다. 같은 일을 백오피스에서도 할 수 있지만(`POST /api/admin/onestore/export`),
백오피스 없이 돌려볼 경로를 남겨 둔다 — 원스토어가 반려할 때 무엇이 어긋났는지
좁히는 데 이 경로가 실제로 쓸모 있었다.

## 사용법
    cd ~/projects/iap
    export GOOGLE_CREDENTIAL="$(python3 -c 'import json;print(json.load(open("env_config.json"))["google-credential"])')"
    python3 scripts/export_onestore_inapp.py \\
        --onestore-export ~/Downloads/InAppList_20260916180549.xlsx \\
        --out ~/Downloads/9c-onestore-inapp.xlsx

`--onestore-export` 는 개발자센터
[인앱 상품 > 관리형 상품 > 상품 일괄 등록하기 > **내보내기**] 로 받은 파일이다.
배포 국가·국가별 통화·기본가격 통화·기등록 SKU 가 전부 거기서 나온다 — 문서에 없고
Play 와도 다르므로 다른 출처가 없다.
"""

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "shared"))

from shared.utils.onestore_export import (  # noqa: E402
    build_rows,
    fetch_l10n_titles,
    fetch_play_onetime_products,
    parse_onestore_export,
    validate_rows,
    write_workbook,
)

PACKAGE_NAME = "com.planetariumlabs.ninechroniclesmobile"
L10N_CSV_URL = "https://assets.nine-chronicles.com/shop/l10n/product.csv"

#: 서버의 `_on_sale_skus()` 와 같은 뜻 — 다만 CLI 는 DB 에 못 붙으니 공개 API 로 읽는다.
IAP_PRODUCT_URL = ("https://iap-api.9c.gg/api/product"
                   "?agent_addr=0x0000000000000000000000000000000000000001"
                   "&planet_id=0x000000000000")


def fetch_on_sale_skus():
    request = urllib.request.Request(
        IAP_PRODUCT_URL, headers={"x-iap-packagename": PACKAGE_NAME})
    with urllib.request.urlopen(request, timeout=30) as response:
        categories = json.load(response)
    return {p["google_sku"] for c in categories for p in c["product_list"]
            if p["product_type"] == "IAP" and p.get("google_sku")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onestore-export", required=True,
                        help="개발자센터 내보내기 xlsx (배포국·통화의 진실 소스)")
    parser.add_argument("--out", default=os.path.expanduser(
        "~/Downloads/9c-onestore-inapp.xlsx"))
    parser.add_argument("--package-name", default=PACKAGE_NAME)
    parser.add_argument("--credential", default=os.environ.get("GOOGLE_CREDENTIAL"),
                        help="Play 서비스계정 JSON (기본: $GOOGLE_CREDENTIAL)")
    args = parser.parse_args()

    if not args.credential:
        parser.error("GOOGLE_CREDENTIAL 이 필요하다 (docstring 의 사용법 참고)")

    with open(args.onestore_export, "rb") as f:
        catalog = parse_onestore_export(f.read())
    print(f"정답표: 배포국 {len(catalog.currency_by_country)}개 / "
          f"기본가격 통화 {catalog.default_currency} / "
          f"기등록 {len(catalog.registered_skus)}건")

    products = fetch_play_onetime_products(args.credential, args.package_name)
    print(f"Play one-time product {len(products)}건")

    result = build_rows(products, catalog, fetch_on_sale_skus(),
                        fetch_l10n_titles(L10N_CSV_URL))

    violations = validate_rows(result.rows, catalog)
    if violations:
        print("\n자체 검증 실패 — 파일을 만들지 않는다:")
        for v in violations[:20]:
            print(f"  {v}")
        return 1

    with open(args.out, "wb") as f:
        f.write(write_workbook(result.rows))
    print(f"\n{args.out}: {len(result.rows)}행 × {len(catalog.currency_by_country)}개국")

    if result.already_registered:
        print(f"이미 등록되어 제외 {len(result.already_registered)}건: "
              f"{result.already_registered}")
    if result.skipped:
        print(f"그 외 제외 {len(result.skipped)}건:")
        for sku, reason in result.skipped:
            print(f"  {sku:36s} {reason}")
    if result.uncovered_countries:
        print(f"⚠️ Play 에 값이 없어 빠진 국가: {result.uncovered_countries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
