-- robot-classifier 음원 등급 분류 컬럼 추가 (library_scanner v2)
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS quality VARCHAR(20);
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS quality_reasons TEXT;

-- 기존 트랙은 재스캔될 때까지 'unclassified' 로 표시
UPDATE tracks SET quality = 'unclassified' WHERE quality IS NULL;
