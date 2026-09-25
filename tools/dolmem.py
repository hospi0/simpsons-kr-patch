# -*- coding: utf-8 -*-
"""돌핀 프로세스에 붙어 게임큐브 RAM(MEM1)을 직접 읽고 쓴다.

돌핀은 스크립트 API가 없다. Dolphin Memory Engine 이 쓰는 것과 같은 방법으로
«돌핀 프로세스 안에 매핑된 24MB MEM1 뷰»를 찾아 ReadProcessMemory 로 읽는다.

  from dolmem import Dolphin
  d = Dolphin()                 # 자동 부착
  d.u32(0x80000000)             # GC 주소로 읽기
  d.write(0x80345678, b'...')

★찾는 법: VirtualQueryEx 로 «크기 0x2000000 · MEM_MAPPED» 구간을 훑고,
  GC RAM 규약으로 **검증**한다 — 오프셋 0x00 에 게임ID(6자), 0x1C 에 매직 0xC2339F3D.
  크기만 보고 고르면 그래픽 버퍼 등을 잡는다.
"""
import ctypes as C
from ctypes import wintypes as W

k32 = C.WinDLL('kernel32', use_last_error=True)
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
MEM_MAPPED, MEM_COMMIT = 0x40000, 0x1000
MEM1_SIZE = 0x2000000
MAGIC = 0xC2339F3D
# ★★★ 이 게임(심슨 GC)은 MMU 가상 메모리를 쓴다 — 힙 객체가 게스트 0x7E000000~0x80000000 에 있다.
#     돌핀은 그 영역을 «fake VMEM» 이라는 별도 32MB 매핑으로 흉내낸다(MEM1 과 다른 host 주소).
#     MEM1 뷰로 읽으면 같은 오프셋의 «코드»가 나오므로 반드시 구분해야 한다.
VMEM_LO, VMEM_HI = 0x7E000000, 0x80000000


class MEMORY_BASIC_INFORMATION64(C.Structure):
    _fields_ = [('BaseAddress', C.c_ulonglong), ('AllocationBase', C.c_ulonglong),
                ('AllocationProtect', W.DWORD), ('__alignment1', W.DWORD),
                ('RegionSize', C.c_ulonglong), ('State', W.DWORD),
                ('Protect', W.DWORD), ('Type', W.DWORD), ('__alignment2', W.DWORD)]


k32.OpenProcess.restype = W.HANDLE
k32.VirtualQueryEx.restype = C.c_size_t


def _pids(name='Dolphin.exe'):
    import subprocess
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ' + name, '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    return [int(l.split('","')[1]) for l in out.splitlines() if l.startswith('"')]


