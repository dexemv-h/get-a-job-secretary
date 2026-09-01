# Stage 6 — OPIc Rating & Calibration Coach

영어 문장을 자연스럽게 고쳐 주는 첨삭기가 아니라,
**예상 OPIc 등급을 판정하고 "왜 바로 위 등급이 아닌지"를 설명하는** 모듈이다.

공식 OPIc의 비공개 채점 알고리즘을 재현하지 않는다.
공개된 ACTFL/OPIc proficiency 원칙 + 사용자가 등록한 실제 응시 샘플만으로 "예상 등급"을 산출한다.

## 판정 원리

1. **Functions → Text Type → Context → Accuracy** 순으로 판단한다.
   문법/어휘/발음/유창성 점수의 합산이 아니다.
2. **Floor / Ceiling 분리.** Floor는 여러 문제에서 안정적으로 반복 가능한 수준,
   Ceiling은 시도하지만 무너지는 수준. 좋은 답변 한 개로 등급을 올리지 않는다.
3. **답변 1개로는 전체 등급을 확정하지 않는다.**
   `min_answers_for_overall`(기본 5) 미만이면 전체 등급은 항상 `판단 보류`.
4. **IH vs AL은 엄격하게.** Advanced 기능을 "보여줬는가"가 아니라
   "여러 주제에서 유지하는가"로 가른다.
5. **발음·억양은 어떤 경우에도 모델이 판정하지 않는다.** 이 파이프라인은 오디오를 모델에
   직접 넣지 않는다(모델이 소리를 듣지 못한다). 음성에서 얻는 것은 전사 텍스트와 시간 정보뿐이다.
   - 시간 정보로 **객관 측정 가능**: 멈춤 분포, 발화 속도, 발화 덩어리 길이, filler 밀도
   - **측정 불가**: 발음 정확도, 억양, 강세, rhythm → 항상 "평가 불가"로 표기

## 파일

| 파일 | 역할 |
|------|------|
| `rubric.py` | 등급 사다리, 기능 항목, 평가 철학(LLM 공통 프롬프트 블록) |
| `rater.py` | 단일 답변 평가 + 지정 출력 형식 리포트 |
| `profile_tracker.py` | 여러 답변 누적 → Floor / Ceiling / 전체 예상 등급 |
| `calibration.py` | 실제 응시 샘플 저장, blind 예측 → 실제 비교 → Calibration Note |
| `transcriber.py` | 로컬 faster-whisper STT (word timestamp 포함, 오디오 외부 전송 없음) |
| `delivery.py` | word timestamp → 멈춤·속도·발화 덩어리·filler 등 delivery 지표 |

## 사용법

### 1. 답변 1개 평가

```bash
python -m main opic rate \
  --question "Tell me about the last time something unexpected happened." \
  --answer answers/q1.txt
```

음성 파일이 있으면 `--audio` 에 경로를 준다. 자동으로 전사하고 delivery 지표까지 뽑아
Fluency / Text Type 판단의 객관 근거로 넣는다.

```bash
python -m main opic rate --question "..." --audio answers/q1.wav
python -m main opic transcribe --audio answers/q1.wav   # 전사 + 지표만 (등급 판정 없음)
```

`--audio` 를 줘도 발음 항목은 여전히 `평가 불가`다. 대신 전사 저신뢰 단어 비율을
**명료도 참고치**로만 표기한다(발음 점수가 아니다).

### 2. 여러 답변 누적 → Floor / Ceiling

`--dir` 안의 `*.txt` 를 모두 평가한다. 각 파일의 첫 줄에 질문을 적는다.
같은 이름의 음성 파일(`q1.txt` ↔ `q1.wav`)이 있으면 그 음성을 전사해 답변으로 쓰고
delivery 지표도 함께 계산한다.

```
Q: Describe a memorable trip you took.
So, last summer I went to Busan with my friends...
```

```bash
python -m main opic session --dir answers/ --detail
```

결과는 `$OPIC_DIR/sessions/` 에 저장된다(`--output` 으로 경로 지정 가능).

### 3. 실제 응시 샘플로 보정

신뢰도는 반드시 구분해서 등록한다.

- `A` Verified Actual Result — 실제 시험 결과가 확인된 응시자
- `B` Claimed Result — 본인 주장, 검증 어려움
- `C` Model / Instructor Answer — 강사·학습용 모범답안

```bash
python -m main opic calibrate add \
  --sample-id S001 --grade IH --evidence A \
  --question "Tell me about your neighborhood." \
  --answer samples/s001.txt --source "본인 성적표"

python -m main opic calibrate run --sample-id S001   # blind 예측 → 실제와 비교
python -m main opic calibrate notes                  # 누적 노트 + 현재 보정 기준
```

`calibrate run` 은 **실제 등급을 프롬프트에 넣지 않은 상태로 먼저 예측**한 뒤 비교한다.
어긋나면 고정된 편향 태그(예: `fluency_overweight`, `length_as_proficiency`)로 원인을 기록한다.

### 보정이 반영되는 조건

샘플 1건으로 기준을 바꾸지 않는다.
`calibration_evidence_levels`(기본 `A`)에 해당하는 노트에서
**같은 편향 태그가 `calibration_min_repeat`(기본 2)회 이상 반복될 때만**
이후 평가 프롬프트에 참고 기준으로 주입된다.
이는 공식 proficiency 원칙을 덮어쓰는 규칙이 아니라 예측 보정용 참고 기준이다.

보정을 끄고 원칙만으로 평가하려면 `--no-calibration` 을 쓴다.

## 설정 (`config/settings.yaml` → `opic_coach`)

| 키 | 기본값 | 의미 |
|----|--------|------|
| `min_answers_for_overall` | 5 | 전체 등급 확정에 필요한 최소 답변 수 |
| `floor_ratio` | 0.7 | 이 비율 이상 도달해야 Floor로 인정 |
| `advanced_success_threshold` | 0.7 | 한 답변이 Advanced 성공으로 카운트되는 기준 |
| `al_advanced_success_ratio` | 0.8 | AL 판정에 필요한 Advanced 성공률 |
| `calibration_min_repeat` | 2 | 편향 태그 반영에 필요한 반복 횟수 |
| `calibration_evidence_levels` | `[A]` | 보정에 쓸 샘플 신뢰도 |

## 음성 입력 설치

음성 기능은 선택 의존성이다. 로컬에서만 필요하다.

```bash
pip install -r requirements-audio.txt
```

`faster-whisper` 는 최초 실행 시 모델을 내려받는다(`small` 기준 약 500MB).
모델 크기는 `settings.yaml` 의 `opic_coach.stt.model` 에서 바꾼다.

> Whisper 계열은 읽기 좋은 전사를 만들려고 `um`/`uh` 를 빼먹는 경향이 있다.
> `verbatim_prompt` 로 완화하지만 완벽하지 않다. 다만 filler 가 빠져도 그 자리는
> pause 로 남기 때문에 hesitation 자체는 지표에 잡힌다.

## 환경 변수

`OPIC_DIR` (기본 `~/opic-coach`) — 샘플/노트/세션 리포트 저장 경로.
