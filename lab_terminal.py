"""v0.9-4a 교육용 가상 Linux 터미널: 허용 목록 기반 명령 해석과 결과 생성(GUI/SQLite 독립).

- 실제 호스트에서 명령을 실행하지 않습니다(os.system/subprocess/eval/exec 미사용). `shlex.split`으로 토큰만 나눕니다.
- 객관식(L1)·블록 조립(L2)·직접 입력(L3)이 모두 같은 `run_command(line, observation)`을 사용합니다.
- 출력은 `lab_model.observe()`의 같은 관찰 결과에서 계산하며 게임 상태를 바꾸지 않습니다(읽기 명령만 지원).
- 출력 형식은 Linux(iputils ping, iproute2 ip)와 비슷하게 만들되 교육용 시뮬레이션입니다. 실제와 다른 오류 안내에는
  '[교육용 안내]'를 붙입니다.
"""
from dataclasses import dataclass, field
import ipaddress
import shlex

from lab_model import LAB_NETWORK

SUPPORTED = ('help', 'ping', 'ip addr', 'ip route', 'clear')
FORBIDDEN = ('|', ';', '&', '>', '<', '`', '$', '\\')
# 실제 Linux에 있지만 이 프로토타입에서는 지원하지 않는 명령(없는 명령과 구분해 안내합니다).
KNOWN_UNSUPPORTED = {
    'traceroute', 'tracepath', 'ss', 'netstat', 'curl', 'wget', 'nc', 'dig', 'nslookup', 'host', 'getent',
    'systemctl', 'journalctl', 'ps', 'top', 'htop', 'free', 'df', 'nvidia-smi', 'ifconfig', 'route', 'arp',
    'ls', 'cat', 'cd', 'pwd', 'echo', 'grep', 'less', 'tail', 'man', 'whoami', 'hostname', 'uname',
}
MUTATING = {'rm', 'sudo', 'su', 'shutdown', 'reboot', 'halt', 'poweroff', 'kill', 'killall', 'mv', 'cp', 'chmod',
            'chown', 'dd', 'mkfs', 'iptables', 'nft'}
IP_OBJECTS = {'addr': 'addr', 'address': 'addr', 'a': 'addr', 'route': 'route', 'r': 'route', 'ro': 'route'}
IP_MUTATING_VERBS = {'add', 'del', 'delete', 'change', 'replace', 'flush', 'set', 'append'}
PING_DEFAULT_COUNT = 4
PING_MAX_COUNT = 10

# 명령어 학습(L1/L2)에서 쓰는 의미 설명. 같은 표를 블록 설명과 터미널 help에서도 사용합니다.
COMMAND_SPECS = {
    'ping': {
        'title': 'ping', 'summary': '대상과의 ICMP 응답 확인',
        'purpose': '대상 주소로 ICMP Echo 요청을 보내 응답(Echo Reply)이 돌아오는지 확인합니다.',
        'can': ['대상까지 ICMP 패킷이 오가는지(도달 가능성)', '응답 시간(RTT)과 손실률', '응답한 장비까지의 대략적 TTL'],
        'cannot': ['응답이 없는 정확한 원인(경로 단절·장비 정지·ICMP 차단 등을 구분하지 못함)',
                   '애플리케이션·서비스 포트의 정상 여부', '패킷이 지나간 경로 자체'],
    },
    'ip route': {
        'title': 'ip route', 'summary': '라우팅 테이블 확인',
        'purpose': '이 단말이 목적지 네트워크로 패킷을 어느 게이트웨이·인터페이스로 보내도록 설정했는지 보여줍니다.',
        'can': ['목적지별 다음 홉(게이트웨이)과 출력 인터페이스', '현재 사용하도록 설정된 경로(주/백업)'],
        'cannot': ['그 경로로 실제 통신이 성공하는지(설정된 경로가 있어도 먼 구간이 끊길 수 있음)', '먼 구간 링크의 상태'],
    },
    'ip addr': {
        'title': 'ip addr', 'summary': '인터페이스 주소 확인',
        'purpose': '이 단말의 네트워크 인터페이스와 할당된 IP 주소, 인터페이스 상태(UP/DOWN)를 보여줍니다.',
        'can': ['이 단말의 인터페이스 이름·IP 주소·서브넷', '이 단말 인터페이스의 링크 상태'],
        'cannot': ['다른 장비(라우터·서버)의 상태', '먼 구간의 단절 여부', '대상까지 통신 가능 여부'],
    },
}
BLOCKS = {
    'command': {'ping': '대상에게 응답을 요청하는 연결 시험 명령', 'ip addr': 'ip 명령 + addr 객체: 내 인터페이스 주소 조회',
                'ip route': 'ip 명령 + route 객체: 라우팅 테이블 조회'},
    'option': {'-c 3': '-c(count): 3번만 보내고 멈춤', '-c 1': '-c(count): 1번만 보내고 멈춤'},
}


