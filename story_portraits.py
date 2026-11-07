"""독창적인 Canvas 인물화. 대화 데이터와 독립된 교체 가능한 렌더러."""


def draw_portrait(canvas, role, active=True):
    """같은 인터페이스에서 PNG 렌더러로 교체할 수 있습니다."""
    canvas.delete('all')
    accent = '#50d7ca' if role == 'player' else '#8caeff'
    canvas.configure(bg='#101c2b', highlightthickness=2,
                     highlightbackground=accent if active else '#29374a')
    if role not in ('player', 'mentor'):
        # 고객/시스템은 인물과 다른 관제 신호 문양입니다.
        for radius in (40, 28, 12):
            canvas.create_oval(60-radius, 80-radius, 60+radius, 80+radius,
                               outline=accent, width=2, tags='signal')
        canvas.create_line(12, 80, 108, 80, fill=accent, tags='signal')
        return
    tags = ('character', role)
    canvas.create_line(10, 12, 34, 12, 34, 18, fill=accent, tags=tags)
    canvas.create_line(86, 148, 110, 148, 110, 130, fill=accent, tags=tags)
    # 성별을 정하지 않는 반가면과 작업복 실루엣. 선배는 긴 코트와 헤드셋을 착용합니다.
    coat = '#30485f' if role == 'player' else '#424967'
    canvas.create_polygon(15, 160, 20, 120, 43, 103, 77, 103, 100, 120, 105, 160,
                          fill=coat, outline='#73829a', width=2, tags=tags)
    canvas.create_polygon(43, 104, 60, 122, 77, 104, 70, 133, 50, 133,
                          fill='#111e2c', tags=tags)
    canvas.create_line(60, 128, 60, 158, fill=accent, width=2, tags=tags)
    canvas.create_rectangle(77, 128, 90, 138, fill=accent, outline='', tags=tags)
    canvas.create_rectangle(51, 88, 69, 107, fill='#b3a59b', outline='', tags=tags)
    canvas.create_oval(35, 34, 85, 100, fill='#c3b7aa', outline='#788495', tags=tags)
    if role == 'player':
        canvas.create_polygon(32, 65, 33, 40, 43, 25, 70, 24, 87, 40, 86, 62,
                              75, 48, 65, 45, 44, 52, fill='#253546', tags=(*tags, 'hair'))
    else:
        canvas.create_polygon(32, 64, 30, 41, 47, 21, 79, 27, 89, 44, 84, 70,
                              76, 42, 51, 47, 38, 63, fill='#a1a9bb', tags=(*tags, 'hair'))
        canvas.create_arc(28, 31, 93, 95, start=0, extent=180, style='arc',
                          outline='#1b293c', width=5, tags=(*tags, 'headset'))
        canvas.create_rectangle(81, 57, 90, 79, fill='#182a40', outline=accent, tags=tags)
        canvas.create_line(86, 76, 80, 90, 68, 90, fill=accent, width=2, tags=tags)
    canvas.create_polygon(38, 62, 82, 62, 78, 77, 43, 77,
                          fill='#132b3c', outline=accent, tags=(*tags, 'visor'))
    canvas.create_line(45, 67, 56, 67, fill=accent, width=2, tags=tags)
    canvas.create_line(64, 67, 75, 67, fill=accent, width=2, tags=tags)
    canvas.create_line(52, 86, 66, 86, fill='#766f70', tags=tags)
    if not active:
        canvas.create_rectangle(0, 0, 120, 165, fill='#07101b', stipple='gray50',
                                outline='', tags='inactive')
