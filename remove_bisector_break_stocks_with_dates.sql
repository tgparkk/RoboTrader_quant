-- BISECTOR_BREAK 패턴 70개 이상인 종목들을 날짜별로 candidate_stocks에서 제거하는 쿼리
-- 생성일: 2025-01-17
-- 총 제거 대상: 189개 종목 (중복 제거 후)
-- 총 제거 기록: 327개 (중복 포함)
================================================================================

-- 1. 전체 제거될 종목들 확인 쿼리
-- 제거될 종목들 전체 확인
SELECT stock_code, stock_name, DATE(selection_date) as selection_date, score, reasons
FROM candidate_stocks 
WHERE stock_code IN ('000150', '000660', '000990', '001040', '001270', '001290', '001720', '001820', '002020', '003480', '003540', '004140', '004370', '005360', '005690', '006730', '006800', '007660', '007810', '007820', '008040', '009780', '010130', '010170', '010820', '011930', '012510', '013030', '014620', '014940', '017960', '018000', '021040', '023160', '023790', '025550', '030530', '032940', '034940', '036200', '036810', '039490', '044180', '049470', '052420', '053260', '054540', '054950', '056080', '059090', '060380', '062040', '064820', '065500', '067310', '071050', '072710', '073010', '074600', '075580', '077970', '078350', '078520', '080220', '080580', '082270', '082740', '082800', '083650', '084990', '085310', '086390', '089010', '089030', '090360', '090710', '092300', '092460', '092870', '093370', '095340', '096350', '097230', '098460', '099410', '099440', '100090', '100660', '100840', '101000', '101670', '101680', '102710', '104830', '108380', '108490', '119850', '120030', '124500', '124560', '125490', '126340', '127120', '131970', '133820', '156100', '160190', '166090', '168360', '177350', '187660', '199430', '200670', '204270', '205100', '207760', '208640', '212710', '217500', '218410', '220100', '222800', '226590', '226950', '232140', '234030', '234340', '235980', '252990', '265740', '267250', '288620', '290650', '298040', '304100', '310210', '317830', '319400', '319660', '332570', '333050', '333430', '336260', '340440', '347850', '348150', '351330', '353200', '356860', '356890', '362320', '365270', '376900', '378850', '380550', '381620', '382900', '389470', '389650', '391710', '393210', '397030', '413630', '417970', '431190', '437730', '441270', '445680', '452160', '452280', '456160', '459510', '460930', '462310', '463020', '466100', '468530', '469750', '475150', '475400', '475830', '475960', '476060', '484810', '484870', '488080', '494310', '499790', '950160')
ORDER BY selection_date, stock_code;

-- 2. 날짜별 제거될 종목들 확인 쿼리
-- 20250901 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250901' 
  AND stock_code IN ('208640', '003540', '362320', '049470', '397030', '187660', '083650', '064820', '460930', '288620', '002020', '001720', '075580', '099410', '054540')
ORDER BY stock_code;

-- 20250902 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250902' 
  AND stock_code IN ('012510', '187660', '391710', '049470', '059090', '044180', '317830', '005360', '073010', '077970', '023790', '351330', '064820', '460930', '082740', '333430', '054540', '030530', '097230', '099410', '014940', '092460', '100840', '108380', '085310', '389470', '126340')
ORDER BY stock_code;

-- 20250903 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250903' 
  AND stock_code IN ('382900', '484870', '099440', '124560', '265740', '092300', '013030', '077970', '100840', '380550', '017960', '437730', '054540')
ORDER BY stock_code;

-- 20250904 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250904' 
  AND stock_code IN ('001820', '459510', '052420', '393210', '018000', '381620', '319400', '347850', '075580', '078520', '397030', '220100', '462310', '036810', '030530', '348150')
ORDER BY stock_code;