class CommandError(ValueError):
    def __init__(self, message, hint=''):
        super().__init__(message)
        self.message, self.hint = message, hint


@dataclass(frozen=True)
class ParsedCommand:
    name: str                   # 'help' | 'ping' | 'ip addr' | 'ip route' | 'clear'
    tokens: tuple
    count: int | None = None
    target: str | None = None
    device: str | None = None


@dataclass
class CommandResult:
    line: str
    ok: bool                    # 명령 구문이 올바르게 해석·실행되었는지(통신 성공 여부와 다름)
    output: str
    kind: str = 'output'        # 'output' | 'error' | 'clear' | 'empty'
    command: str | None = None
    hint: str = ''
    time_label: str = ''
    facts: dict = field(default_factory=dict)


def parse_command(line):
    """허용 목록 기반 해석. 잘못된 구문은 CommandError(실제와 비슷한 메시지, 교육용 힌트)를 냅니다."""
    text = line.strip()
    if any(ch in text for ch in FORBIDDEN):
        raise CommandError('[교육용 안내] 이 터미널은 파이프(|)·리디렉션(>, <)·명령 연결(;, &&)·변수 치환($)을 지원하지 않습니다.',
                           '명령은 한 줄에 하나씩 입력해 주세요.')
    try:
        tokens = tuple(shlex.split(text, posix=True))
    except ValueError:
        raise CommandError('[교육용 안내] 따옴표가 닫히지 않았습니다.', '따옴표 없이 입력해도 됩니다.') from None
    if not tokens:
        return None
    head = tokens[0]
    if head == 'help':
        return ParsedCommand('help', tokens)
    if head == 'clear':
        return ParsedCommand('clear', tokens)
    if head == 'ping':
        return _parse_ping(tokens)
    if head == 'ip':
        return _parse_ip(tokens)
    if head in MUTATING:
        raise CommandError(f'[교육용 안내] {head}: 상태를 바꾸는 명령은 이 교육용 터미널에서 실행할 수 없습니다(읽기 명령만 지원).',
                           '네트워크 조치는 관제실의 대응 버튼을 사용하세요.')
    if head in KNOWN_UNSUPPORTED:
        raise CommandError(f'[교육용 안내] {head}: 실제 Linux 명령이지만 이 프로토타입은 아직 지원하지 않습니다.',
                           '지원 명령: help, ping, ip addr, ip route, clear')
    raise CommandError(f'bash: {head}: command not found', '지원 명령은 help로 확인할 수 있습니다.')


def _parse_ping(tokens):
    count, target, rest = None, None, list(tokens[1:])
    while rest:
        token = rest.pop(0)
        if token == '-c':
            if not rest:
                raise CommandError("ping: option requires an argument -- 'c'", '-c 뒤에 보낼 횟수를 적어 주세요. 예: -c 3')
            value = rest.pop(0)
            if not value.isdigit() or not 1 <= int(value) <= PING_MAX_COUNT:
                raise CommandError(f"ping: invalid argument: '{value}'",
                                   f'[교육용 안내] 이 터미널은 -c 값으로 1~{PING_MAX_COUNT}만 지원합니다.')
            count = int(value)
        elif token.startswith('-c') and len(token) > 2:
            rest.insert(0, token[2:])
            rest.insert(0, '-c')
        elif token.startswith('-') and len(token) > 1:
            letter = token[2:] if token.startswith('--') else token[1]
            raise CommandError(f"ping: invalid option -- '{letter}'" if not token.startswith('--')
                               else f"ping: unrecognized option '{token}'",
                               '[교육용 안내] 이 터미널의 ping은 -c(보낼 횟수) 옵션만 지원합니다.')
        elif target is None:
            target = token
        else:
            raise CommandError('[교육용 안내] ping: 대상 주소는 하나만 입력합니다.', '예: ping -c 3 10.0.0.20')
    if target is None:
        raise CommandError('ping: usage error: Destination address required', '보낼 대상 주소를 마지막에 적어 주세요.')
    return ParsedCommand('ping', tokens, count=count, target=target)


