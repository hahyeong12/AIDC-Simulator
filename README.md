# AIDC Simulator — 울산 데이터센터 운영 시뮬레이션

> OSS/데이터베이스 텀프로젝트용 개발 초기 버전 v0.1

## 프로젝트 목적
플레이어가 가상의 울산 AI 데이터센터 운영 직원이 되어 해외 고객의 AI 작업 요청을 처리하는 미션 기반 게임입니다. GPU 자원 할당, 네트워크 회선 장애, 운영 의사결정의 관계를 초보자도 경험하도록 설계했습니다.

**주의:** 고객사·사건·자원 단위·점수는 게임을 위한 가상 설정이며 실제 데이터센터의 사양이나 특정 기업의 운영 체계를 재현한 것은 아닙니다.

## 현재 구현 기능
- Tkinter GUI에서 미션 스토리를 확인하고 버튼으로 행동 선택
- 고성능/절약형 GPU 자원 배분
- 가상의 통신 회선 장애와 세 가지 대응 방법
- 대응 결과에 따른 성공/실패 및 점수 계산
- SQLite 테이블 4개에 고객·미션·수행 기록·사건 로그 저장
- 최근 수행 기록 조회 및 더블클릭 시 상세 로그 조회
- 게임 규칙과 DB의 자동 테스트 5개

## 설치 및 실행
- Python 3.10 이상 (추가 pip 패키지 없음)
- Windows PowerShell 또는 명령 프롬프트에서 이 폴더로 이동:

```powershell
python main.py
```

GUI가 실행되지 않고 tkinter 관련 오류가 뜨면, `python -m tkinter`로 설치 여부를 확인하십시오. Windows용 공식 Python 설치 프로그램에는 보통 Tk가 포함됩니다.

첫 실행 시 `aidc_game.db` 파일이 자동 생성되며, 수행 결과와 로그는 종료 후에도 남습니다.

## 테스트
```powershell
python -m unittest discover -s tests -v
```

## 폴더 구조
```text
AIDC_Simulator/
├── main.py            # 화면과 버튼 이벤트
├── game.py            # 자원 계산 / 게임 규칙 / 점수 판정
├── database.py        # DB 초기화, SQL 저장 및 조회
├── tests/
│   └── test_game.py   # 테스트
├── .gitignore
├── DEV_NOTES.md       # 코드 학습 설명
└── README.md
```

## 데이터베이스 설계
| 테이블 | 의미 | 핵심 칼럼 |
| --- | --- | --- |
| clients | 고객사 | id(PK), company_name, country |
| missions | 고객사별 작업 요청 | id(PK), client_id(FK), title, description |
| playthroughs | 미션 수행 결과 | id(PK), mission_id(FK), plan, response, status, score |
| event_logs | 행동 및 사건 기록 | id(PK), playthrough_id(FK), message, created_at |

관계: `clients 1:N missions 1:N playthroughs 1:N event_logs`

예: 수행 결과와 고객명을 함께 조회
```sql
SELECT p.id, c.company_name, p.plan, p.response, p.status, p.score
FROM playthroughs AS p
JOIN missions AS m ON p.mission_id = m.id
JOIN clients AS c ON m.client_id = c.id
ORDER BY p.id DESC;
```

## v0.1 게임 규칙 (가상 수치)
- 초기 GPU 10, 전력 10, 네트워크 8단위
- 고성능: GPU 7 / 전력 7 / 필요 네트워크 5
- 절약형: GPU 4 / 전력 4 / 필요 네트워크 3
- 장애로 네트워크 가용치가 2로 감소
- 우회: 가용 네트워크 +4; 압축: 필요 네트워크 -2; 유지: 변화 없음
- 필요 네트워크가 가용 네트워크 이하일 때 성공
- 점수 = 80 + 모드 보너스 - 대응 페널티 + 성공(+10)/실패(-65). 0~100 범위로 제한

## 개발 로드맵
- [x] 첫 미션, 선택에 따른 결과, SQLite 기록
- [ ] GPU 과부하, 냉각 이상, 전력 제한 추가
- [ ] 고객 만족도, 운영 자원의 회차 간 연동
- [ ] 게임 밸런싱, GUI 개선, 테스트 확장, 스크린샷 및 README 완성

## 사용 출처
v0.1 소스는 본 프로젝트를 위해 새로 작성된 예시 구현입니다. 추후 외부 코드·이미지·폰트·음원 등을 쓰면 라이선스와 저작자 출처를 표시해야 합니다.
