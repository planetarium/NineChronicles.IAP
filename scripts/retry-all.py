#!/usr/bin/env python3

import argparse
import logging
import os
import requests
import json
import sys
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# .env 파일 로드
load_dotenv()

# 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")

# Planet 별 GraphQL 엔드포인트
PLANET_ENDPOINTS = {
    "0x000000000000": "https://odin-rpc-1.nine-chronicles.com/graphql",
    "0x000000000001": "https://heimdall-rpc-1.nine-chronicles.com/graphql",
    "0x100000000000": "https://odin-internal-rpc.nine-chronicles.com/graphql",
    "0x100000000001": "https://heimdall-internal-rpc.nine-chronicles.com/graphql"
}

def get_db_connection():
    """데이터베이스 엔진 및 세션 생성"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL 환경 변수가 설정되지 않았습니다.")
    
    engine = create_engine(DATABASE_URL)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return scoped_session(session_factory)

def get_pending_receipts(session) -> List[Dict]:
    """CREATED, STAGED 또는 INVALID 상태이고 tx가 있는 영수증 중 생성된 지 10분 이상 지난 것들을 nonce 오름차순으로 조회"""
    query = text(
        """
        SELECT id, tx, planet_id, nonce, tx_status, created_at 
        FROM receipt 
        WHERE tx_status IN ('CREATED', 'INVALID') 
        AND tx IS NOT NULL 
        AND created_at < NOW() - INTERVAL '10 minutes'
        ORDER BY nonce ASC
        """
    )
    
    result = []
    for row in session.execute(query):
        result.append({
            "id": row[0],
            "tx": row[1],
            "planet_id": row[2],
            "nonce": row[3],
            "tx_status": row[4],
            "created_at": row[5]
        })
    
    return result

def stage_transaction(planet_id: str, tx: str) -> Optional[str]:
    """GraphQL API로 트랜잭션 제출"""
    endpoint = PLANET_ENDPOINTS.get(planet_id)
    if not endpoint:
        logger.error(f"알 수 없는 planet_id: {planet_id}")
        return None
    
    query = """
    mutation {
      stageTransaction(payload: "%s")
    }
    """ % tx
    
    try:
        response = requests.post(
            endpoint, 
            json={"query": query}
        )
        
        if response.status_code != 200:
            logger.error(f"API 요청 실패: {response.status_code} - {response.text}")
            return None
        
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL 오류: {data['errors']}")
            return None
            
        return data["data"]["stageTransaction"]
    
    except Exception as e:
        logger.error(f"요청 중 오류 발생: {e}")
        return None

def update_receipt_status(session, receipt_id: int, tx_id: str, dry_run: bool = False):
    """영수증 상태 업데이트"""
    if dry_run:
        logger.info(f"[DRY-RUN] receipt_id={receipt_id}의 상태를 STAGED로 업데이트, tx_id={tx_id}")
        return
    
    query = text(
        "UPDATE receipt SET tx_status = 'STAGED', tx_id = :tx_id WHERE id = :receipt_id"
    )
    session.execute(query, {"tx_id": tx_id, "receipt_id": receipt_id})
    session.commit()
    logger.info(f"receipt_id={receipt_id}의 상태를 STAGED로 업데이트, tx_id={tx_id}")

def process_receipts(dry_run: bool = False):
    """보류 중인 영수증 처리"""
    db = get_db_connection()
    
    try:
        receipts = get_pending_receipts(db)
        logger.info(f"처리할 영수증 {len(receipts)}개 발견 (생성된 지 10분 이상 지난 것들만)")
        
        if not receipts:
            logger.info("처리할 영수증이 없습니다.")
            return
            
        created_count = sum(1 for r in receipts if r['tx_status'] == 'CREATED')
        staged_count = sum(1 for r in receipts if r['tx_status'] == 'STAGED')
        invalid_count = sum(1 for r in receipts if r['tx_status'] == 'INVALID')
        logger.info(f"CREATED 상태: {created_count}개, STAGED 상태: {staged_count}개, INVALID 상태: {invalid_count}개")
        
        logger.info(f"nonce 오름차순으로 처리를 시작합니다.")
        
        for receipt in receipts:
            receipt_id = receipt['id']
            tx = receipt['tx']
            planet_id = bytes(receipt['planet_id']).decode()
            tx_status = receipt['tx_status']
            nonce = receipt['nonce']
            created_at = receipt['created_at']
            
            logger.info(f"영수증 {receipt_id} 처리 중 (planet_id: {planet_id}, 현재 상태: {tx_status}, nonce: {nonce}, 생성 시간: {created_at})")
            
            if dry_run:
                logger.info(f"[DRY-RUN] {PLANET_ENDPOINTS.get(planet_id, '알 수 없는 엔드포인트')}로 요청 보낼 예정")
                continue
                
            tx_id = stage_transaction(planet_id, tx)
            
            if tx_id:
                update_receipt_status(db, receipt_id, tx_id, dry_run)
            else:
                logger.error(f"영수증 {receipt_id}에 대한 트랜잭션 스테이징 실패")
                
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser(description="CREATED, STAGED 또는 INVALID 상태의 트랜잭션을 처리하고 상태를 업데이트합니다")
    parser.add_argument("--dry-run", action="store_true", help="변경 사항을 적용하지 않고 실행할 작업 미리보기")
    args = parser.parse_args()
    
    if args.dry_run:
        logger.info("DRY-RUN 모드로 실행 중")
    
    process_receipts(args.dry_run)
    
    if args.dry_run:
        logger.info("DRY-RUN 완료")
    else:
        logger.info("처리 완료")

if __name__ == "__main__":
    main()