def _parse_ip(tokens):
    if len(tokens) == 1:
        raise CommandError('Usage: ip [ OPTIONS ] OBJECT { COMMAND | help }',
                           '[교육용 안내] 이 터미널은 ip addr, ip route를 지원합니다.')
    obj = IP_OBJECTS.get(tokens[1])
    if obj is None:
        if tokens[1].startswith('-'):
            raise CommandError(f'[교육용 안내] ip: 옵션 {tokens[1]}은 지원하지 않습니다.', '예: ip addr, ip route')
        raise CommandError(f'Object "{tokens[1]}" is unknown, try "ip help".', '이 터미널은 ip addr, ip route를 지원합니다.')
    rest = list(tokens[2:])
    full = 'address' if obj == 'addr' else 'route'
    if rest and rest[0] in IP_MUTATING_VERBS:
        raise CommandError(f'[교육용 안내] ip {obj} {rest[0]}: 설정을 바꾸는 명령은 이 교육용 터미널에서 실행할 수 없습니다.',
                           '네트워크 조치는 관제실의 대응 버튼을 사용하세요.')
    if rest and rest[0] in ('show', 'list', 'ls'):
        rest.pop(0)
    device = None
    if obj == 'addr' and rest:
        if rest[0] == 'dev':
            rest.pop(0)
        if rest and not rest[0].startswith('-') and _known_device(rest[0]):
            device = rest.pop(0)
        elif rest and _looks_like_device(rest[0]):
            raise CommandError(f'Device "{rest[0]}" does not exist.', '인터페이스 이름은 ip addr로 확인할 수 있습니다.')
    if rest:
        hint = {'addr': 'ip addr은 대상 주소나 -c 옵션을 받지 않습니다. 이 단말의 인터페이스 주소를 보여줍니다.',
                'route': 'ip route는 -c 옵션이나 대상 주소 없이 전체 라우팅 테이블을 보여줍니다. '
                         '(실제 Linux의 ip route get <주소>는 이 프로토타입에서 미지원)'}[obj]
        raise CommandError(f'Command "{rest[0]}" is unknown, try "ip {full} help".', hint)
    return ParsedCommand('ip '+obj, tokens, device=device)


def _known_device(name):
    return any(i['name'] == name for i in LAB_NETWORK['interfaces'])


def _looks_like_device(name):
    return name.isalnum() and not name.isdigit() and name not in ('help',)


def run_command(line, observation):
    """한 줄을 해석해 현재 관찰 상태에서 출력을 계산합니다. 객관식·블록·터미널이 모두 이 함수를 씁니다."""
    time_label = observation.time_label
    try:
        parsed = parse_command(line)
    except CommandError as error:
        return CommandResult(line, False, error.message, 'error', hint=error.hint, time_label=time_label)
    if parsed is None:
        return CommandResult(line, True, '', 'empty', time_label=time_label)
    if parsed.name == 'clear':
        return CommandResult(line, True, '', 'clear', 'clear', time_label=time_label)
    if parsed.name == 'help':
        return CommandResult(line, True, help_text(), command='help', time_label=time_label)
    if parsed.name == 'ip addr':
        output, facts = ip_addr(parsed.device)
    elif parsed.name == 'ip route':
        output, facts = ip_route(observation)
    else:
        output, facts = ping(parsed, observation)
    return CommandResult(line, True, output, command=parsed.name, time_label=time_label, facts=facts)


def help_text():
    lines = ['교육용 가상 터미널 (실제 Windows/Linux 명령을 실행하지 않습니다)', '',
             '지원 명령:']
    for name in ('ping', 'ip addr', 'ip route'):
        lines.append(f'  {name:<10} {COMMAND_SPECS[name]["summary"]}')
    lines += ['  help       이 도움말', '  clear      화면 지우기', '',
              '사용 예 형식:  ping [-c 횟수] <주소>     ip addr [show <인터페이스>]     ip route',
              '읽기 명령만 지원합니다. 파이프·리디렉션·파일 명령은 없습니다.']
    return '\n'.join(lines)


def ip_addr(device=None):
    lines = []
    for index, iface in enumerate(LAB_NETWORK['interfaces'], start=1):
        if device and iface['name'] != device:
            continue
        name, address, prefix = iface['name'], iface['address'], iface['prefix']
        if name == 'lo':
            lines += [f'{index}: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000',
                      '    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00',
                      f'    inet {address}/{prefix} scope host lo']
        else:
            network = ipaddress.ip_network(f'{address}/{prefix}', strict=False)
            lines += [f'{index}: {name}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000',
                      f'    link/ether {iface["mac"]} brd ff:ff:ff:ff:ff:ff',
                      f'    inet {address}/{prefix} brd {network.broadcast_address} scope global {name}']
        lines.append('       valid_lft forever preferred_lft forever')
    # 이 미션의 단절은 라우터 너머 구간이므로 이 단말의 인터페이스는 모두 UP입니다.
    return '\n'.join(lines), {'interfaces': [i['name'] for i in LAB_NETWORK['interfaces'] if not device or i['name'] == device],
                              'all_up': True}