-- 20250905 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250905' 
  AND stock_code IN ('080220', '220100', '382900', '441270', '484870', '084990', '006730', '499790', '082800', '077970', '462310', '086390', '099410', '348150', '001040', '380550', '393210', '064820', '317830', '014940', '351330', '124500')
ORDER BY stock_code;

-- 20250908 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250908' 
  AND stock_code IN ('333050', '177350', '034940', '100090', '235980', '381620', '217500', '431190', '052420', '466100', '389650', '065500', '441270')
ORDER BY stock_code;

-- 20250909 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250909' 
  AND stock_code IN ('092870', '075580', '054950', '378850', '014940', '092460', '049470', '332570', '014620', '004140', '460930', '001820', '064820', '077970', '413630', '437730', '340440', '052420', '073010', '200670', '086390', '013030', '034940')
ORDER BY stock_code;

-- 20250910 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250910' 
  AND stock_code IN ('160190', '199430', '463020', '317830', '007820', '381620', '475400', '099440', '001040', '476060', '120030', '092870', '376900', '437730', '007810', '310210', '484810', '036810', '036200', '086390', '095340', '089030', '226950', '102710', '380550')
ORDER BY stock_code;

-- 20250911 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250911' 
  AND stock_code IN ('001820', '025550', '096350', '380550', '120030', '156100', '049470', '469750', '000150', '044180', '177350', '023160', '000990', '053260', '133820', '459510', '090710', '014620', '298040', '001270', '101000', '119850', '013030', '014940', '468530', '378850', '131970', '445680', '332570', '032940', '092460', '333430', '075580', '235980', '391710', '356860', '234030', '085310', '006800', '456160', '100840', '099410', '007660', '097230', '484810', '000660', '003480', '494310')
ORDER BY stock_code;

-- 20250912 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250912' 
  AND stock_code IN ('004370', '086390', '039490', '475150', '100660', '382900', '319660', '092870', '030530', '010170', '437730', '082270', '365270', '101670', '099440', '036200', '232140', '356860', '074600', '218410', '336260', '062040', '168360', '484810')
ORDER BY stock_code;

-- 20250915 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250915' 
  AND stock_code IN ('950160', '104830', '304100', '205100', '353200', '100090', '156100', '212710', '160190', '010130', '310210', '023790', '064820', '014940', '090360', '437730', '108490', '234340', '056080', '177350', '075580', '060380', '010820', '036200', '484810', '131970', '452160', '466100', '078350', '463020', '204270', '036810', '222800', '356890', '054540', '003480', '067310', '356860', '018000', '319400', '001290', '008040', '391710', '252990', '032940', '317830', '459510', '097230')
ORDER BY stock_code;

-- 20250916 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250916' 
  AND stock_code IN ('098460', '466100', '090710', '381620', '093370', '356890', '452280', '005690', '365270', '004370', '071050', '456160', '226590', '475830', '064820', '290650', '200670', '333430', '101680', '417970', '166090', '267250', '127120', '089030', '475960', '023790', '413630', '007820', '099410', '319660', '468530', '080580', '044180', '062040', '234030')
ORDER BY stock_code;

-- 20250917 날짜의 제거될 종목들 확인
SELECT stock_code, stock_name, selection_date, score, reasons
FROM candidate_stocks 
WHERE DATE(selection_date) = '20250917' 
  AND stock_code IN ('207760', '085310', '008040', '351330', '452280', '009780', '072710', '125490', '336260', '090710', '021040', '397030', '488080', '011930', '391710', '381620', '466100', '089010')
ORDER BY stock_code;

-- 3. 전체 제거 쿼리 (단일 쿼리 - 권장)
-- BISECTOR_BREAK 패턴 70개 이상인 종목들을 candidate_stocks에서 제거
-- 총 189개 종목 (중복 제거 후)

