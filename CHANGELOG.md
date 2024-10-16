# CHANGELOG of NineChronicles.IAP

## 0.12.0 (2024-03-27)

### Feature

- Add AvatarLevel table and cache level data
- Add all product list API

### Enhancement

- Move all views into `/views` router
- Optimize Queries

### Bugfix

- Consume valid purchase to avoid unintended refund

## 0.5.2 (2023-11-08)

### Enhancement

- Change GQL scheme from `exceptionName` to `exceptionNames` to apply GQL scheme update

## 0.5.1 (2023-10-23)

### Bugfix

- Remove `productId` comparison with nullable field in google receipt
  validation. ([PR#87](https://github.com/planetarium/NineChronicles.IAP/pull/87))
