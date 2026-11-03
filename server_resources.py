"""서버별 자동 배정과 점유 원장. GUI/SQLite와 독립된 가상 용량 규칙."""
from dataclasses import dataclass, asdict
from itertools import combinations, product


@dataclass(frozen=True)
class ServerSpec:
    key: str
    name: str
    gpu: int
    power: int


SERVERS = (ServerSpec('A', 'Server A', 4, 4), ServerSpec('B', 'Server B', 3, 2),
           ServerSpec('C', 'Server C', 2, 3), ServerSpec('D', 'Server D', 1, 1))


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

    def plans(self, gpu, power):
        """GPU/전력이 모두 양수인 조각만 허용. 적은 서버, A~D, 큰 조각 순서."""
        if type(gpu) is not int or type(power) is not int or min(gpu, power) <= 0:
            raise ValueError('배정 GPU와 전력은 양의 정수여야 합니다.')
        for count in range(1, len(SERVERS)+1):
            for group in combinations(SERVERS, count):
                capacities = [(s, self.free_slots(s), s.power-self.usage(s.key)[1]) for s in group]
                if sum(len(free) for _, free, _ in capacities) < gpu or sum(p for _, _, p in capacities) < power:
                    continue
                choices = [[(g, p) for g in range(min(gpu, len(free)), 0, -1)
                            for p in range(min(power, available), 0, -1)] for _, free, available in capacities]
                for parts in product(*choices):
                    if sum(g for g, _ in parts) == gpu and sum(p for _, p in parts) == power:
                        yield tuple(ServerSlice(s.key, free[:g], p)
                                    for (s, free, _), (g, p) in zip(capacities, parts))

    def plan(self, gpu, power):
        return next(self.plans(gpu, power), None)

    def reserve(self, allocation):
        if type(allocation.playthrough_id) is not int or allocation.playthrough_id <= 0:
            raise ValueError('수행 ID가 올바르지 않습니다.')
        if allocation.playthrough_id in self.allocations:
            raise ValueError('이미 서버 자원을 배정한 수행입니다.')
        if not allocation.slices or len({s.server_id for s in allocation.slices}) != len(allocation.slices):
            raise ValueError('서버별 배정 조각이 중복되거나 없습니다.')
        for part in allocation.slices:
            spec = next((s for s in SERVERS if s.key == part.server_id), None)
            if (spec is None or type(part.power) is not int or part.power < 0
                    or any(type(i) is not int for i in part.gpu_slots)
                    or len(set(part.gpu_slots)) != part.gpu
                    or not set(part.gpu_slots) <= set(self.free_slots(spec))
                    or part.power+self.usage(spec.key)[1] > spec.power
                    or (not allocation.legacy and (part.gpu == 0 or part.power == 0))
                    or part.gpu+part.power == 0):
                raise ValueError('서버별 GPU·전력 조건이 성립하지 않거나 이미 점유한 슬롯입니다.')
        self.allocations[allocation.playthrough_id] = allocation

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
