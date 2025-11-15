-- BISECTOR_BREAK 패턴 70개 이상인 종목들을 candidate_stocks에서 제거하는 쿼리
-- 생성일: 2025-01-17
-- 총 제거 대상 종목: 189개
================================================================================

-- 1. 제거될 종목들 확인 쿼리
-- 제거될 종목들 확인
SELECT stock_code, stock_name, created_at 
FROM candidate_stocks 
WHERE stock_code IN ('000150', '000660', '000990', '001040', '001270', '001290', '001720', '001820', '002020', '003480', '003540', '004140', '004370', '005360', '005690', '006730', '006800', '007660', '007810', '007820', '008040', '009780', '010130', '010170', '010820', '011930', '012510', '013030', '014620', '014940', '017960', '018000', '021040', '023160', '023790', '025550', '030530', '032940', '034940', '036200', '036810', '039490', '044180', '049470', '052420', '053260', '054540', '054950', '056080', '059090', '060380', '062040', '064820', '065500', '067310', '071050', '072710', '073010', '074600', '075580', '077970', '078350', '078520', '080220', '080580', '082270', '082740', '082800', '083650', '084990', '085310', '086390', '089010', '089030', '090360', '090710', '092300', '092460', '092870', '093370', '095340', '096350', '097230', '098460', '099410', '099440', '100090', '100660', '100840', '101000', '101670', '101680', '102710', '104830', '108380', '108490', '119850', '120030', '124500', '124560', '125490', '126340', '127120', '131970', '133820', '156100', '160190', '166090', '168360', '177350', '187660', '199430', '200670', '204270', '205100', '207760', '208640', '212710', '217500', '218410', '220100', '222800', '226590', '226950', '232140', '234030', '234340', '235980', '252990', '265740', '267250', '288620', '290650', '298040', '304100', '310210', '317830', '319400', '319660', '332570', '333050', '333430', '336260', '340440', '347850', '348150', '351330', '353200', '356860', '356890', '362320', '365270', '376900', '378850', '380550', '381620', '382900', '389470', '389650', '391710', '393210', '397030', '413630', '417970', '431190', '437730', '441270', '445680', '452160', '452280', '456160', '459510', '460930', '462310', '463020', '466100', '468530', '469750', '475150', '475400', '475830', '475960', '476060', '484810', '484870', '488080', '494310', '499790', '950160')
ORDER BY stock_code;

-- 2. 단일 DELETE 쿼리 (권장)
-- BISECTOR_BREAK 패턴 70개 이상인 종목들을 candidate_stocks에서 제거
-- 총 189개 종목 제거

DELETE FROM candidate_stocks 
WHERE stock_code IN ('000150', '000660', '000990', '001040', '001270', '001290', '001720', '001820', '002020', '003480', '003540', '004140', '004370', '005360', '005690', '006730', '006800', '007660', '007810', '007820', '008040', '009780', '010130', '010170', '010820', '011930', '012510', '013030', '014620', '014940', '017960', '018000', '021040', '023160', '023790', '025550', '030530', '032940', '034940', '036200', '036810', '039490', '044180', '049470', '052420', '053260', '054540', '054950', '056080', '059090', '060380', '062040', '064820', '065500', '067310', '071050', '072710', '073010', '074600', '075580', '077970', '078350', '078520', '080220', '080580', '082270', '082740', '082800', '083650', '084990', '085310', '086390', '089010', '089030', '090360', '090710', '092300', '092460', '092870', '093370', '095340', '096350', '097230', '098460', '099410', '099440', '100090', '100660', '100840', '101000', '101670', '101680', '102710', '104830', '108380', '108490', '119850', '120030', '124500', '124560', '125490', '126340', '127120', '131970', '133820', '156100', '160190', '166090', '168360', '177350', '187660', '199430', '200670', '204270', '205100', '207760', '208640', '212710', '217500', '218410', '220100', '222800', '226590', '226950', '232140', '234030', '234340', '235980', '252990', '265740', '267250', '288620', '290650', '298040', '304100', '310210', '317830', '319400', '319660', '332570', '333050', '333430', '336260', '340440', '347850', '348150', '351330', '353200', '356860', '356890', '362320', '365270', '376900', '378850', '380550', '381620', '382900', '389470', '389650', '391710', '393210', '397030', '413630', '417970', '431190', '437730', '441270', '445680', '452160', '452280', '456160', '459510', '460930', '462310', '463020', '466100', '468530', '469750', '475150', '475400', '475830', '475960', '476060', '484810', '484870', '488080', '494310', '499790', '950160');

