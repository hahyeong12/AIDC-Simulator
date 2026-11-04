"""서버 배정안 생성·검증과 점유 원장. GUI/SQLite와 독립된 가상 용량 규칙."""
from dataclasses import dataclass, asdict
from itertools import combinations, product, islice


@dataclass(frozen=True)
class ServerSpec:
    key: str
    name: str
    gpu: int
    power: int


SERVERS = (ServerSpec('A', 'Server A', 4, 4), ServerSpec('B', 'Server B', 3, 2),
           ServerSpec('C', 'Server C', 2, 3), ServerSpec('D', 'Server D', 1, 1))


@dataclass(frozen=True)
class ServerHealth:
    state: str = 'HEALTHY'
    repair_left: int = 0
    reason: str = ''

    def __post_init__(self):
        if (self.state not in ('HEALTHY', 'FAULT', 'REPAIRING')
                or type(self.repair_left) is not int
                or (self.state == 'REPAIRING' and self.repair_left not in (10, 20))
                or (self.state != 'REPAIRING' and self.repair_left != 0)
                or not isinstance(self.reason, str)):
            raise ValueError('저장된 서버 장애/복구 상태가 올바르지 않습니다.')


@dataclass(frozen=True)
class ServerSlice:
    server_id: str
    gpu_slots: tuple[int, ...]
    power: int

    @property
    def gpu(self):
        return len(self.gpu_slots)


@dataclass(frozen=True)
class Allocation:
    playthrough_id: int
    slices: tuple[ServerSlice, ...]
    legacy: bool = False
    reconstructed: bool = False

    @property
    def gpu(self):
        return sum(s.gpu for s in self.slices)

    @property
    def power(self):
        return sum(s.power for s in self.slices)

    def payload(self):
        return asdict(self)

    @classmethod
    def from_payload(cls, value):
        return cls(value['playthrough_id'], tuple(ServerSlice(s['server_id'], tuple(s['gpu_slots']), s['power'])
                                                  for s in value['slices']),
                   value.get('legacy', False), value.get('reconstructed', False))


