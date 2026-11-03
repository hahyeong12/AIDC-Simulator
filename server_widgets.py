"""Reusable Canvas chip and battery drawing functions. No game or sample state."""
BG = '#080e18'
PANEL = '#101c2a'
SURFACE = '#152536'
EDGE = '#2a4054'
TEXT = '#e5eef7'
MUTED = '#91a6bb'
CYAN = '#4ce4cd'
BLUE = '#74abff'
PURPLE = '#c2a0ff'
RED = '#ff6e7f'
FONT = 'Malgun Gothic'
MONO = 'Consolas'


OWNER_COLORS = {'sg': CYAN, 'jp': BLUE, 'us': PURPLE}

def availability_hint(available, total, required=None, fault=False):
    if fault:
        return 'FAULT', RED
    if required is not None:
        gap = max(0, required-available)
        return (f'요청{required} · {gap}개 부족', RED) if gap else (f'요청{required} · 가능', CYAN)
    return ('모두 가용' if available == total else '전체 배정' if available == 0 else f'가용 {available}개'), MUTED


def ink(canvas, x, y, text, size=10, color=TEXT, bold=False, anchor='nw', **kwargs):
    return canvas.create_text(x, y, text=text, anchor=anchor, fill=color,
                              font=(FONT, size, 'bold' if bold else 'normal'), **kwargs)


def gpu_state(usage, index, installed=True):
    """샘플 값을 변경하지 않고 장비 한 개의 표시 상태만 해석합니다."""
    return 'empty' if not installed else 'fault' if usage.fault else 'busy' if index < usage.gpu else 'available'


def reset_hardware(canvas):
    canvas.gpu_leds = []
    canvas.gpu_traces = []


def gpu_module(canvas, x, y, width, height, state, owner=None, index=0, tags=(), body_tags=(), summary=False):
    """해상도와 무관하게 작은 PCB·칩·핀으로 표현합니다. 팬은 사용하지 않습니다."""
    width, height = min(width, 64), min(height, 27)
    color = RED if state == 'fault' else OWNER_COLORS.get(owner, CYAN) if state == 'busy' else CYAN
    empty = state == 'empty'
    board = '#0b101b' if state in ('fault', 'empty') else '#102e30' if state == 'available' else '#192b40'
    edge = '#283645' if empty else '#653d4a' if state == 'fault' else '#346a69' if state == 'available' else color
    # 바깥 장착 홈과 절삭된 PCB 모서리. 배터리의 단자/충전 막대는 사용하지 않습니다.
    canvas.create_rectangle(x, y, x+width, y+height, fill='#080f19', outline='#23374b', tags=tags)
    canvas.create_polygon(x+3, y+2, x+width-6, y+2, x+width-2, y+6,
                          x+width-2, y+height-3, x+6, y+height-3, x+3, y+height-6,
                          fill=board, outline=edge, tags=tags+body_tags+('gpu-body', f'gpu-{state}'))
    led = canvas.create_oval(x+width-6, y+3, x+width-3, y+6,
                             fill='#263342' if empty else color, outline='',
                             tags=tags+('gpu-led',)+(('available-gpu',) if state == 'available' else ()))
    canvas.gpu_leds.append((led, state))
    if empty:
        canvas.create_line(x+8, y+height/2, x+width-9, y+height/2,
                            fill='#263748', dash=(2, 3), tags=tags)
        ink(canvas, x+width/2, y+height/2, 'OFF', 7, '#536578', anchor='center', tags=tags+('gpu-state-label',))
        return
    code = owner.upper() if owner else ''
    if summary:
        # 상단은 실리콘 다이와 핀만 표시하는 요약 아이콘입니다.
        cx, cy = x+width/2-1, y+height/2
        for offset in (-4, 0, 4):
            canvas.create_line(cx-8, cy+offset, cx+8, cy+offset, fill=edge, tags=tags)
            canvas.create_line(cx+offset, cy-7, cx+offset, cy+7, fill=edge, tags=tags)
        canvas.create_rectangle(cx-5, cy-5, cx+5, cy+5, fill='#08131b', outline=color, tags=tags+('gpu-die',))
        ink(canvas, cx, cy, '!' if state == 'fault' else code[:1] if state == 'busy' else '·',
            7, color, True, anchor='center', tags=tags)
        return
    fault = state == 'fault'
    cx, cy = (x+width/2, y+8) if fault else (x+12, y+height/2)
    for offset in (-3, 0, 3):
        canvas.create_line(cx-7, cy+offset, cx+7, cy+offset, fill='#39404b' if fault else edge, tags=tags)
        canvas.create_line(cx+offset, cy-6, cx+offset, cy+6, fill='#39404b' if fault else '#b39a64', tags=tags+('gpu-contact',))
    canvas.create_rectangle(cx-4, cy-4, cx+4, cy+4, fill='#080d15' if fault else '#091f28',
                            outline='#64505b' if fault else color, tags=tags+('gpu-die',))
    # 단선 형태의 회로와 코너 빛으로 정상 활성 상태를 표현합니다.
    trace_y = y+4 if fault else y+height-4
    trace = canvas.create_line(x+5, trace_y-2, x+5, trace_y, x+width-9, trace_y,
                                fill='#323640' if fault else color, tags=tags+('gpu-circuit',))
    canvas.gpu_traces.append((trace, state, color))
    if fault:
        ink(canvas, x+width/2, y+20, 'FAULT', 7, RED, True, anchor='center', tags=tags+('gpu-state-label',))
    else:
        ink(canvas, cx, cy, str(index+1), 6, TEXT, anchor='center', tags=tags)
        ink(canvas, x+width-7, cy, code if state == 'busy' else 'ON', 7, color, True,
            anchor='e', tags=tags+('gpu-owner-code', 'gpu-state-label'))


def animate_hardware(canvas, phase):
    for led, state in canvas.gpu_leds:
        if state == 'available':
            canvas.itemconfigure(led, fill=CYAN if phase % 2 else '#329f97')
    for trace, state, color in canvas.gpu_traces:
        if state in ('available', 'busy'):
            canvas.itemconfigure(trace, fill=color if phase % 2 else '#2c515a')


def battery(canvas, x, y, width, height, available, total, tags=(), shortage=False):
    """가용 전력을 채운 배터리. GPU 슬롯과 형태로 구분합니다."""
    color = RED if shortage else CYAN if available else MUTED
    canvas.create_rectangle(x, y, x+width-6, y+height, outline=color, width=2, tags=tags+('battery-frame',))
    canvas.create_rectangle(x+width-5, y+height*.32, x+width, y+height*.68,
                            fill=color, outline='', tags=tags)
    inside = width-14
    if available:
        canvas.create_rectangle(x+4, y+4, x+4+inside*available/total, y+height-4,
                                fill=color, outline='', tags=tags)
    # 숫자를 함께 표시하므로 색상만으로 잔량을 구분하지 않아도 됩니다.
    canvas.create_text(x+(width-6)/2, y+height/2, text=f'가용 {available/total:.0%}',
                       fill=BG if available/total >= .6 else TEXT, font=(MONO, 10, 'bold'), tags=tags+('battery-percent',))