-- 3. 개별 DELETE 쿼리들 (트랜잭션용)
-- 개별 DELETE 쿼리들 (트랜잭션으로 실행 가능)
BEGIN TRANSACTION;

DELETE FROM candidate_stocks WHERE stock_code = '000150';
DELETE FROM candidate_stocks WHERE stock_code = '000660';
DELETE FROM candidate_stocks WHERE stock_code = '000990';
DELETE FROM candidate_stocks WHERE stock_code = '001040';
DELETE FROM candidate_stocks WHERE stock_code = '001270';
DELETE FROM candidate_stocks WHERE stock_code = '001290';
DELETE FROM candidate_stocks WHERE stock_code = '001720';
DELETE FROM candidate_stocks WHERE stock_code = '001820';
DELETE FROM candidate_stocks WHERE stock_code = '002020';
DELETE FROM candidate_stocks WHERE stock_code = '003480';
DELETE FROM candidate_stocks WHERE stock_code = '003540';
DELETE FROM candidate_stocks WHERE stock_code = '004140';
DELETE FROM candidate_stocks WHERE stock_code = '004370';
DELETE FROM candidate_stocks WHERE stock_code = '005360';
DELETE FROM candidate_stocks WHERE stock_code = '005690';
DELETE FROM candidate_stocks WHERE stock_code = '006730';
DELETE FROM candidate_stocks WHERE stock_code = '006800';
DELETE FROM candidate_stocks WHERE stock_code = '007660';
DELETE FROM candidate_stocks WHERE stock_code = '007810';
DELETE FROM candidate_stocks WHERE stock_code = '007820';
DELETE FROM candidate_stocks WHERE stock_code = '008040';
DELETE FROM candidate_stocks WHERE stock_code = '009780';
DELETE FROM candidate_stocks WHERE stock_code = '010130';
DELETE FROM candidate_stocks WHERE stock_code = '010170';
DELETE FROM candidate_stocks WHERE stock_code = '010820';
DELETE FROM candidate_stocks WHERE stock_code = '011930';
DELETE FROM candidate_stocks WHERE stock_code = '012510';
DELETE FROM candidate_stocks WHERE stock_code = '013030';
DELETE FROM candidate_stocks WHERE stock_code = '014620';
DELETE FROM candidate_stocks WHERE stock_code = '014940';
DELETE FROM candidate_stocks WHERE stock_code = '017960';
DELETE FROM candidate_stocks WHERE stock_code = '018000';
DELETE FROM candidate_stocks WHERE stock_code = '021040';
DELETE FROM candidate_stocks WHERE stock_code = '023160';
DELETE FROM candidate_stocks WHERE stock_code = '023790';
DELETE FROM candidate_stocks WHERE stock_code = '025550';
DELETE FROM candidate_stocks WHERE stock_code = '030530';
DELETE FROM candidate_stocks WHERE stock_code = '032940';
DELETE FROM candidate_stocks WHERE stock_code = '034940';
DELETE FROM candidate_stocks WHERE stock_code = '036200';
DELETE FROM candidate_stocks WHERE stock_code = '036810';
DELETE FROM candidate_stocks WHERE stock_code = '039490';
DELETE FROM candidate_stocks WHERE stock_code = '044180';
DELETE FROM candidate_stocks WHERE stock_code = '049470';
DELETE FROM candidate_stocks WHERE stock_code = '052420';
DELETE FROM candidate_stocks WHERE stock_code = '053260';
DELETE FROM candidate_stocks WHERE stock_code = '054540';
DELETE FROM candidate_stocks WHERE stock_code = '054950';
DELETE FROM candidate_stocks WHERE stock_code = '056080';
DELETE FROM candidate_stocks WHERE stock_code = '059090';
DELETE FROM candidate_stocks WHERE stock_code = '060380';
DELETE FROM candidate_stocks WHERE stock_code = '062040';
DELETE FROM candidate_stocks WHERE stock_code = '064820';
DELETE FROM candidate_stocks WHERE stock_code = '065500';
DELETE FROM candidate_stocks WHERE stock_code = '067310';
DELETE FROM candidate_stocks WHERE stock_code = '071050';
DELETE FROM candidate_stocks WHERE stock_code = '072710';
DELETE FROM candidate_stocks WHERE stock_code = '073010';
DELETE FROM candidate_stocks WHERE stock_code = '074600';
DELETE FROM candidate_stocks WHERE stock_code = '075580';
DELETE FROM candidate_stocks WHERE stock_code = '077970';
DELETE FROM candidate_stocks WHERE stock_code = '078350';
DELETE FROM candidate_stocks WHERE stock_code = '078520';
DELETE FROM candidate_stocks WHERE stock_code = '080220';
DELETE FROM candidate_stocks WHERE stock_code = '080580';
DELETE FROM candidate_stocks WHERE stock_code = '082270';
DELETE FROM candidate_stocks WHERE stock_code = '082740';
DELETE FROM candidate_stocks WHERE stock_code = '082800';
DELETE FROM candidate_stocks WHERE stock_code = '083650';
DELETE FROM candidate_stocks WHERE stock_code = '084990';
DELETE FROM candidate_stocks WHERE stock_code = '085310';
DELETE FROM candidate_stocks WHERE stock_code = '086390';
DELETE FROM candidate_stocks WHERE stock_code = '089010';
DELETE FROM candidate_stocks WHERE stock_code = '089030';
DELETE FROM candidate_stocks WHERE stock_code = '090360';
DELETE FROM candidate_stocks WHERE stock_code = '090710';
DELETE FROM candidate_stocks WHERE stock_code = '092300';
DELETE FROM candidate_stocks WHERE stock_code = '092460';
DELETE FROM candidate_stocks WHERE stock_code = '092870';
DELETE FROM candidate_stocks WHERE stock_code = '093370';
DELETE FROM candidate_stocks WHERE stock_code = '095340';
DELETE FROM candidate_stocks WHERE stock_code = '096350';
DELETE FROM candidate_stocks WHERE stock_code = '097230';
DELETE FROM candidate_stocks WHERE stock_code = '098460';
DELETE FROM candidate_stocks WHERE stock_code = '099410';
DELETE FROM candidate_stocks WHERE stock_code = '099440';
DELETE FROM candidate_stocks WHERE stock_code = '100090';
DELETE FROM candidate_stocks WHERE stock_code = '100660';
DELETE FROM candidate_stocks WHERE stock_code = '100840';
DELETE FROM candidate_stocks WHERE stock_code = '101000';
DELETE FROM candidate_stocks WHERE stock_code = '101670';
DELETE FROM candidate_stocks WHERE stock_code = '101680';
DELETE FROM candidate_stocks WHERE stock_code = '102710';
DELETE FROM candidate_stocks WHERE stock_code = '104830';
DELETE FROM candidate_stocks WHERE stock_code = '108380';
DELETE FROM candidate_stocks WHERE stock_code = '108490';
DELETE FROM candidate_stocks WHERE stock_code = '119850';
DELETE FROM candidate_stocks WHERE stock_code = '120030';
DELETE FROM candidate_stocks WHERE stock_code = '124500';
DELETE FROM candidate_stocks WHERE stock_code = '124560';
DELETE FROM candidate_stocks WHERE stock_code = '125490';
DELETE FROM candidate_stocks WHERE stock_code = '126340';
DELETE FROM candidate_stocks WHERE stock_code = '127120';
DELETE FROM candidate_stocks WHERE stock_code = '131970';
DELETE FROM candidate_stocks WHERE stock_code = '133820';
DELETE FROM candidate_stocks WHERE stock_code = '156100';
DELETE FROM candidate_stocks WHERE stock_code = '160190';
DELETE FROM candidate_stocks WHERE stock_code = '166090';
DELETE FROM candidate_stocks WHERE stock_code = '168360';
DELETE FROM candidate_stocks WHERE stock_code = '177350';
DELETE FROM candidate_stocks WHERE stock_code = '187660';
DELETE FROM candidate_stocks WHERE stock_code = '199430';
DELETE FROM candidate_stocks WHERE stock_code = '200670';
DELETE FROM candidate_stocks WHERE stock_code = '204270';
DELETE FROM candidate_stocks WHERE stock_code = '205100';
DELETE FROM candidate_stocks WHERE stock_code = '207760';
DELETE FROM candidate_stocks WHERE stock_code = '208640';
DELETE FROM candidate_stocks WHERE stock_code = '212710';
DELETE FROM candidate_stocks WHERE stock_code = '217500';
DELETE FROM candidate_stocks WHERE stock_code = '218410';
DELETE FROM candidate_stocks WHERE stock_code = '220100';
DELETE FROM candidate_stocks WHERE stock_code = '222800';
DELETE FROM candidate_stocks WHERE stock_code = '226590';
DELETE FROM candidate_stocks WHERE stock_code = '226950';
DELETE FROM candidate_stocks WHERE stock_code = '232140';
DELETE FROM candidate_stocks WHERE stock_code = '234030';
DELETE FROM candidate_stocks WHERE stock_code = '234340';
DELETE FROM candidate_stocks WHERE stock_code = '235980';
DELETE FROM candidate_stocks WHERE stock_code = '252990';
DELETE FROM candidate_stocks WHERE stock_code = '265740';
DELETE FROM candidate_stocks WHERE stock_code = '267250';
DELETE FROM candidate_stocks WHERE stock_code = '288620';
DELETE FROM candidate_stocks WHERE stock_code = '290650';
DELETE FROM candidate_stocks WHERE stock_code = '298040';
DELETE FROM candidate_stocks WHERE stock_code = '304100';
DELETE FROM candidate_stocks WHERE stock_code = '310210';
DELETE FROM candidate_stocks WHERE stock_code = '317830';
DELETE FROM candidate_stocks WHERE stock_code = '319400';
DELETE FROM candidate_stocks WHERE stock_code = '319660';
DELETE FROM candidate_stocks WHERE stock_code = '332570';
DELETE FROM candidate_stocks WHERE stock_code = '333050';
DELETE FROM candidate_stocks WHERE stock_code = '333430';
DELETE FROM candidate_stocks WHERE stock_code = '336260';
DELETE FROM candidate_stocks WHERE stock_code = '340440';
DELETE FROM candidate_stocks WHERE stock_code = '347850';
DELETE FROM candidate_stocks WHERE stock_code = '348150';
DELETE FROM candidate_stocks WHERE stock_code = '351330';
DELETE FROM candidate_stocks WHERE stock_code = '353200';
DELETE FROM candidate_stocks WHERE stock_code = '356860';
DELETE FROM candidate_stocks WHERE stock_code = '356890';
DELETE FROM candidate_stocks WHERE stock_code = '362320';
DELETE FROM candidate_stocks WHERE stock_code = '365270';
DELETE FROM candidate_stocks WHERE stock_code = '376900';
DELETE FROM candidate_stocks WHERE stock_code = '378850';
DELETE FROM candidate_stocks WHERE stock_code = '380550';
DELETE FROM candidate_stocks WHERE stock_code = '381620';
DELETE FROM candidate_stocks WHERE stock_code = '382900';
DELETE FROM candidate_stocks WHERE stock_code = '389470';
DELETE FROM candidate_stocks WHERE stock_code = '389650';
DELETE FROM candidate_stocks WHERE stock_code = '391710';
DELETE FROM candidate_stocks WHERE stock_code = '393210';
DELETE FROM candidate_stocks WHERE stock_code = '397030';
DELETE FROM candidate_stocks WHERE stock_code = '413630';
DELETE FROM candidate_stocks WHERE stock_code = '417970';
DELETE FROM candidate_stocks WHERE stock_code = '431190';
DELETE FROM candidate_stocks WHERE stock_code = '437730';
DELETE FROM candidate_stocks WHERE stock_code = '441270';
DELETE FROM candidate_stocks WHERE stock_code = '445680';
DELETE FROM candidate_stocks WHERE stock_code = '452160';
DELETE FROM candidate_stocks WHERE stock_code = '452280';
DELETE FROM candidate_stocks WHERE stock_code = '456160';
DELETE FROM candidate_stocks WHERE stock_code = '459510';
DELETE FROM candidate_stocks WHERE stock_code = '460930';
DELETE FROM candidate_stocks WHERE stock_code = '462310';
DELETE FROM candidate_stocks WHERE stock_code = '463020';
DELETE FROM candidate_stocks WHERE stock_code = '466100';
DELETE FROM candidate_stocks WHERE stock_code = '468530';
DELETE FROM candidate_stocks WHERE stock_code = '469750';
DELETE FROM candidate_stocks WHERE stock_code = '475150';
DELETE FROM candidate_stocks WHERE stock_code = '475400';
DELETE FROM candidate_stocks WHERE stock_code = '475830';
DELETE FROM candidate_stocks WHERE stock_code = '475960';
DELETE FROM candidate_stocks WHERE stock_code = '476060';
DELETE FROM candidate_stocks WHERE stock_code = '484810';
DELETE FROM candidate_stocks WHERE stock_code = '484870';
DELETE FROM candidate_stocks WHERE stock_code = '488080';
DELETE FROM candidate_stocks WHERE stock_code = '494310';
DELETE FROM candidate_stocks WHERE stock_code = '499790';
DELETE FROM candidate_stocks WHERE stock_code = '950160';

