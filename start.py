#!/usr/bin/env python3
"""
Google Maps 리뷰 스크래퍼 - CSV 파일 일괄 처리
========================================

CSV 파일에서 레스토랑 정보를 읽어 구글 맵스 리뷰를 일괄 스크랩합니다.

source venv/bin/activate
python start.py --csv treat/restaurants_001.csv --base-dir treat/restaurants_001 --headless
python start.py --csv treat/restaurants_006.csv --base-dir treat/restaurants_006 --headless
"""
#!/usr/bin/env python3
"""
Google Maps 리뷰 스크래퍼 - CSV 파일 일괄 처리
========================================

CSV 파일에서 레스토랑 정보를 읽어 구글 맵스 리뷰를 일괄 스크랩합니다.

source venv/bin/activate
python start.py --csv treat/restaurants_001.csv --base-dir treat/restaurants_001 --headless --skip-exists
python start.py --csv treat/restaurants_006.csv --base-dir treat/restaurants_006 --headless --skip-exists
"""

import os
import logging
import time
import argparse
import pandas as pd
from pathlib import Path
import yaml
import json

from modules.config import load_config
from modules.scraper import GoogleReviewsScraper

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
log = logging.getLogger("start")

def parse_args():
    """명령줄 인수 파싱"""
    parser = argparse.ArgumentParser(description="CSV 파일에서 레스토랑 정보를 불러와 Google Maps 리뷰 스크랩")
    
    parser.add_argument("--csv", type=str, required=True,
                        help="레스토랑 정보가 담긴 CSV 파일 경로 (필수)")
    
    parser.add_argument("--base-dir", type=str, default="restaurant_data",
                        help="데이터 저장 기본 디렉토리 (기본값: restaurant_data)")
    
    parser.add_argument("--headless", action="store_true", 
                        help="헤드리스 모드로 브라우저 실행 (기본값: False)")
    
    parser.add_argument("--sort-by", type=str, choices=["newest", "highest", "lowest", "relevance"],
                        default="newest", help="리뷰 정렬 방식 (기본값: newest)")
    
    parser.add_argument("--limit", type=int, default=0,
                        help="처리할 최대 레스토랑 수 (기본값: 0, 모두 처리)")
    
    parser.add_argument("--download-images", action="store_true", default=True,
                        help="리뷰 이미지 다운로드 여부 (기본값: True)")
    
    parser.add_argument("--skip-exists", action="store_true", 
                        help="이미 처리한 레스토랑 건너뛰기 (폴더 존재 + reviews.json 존재 + 내용이 빈 리스트가 아닌 경우)")
    
    return parser.parse_args()

def should_skip_restaurant(base_dir):
    """
    레스토랑을 건너뛸지 판단하는 함수
    조건: 폴더 존재 + reviews.json 존재 + 파일 크기 > 10바이트 + 내용이 빈 리스트가 아님
    """
    try:
        # 1. 폴더가 존재하는지 확인
        if not base_dir.exists():
            return False, "폴더가 존재하지 않음"
        
        # 2. reviews.json 파일이 존재하는지 확인
        json_path = base_dir / "reviews.json"
        if not json_path.exists():
            return False, "reviews.json 파일이 존재하지 않음"
        
        # 3. 파일 크기 확인 (최소 10바이트 이상)
        if json_path.stat().st_size <= 10:
            return False, f"reviews.json 파일이 너무 작음 ({json_path.stat().st_size} 바이트)"
        
        # 4. 파일 내용 확인 (빈 리스트가 아닌지)
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
            # JSON 파싱 시도
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    if len(data) == 0:
                        return False, "reviews.json이 빈 리스트임"
                    else:
                        return True, f"유효한 리뷰 데이터 {len(data)}개 존재"
                else:
                    # 리스트가 아닌 경우도 데이터가 있다고 판단
                    return True, "유효한 데이터 존재 (리스트 형태 아님)"
            except json.JSONDecodeError as e:
                return False, f"JSON 파싱 오류: {e}"
                
        except Exception as e:
            return False, f"파일 읽기 오류: {e}"
            
    except Exception as e:
        return False, f"검사 중 오류: {e}"

def load_restaurants_from_csv(csv_path):
    """CSV 파일에서 레스토랑 정보 불러오기"""
    try:
        # 다양한 인코딩 시도
        encodings = ['utf-8', 'cp949', 'euc-kr', 'latin1']
        df = None
        
        for encoding in encodings:
            try:
                df = pd.read_csv(csv_path, encoding=encoding)
                log.info(f"CSV 파일 로드 성공 (인코딩: {encoding})")
                break
            except UnicodeDecodeError:
                continue
        
        if df is None:
            log.error("CSV 파일을 로드할 수 없습니다. 지원되지 않는 인코딩입니다.")
            return []
        
        # 필요한 컬럼이 있는지 확인
        required_columns = ['displayName']
        recommended_columns = ['googleMapsUri', 'placeUri', 'id']
        
        missing_required = [col for col in required_columns if col not in df.columns]
        if missing_required:
            log.error(f"CSV 파일에 필수 컬럼이 없습니다: {missing_required}")
            return []
        
        missing_recommended = [col for col in recommended_columns if col not in df.columns]
        if missing_recommended:
            log.warning(f"CSV 파일에 권장 컬럼이 없습니다: {missing_recommended}")
        
        # 데이터프레임을 딕셔너리 리스트로 변환
        restaurants = df.fillna('').to_dict('records')
        
        log.info(f"CSV 파일에서 {len(restaurants)}개의 레스토랑 정보를 불러왔습니다.")
        return restaurants
    except Exception as e:
        log.error(f"CSV 파일 로드 중 오류 발생: {e}")
        return []

