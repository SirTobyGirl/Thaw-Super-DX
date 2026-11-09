"""Persistent virtual Xbox360 gamepad. Commands (one per line) on scratchpad/vk.fifo: A B X Y Start Select Guide Up Down Left Right quit"""
import fcntl,os,struct,sys,time
S=os.path.dirname(os.path.abspath(__file__)); FIFO=S+'/vk.fifo'
UI_SET_EVBIT=0x40045564; UI_SET_KEYBIT=0x40045565; UI_SET_ABSBIT=0x40045567; UI_DEV_SETUP=0x405c5503; UI_ABS_SETUP=0x401c5504; UI_DEV_CREATE=0x5501
BTN={'A':0x130,'B':0x131,'X':0x133,'Y':0x134,'L1':0x136,'R1':0x137,'Select':0x13a,'Start':0x13b,'Guide':0x13c,'L3':0x13d}
HAT={'Up':(0x11,-1),'Down':(0x11,1),'Left':(0x10,-1),'Right':(0x10,1)}
fd=os.open('/dev/uinput',os.O_WRONLY|os.O_NONBLOCK)
fcntl.ioctl(fd,UI_SET_EVBIT,1); fcntl.ioctl(fd,UI_SET_EVBIT,3)
for c in BTN.values(): fcntl.ioctl(fd,UI_SET_KEYBIT,c)
def absax(code,mn,mx,fuzz=0,flat=0):
    fcntl.ioctl(fd,UI_SET_ABSBIT,code)
    fcntl.ioctl(fd,UI_ABS_SETUP,struct.pack('=Hxxiiiiii',code,0,mn,mx,fuzz,flat,0))
for c in (0,1,3,4): absax(c,-32768,32767,16,128)
for c in (2,5): absax(c,0,255)
for c in (0x10,0x11): absax(c,-1,1)
fcntl.ioctl(fd,UI_DEV_SETUP,struct.pack('=HHHH80sI',3,0x045e,0x028e,0x0110,b'Microsoft X-Box 360 pad',0))
fcntl.ioctl(fd,UI_DEV_CREATE)
def ev(t,c,v): os.write(fd,struct.pack('llHHi',0,0,t,c,v))
if os.path.exists(FIFO): os.remove(FIFO)
os.mkfifo(FIFO)
while True:
    with open(FIFO) as f:
        for line in f:
            k=line.strip()
            if k=='quit': sys.exit(0)
            if k=='SaveState':
                for b in ('Select','R1'): ev(1,BTN[b],1)
                ev(0,0,0); time.sleep(0.3)
                for b in ('Select','R1'): ev(1,BTN[b],0)
                ev(0,0,0); time.sleep(0.5)
            elif k in BTN: ev(1,BTN[k],1); ev(0,0,0); time.sleep(0.15); ev(1,BTN[k],0); ev(0,0,0); time.sleep(0.25)
            elif k in HAT: c,v=HAT[k]; ev(3,c,v); ev(0,0,0); time.sleep(0.15); ev(3,c,0); ev(0,0,0); time.sleep(0.25)