def active_route(observation):
    return LAB_NETWORK['routers'][observation.network.active_path]


def ip_route(observation):
    router = active_route(observation)
    lines = [f'{LAB_NETWORK["aidc_subnet"]} via {router["address"]} dev {router["dev"]} proto static']
    for iface in LAB_NETWORK['interfaces']:
        if iface['name'] == 'lo':
            continue
        network = ipaddress.ip_network(f'{iface["address"]}/{iface["prefix"]}', strict=False)
        lines.append(f'{network} dev {iface["name"]} proto kernel scope link src {iface["address"]}')
    return '\n'.join(lines), {'aidc_via': router['address'], 'aidc_dev': router['dev'],
                              'path': observation.network.active_path}


def _destination(observation, target):
    """대상 주소의 교육용 도달 결과: (kind, responder, ttl, base_ms). kind = reply | timeout | unreachable | no_route."""
    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        return 'unknown_host', None, None, None
    net = observation.network
    local = {i['address'] for i in LAB_NETWORK['interfaces']}
    if str(address) in local or address.is_loopback:
        return 'reply', str(address), 64, .04
    for iface in LAB_NETWORK['interfaces']:
        if iface['name'] == 'lo':
            continue
        if address in ipaddress.ip_network(f'{iface["address"]}/{iface["prefix"]}', strict=False):
            router = next(r for r in LAB_NETWORK['routers'].values() if r['dev'] == iface['name'])
            if str(address) == router['address']:
                return 'reply', str(address), 64, .6
            return 'unreachable', iface['address'], None, None
    if address in ipaddress.ip_network(LAB_NETWORK['aidc_subnet']):
        if not net.link_ok:
            return 'timeout', None, None, None   # 설정된 경로는 있지만 먼 구간이 끊겨 응답이 오지 않습니다.
        backup = net.active_path == 'backup'
        base = 31.8 if backup else 12.4
        if net.congested:
            base += 80
        hops = 1 if backup else 0
        if str(address) == LAB_NETWORK['aidc_gateway']['address']:
            return 'reply', str(address), 63-hops, base-1
        key = next((k for k, v in LAB_NETWORK['servers'].items() if v == str(address)), None)
        if key is None:
            return 'unreachable', LAB_NETWORK['aidc_gateway']['address'], None, None
        if observation.server(key).health != 'HEALTHY':
            return 'timeout', None, None, None   # 교육용 모델: 장애·복구 중인 서버는 응답하지 않습니다.
        return 'reply', str(address), 62-hops, base
    return 'no_route', None, None, None


def ping(parsed, observation):
    count = parsed.count or PING_DEFAULT_COUNT
    target = parsed.target
    kind, responder, ttl, base = _destination(observation, target)
    facts = {'target': target, 'transmitted': count, 'received': 0, 'kind': kind,
             'path': observation.network.active_path, 'default_count': parsed.count is None}
    if kind == 'unknown_host':
        return (f'ping: {target}: Name or service not known\n'
                '[교육용 안내] 이 터미널은 이름 해석(DNS)을 지원하지 않습니다. IP 주소를 입력해 주세요.'), facts
    if kind == 'no_route':
        return 'ping: connect: Network is unreachable', facts
    lines = [f'PING {target} ({target}) 56(84) bytes of data.']
    received, times = 0, []
    for seq in range(1, count+1):
        if kind == 'reply':
            rtt = round(base + (seq*37 % 11)/10, 1)
            times.append(rtt)
            received += 1
            lines.append(f'64 bytes from {responder}: icmp_seq={seq} ttl={ttl} time={rtt} ms')
        elif kind == 'unreachable':
            lines.append(f'From {responder} icmp_seq={seq} Destination Host Unreachable')
    loss = round((count-received)/count*100)
    elapsed = (count-1)*1000 + (count*3 if kind != 'timeout' else count*12)
    lines += ['', f'--- {target} ping statistics ---']
    stats = f'{count} packets transmitted, {received} received'
    if kind == 'unreachable':
        stats += f', +{count} errors'
    lines.append(f'{stats}, {loss}% packet loss, time {elapsed}ms')
    if times:
        avg = sum(times)/len(times)
        mdev = (sum((t-avg)**2 for t in times)/len(times))**.5
        lines.append(f'rtt min/avg/max/mdev = {min(times):.3f}/{avg:.3f}/{max(times):.3f}/{mdev:.3f} ms')
    if parsed.count is None:
        lines.append(f'[교육용 안내] -c 없이 실행해 {PING_DEFAULT_COUNT}회 후 멈췄습니다. 실제 Linux의 ping은 Ctrl+C로 멈출 때까지 계속 보냅니다.')
    facts['received'] = received
    return '\n'.join(lines), facts