class Dolphin(object):
    def __init__(self, pid=None):
        pids = [pid] if pid else _pids()
        if not pids:
            raise SystemExit('★돌핀이 실행돼 있지 않다(Dolphin.exe)')
        for p in pids:
            h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ |
                                PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, p)
            if not h:
                continue
            base = self._find_mem1(h)
            if base:
                self.h, self.pid, self.base = h, p, base
                return
            k32.CloseHandle(h)
        raise SystemExit('★MEM1 을 못 찾았다 — 게임이 «실행 중»이어야 한다(정지 상태 아님)')

    def _find_mem1(self, h):
        mbi = MEMORY_BASIC_INFORMATION64()
        a = 0
        while a < 0x7FFFFFFFFFFF:
            if not k32.VirtualQueryEx(h, C.c_void_p(a), C.byref(mbi), C.sizeof(mbi)):
                break
            if (mbi.RegionSize == MEM1_SIZE and mbi.State == MEM_COMMIT
                    and mbi.Type == MEM_MAPPED):
                buf = (C.c_char * 0x20)()
                n = C.c_size_t()
                if k32.ReadProcessMemory(h, C.c_void_p(mbi.BaseAddress), buf, 0x20, C.byref(n)):
                    b = bytes(buf)
                    if int.from_bytes(b[0x1C:0x20], 'big') == MAGIC and b[:4].isalnum():
                        return mbi.BaseAddress
            a = mbi.BaseAddress + mbi.RegionSize
        return None

    # ── fake VMEM (게스트 0x7E000000~0x80000000) 매핑 찾기
    def find_vmem(self, sample, ok):
        """sample = 그 영역의 «확실한» 게스트 포인터, ok(bytes)->bool 이 내용을 검증한다.
        32MB MEM_MAPPED 구간을 훑어 sample 이 «말이 되는» 곳을 고른다(MEM1 은 제외)."""
        if getattr(self, 'vbase', None) is not None:
            return self.vbase
        off = sample - VMEM_LO
        mbi = MEMORY_BASIC_INFORMATION64()
        a = 0
        while a < 0x7FFFFFFFFFFF:
            if not k32.VirtualQueryEx(self.h, C.c_void_p(a), C.byref(mbi), C.sizeof(mbi)):
                break
            if (mbi.RegionSize == MEM1_SIZE and mbi.State == MEM_COMMIT
                    and mbi.Type == MEM_MAPPED and mbi.BaseAddress != self.base):
                buf = (C.c_char * 0x40)()
                n = C.c_size_t()
                if k32.ReadProcessMemory(self.h, C.c_void_p(mbi.BaseAddress + off),
                                         buf, 0x40, C.byref(n)) and ok(bytes(buf)):
                    self.vbase = mbi.BaseAddress
                    return self.vbase
            a = mbi.BaseAddress + mbi.RegionSize
        raise SystemExit('★fake VMEM 을 못 찾았다')

    def _host(self, gcaddr):
        if VMEM_LO <= gcaddr < VMEM_HI:
            vb = getattr(self, 'vbase', None)
            if vb is None:
                raise SystemExit('★0x%08X 는 VMEM 영역 — find_vmem() 을 먼저 부를 것' % gcaddr)
            return vb + (gcaddr - VMEM_LO)
        return self.base + (gcaddr & 0x01FFFFFF)

    # ── 기본 읽기/쓰기 (인수는 «GC 주소» 0x80xxxxxx 또는 0x7Exxxxxx)
    def read(self, gcaddr, size):
        buf = (C.c_char * size)()
        n = C.c_size_t()
        if not k32.ReadProcessMemory(self.h, C.c_void_p(self._host(gcaddr)), buf, size, C.byref(n)):
            raise OSError('읽기 실패 0x%08X' % gcaddr)
        return bytes(buf)

    def write(self, gcaddr, data):
        n = C.c_size_t()
        if not k32.WriteProcessMemory(self.h, C.c_void_p(self._host(gcaddr)),
                                      data, len(data), C.byref(n)):
            raise OSError('쓰기 실패 0x%08X' % gcaddr)

    def dump(self):
        """MEM1 24MB 통째로."""
        return self.read(0x80000000, MEM1_SIZE)

    def u8(self, a):  return self.read(a, 1)[0]
    def u16(self, a): return int.from_bytes(self.read(a, 2), 'big')
    def u32(self, a): return int.from_bytes(self.read(a, 4), 'big')
    def s16(self, a):
        v = self.u16(a); return v - 0x10000 if v >= 0x8000 else v
    def s32(self, a):
        v = self.u32(a); return v - 0x100000000 if v >= 0x80000000 else v
    def f32(self, a):
        import struct; return struct.unpack('>f', self.read(a, 4))[0]

    def gameid(self):
        return self.read(0x80000000, 6).decode('latin1')


if __name__ == '__main__':
    d = Dolphin()
    print('부착 성공 — PID %d · MEM1 호스트주소 0x%X' % (d.pid, d.base))
    print('게임ID %s · 디스크명 %s'
          % (d.gameid(), d.read(0x80000020, 0x20).split(b'\0')[0].decode('latin1')))