class ServerPool:
    def __init__(self):
        self.allocations = {}
        self.hardware = {s.key:ServerHealth() for s in SERVERS}

    def available(self):
        """정상 서버의 미점유 자원만 가용량으로 반환합니다."""
        return tuple(sum((s.gpu, s.power)[i]-self.usage(s.key)[i] for s in SERVERS
                         if self.hardware[s.key].state == 'HEALTHY') for i in (0, 1))

    def excluding(self, playthrough_id):
        """미리보기 전용 복사본. 해당 수행만 제외하고 다른 고객은 유지합니다."""
        pool = ServerPool()
        pool.hardware = dict(self.hardware)
        pool.allocations = {pid:a for pid,a in self.allocations.items() if pid != playthrough_id}
        return pool

    def usage(self, server_id):
        parts = [s for a in self.allocations.values() for s in a.slices if s.server_id == server_id]
        return sum(s.gpu for s in parts), sum(s.power for s in parts)

    @property
    def gpu_used(self):
        return sum(a.gpu for a in self.allocations.values())

    @property
    def power_used(self):
        return sum(a.power for a in self.allocations.values())

    def free_slots(self, spec):
        occupied = {slot for a in self.allocations.values() for s in a.slices
                    if s.server_id == spec.key for slot in s.gpu_slots}
        return tuple(i for i in range(spec.gpu) if i not in occupied)

    def plans(self, gpu, power, preferred=()):
        """GPU/전력이 모두 양수인 조각만 허용. 적은 서버, A~D, 큰 조각 순서."""
        if type(gpu) is not int or type(power) is not int or min(gpu, power) <= 0:
            raise ValueError('배정 GPU와 전력은 양의 정수여야 합니다.')
        healthy = tuple(s for s in SERVERS if self.hardware[s.key].state == 'HEALTHY')
        preferred_slots = {s.server_id:set(s.gpu_slots) for s in preferred}
        for count in range(1, len(healthy)+1):
            for group in combinations(healthy, count):
                capacities = [(s, self.free_slots(s), s.power-self.usage(s.key)[1]) for s in group]
                capacities = [(s, tuple(sorted(free, key=lambda slot:(slot not in preferred_slots.get(s.key, ()), slot))), p)
                              for s,free,p in capacities]
                if sum(len(free) for _, free, _ in capacities) < gpu or sum(p for _, _, p in capacities) < power:
                    continue
                choices = [[(g, p) for g in range(min(gpu, len(free)), 0, -1)
                            for p in range(min(power, available), 0, -1)] for _, free, available in capacities]
                for parts in product(*choices):
                    if sum(g for g, _ in parts) == gpu and sum(p for _, p in parts) == power:
                        yield tuple(ServerSlice(s.key, tuple(sorted(free[:g])), p)
                                    for (s, free, _), (g, p) in zip(capacities, parts))

    def plan(self, gpu, power):
        return next(self.plans(gpu, power), None)

    def options(self, gpu, power):
        """기존 추천 순서의 서로 다른 배분 최대 3개. 슬롯 순열은 별도 안이 아닙니다."""
        return tuple(islice(self.plans(gpu, power), 3))

    def validate_plan(self, parts, gpu, power):
        """사용자가 고른 고정 슬롯을 현재 원장과 대조하며 점유하지 않습니다."""
        if (not isinstance(parts, tuple) or not parts
                or any(not isinstance(s, ServerSlice) or not isinstance(s.gpu_slots, tuple) for s in parts)):
            raise ValueError('서버 배정 계획의 형식이 올바르지 않습니다.')
        if (sum(s.gpu for s in parts), sum(s.power for s in parts)) != (gpu, power):
            raise ValueError('선택한 서버 배정 계획의 GPU·전력 합계가 운영 모드와 다릅니다.')
        self._validate_slices(parts)

    def reserve(self, allocation):
        if type(allocation.playthrough_id) is not int or allocation.playthrough_id <= 0:
            raise ValueError('수행 ID가 올바르지 않습니다.')
        if allocation.playthrough_id in self.allocations:
            raise ValueError('이미 서버 자원을 배정한 수행입니다.')
        self._validate_slices(allocation.slices, legacy=allocation.legacy)
        self.allocations[allocation.playthrough_id] = allocation

    def _validate_slices(self, parts, legacy=False):
        if not parts or len({s.server_id for s in parts}) != len(parts):
            raise ValueError('서버별 배정 조각이 중복되거나 없습니다.')
        for part in parts:
            spec = next((s for s in SERVERS if s.key == part.server_id), None)
            if (spec is None or self.hardware[spec.key].state != 'HEALTHY'
                    or type(part.power) is not int or part.power < 0
                    or any(type(i) is not int for i in part.gpu_slots)
                    or len(set(part.gpu_slots)) != part.gpu
                    or not set(part.gpu_slots) <= set(self.free_slots(spec))
                    or part.power+self.usage(spec.key)[1] > spec.power
                    or (not legacy and (part.gpu == 0 or part.power == 0))
                    or part.gpu+part.power == 0):
                raise ValueError('서버별 GPU·전력 조건이 성립하지 않거나 이미 점유한 슬롯입니다.')

    def migration_options(self, playthrough_id):
        current = self.allocations[playthrough_id]
        pool = self.excluding(playthrough_id)
        old = {s.server_id:s for s in current.slices if self.hardware[s.server_id].state == 'HEALTHY'}
        def preservation(parts):
            gpu = sum(len(set(s.gpu_slots) & set(old[s.server_id].gpu_slots)) for s in parts if s.server_id in old)
            power = sum(min(s.power, old[s.server_id].power) for s in parts if s.server_id in old)
            return -gpu, -power
        # 정렬 동률에는 기존 탐색 순서가 유지됩니다. 조회용 복사본만 사용합니다.
        plans = sorted(pool.plans(current.gpu, current.power, preferred=current.slices), key=preservation)
        return tuple(plans[:3])

    def release(self, playthrough_id):
        if playthrough_id not in self.allocations:
            raise ValueError('이미 반환했거나 배정하지 않은 수행입니다.')
        return self.allocations.pop(playthrough_id)

    def restore_legacy(self, jobs):
        """과거 진행 작업은 가능하면 공동 탐색, 불가능하면 독립 자원 호환 배치."""
        jobs = list(jobs)
        failed = set()
        def search(index):
            if index == len(jobs):
                return True
            pid, gpu, power = jobs[index]
            key = (index, tuple(self.usage(s.key) for s in SERVERS))
            if key in failed:
                return False
            for parts in self.plans(gpu, power):
                self.reserve(Allocation(pid, parts, reconstructed=True))
                if search(index+1):
                    return True
                self.release(pid)
            failed.add(key)
            return False
        if search(0):
            return
        for pid, gpu, power in jobs:
            remaining_gpu, remaining_power = gpu, power
            parts = []
            for spec in SERVERS:
                free = self.free_slots(spec)
                g = min(remaining_gpu, len(free))
                p = min(remaining_power, spec.power-self.usage(spec.key)[1])
                if g or p:
                    parts.append(ServerSlice(spec.key, free[:g], p))
                remaining_gpu -= g
                remaining_power -= p
            if remaining_gpu or remaining_power:
                raise ValueError('과거 점유가 데이터센터 전체 용량을 초과합니다.')
            self.reserve(Allocation(pid, tuple(parts), legacy=True, reconstructed=True))
