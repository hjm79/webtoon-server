# Manager-embedded reader

원본 `https://github.com/murianwind/webtoon-server`의 독립 실행·프로필·읽음 기록 기능을 유지하며 관리기 내부에서 읽는 기능을 추가한다. 기존 MIT LICENSE와 저작권 고지는 유지한다.

## 허용 관리기 주소

```text
EMBED_ALLOWED_ORIGINS=http://192.168.1.26:8230
```

쉼표로 여러 origin을 지정할 수 있다. HTTP(S)의 정확한 origin만 허용하며 wildcard·경로·쿼리·사용자 정보가 포함된 값은 거절한다. 기본값은 같은 origin의 프레임만 허용한다. 설정은 CSP `frame-ancestors`와 내장 리더 메시지 검증에 함께 사용한다.

```text
/reader.html?series=<series-id>&embed=1&parent_origin=http%3A%2F%2F192.168.1.26%3A8230
```

회차가 없는 series-only URL은 브라우저의 기존 인증으로 `/api/series/{id}/continue`를 조회해 첫 회차 또는 이어보던 위치를 연다. 기존 chapter/page deep link는 유지한다. 인증·프로필·접속 시간 제한을 우회하지 않는다.

메시지는 지정한 부모 origin으로만 전송하며, 부모는 `event.origin`, `event.source`, 메시지의 source/version을 검증한다. 닫기 요청 시 읽음 위치 저장에 성공한 뒤 close를 보낸다. 저장 실패 시 리더와 재시도 안내를 유지한다.

동명 작품은 platform을 지정해 조회한다. 플랫폼을 생략했거나 같은 플랫폼 안에서 여러 작품이 일치하면 lookup은 임의로 고르지 않고 HTTP 409를 반환한다. 고유한 보관 라이브러리 작품은 기존처럼 조회할 수 있다.

## 빌드와 테스트

```sh
docker build -f Dockerfile.fork -t webtoon-server:fork .
python -m pytest -q
node --test tests/js/*.cjs
```

기반 이미지 digest는 `Dockerfile.fork`에 고정한다. 새 의존성이나 기반 이미지로 바꿀 때는 전체 회귀 테스트와 실제 내장 리더 표시·읽음 위치 저장을 다시 검증한다.
