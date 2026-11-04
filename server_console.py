"""실제 Session의 서버 원장을 읽는 관제실. 배정/DB 변경은 수행하지 않습니다."""
import tkinter as tk
from tkinter import ttk

from server_resources import SERVERS
from game import GameState, game_time
from server_widgets import (BG, PANEL, SURFACE, EDGE, TEXT, MUTED, CYAN, RED, FONT,
                            ink, gpu_module, battery, reset_hardware, animate_hardware)


def customer_code(run):
    return {'싱가포르':'sg', '일본':'jp', '미국':'us'}.get(run.mission['country'], 'x')


def server_views(session, exclude_playthrough=None):
    runs = {r.playthrough_id:r for r in session.runs.values() if r.state.allocated}
    result = []
    for spec in SERVERS:
        slots = [None]*spec.gpu
        owners = []
        for pid, allocation in session.servers.allocations.items():
            if pid == exclude_playthrough:
                continue
            part = next((s for s in allocation.slices if s.server_id == spec.key), None)
            if part is None:
                continue
            run = runs[pid]
            item = {'request_id':run.request['id'], 'playthrough_id':pid, 'company':run.mission['company_name'],
                    'code':customer_code(run), 'gpu':part.gpu, 'power':part.power, 'phase':run.state.phase,
                    'network':run.state.phase in ('incident','paused') or (
                        run.state.phase=='recovering' and run.state.incident_occurred),
                    'hardware':bool(session.hardware_servers(run)), 'migration_left':run.migration_left,
                    'legacy':allocation.legacy, 'reconstructed':allocation.reconstructed}
            owners.append(item)
            for slot in part.gpu_slots:
                slots[slot] = item
        g, p = sum(o['gpu'] for o in owners), sum(o['power'] for o in owners)
        health = session.servers.hardware[spec.key]
        healthy = health.state == 'HEALTHY'
        result.append({'spec':spec, 'slots':slots, 'owners':owners, 'gpu_used':g, 'power_used':p,
                       'gpu_available':spec.gpu-g if healthy else 0, 'power_available':spec.power-p if healthy else 0,
                       'gpu_unavailable':0 if healthy else spec.gpu-g, 'power_unavailable':0 if healthy else spec.power-p,
                       'health':health.state, 'repair_left':health.repair_left, 'reason':health.reason,
                       'status':('ACTIVE' if owners else 'IDLE') if healthy else health.state,
                       'network':any(o['network'] for o in owners)})
    return result


