"""실행 중인 게임 저장 파일의 중복 사용 방지. 종료 시 OS 잠금을 반환합니다."""
import os


class SaveLease:
    def __init__(self, path):
        self.file = None
        lock_path = str(path) + '.lock'
        handle = open(lock_path, 'a+b')
        try:
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ValueError('이 저장 슬롯은 다른 게임에서 사용 중입니다. 먼저 해당 게임을 종료해 주세요.') from exc
        self.file = handle

    def close(self):
        if self.file is not None:
            # 파일은 지우지 않습니다. 잠금 파일 교체로 동시 실행이 허용되는 경합을 피합니다.
            self.file.close()
            self.file = None