def interpret(result, observation):
    """초급·중급용 해석 도움. 단정하지 않고 관찰 사실과 그 한계만 말합니다(고급에서는 보여 주지 않음)."""
    if not result.ok:
        return result.hint
    facts = result.facts
    if result.command == 'ping':
        if facts['kind'] == 'reply':
            return ('응답이 돌아왔습니다. 대상까지 ICMP 수준의 통신이 가능합니다. '
                    '다만 고객 작업(애플리케이션)이 정상이라는 증명은 아닙니다.')
        if facts['kind'] == 'timeout':
            return ('응답이 하나도 오지 않았습니다(100% 손실). 경로 단절일 수도, 대상 장비가 멈췄거나 ICMP가 막혔을 수도 있습니다. '
                    'ping 실패만으로 원인을 단정하지 말고 가까운 게이트웨이 응답이나 라우팅 설정 같은 다른 증거와 비교해 보세요.')
        if facts['kind'] == 'unreachable':
            return '게이트웨이가 대상 장비를 찾지 못했다고 알려 왔습니다. 주소가 맞는지 다시 확인해 보세요.'
        return '대상으로 갈 경로가 없거나 주소 형식이 올바르지 않습니다.'
    if result.command == 'ip route':
        return (f'AIDC 네트워크({LAB_NETWORK["aidc_subnet"]})로 가는 패킷은 {facts["aidc_via"]}({facts["aidc_dev"]})로 보내도록 '
                '설정되어 있습니다. 설정된 경로가 있다는 것과 그 경로로 실제 통신이 되는지는 별개입니다.')
    if result.command == 'ip addr':
        return '이 단말의 인터페이스는 모두 UP이고 주소가 할당되어 있습니다. 라우터 너머 먼 구간의 상태는 이 명령으로 보이지 않습니다.'
    return ''


def assemble(command=None, option=None, target=None):
    """블록(명령·옵션·대상)을 실제 명령 문법 순서의 한 줄로 이어 붙입니다. 검증은 parse_command가 합니다."""
    return ' '.join(part for part in (command, option, target) if part)


def block_feedback(command=None, option=None, target=None):
    """블록 조립 피드백: 각 블록의 역할 + 같은 해석기에서 나온 구문 오류. 반환: (줄, 오류 목록)."""
    line = assemble(command, option, target)
    roles = []
    if command:
        roles.append(f'{command}: {BLOCKS["command"].get(command, "")}')
    else:
        roles.append('명령 블록이 비어 있습니다. 무엇을 확인할지부터 정하세요.')
    if option:
        roles.append(f'{option}: {BLOCKS["option"].get(option, "")}')
    if target:
        roles.append(f'{target}: 교육용 가상 대상 주소')
    errors = []
    if command:
        try:
            parse_command(line)
        except CommandError as error:
            errors.append(error.message + (f' — {error.hint}' if error.hint else ''))
    return line, roles, errors


# L1 객관식 질문. 정답 판정은 미션 결과와 무관하며 틀려도 미션을 실패시키지 않습니다.
CHOICE_QUESTION = '현재 서버까지 통신할 수 있는지 확인하려면 어떤 도구를 사용할까요?'
CHOICE_FIT = {
    'ping': ('best', '이 질문에 직접 답하는 도구입니다. 대상에 응답을 요청해 실제로 패킷이 오가는지 봅니다.'),
    'ip route': ('partial', '경로 설정을 보는 도구입니다. 경로가 설정돼 있어도 실제 통신 가능 여부는 알 수 없습니다. 다른 도구와 함께 쓰면 좋습니다.'),
    'ip addr': ('partial', '내 단말의 주소를 보는 도구입니다. 서버까지의 통신 가능 여부는 알려 주지 않습니다.'),
}


def choice_command(name, observation):
    """객관식 선택을 실제 명령 한 줄로 바꿉니다(블록·터미널과 같은 해석기로 실행)."""
    return f'ping -c 3 {observation.target_address}' if name == 'ping' else name