class LiveOverview(tk.Canvas):
    def __init__(self, parent, session):
        super().__init__(parent, height=76, bg=PANEL, highlightthickness=1, highlightbackground=EDGE)
        self.session = session
        self.bind('<Configure>', lambda _: self.refresh())

    def refresh(self):
        self.delete('all'); reset_hardware(self)
        w = self.winfo_width()
        if w < 100:
            return
        views = server_views(self.session)
        gpu_total,power_total=sum(v['spec'].gpu for v in views),sum(v['spec'].power for v in views)
        self.values = {'gpu_total':gpu_total,'power_total':power_total,
                       'gpu_available':sum(v['gpu_available'] for v in views),
                       'power_available':sum(v['power_available'] for v in views),
                       'gpu_used':sum(v['gpu_used'] for v in views), 'power_used':sum(v['power_used'] for v in views),
                       'gpu_unavailable':sum(v['gpu_unavailable'] for v in views),
                       'power_unavailable':sum(v['power_unavailable'] for v in views),
                       'hardware':sum(v['health'] != 'HEALTHY' for v in views),
                       'active_servers':sum(bool(v['owners']) for v in views),
                       'jobs':len(self.session.servers.allocations),
                       'network':len({o['playthrough_id'] for v in views for o in v['owners']
                                      if o['network']})}
        g_end, p_end = w*.34, w*.66
        ink(self, 14, 6, 'GPU AVAILABLE', 9, MUTED, True)
        ink(self, 14, 25, f'{self.values["gpu_available"]:02d}', 26, CYAN, True)
        ink(self, 75, 43, f'/ {gpu_total}', 11, MUTED)
        modules = [(owner,v['health']) for v in views for owner in v['slots']]
        cw = (g_end-133)/5-4
        for i, (owner,health) in enumerate(modules):
            gpu_module(self, 119+(i % 5)*(cw+4), 27+(i//5)*21, cw, 17,
                       'fault' if health != 'HEALTHY' else 'busy' if owner else 'available', owner['code'] if owner else None,
                       body_tags=('summary-gpu',), summary=True)
        ink(self, g_end+16, 6, 'POWER / 가용 전력', 9, MUTED, True)
        ink(self, g_end+16, 28, f'{self.values["power_available"]:02d}', 24, CYAN, True)
        battery(self, g_end+94, 29, p_end-g_end-111, 27, self.values['power_available'], power_total)
        ink(self, 14, 62, f'사용 {self.values["gpu_used"]} · 장애 미점유 {self.values["gpu_unavailable"]}', 8, MUTED)
        ink(self, g_end+16, 62, f'사용 {self.values["power_used"]} · 장애 미점유 {self.values["power_unavailable"]}', 8, MUTED)
        cell = (w-p_end)/3
        for i, (label, key) in enumerate((('운영 서버','active_servers'), ('진행 작업','jobs'), ('네트워크 경고','network'))):
            x = p_end+cell*(i+.5)
            ink(self, x, 9, label, 9, MUTED, anchor='n')
            ink(self, x, 30, str(self.values[key]), 22,
                '#ffbf69' if key == 'network' and self.values[key] else TEXT, True, anchor='n')
        ink(self, p_end+8, 62, f'장비 사용 불가 {self.values["hardware"]}대', 8, RED if self.values['hardware'] else MUTED)


class LiveServerRoom(tk.Canvas):
    def __init__(self, parent, session, on_select):
        super().__init__(parent, bg='#0a1421', highlightthickness=1, highlightbackground=EDGE, takefocus=True)
        self.session, self.on_select = session, on_select
        self.selected, self.timer, self.phase = 'A', None, 0
        self.rack_bounds = {}
        self.extra_canvases = []
        self.bind('<Configure>', lambda _: self.redraw())
        self.bind('<Destroy>', lambda e: self.stop() if e.widget == self else None)
        for key, step in (('<Left>',-1),('<Right>',1),('<Up>',-2),('<Down>',2)):
            self.bind(key, lambda _, n=step: self.select(SERVERS[(next(i for i,s in enumerate(SERVERS) if s.key==self.selected)+n)%4].key))

    def select(self, key):
        self.selected = key
        self.focus_set()
        self.redraw()
        self.on_select(key)

    def redraw(self):
        self.delete('all'); reset_hardware(self)
        self.views = server_views(self.session)
        w, h = self.winfo_width(), self.winfo_height()
        if min(w, h) < 80:
            return
        self.columns = 4 if w >= 620 else 2
        rows = 1 if self.columns == 4 else 2
        ink(self, 12, 9, 'ULSAN / SERVER FLOOR', 10, TEXT, True)
        rw = (w-28-10*(self.columns-1))/self.columns
        rh = (h-40-10*(rows-1))/rows
        self.rack_bounds.clear()
        for i, v in enumerate(self.views):
            x, y = 14+(i % self.columns)*(rw+10), 29+(i//self.columns)*(rh+10)
            spec = v['spec']; tag = 'server-'+spec.key; tags=(tag,)
            self.rack_bounds[spec.key] = (x,y,x+rw,y+rh)
            self.create_polygon(x+6,y,x+rw-6,y,x+rw,y+6,x+rw,y+rh-6,x+rw-6,y+rh,x+6,y+rh,x,y+rh-6,x,y+6,
                                fill=SURFACE, outline=RED if v['health'] != 'HEALTHY' else CYAN if spec.key==self.selected else EDGE,
                                width=2, tags=tags+('rack-border',))
            for rail in (x+5, x+rw-7):
                self.create_line(rail,y+24,rail,y+rh-8,fill=EDGE,width=2,tags=tags)
            ink(self,x+12,y+7,spec.name,10,TEXT,True,tags=tags)
            status = v['status'] if v['health'] != 'HEALTHY' else 'NET' if v['network'] else v['status']
            ink(self,x+rw-12,y+10,status,8,RED if v['health'] != 'HEALTHY' else '#ffbf69' if v['network'] else MUTED,anchor='ne',tags=tags)
            tall = self.columns == 4
            mw = min(60,(rw-36)/2) if tall else (rw-30)/4-3
            for j in range(4):
                mx = x+(rw-2*mw-8)/2+(j%2)*(mw+8) if tall else x+12+j*(mw+3)
                my = y+48+(j//2)*32 if tall else y+30
                owner = v['slots'][j] if j < spec.gpu else None
                state = 'empty' if j >= spec.gpu else 'fault' if v['health'] != 'HEALTHY' else 'busy' if owner else 'available'
                gpu_module(self,mx,my,mw,27,state,owner['code'] if owner else None,j,tags=tags,
                           body_tags=('gpu-slot',) if j < spec.gpu else ('spare-bay',))
            names = '/'.join(dict.fromkeys(o['code'].upper() for o in v['owners'])) or '미점유'
            if v['repair_left']:
                names += f' · 복구 {v["repair_left"]}분'
            if v['network'] and v['health'] != 'HEALTHY':
                names += ' · NET'
            if any(o['legacy'] for o in v['owners']):
                names += ' · 호환'
            elif any(o['reconstructed'] for o in v['owners']):
                names += ' · 복원'
            if tall:
                ink(self,x+12,y+29,names,8,CYAN if v['owners'] else MUTED,tags=tags+('owner-label',))
                ink(self,x+12,y+rh-104,'GPU AVAILABLE',8,MUTED,tags=tags)
                ink(self,x+12,y+rh-86,f'{v["gpu_available"]}/{spec.gpu}',20,CYAN,True,tags=tags)
                ink(self,x+12,y+rh-55,f'전력 가용 {v["power_available"]}/{spec.power}',9,TEXT,tags=tags)
                battery(self,x+12,y+rh-31,rw-24,19,v['power_available'],spec.power,tags)
            else:
                ink(self,x+12,y+64,f'GPU {v["gpu_available"]}/{spec.gpu}',11,CYAN,True,tags=tags)
                battery(self,x+rw-96,y+65,83,18,v['power_available'],spec.power,tags)
                ink(self,x+rw-13,y+86,f'전력 {v["power_available"]}/{spec.power}',8,MUTED,anchor='ne',tags=tags)
                ink(self,x+12,y+rh-12,names,9,CYAN if v['owners'] else MUTED,anchor='w',tags=tags+('owner-label',))
            self.tag_bind(tag,'<Button-1>',lambda _, key=spec.key:self.select(key))
        animate_hardware(self,self.phase)

    def start(self):
        if self.timer is None:
            self.timer = self.after(450,self._tick)

    def _tick(self):
        self.timer = None
        self.phase = (self.phase+1)%20
        for canvas in (self,*self.extra_canvases):
            if hasattr(canvas,'gpu_leds'):
                animate_hardware(canvas,self.phase)
        self.start()

    def stop(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None


class LiveInspector(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,bg=PANEL,width=236,height=190,highlightthickness=0)
        self.view = None
        self.bind('<Configure>',lambda _:self.draw())

    def draw(self):
        self.delete('all'); reset_hardware(self)
        if self.view is None:
            return
        v = self.values = self.view; spec=v['spec']; w=self.winfo_width()
        ink(self,10,10,spec.name,14,TEXT,True)
        ink(self,w-10,14,v['status'],9,CYAN if v['owners'] else MUTED,anchor='ne')
        ink(self,10,43,f'GPU 총{spec.gpu} · 사용{v["gpu_used"]} · 가용{v["gpu_available"]}',10,CYAN)
        for i in range(spec.gpu):
            owner=v['slots'][i]
            gpu_module(self,10+i*54,69,49,27,'fault' if v['health'] != 'HEALTHY' else 'busy' if owner else 'available',owner['code'] if owner else None,i,
                       body_tags=('detail-gpu-slot',))
        ink(self,10,111,f'전력 총{spec.power} · 사용{v["power_used"]} · 가용{v["power_available"]}',10,TEXT)
        battery(self,10,137,max(80,w-20),24,v['power_available'],spec.power)
        message = ('네트워크 지연 · 장비 정상' if v['network'] else '이전 저장 호환 · 장비 정상'
                   if any(o['legacy'] for o in v['owners']) else '저장 위치 재구성 · 장비 정상'
                   if any(o['reconstructed'] for o in v['owners']) else '장비 정상 · 물리 장애 없음')
        if v['health'] != 'HEALTHY':
            message = (f'장비 복구 중 · 잔여 {v["repair_left"]}분' if v['repair_left'] else '교육용 서버 장애 · 현재 사용 불가')
        ink(self,10,170,message,9,
            RED if v['health'] != 'HEALTHY' else '#ffbf69' if v['network'] else MUTED)


class ServerPanel(tk.Frame):
    def __init__(self,parent,session):
        super().__init__(parent,bg=PANEL,width=250)
        self.session, self.selected, self.preview_plan = session, 'A', 'performance'
        self.book=ttk.Notebook(self); self.book.pack(fill='both',expand=True)
        inspector=tk.Frame(self.book,bg=PANEL)
        review=tk.Frame(self.book,bg=PANEL,padx=8,pady=6)
        self.book.add(inspector,text='서버 Inspector'); self.book.add(review,text='배정 미리보기')
        self.inspector_frame,self.review_frame=inspector,review
        self.inspector=LiveInspector(inspector); self.inspector.pack(fill='x')
        hardware_controls=tk.Frame(inspector,bg=PANEL)
        hardware_controls.pack(fill='x',padx=3,pady=(0,3))
        self.fault_button=tk.Button(hardware_controls,text='교육용 서버 장애',bg=SURFACE,fg=RED,font=(FONT,8),relief='flat')
        self.repair_button=tk.Button(hardware_controls,text='장비 복구 · 20분',bg=SURFACE,fg=CYAN,font=(FONT,8),relief='flat')
        self.fault_button.pack(side='left',fill='x',expand=True,padx=(0,3))
        self.repair_button.pack(side='left',fill='x',expand=True)
        self.owners=ttk.Treeview(inspector,columns=('client','resources'),show='headings',height=3)
        self.owners.heading('client',text='점유 고객 / 네트워크'); self.owners.heading('resources',text='GPU / 전력')
        self.owners.column('client',width=150,minwidth=80);self.owners.column('resources',width=80,minwidth=60)
        self.owners.pack(fill='both',expand=True)
        self.owners.bind('<MouseWheel>',lambda e:self.owners.yview_scroll(-int(e.delta/120),'units'))
        self.preview_title=tk.Label(review,bg=PANEL,fg=TEXT,font=(FONT,10,'bold'),anchor='w')
        self.preview_title.pack(fill='x')
        self.preview_frame=review
        self.preview=tk.Label(review,bg=PANEL,fg=CYAN,font=(FONT,9),anchor='nw',justify='left',wraplength=225)
        self.preview.pack(fill='x',pady=(6,4))
        self.compare_button=tk.Button(review,text='배정 계획 비교·선택',bg=SURFACE,fg=CYAN,
                                      activebackground=EDGE,activeforeground=TEXT,font=(FONT,9),relief='flat',pady=5)
        self.compare_button.pack(fill='x',pady=(0,5))
        self.plan_text=tk.Text(review,bg='#0b1522',fg=TEXT,font=(FONT,9),height=5,width=1,wrap='word',bd=0)
        self.plan_text.pack(fill='both',expand=True)
        self.refresh()
        self.show_preview()

    def select_server(self,key):
        self.selected=key; self.refresh(); self.book.select(self.inspector_frame)

    def show_preview(self):
        self.book.select(self.review_frame)

    def refresh(self,key=None):
        if key is not None:
            self.preview_plan=key
        views=server_views(self.session)
        self.view=next(v for v in views if v['spec'].key==self.selected)
        self.inspector.view=self.view; self.inspector.draw()
        self.fault_button.configure(state='normal' if self.view['health'] == 'HEALTHY' else 'disabled')
        self.repair_button.configure(state='normal' if self.view['health'] == 'FAULT' else 'disabled')
        self.owners.delete(*self.owners.get_children())
        for o in self.view['owners']:
            note=(' · HW' if o['hardware'] else '')+(' · NET' if o['network'] else '')
            note+= ' · 이전' if o['migration_left'] else ' · 준비' if o['phase']=='recovering' else ''
            self.owners.insert('', 'end',iid=str(o['playthrough_id']),values=(o['company']+note,f'{o["gpu"]} / {o["power"]}'))
        run=self.session.current; s=run.state; c=self.session.center; p=s.plans[self.preview_plan]
        self.compare_button.configure(state='normal' if run.request['status'] in ('new','review','waiting') else 'disabled')
        if s.allocated:
            title='현재 작업 점유 자원'
            text=f'현재 작업 GPU {s.gpu_used} / 전력 {s.power_used}\n{s.plans[s.plan]["label"]} · 진행 {s.progress:.0f}%\n예상 잔여 {s.remaining_minutes}분'
            if self.session.hardware_status(run):
                text+='\n'+self.session.hardware_status(run)
            parts=self.session.servers.allocations[run.playthrough_id].slices
            detail='실제 점유\n'+'\n'.join(f'Server {part.server_id}: GPU {part.gpu} / 전력 {part.power}' for part in parts)
        elif run.request['status'] in ('new','review','waiting') or (s.phase=='finished' and not s.succeeded and not run.followup_closed):
            plan=self.session.allocation_preview(run,self.preview_plan)
            title=f'배정 검토 · {p["label"]}'
            available_gpu,available_power=self.session.servers.available()
            dg,dp=available_gpu-p['gpu'],available_power-p['power']
            result=plan['reason'] if plan['allowed'] else '배정 불가 · '+plan['reason']
            text=f'GPU {p["gpu"]} 필요 / 가용 {available_gpu} → '+(f'잔여 {dg}' if dg>=0 else f'부족 {-dg}')+'\n'
            text+=f'전력 {p["power"]} 필요 / 가용 {available_power} → '+(f'잔여 {dp}' if dp>=0 else f'부족 {-dp}')+'\n'+result+'\n'
            retry=s.phase=='finished'
            estimates={k:(GameState(country=s.country).estimate_minutes(k)+20 if retry else s.estimate_minutes(k)) for k in s.plans}
            text+='\n'.join(f'{short} {estimates[k]}분 → {game_time(self.session.minute+estimates[k])}'
                            for k,short in (('performance','고성능'),('economy','절약형')))
            if run.terms:
                text+='\n'+('기한 내 예상' if self.session.minute+estimates[self.preview_plan]<=run.terms['due'] else '기한 초과 예상')
            detail=self.session.allocation_summary(plan['slices']) if plan['slices'] else '동의 또는 서버 자원 조건을 확인해 주세요.'
        else:
            title='요청 처리 결과'; text='자원 반환 완료 · 현재 점유 없음' if s.phase=='finished' else '요청 종료 · 배정 자원 없음'; detail=s.result_text
        self.preview_title.configure(text=title);self.preview.configure(text=text)
        self.plan_text.configure(state='normal');self.plan_text.delete('1.0','end');self.plan_text.insert('1.0',detail);self.plan_text.configure(state='disabled')