DELETE FROM candidate_stocks 
WHERE stock_code IN ('000150', '000660', '000990', '001040', '001270', '001290', '001720', '001820', '002020', '003480', '003540', '004140', '004370', '005360', '005690', '006730', '006800', '007660', '007810', '007820', '008040', '009780', '010130', '010170', '010820', '011930', '012510', '013030', '014620', '014940', '017960', '018000', '021040', '023160', '023790', '025550', '030530', '032940', '034940', '036200', '036810', '039490', '044180', '049470', '052420', '053260', '054540', '054950', '056080', '059090', '060380', '062040', '064820', '065500', '067310', '071050', '072710', '073010', '074600', '075580', '077970', '078350', '078520', '080220', '080580', '082270', '082740', '082800', '083650', '084990', '085310', '086390', '089010', '089030', '090360', '090710', '092300', '092460', '092870', '093370', '095340', '096350', '097230', '098460', '099410', '099440', '100090', '100660', '100840', '101000', '101670', '101680', '102710', '104830', '108380', '108490', '119850', '120030', '124500', '124560', '125490', '126340', '127120', '131970', '133820', '156100', '160190', '166090', '168360', '177350', '187660', '199430', '200670', '204270', '205100', '207760', '208640', '212710', '217500', '218410', '220100', '222800', '226590', '226950', '232140', '234030', '234340', '235980', '252990', '265740', '267250', '288620', '290650', '298040', '304100', '310210', '317830', '319400', '319660', '332570', '333050', '333430', '336260', '340440', '347850', '348150', '351330', '353200', '356860', '356890', '362320', '365270', '376900', '378850', '380550', '381620', '382900', '389470', '389650', '391710', '393210', '397030', '413630', '417970', '431190', '437730', '441270', '445680', '452160', '452280', '456160', '459510', '460930', '462310', '463020', '466100', '468530', '469750', '475150', '475400', '475830', '475960', '476060', '484810', '484870', '488080', '494310', '499790', '950160');