-- 커밋하기 전에 결과 확인
-- COMMIT;
-- ROLLBACK; -- 문제가 있으면 롤백

-- 4. 제거 후 확인 쿼리
SELECT COUNT(*) as remaining_stocks FROM candidate_stocks;

-- 5. 제거된 종목들 목록
-- 000150, 000660, 000990, 001040, 001270, 001290, 001720, 001820, 002020, 003480, 003540, 004140, 004370, 005360, 005690, 006730, 006800, 007660, 007810, 007820, 008040, 009780, 010130, 010170, 010820, 011930, 012510, 013030, 014620, 014940, 017960, 018000, 021040, 023160, 023790, 025550, 030530, 032940, 034940, 036200, 036810, 039490, 044180, 049470, 052420, 053260, 054540, 054950, 056080, 059090, 060380, 062040, 064820, 065500, 067310, 071050, 072710, 073010, 074600, 075580, 077970, 078350, 078520, 080220, 080580, 082270, 082740, 082800, 083650, 084990, 085310, 086390, 089010, 089030, 090360, 090710, 092300, 092460, 092870, 093370, 095340, 096350, 097230, 098460, 099410, 099440, 100090, 100660, 100840, 101000, 101670, 101680, 102710, 104830, 108380, 108490, 119850, 120030, 124500, 124560, 125490, 126340, 127120, 131970, 133820, 156100, 160190, 166090, 168360, 177350, 187660, 199430, 200670, 204270, 205100, 207760, 208640, 212710, 217500, 218410, 220100, 222800, 226590, 226950, 232140, 234030, 234340, 235980, 252990, 265740, 267250, 288620, 290650, 298040, 304100, 310210, 317830, 319400, 319660, 332570, 333050, 333430, 336260, 340440, 347850, 348150, 351330, 353200, 356860, 356890, 362320, 365270, 376900, 378850, 380550, 381620, 382900, 389470, 389650, 391710, 393210, 397030, 413630, 417970, 431190, 437730, 441270, 445680, 452160, 452280, 456160, 459510, 460930, 462310, 463020, 466100, 468530, 469750, 475150, 475400, 475830, 475960, 476060, 484810, 484870, 488080, 494310, 499790, 950160