def create_config_for_restaurant(restaurant, args):
    """각 레스토랑에 대한 설정 생성"""
    # 기본 설정
    config = {
        "headless": args.headless,
        "sort_by": args.sort_by,
        "download_images": args.download_images,
        "backup_to_json": True,
        "use_mongodb": False,
        "overwrite_existing": False,
        "stop_on_match": False,
        "convert_dates": True,
        "download_threads": 4,
        "store_local_paths": True,
        "replace_urls": False,
        "preserve_original_urls": True,
    }
    
    # 폴더명으로 사용할 displayName 가져오기
    folder_name = restaurant.get('displayName', '')
    if not folder_name:
        log.warning(f"displayName이 없습니다. 레스토랑 정보: {restaurant}")
        folder_name = f"restaurant_{restaurant.get('id', 'unknown')}"
    
    # 특수문자 제거 및 폴더명 정리
    folder_name = "".join(c if c.isalnum() or c in [' ', '_', '-'] else '_' for c in folder_name)
    
    # 구글맵스 URL 가져오기 (googleMapsUri 또는 placeUri)
    url = restaurant.get('googleMapsUri') or restaurant.get('placeUri')
    
    # URL이 없는 경우 검색 URL 생성 시도
    if not url:
        name = restaurant.get('name', '')
        address = restaurant.get('formattedAddress', '') or restaurant.get('shortFormattedAddress', '')
        if name and address:
            search_query = f"{name} {address}".replace(' ', '+')
            url = f"https://www.google.com/maps/search/{search_query}"
            log.warning(f"URL이 없어 검색 URL을 생성했습니다: {url}")
        else:
            log.error(f"레스토랑 URL을 생성할 수 없습니다: {restaurant}")
            return None, None, None
    
    # /data=!4m4!3m3!1s0... 부분 추가 (리뷰 페이지로 이동)
    if "data=" not in url and "!9m1!1b1" not in url and "place" in url:
        place_id = restaurant.get('id', '')
        if place_id and place_id.strip() != "":
            # URL에 리뷰 파라미터 추가
            if url.endswith('/'):
                url = f"{url}data=!4m4!3m3!1s{place_id}!9m1!1b1"
            else:
                url = f"{url}/data=!4m4!3m3!1s{place_id}!9m1!1b1"
            log.info(f"리뷰 URL로 변환: {url}")
    
    # 기본 폴더 경로 생성
    base_dir = Path(args.base_dir) / folder_name
    image_dir = base_dir / "review_images"
    
    # 설정 업데이트
    config.update({
        "url": url,
        "json_path": str(base_dir / "reviews.json"),
        "seen_ids_path": str(base_dir / "seen.ids"),
        "image_dir": str(image_dir),
        "custom_params": {
            "company": folder_name,
            "source": "Google Maps",
            "restaurant_id": restaurant.get('id', ''),
            "address": restaurant.get('formattedAddress', ''),
            "rating": restaurant.get('rating', 0),
            "userRatingCount": restaurant.get('userRatingCount', 0)
        }
    })
    
    return config, base_dir, folder_name

def save_config(config, config_path):
    """설정 파일 저장"""
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        log.error(f"설정 파일 저장 중 오류: {e}")
        return False