-- 4. 날짜별 제거 쿼리들
-- 20250901 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (15개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250901' 
  AND stock_code IN ('208640', '003540', '362320', '049470', '397030', '187660', '083650', '064820', '460930', '288620', '002020', '001720', '075580', '099410', '054540');

-- 20250902 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (27개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250902' 
  AND stock_code IN ('012510', '187660', '391710', '049470', '059090', '044180', '317830', '005360', '073010', '077970', '023790', '351330', '064820', '460930', '082740', '333430', '054540', '030530', '097230', '099410', '014940', '092460', '100840', '108380', '085310', '389470', '126340');

-- 20250903 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (13개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250903' 
  AND stock_code IN ('382900', '484870', '099440', '124560', '265740', '092300', '013030', '077970', '100840', '380550', '017960', '437730', '054540');

-- 20250904 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (16개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250904' 
  AND stock_code IN ('001820', '459510', '052420', '393210', '018000', '381620', '319400', '347850', '075580', '078520', '397030', '220100', '462310', '036810', '030530', '348150');

-- 20250905 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (22개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250905' 
  AND stock_code IN ('080220', '220100', '382900', '441270', '484870', '084990', '006730', '499790', '082800', '077970', '462310', '086390', '099410', '348150', '001040', '380550', '393210', '064820', '317830', '014940', '351330', '124500');

-- 20250908 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (13개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250908' 
  AND stock_code IN ('333050', '177350', '034940', '100090', '235980', '381620', '217500', '431190', '052420', '466100', '389650', '065500', '441270');

-- 20250909 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (23개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250909' 
  AND stock_code IN ('092870', '075580', '054950', '378850', '014940', '092460', '049470', '332570', '014620', '004140', '460930', '001820', '064820', '077970', '413630', '437730', '340440', '052420', '073010', '200670', '086390', '013030', '034940');

-- 20250910 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (25개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250910' 
  AND stock_code IN ('160190', '199430', '463020', '317830', '007820', '381620', '475400', '099440', '001040', '476060', '120030', '092870', '376900', '437730', '007810', '310210', '484810', '036810', '036200', '086390', '095340', '089030', '226950', '102710', '380550');

-- 20250911 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (48개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250911' 
  AND stock_code IN ('001820', '025550', '096350', '380550', '120030', '156100', '049470', '469750', '000150', '044180', '177350', '023160', '000990', '053260', '133820', '459510', '090710', '014620', '298040', '001270', '101000', '119850', '013030', '014940', '468530', '378850', '131970', '445680', '332570', '032940', '092460', '333430', '075580', '235980', '391710', '356860', '234030', '085310', '006800', '456160', '100840', '099410', '007660', '097230', '484810', '000660', '003480', '494310');

-- 20250912 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (24개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250912' 
  AND stock_code IN ('004370', '086390', '039490', '475150', '100660', '382900', '319660', '092870', '030530', '010170', '437730', '082270', '365270', '101670', '099440', '036200', '232140', '356860', '074600', '218410', '336260', '062040', '168360', '484810');

-- 20250915 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (48개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250915' 
  AND stock_code IN ('950160', '104830', '304100', '205100', '353200', '100090', '156100', '212710', '160190', '010130', '310210', '023790', '064820', '014940', '090360', '437730', '108490', '234340', '056080', '177350', '075580', '060380', '010820', '036200', '484810', '131970', '452160', '466100', '078350', '463020', '204270', '036810', '222800', '356890', '054540', '003480', '067310', '356860', '018000', '319400', '001290', '008040', '391710', '252990', '032940', '317830', '459510', '097230');

-- 20250916 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (35개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250916' 
  AND stock_code IN ('098460', '466100', '090710', '381620', '093370', '356890', '452280', '005690', '365270', '004370', '071050', '456160', '226590', '475830', '064820', '290650', '200670', '333430', '101680', '417970', '166090', '267250', '127120', '089030', '475960', '023790', '413630', '007820', '099410', '319660', '468530', '080580', '044180', '062040', '234030');

-- 20250917 날짜의 BISECTOR_BREAK 패턴 70개 이상인 종목들 제거 (18개)
DELETE FROM candidate_stocks 
WHERE DATE(selection_date) = '20250917' 
  AND stock_code IN ('207760', '085310', '008040', '351330', '452280', '009780', '072710', '125490', '336260', '090710', '021040', '397030', '488080', '011930', '391710', '381620', '466100', '089010');

-- 5. 개별 DELETE 쿼리들 (트랜잭션용)
-- 개별 DELETE 쿼리들 (트랜잭션으로 실행 가능)
BEGIN TRANSACTION;

-- 20250901 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '208640' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '003540' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '362320' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '049470' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '397030' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '187660' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '083650' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '064820' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '460930' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '288620' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '002020' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '001720' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '075580' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '099410' AND DATE(selection_date) = '20250901';
DELETE FROM candidate_stocks WHERE stock_code = '054540' AND DATE(selection_date) = '20250901';

-- 20250902 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '012510' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '187660' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '391710' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '049470' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '059090' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '044180' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '317830' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '005360' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '073010' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '077970' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '023790' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '351330' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '064820' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '460930' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '082740' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '333430' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '054540' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '030530' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '097230' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '099410' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '014940' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '092460' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '100840' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '108380' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '085310' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '389470' AND DATE(selection_date) = '20250902';
DELETE FROM candidate_stocks WHERE stock_code = '126340' AND DATE(selection_date) = '20250902';

-- 20250903 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '382900' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '484870' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '099440' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '124560' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '265740' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '092300' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '013030' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '077970' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '100840' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '380550' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '017960' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '437730' AND DATE(selection_date) = '20250903';
DELETE FROM candidate_stocks WHERE stock_code = '054540' AND DATE(selection_date) = '20250903';

-- 20250904 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '001820' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '459510' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '052420' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '393210' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '018000' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '381620' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '319400' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '347850' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '075580' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '078520' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '397030' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '220100' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '462310' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '036810' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '030530' AND DATE(selection_date) = '20250904';
DELETE FROM candidate_stocks WHERE stock_code = '348150' AND DATE(selection_date) = '20250904';

-- 20250905 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '080220' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '220100' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '382900' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '441270' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '484870' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '084990' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '006730' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '499790' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '082800' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '077970' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '462310' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '086390' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '099410' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '348150' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '001040' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '380550' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '393210' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '064820' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '317830' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '014940' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '351330' AND DATE(selection_date) = '20250905';
DELETE FROM candidate_stocks WHERE stock_code = '124500' AND DATE(selection_date) = '20250905';

-- 20250908 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '333050' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '177350' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '034940' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '100090' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '235980' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '381620' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '217500' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '431190' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '052420' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '466100' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '389650' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '065500' AND DATE(selection_date) = '20250908';
DELETE FROM candidate_stocks WHERE stock_code = '441270' AND DATE(selection_date) = '20250908';

-- 20250909 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '092870' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '075580' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '054950' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '378850' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '014940' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '092460' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '049470' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '332570' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '014620' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '004140' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '460930' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '001820' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '064820' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '077970' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '413630' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '437730' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '340440' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '052420' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '073010' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '200670' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '086390' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '013030' AND DATE(selection_date) = '20250909';
DELETE FROM candidate_stocks WHERE stock_code = '034940' AND DATE(selection_date) = '20250909';

-- 20250910 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '160190' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '199430' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '463020' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '317830' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '007820' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '381620' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '475400' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '099440' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '001040' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '476060' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '120030' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '092870' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '376900' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '437730' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '007810' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '310210' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '484810' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '036810' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '036200' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '086390' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '095340' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '089030' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '226950' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '102710' AND DATE(selection_date) = '20250910';
DELETE FROM candidate_stocks WHERE stock_code = '380550' AND DATE(selection_date) = '20250910';

-- 20250911 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '001820' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '025550' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '096350' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '380550' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '120030' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '156100' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '049470' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '469750' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '000150' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '044180' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '177350' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '023160' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '000990' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '053260' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '133820' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '459510' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '090710' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '014620' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '298040' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '001270' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '101000' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '119850' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '013030' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '014940' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '468530' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '378850' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '131970' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '445680' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '332570' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '032940' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '092460' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '333430' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '075580' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '235980' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '391710' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '356860' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '234030' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '085310' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '006800' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '456160' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '100840' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '099410' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '007660' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '097230' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '484810' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '000660' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '003480' AND DATE(selection_date) = '20250911';
DELETE FROM candidate_stocks WHERE stock_code = '494310' AND DATE(selection_date) = '20250911';

-- 20250912 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '004370' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '086390' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '039490' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '475150' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '100660' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '382900' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '319660' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '092870' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '030530' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '010170' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '437730' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '082270' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '365270' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '101670' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '099440' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '036200' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '232140' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '356860' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '074600' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '218410' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '336260' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '062040' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '168360' AND DATE(selection_date) = '20250912';
DELETE FROM candidate_stocks WHERE stock_code = '484810' AND DATE(selection_date) = '20250912';

-- 20250915 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '950160' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '104830' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '304100' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '205100' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '353200' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '100090' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '156100' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '212710' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '160190' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '010130' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '310210' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '023790' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '064820' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '014940' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '090360' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '437730' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '108490' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '234340' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '056080' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '177350' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '075580' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '060380' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '010820' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '036200' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '484810' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '131970' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '452160' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '466100' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '078350' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '463020' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '204270' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '036810' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '222800' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '356890' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '054540' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '003480' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '067310' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '356860' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '018000' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '319400' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '001290' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '008040' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '391710' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '252990' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '032940' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '317830' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '459510' AND DATE(selection_date) = '20250915';
DELETE FROM candidate_stocks WHERE stock_code = '097230' AND DATE(selection_date) = '20250915';

-- 20250916 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '098460' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '466100' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '090710' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '381620' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '093370' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '356890' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '452280' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '005690' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '365270' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '004370' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '071050' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '456160' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '226590' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '475830' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '064820' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '290650' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '200670' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '333430' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '101680' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '417970' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '166090' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '267250' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '127120' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '089030' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '475960' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '023790' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '413630' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '007820' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '099410' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '319660' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '468530' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '080580' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '044180' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '062040' AND DATE(selection_date) = '20250916';
DELETE FROM candidate_stocks WHERE stock_code = '234030' AND DATE(selection_date) = '20250916';

-- 20250917 날짜 종목들
DELETE FROM candidate_stocks WHERE stock_code = '207760' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '085310' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '008040' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '351330' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '452280' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '009780' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '072710' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '125490' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '336260' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '090710' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '021040' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '397030' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '488080' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '011930' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '391710' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '381620' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '466100' AND DATE(selection_date) = '20250917';
DELETE FROM candidate_stocks WHERE stock_code = '089010' AND DATE(selection_date) = '20250917';

-- 커밋하기 전에 결과 확인
-- COMMIT;
-- ROLLBACK; -- 문제가 있으면 롤백

-- 6. 제거 후 확인 쿼리
SELECT COUNT(*) as remaining_stocks FROM candidate_stocks;

-- 7. 날짜별 제거 통계
-- 20250901: 15개 종목
-- 20250902: 27개 종목
-- 20250903: 13개 종목
-- 20250904: 16개 종목
-- 20250905: 22개 종목
-- 20250908: 13개 종목
-- 20250909: 23개 종목
-- 20250910: 25개 종목
-- 20250911: 48개 종목
-- 20250912: 24개 종목
-- 20250915: 48개 종목
-- 20250916: 35개 종목
-- 20250917: 18개 종목

-- 8. 제거된 종목들 목록 (중복 제거 후)
-- 000150, 000660, 000990, 001040, 001270, 001290, 001720, 001820, 002020, 003480, 003540, 004140, 004370, 005360, 005690, 006730, 006800, 007660, 007810, 007820, 008040, 009780, 010130, 010170, 010820, 011930, 012510, 013030, 014620, 014940, 017960, 018000, 021040, 023160, 023790, 025550, 030530, 032940, 034940, 036200, 036810, 039490, 044180, 049470, 052420, 053260, 054540, 054950, 056080, 059090, 060380, 062040, 064820, 065500, 067310, 071050, 072710, 073010, 074600, 075580, 077970, 078350, 078520, 080220, 080580, 082270, 082740, 082800, 083650, 084990, 085310, 086390, 089010, 089030, 090360, 090710, 092300, 092460, 092870, 093370, 095340, 096350, 097230, 098460, 099410, 099440, 100090, 100660, 100840, 101000, 101670, 101680, 102710, 104830, 108380, 108490, 119850, 120030, 124500, 124560, 125490, 126340, 127120, 131970, 133820, 156100, 160190, 166090, 168360, 177350, 187660, 199430, 200670, 204270, 205100, 207760, 208640, 212710, 217500, 218410, 220100, 222800, 226590, 226950, 232140, 234030, 234340, 235980, 252990, 265740, 267250, 288620, 290650, 298040, 304100, 310210, 317830, 319400, 319660, 332570, 333050, 333430, 336260, 340440, 347850, 348150, 351330, 353200, 356860, 356890, 362320, 365270, 376900, 378850, 380550, 381620, 382900, 389470, 389650, 391710, 393210, 397030, 413630, 417970, 431190, 437730, 441270, 445680, 452160, 452280, 456160, 459510, 460930, 462310, 463020, 466100, 468530, 469750, 475150, 475400, 475830, 475960, 476060, 484810, 484870, 488080, 494310, 499790, 950160
