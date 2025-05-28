#!/usr/bin/env python3
"""
Google Maps 리뷰 스크래퍼 - CSV 파일 일괄 처리 (개선된 재시도 로직 포함)
========================================

CSV 파일에서 레스토랑 정보를 읽어 구글 맵스 리뷰를 일괄 스크랩합니다.
meta.json과 reviews.json의 차이가 큰 경우 자동으로 재시도합니다.

source venv/bin/activate
python start.py --csv treat/restaurants_006.csv --base-dir treat/restaurants_006 --headless --skip-exists --retry-threshold 0.3
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
    
    parser.add_argument("--retry-threshold", type=float, default=0.3,
                        help="재시도를 위한 차이 비율 임계값 (기본값: 0.3, 30%)")
    
    parser.add_argument("--max-retries", type=int, default=3,
                        help="최대 재시도 횟수 (기본값: 3)")
    
    parser.add_argument("--retry-delay", type=int, default=5,
                        help="재시도 사이의 대기 시간(초) (기본값: 5)")
    
    return parser.parse_args()

def check_review_quality(base_dir, retry_threshold=0.3):
    """
    리뷰 품질 검사 - meta.json과 reviews.json의 차이 분석
    
    Args:
        base_dir: 레스토랑 데이터 디렉토리
        retry_threshold: 재시도를 위한 차이 비율 임계값
    
    Returns:
        tuple: (should_retry, reason, stats_dict)
    """
    try:
        reviews_path = base_dir / "reviews.json"
        meta_path = base_dir / "meta.json"
        
        # 파일 존재 여부 확인
        if not reviews_path.exists():
            return True, "reviews.json 파일이 존재하지 않음", {}
        
        if not meta_path.exists():
            return False, "meta.json 파일이 존재하지 않음 (정상적일 수 있음)", {}
        
        # 파일 읽기
        with open(reviews_path, 'r', encoding='utf-8') as f:
            reviews_data = json.load(f)
        
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta_data = json.load(f)
        
        # 데이터 분석
        review_count = len(reviews_data) if isinstance(reviews_data, list) else 0
        user_ratings_count = meta_data.get('userRatingCount', 0)
        
        # 통계 정보
        stats = {
            'review_count': review_count,
            'user_ratings_count': user_ratings_count,
            'difference': user_ratings_count - review_count,
            'difference_ratio': 0
        }
        
        # 차이 비율 계산 (0으로 나누기 방지)
        if user_ratings_count > 0:
            stats['difference_ratio'] = (user_ratings_count - review_count) / user_ratings_count
        
        # 재시도 조건 판단
        should_retry = False
        reason = f"리뷰 수: {review_count}, 총 평점 수: {user_ratings_count}"
        
        # 1. 리뷰가 하나도 없는 경우
        if review_count == 0 and user_ratings_count > 0:
            should_retry = True
            reason += " - 리뷰가 하나도 수집되지 않음"
        
        # 2. 차이 비율이 임계값을 초과하는 경우
        elif abs(stats['difference_ratio']) > retry_threshold and user_ratings_count > 10:
            should_retry = True
            reason += f" - 차이 비율 {stats['difference_ratio']:.2%} > 임계값 {retry_threshold:.2%}"
        
        # 3. 총 평점 수가 많은데 리뷰 수가 너무 적은 경우
        elif user_ratings_count > 100 and review_count < 10:
            should_retry = True
            reason += " - 총 평점 수 대비 수집된 리뷰 수가 너무 적음"
        
        else:
            reason += " - 정상 범위"
        
        return should_retry, reason, stats
        
    except json.JSONDecodeError as e:
        return True, f"JSON 파일 파싱 오류: {e}", {}
    except Exception as e:
        return True, f"품질 검사 중 오류: {e}", {}

def should_skip_restaurant(base_dir, retry_threshold=0.3):
    """
    레스토랑을 건너뛸지 판단하는 함수 (품질 검사 포함)
    """
    try:
        # 1. 기본 파일 존재 확인
        if not base_dir.exists():
            return False, "폴더가 존재하지 않음"
        
        reviews_path = base_dir / "reviews.json"
        if not reviews_path.exists():
            return False, "reviews.json 파일이 존재하지 않음"
        
        # 2. 파일 크기 확인
        if reviews_path.stat().st_size <= 10:
            return False, f"reviews.json 파일이 너무 작음 ({reviews_path.stat().st_size} 바이트)"
        
        # 3. 품질 검사
        should_retry, reason, stats = check_review_quality(base_dir, retry_threshold)
        
        if should_retry:
            return False, f"품질 검사 실패: {reason}"
        else:
            return True, f"품질 검사 통과: {reason}"
            
    except Exception as e:
        return False, f"검사 중 오류: {e}"

def analyze_existing_data(base_dir_path, retry_threshold=0.3):
    """
    기존 데이터를 분석하여 재시도가 필요한 레스토랑 목록 반환
    """
    retry_candidates = []
    
    if not os.path.exists(base_dir_path):
        return retry_candidates
    
    log.info(f"기존 데이터 분석 중: {base_dir_path}")
    
    for folder_name in os.listdir(base_dir_path):
        folder_path = Path(base_dir_path) / folder_name
        if not folder_path.is_dir():
            continue
        
        should_retry, reason, stats = check_review_quality(folder_path, retry_threshold)
        
        if should_retry:
            retry_candidates.append({
                'folder_name': folder_name,
                'folder_path': folder_path,
                'reason': reason,
                'stats': stats
            })
            log.info(f"재시도 후보: {folder_name} - {reason}")
    
    return retry_candidates

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
    
    # 구글맵스 URL 가져오기
    url = restaurant.get('googleMapsUri') or restaurant.get('placeUri')
    
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
    
    # 리뷰 페이지 URL 생성
    if "data=" not in url and "!9m1!1b1" not in url and "place" in url:
        place_id = restaurant.get('id', '')
        if place_id and place_id.strip() != "":
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

def scrape_restaurant_with_retry(restaurant, args, attempt_num, total_restaurants):
    """
    단일 레스토랑 스크래핑 (재시도 로직 포함)
    """
    restaurant_name = restaurant.get('displayName') or restaurant.get('name', 'Unknown')
    log.info(f"[{attempt_num}/{total_restaurants}] 레스토랑 처리 중: {restaurant_name}")
    
    # 레스토랑 설정 생성
    result = create_config_for_restaurant(restaurant, args)
    if result is None:
        log.warning(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: 설정 생성 실패")
        return False, "설정 생성 실패"
    
    config, base_dir, folder_name = result
    
    # 디렉토리 생성
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(Path(config["image_dir"]), exist_ok=True)
    
    # 기존 데이터 건너뛰기 검사
    if args.skip_exists:
        should_skip, reason = should_skip_restaurant(base_dir, args.retry_threshold)
        if should_skip:
            log.info(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: {reason}, 건너뜀")
            return True, "건너뜀"
    
    # 설정 파일 저장
    config_path = base_dir / "config.yaml"
    if not save_config(config, config_path):
        log.error(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: 설정 파일 저장 실패")
        return False, "설정 파일 저장 실패"
    
    # 스크래핑 시도 (재시도 로직)
    for retry_attempt in range(1, args.max_retries + 1):
        if retry_attempt > 1:
            log.info(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: {retry_attempt}번째 재시도")
            time.sleep(args.retry_delay)
        
        try:
            # 스크래퍼 실행
            scraper = GoogleReviewsScraper(config)
            scraper.scrape()
            
            # 품질 검사
            should_retry, reason, stats = check_review_quality(base_dir, args.retry_threshold)
            
            if not should_retry:
                log.info(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: 성공 - {reason}")
                if stats:
                    log.info(f"    └ 통계: 리뷰 {stats['review_count']}개, 총 평점 {stats['user_ratings_count']}개")
                return True, "성공"
            else:
                if retry_attempt < args.max_retries:
                    log.warning(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: 품질 기준 미달 - {reason}")
                    if stats:
                        log.warning(f"    └ 통계: 리뷰 {stats['review_count']}개, 총 평점 {stats['user_ratings_count']}개, 차이율 {stats.get('difference_ratio', 0):.2%}")
                else:
                    log.error(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: 최대 재시도 초과 - {reason}")
                    return False, f"품질 기준 미달: {reason}"
        
        except Exception as e:
            log.error(f"[{attempt_num}/{total_restaurants}] {restaurant_name}: 스크래핑 오류: {e}")
            if retry_attempt >= args.max_retries:
                import traceback
                log.error(traceback.format_exc())
                return False, f"스크래핑 오류: {e}"
    
    return False, "알 수 없는 오류"

def main():
    """메인 함수"""
    args = parse_args()
    
    # 기존 데이터 분석 (재시도 필요한 항목 찾기)
    if args.skip_exists:
        retry_candidates = analyze_existing_data(args.base_dir, args.retry_threshold)
        if retry_candidates:
            log.warning(f"재시도가 필요한 기존 레스토랑 {len(retry_candidates)}개 발견:")
            for candidate in retry_candidates[:5]:  # 처음 5개만 표시
                log.warning(f"  - {candidate['folder_name']}: {candidate['reason']}")
            if len(retry_candidates) > 5:
                log.warning(f"  ... 외 {len(retry_candidates) - 5}개")
    
    # CSV 파일에서 레스토랑 정보 로드
    restaurants = load_restaurants_from_csv(args.csv)
    
    if not restaurants:
        log.error("레스토랑 정보를 불러오지 못했습니다.")
        return
    
    # 레스토랑 수 제한 적용
    if args.limit > 0 and args.limit < len(restaurants):
        log.info(f"처리할 레스토랑 수를 {args.limit}개로 제한합니다.")
        restaurants = restaurants[:args.limit]
    
    # 사전 필터링 (skip-exists)
    if args.skip_exists:
        to_process = []
        skip_count = 0
        
        for restaurant in restaurants:
            restaurant_name = restaurant.get('displayName') or restaurant.get('name', 'Unknown')
            result = create_config_for_restaurant(restaurant, args)
            if result is None:
                continue
            
            config, base_dir, folder_name = result
            should_skip, reason = should_skip_restaurant(base_dir, args.retry_threshold)
            
            if should_skip:
                skip_count += 1
            else:
                to_process.append(restaurant)
        
        log.info(f"사전 검사 완료 - 건너뜀: {skip_count}개, 처리 예정: {len(to_process)}개")
        restaurants = to_process
    
    if not restaurants:
        log.info("처리할 레스토랑이 없습니다.")
        return
    
    # 진행 확인
    proceed = input(f"\n설정 요약:\n"
                   f"  - 처리할 레스토랑: {len(restaurants)}개\n"
                   f"  - 재시도 임계값: {args.retry_threshold:.1%}\n"
                   f"  - 최대 재시도: {args.max_retries}회\n"
                   f"  - 재시도 간격: {args.retry_delay}초\n"
                   f"\n진행하시겠습니까? (y/n): ").strip().lower()
    
    if proceed != 'y':
        log.info("작업을 취소합니다.")
        return
    
    # 기본 디렉토리 생성
    os.makedirs(args.base_dir, exist_ok=True)
    
    # 처리 결과 통계
    success = 0
    failed = 0
    skipped = 0
    
    # 각 레스토랑 처리
    for i, restaurant in enumerate(restaurants):
        success_result, reason = scrape_restaurant_with_retry(restaurant, args, i+1, len(restaurants))
        
        if "건너뜀" in reason:
            skipped += 1
        elif success_result:
            success += 1
        else:
            failed += 1
        
        # 레스토랑 간 딜레이
        if i < len(restaurants) - 1:
            time.sleep(2)
    
    # 결과 요약
    log.info(f"\n{'='*50}")
    log.info("처리 결과 요약:")
    log.info(f"  총 레스토랑 수: {len(restaurants)}")
    log.info(f"  성공: {success}")
    log.info(f"  실패: {failed}")
    log.info(f"  건너뜀: {skipped}")
    log.info(f"  성공률: {success/(len(restaurants)) * 100:.1f}%")
    
    # 재시도 통계 추가 분석
    if success > 0:
        log.info(f"\n품질 분석 완료. 재시도 임계값: {args.retry_threshold:.1%}")
        log.info("상세한 분석을 위해서는 별도의 분석 스크립트를 실행하세요.")
    
    log.info("\n모든 처리 완료!")

if __name__ == "__main__":
    main()