def main():
    """메인 함수"""
    # 명령줄 인수 파싱
    args = parse_args()
    
    # CSV 파일에서 레스토랑 정보 로드
    restaurants = load_restaurants_from_csv(args.csv)
    
    if not restaurants:
        log.error("레스토랑 정보를 불러오지 못했습니다.")
        return
    
    # 레스토랑 수 제한 적용
    if args.limit > 0 and args.limit < len(restaurants):
        log.info(f"처리할 레스토랑 수를 {args.limit}개로 제한합니다.")
        restaurants = restaurants[:args.limit]
    
    # skip-exists 옵션이 활성화된 경우 사전 검사
    if args.skip_exists:
        log.info("--skip-exists 옵션이 활성화되어 있습니다. 사전 검사를 진행합니다...")
        to_process = []
        skip_count = 0
        
        for restaurant in restaurants:
            restaurant_name = restaurant.get('displayName') or restaurant.get('name', 'Unknown')
            
            # 레스토랑 설정 생성 (폴더 경로 확인용)
            result = create_config_for_restaurant(restaurant, args)
            if result is None:
                continue
            
            config, base_dir, folder_name = result
            
            # 건너뛸지 판단
            should_skip, reason = should_skip_restaurant(base_dir)
            
            if should_skip:
                log.info(f"건너뜀: {restaurant_name} - {reason}")
                skip_count += 1
            else:
                log.info(f"처리 예정: {restaurant_name} - {reason}")
                to_process.append(restaurant)
        
        log.info(f"사전 검사 완료 - 건너뜀: {skip_count}개, 처리 예정: {len(to_process)}개")
        restaurants = to_process
    
    if not restaurants:
        log.info("처리할 레스토랑이 없습니다.")
        return
    
    # 스크랩 실행 여부 확인
    proceed = input(f"{len(restaurants)}개의 레스토랑을 스크랩할 준비가 되었습니다. 진행하시겠습니까? (y/n): ").strip().lower()
    if proceed != 'y':
        log.info("스크랩 작업을 취소합니다.")
        return
    
    # 기본 디렉토리 생성
    os.makedirs(args.base_dir, exist_ok=True)
    
    # 처리 결과 요약
    success = 0
    failed = 0
    skipped = 0
    
    # 최대 재시도 횟수 설정
    max_retries = 3
    
    # 각 레스토랑 처리
    for i, restaurant in enumerate(restaurants):
        restaurant_name = restaurant.get('displayName') or restaurant.get('name', 'Unknown')
        log.info(f"[{i+1}/{len(restaurants)}] 레스토랑 처리 중: {restaurant_name}")
        
        # 레스토랑 설정 생성
        result = create_config_for_restaurant(restaurant, args)
        if result is None:
            log.warning(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 설정 생성 실패, 건너뜁니다.")
            skipped += 1
            continue
        
        config, base_dir, folder_name = result
        
        # 디렉토리 생성
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(Path(config["image_dir"]), exist_ok=True)
        
        # 개선된 건너뛰기 로직 (사전 검사에서 걸러지지 않았다면 다시 한 번 확인)
        if args.skip_exists:
            should_skip, reason = should_skip_restaurant(base_dir)
            if should_skip:
                log.info(f"[{i+1}/{len(restaurants)}] {restaurant_name}: {reason}, 건너뜁니다.")
                skipped += 1
                continue
        
        # 설정 파일 저장
        config_path = base_dir / "config.yaml"
        if not save_config(config, config_path):
            log.error(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 설정 파일 저장 실패, 건너뜁니다.")
            failed += 1
            continue
        
        # 스크래퍼 실행 (재시도 로직 추가)
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                log.info(f"[{i+1}/{len(restaurants)}] {restaurant_name}: {attempt}번째 재시도 중...")
            else:
                log.info(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 스크래퍼 실행 시작")
            
            try:
                # 스크래퍼 초기화 및 실행
                scraper = GoogleReviewsScraper(config)
                success_scrape = scraper.scrape()
                
                # 스크래핑 성공 여부 검증 (개선된 로직 사용)
                json_path = base_dir / "reviews.json"
                should_skip, reason = should_skip_restaurant(base_dir)
                
                if should_skip:  # 성공적으로 데이터가 있다면
                    log.info(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 스크래핑 완료 및 검증 성공 - {reason} (시도 {attempt}/{max_retries})")
                    success += 1
                    break
                elif attempt < max_retries:
                    log.warning(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 스크래핑 검증 실패 - {reason}, 재시도 예정 ({attempt}/{max_retries})")
                    time.sleep(5)  # 재시도 전 대기
                else:
                    log.error(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 최대 재시도 횟수 초과, 스크래핑 실패 - {reason}")
                    failed += 1
            except Exception as e:
                log.error(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 스크래핑 중 오류: {e}")
                import traceback
                log.error(traceback.format_exc())
                
                if attempt < max_retries:
                    log.warning(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 오류 발생, 재시도 예정 ({attempt}/{max_retries})")
                    time.sleep(5)  # 재시도 전 대기
                else:
                    log.error(f"[{i+1}/{len(restaurants)}] {restaurant_name}: 최대 재시도 횟수 초과, 스크래핑 실패")
                    failed += 1
                    break
        
        # 레스토랑 사이에 약간의 딜레이 추가
        if i < len(restaurants) - 1:
            log.info("다음 레스토랑으로 넘어가기 전 5초 대기...")
            time.sleep(5)
    
    # 결과 요약 출력
    log.info("\n=== 처리 결과 요약 ===")
    log.info(f"총 레스토랑 수: {len(restaurants)}")
    log.info(f"스크래핑 성공: {success}")
    log.info(f"스크래핑 실패: {failed}")
    log.info(f"처리 건너뜀: {skipped}")
    
    log.info("\n모든 레스토랑 처리 완료!")
    
if __name__ == "__main__":
    main()