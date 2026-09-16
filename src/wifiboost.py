#!/usr/bin/env python3
"""WifiBoost Windows 11 Wi-Fi + TCP helper. Not a radio amplifier."""
from __future__ import annotations
import ctypes, json, os, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path
try:
    import customtkinter as ctk
except ImportError:
    print('Install deps first: pip install -r requirements.txt')
    sys.exit(1)
APP_NAME='WifiBoost'
APP_VERSION='1.0.0'
BACKUP_DIR=Path(os.environ.get('LOCALAPPDATA', Path.home()))/'WifiBoost'/'backups'
SAFE_TCP_COMMANDS=[
    ('TCP auto-tuning = normal',['netsh','interface','tcp','set','global','autotuninglevel=normal']),
    ('Disable scaling heuristics',['netsh','interface','tcp','set','heuristics','disabled']),
    ('Enable RSS',['netsh','interface','tcp','set','global','rss=enabled']),
    ('Enable RSC',['netsh','interface','tcp','set','global','rsc=enabled']),
    ('ECN enabled',['netsh','interface','tcp','set','global','ecncapability=enabled']),
    ('TCP Fast Open on',['netsh','interface','tcp','set','global','fastopen=enabled']),
]
WLAN_SUBGROUP='19cbb8fa-5279-450e-9fac-8a3d5fedd0c1'
WLAN_POWER_SETTING='12bbebe6-58d6-4636-95bb-3217ef867c1a'

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin():
    if getattr(sys,'frozen',False):
        params=' '.join(f'"{a}"' if ' ' in str(a) else str(a) for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(None,'runas',sys.executable,params,None,1)
        return
    script=os.path.abspath(sys.argv[0])
    ctypes.windll.shell32.ShellExecuteW(None,'runas',sys.executable,f'"{script}"',None,1)

def run_cmd(args, timeout=45):
    try:
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,creationflags=flags)
        return p.returncode,((p.stdout or '')+(p.stderr or '')).strip()
    except FileNotFoundError:
        return 127,f'Command not found: {args[0]}'
    except subprocess.TimeoutExpired:
        return 124,'Timed out'
    except Exception as e:
        return 1,str(e)

def run_ps(script, timeout=60):
    return run_cmd(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',script],timeout)

def parse_netsh_wlan_interfaces(text):
    info={}
    for raw in text.splitlines():
        if ':' not in raw: continue
        key,_,val=raw.partition(':')
        info[key.strip().lower()]=val.strip()
    return info

class Engine:
    def current_status(self):
        status={'admin':is_admin(),'ssid':'—','state':'—','signal':'—','radio':'—','channel':'—','receive_rate':'—','transmit_rate':'—','adapter':'—','tcp':'—'}
        code,out=run_cmd(['netsh','wlan','show','interfaces'])
        if code==0 and out:
            p=parse_netsh_wlan_interfaces(out)
            status['ssid']=p.get('ssid') or 'Not connected'
            status['state']=p.get('state') or '—'
            status['signal']=p.get('signal') or '—'
            status['radio']=p.get('radio type') or '—'
            status['channel']=p.get('channel') or '—'
            status['receive_rate']=p.get('receive rate (mbps)') or '—'
            status['transmit_rate']=p.get('transmit rate (mbps)') or '—'
            status['adapter']=p.get('name') or '—'
        code,out=run_cmd(['netsh','interface','tcp','show','global'])
        if code==0: status['tcp']=out
        return status
    def list_wifi_adapters(self):
        code,out=run_ps("Get-NetAdapter | Where-Object {$_.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN|802.11'} | Select-Object -ExpandProperty Name")
        if code!=0 or not out.strip(): return []
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    def backup_state(self):
        BACKUP_DIR.mkdir(parents=True,exist_ok=True)
        _,tcp=run_cmd(['netsh','interface','tcp','show','global'])
        _,heur=run_cmd(['netsh','interface','tcp','show','heuristics'])
        _,dns=run_cmd(['netsh','interface','ip','show','dnsservers'])
        path=BACKUP_DIR/f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps({'when':datetime.now().isoformat(timespec='seconds'),'tcp_global':tcp,'heuristics':heur,'dns':dns},indent=2),encoding='utf-8')
        return path
    def apply_tcp_safe(self,log):
        for label,cmd in SAFE_TCP_COMMANDS:
            code,out=run_cmd(cmd)
            log(f"[{'OK' if code==0 else 'FAIL'}] {label}")
            if out:
                for line in out.splitlines()[:4]: log('    '+line)
        for template in ('Internet','InternetCustom'):
            code,out=run_cmd(['netsh','int','tcp','set','supplemental',f'Template={template}','CongestionProvider=cubic'])
            log(f"[{'OK' if code==0 else 'SKIP'}] Congestion CUBIC on {template}")
            if out: log('    '+out.splitlines()[0])
    def apply_wifi_power(self,log):
        for flag in (['/SETACVALUEINDEX','SCHEME_CURRENT',WLAN_SUBGROUP,WLAN_POWER_SETTING,'0'],['/SETDCVALUEINDEX','SCHEME_CURRENT',WLAN_SUBGROUP,WLAN_POWER_SETTING,'0']):
            code,out=run_cmd(['powercfg',*flag])
            log(f"[{'OK' if code==0 else 'FAIL'}] powercfg {flag[0]}")
            if out: log('    '+out)
        run_cmd(['powercfg','/SETACTIVE','SCHEME_CURRENT'])
        ps=r"""
$adapters = Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN|802.11' -and $_.Status -ne 'Disabled' }
foreach ($a in $adapters) {
  try { Disable-NetAdapterPowerManagement -Name $a.Name -ErrorAction SilentlyContinue; Write-Output ('power-mgmt off: ' + $a.Name) } catch { Write-Output ('power-mgmt skip: ' + $a.Name) }
  foreach ($k in @('*PowerSaveMode','PowerSaveMode','*MIMOPowerSaveMode','MIMOPowerSaveMode','RoamAggressiveness')) {
    try {
      $hit = Get-NetAdapterAdvancedProperty -Name $a.Name -RegistryKeyword $k -ErrorAction SilentlyContinue
      if ($hit) { Set-NetAdapterAdvancedProperty -Name $a.Name -RegistryKeyword $k -RegistryValue 0 -ErrorAction Stop; Write-Output ('set ' + $k + ' on ' + $a.Name) }
    } catch { Write-Output ('skip ' + $k) }
  }
}
"""
        code,out=run_ps(ps)
        log(f"[{'OK' if code==0 else 'FAIL'}] adapter advanced properties")
        for line in (out or '').splitlines(): log('    '+line)
    def set_dns(self,provider,log):
        servers={'cloudflare':('1.1.1.1','1.0.0.1'),'google':('8.8.8.8','8.8.4.4'),'quad9':('9.9.9.9','149.112.112.112'),'dhcp':None}
        choice=servers.get(provider)
        adapters=self.list_wifi_adapters()
        if not adapters:
            log('[FAIL] No Wi-Fi adapter found'); return
        for name in adapters:
            safe=name.replace("'","''")
            if choice is None:
                script=f"Set-DnsClientServerAddress -InterfaceAlias '{safe}' -ResetServerAddresses"
                label=f'DNS DHCP on {name}'
            else:
                script=f"Set-DnsClientServerAddress -InterfaceAlias '{safe}' -ServerAddresses '{choice[0]}','{choice[1]}'"
                label=f'DNS {provider} on {name}'
            code,out=run_ps(script)
            log(f"[{'OK' if code==0 else 'FAIL'}] {label}")
            if out: log('    '+out)
    def flush_dns(self,log):
        code,out=run_cmd(['ipconfig','/flushdns']); log(f"[{'OK' if code==0 else 'FAIL'}] flush DNS")
        if out: log('    '+out)
        code,out=run_cmd(['netsh','interface','ip','delete','arpcache']); log(f"[{'OK' if code==0 else 'SKIP'}] clear ARP")
        if out: log('    '+out)
    def restart_wifi(self,log):
        adapters=self.list_wifi_adapters()
        if not adapters:
            log('[FAIL] No Wi-Fi adapter found'); return
        for name in adapters:
            safe=name.replace("'","''")
            log(f"Restarting adapter '{name}'")
            run_ps(f"Disable-NetAdapter -Name '{safe}' -Confirm:$false")
            time.sleep(2)
            code,out=run_ps(f"Enable-NetAdapter -Name '{safe}' -Confirm:$false")
            log(f"[{'OK' if code==0 else 'FAIL'}] enable {name}")
            if out: log('    '+out)
    def reset_stack(self,log):
        code,out=run_cmd(['netsh','winsock','reset']); log(f"[{'OK' if code==0 else 'FAIL'}] winsock reset")
        if out: log('    '+out)
        code,out=run_cmd(['netsh','int','ip','reset']); log(f"[{'OK' if code==0 else 'FAIL'}] ip reset")
        if out:
            for line in out.splitlines()[:8]: log('    '+line)
        self.flush_dns(log)
        log('A reboot is required for winsock/ip reset to finish.')
    def optimize_all(self,dns,log):
        path=self.backup_state(); log(f'Backup saved: {path}')
        self.apply_tcp_safe(log); self.apply_wifi_power(log); self.set_dns(dns,log); self.flush_dns(log)
        return path

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP_NAME} {APP_VERSION}')
        self.geometry('920x680'); self.minsize(820,600)
        ctk.set_appearance_mode('dark'); ctk.set_default_color_theme('blue')
        self.engine=Engine(); self._busy=False
        self.grid_columnconfigure(1,weight=1); self.grid_rowconfigure(0,weight=1)
        side=ctk.CTkFrame(self,width=260,corner_radius=0)
        side.grid(row=0,column=0,sticky='nsew'); side.grid_propagate(False)
        ctk.CTkLabel(side,text='WIFI BOOST',font=ctk.CTkFont(size=22,weight='bold')).pack(pady=(22,4))
        ctk.CTkLabel(side,text='Windows 11 helper\nNot a radio amplifier',justify='center',text_color='#9aa4b2').pack(pady=(0,16))
        self.admin_label=ctk.CTkLabel(side,text=''); self.admin_label.pack(pady=(0,12))
        self.dns_var=ctk.StringVar(value='cloudflare')
        ctk.CTkLabel(side,text='DNS provider').pack(anchor='w',padx=18)
        ctk.CTkOptionMenu(side,variable=self.dns_var,values=['cloudflare','google','quad9','dhcp'],width=220).pack(padx=18,pady=(4,16))
        for text,fn in [('Apply safe optimize',self.on_optimize),('Flush DNS + ARP',self.on_flush),('Restart Wi-Fi adapter',self.on_restart),('Reset Winsock + TCP/IP',self.on_reset),('Refresh status',self.on_refresh)]:
            ctk.CTkButton(side,text=text,command=fn,width=220,height=36).pack(pady=5)
        main=ctk.CTkFrame(self,fg_color='transparent')
        main.grid(row=0,column=1,sticky='nsew',padx=16,pady=16)
        main.grid_columnconfigure((0,1,2),weight=1); main.grid_rowconfigure(3,weight=1)
        self.cards={}
        for i,key in enumerate(('SSID','Signal','Channel','Radio','Rx Mbps','Tx Mbps')):
            card=ctk.CTkFrame(main,height=78)
            card.grid(row=i//3,column=i%3,sticky='nsew',padx=6,pady=6)
            ctk.CTkLabel(card,text=key,text_color='#9aa4b2').pack(anchor='w',padx=12,pady=(10,0))
            val=ctk.CTkLabel(card,text='—',font=ctk.CTkFont(size=18,weight='bold')); val.pack(anchor='w',padx=12,pady=(0,10))
            self.cards[key]=val
        warn=ctk.CTkTextbox(main,height=92)
        warn.grid(row=2,column=0,columnspan=3,sticky='ew',padx=6,pady=8)
        warn.insert('1.0','Can: disable NIC power-save, restore TCP auto-tuning, RSS/RSC/ECN/Fast Open, DNS, flush, restart NIC, reset Winsock.\nCannot: raise ISP cap, fix a jammed 2.4 GHz channel, or increase legal TX power.')
        warn.configure(state='disabled')
        self.log=ctk.CTkTextbox(main); self.log.grid(row=3,column=0,columnspan=3,sticky='nsew',padx=6)
        self._set_admin_badge(); self.after(200,self.on_refresh)
    def _set_admin_badge(self):
        if is_admin(): self.admin_label.configure(text='Running as Administrator',text_color='#3ddc97')
        else: self.admin_label.configure(text='Not elevated — most actions will fail',text_color='#ff6b6b')
    def write_log(self,msg):
        self.log.insert('end',msg+'\n'); self.log.see('end')
    def run_bg(self,fn,need_admin=True):
        if self._busy:
            self.write_log('Already running a task.'); return
        if need_admin and not is_admin():
            self.write_log('Need Administrator.'); return
        self._busy=True
        def worker():
            try: fn()
            except Exception as e:
                self.after(0,lambda err=e: self.write_log(f'[ERROR] {err}'))
            finally:
                self.after(0,lambda: setattr(self,'_busy',False))
        threading.Thread(target=worker,daemon=True).start()
    def fill_status(self,st):
        mapping={'SSID':st.get('ssid','—'),'Signal':st.get('signal','—'),'Channel':st.get('channel','—'),'Radio':st.get('radio','—'),'Rx Mbps':st.get('receive_rate','—'),'Tx Mbps':st.get('transmit_rate','—')}
        for k,v in mapping.items(): self.cards[k].configure(text=v or '—')
        self.write_log('— status —'); self.write_log('Adapter: '+str(st.get('adapter')))
        if st.get('tcp'):
            for line in st['tcp'].splitlines():
                if line.strip(): self.write_log('TCP  '+line.strip())
    def on_refresh(self):
        def job():
            st=self.engine.current_status(); self.after(0,lambda: self.fill_status(st))
        self.run_bg(job,need_admin=False)
    def on_optimize(self):
        dns=self.dns_var.get()
        def job():
            def log(m): self.after(0,lambda m=m: self.write_log(m))
            log('Applying safe optimize...'); self.engine.optimize_all(dns,log)
            log('Done. Re-test speed.'); st=self.engine.current_status(); self.after(0,lambda: self.fill_status(st))
        self.run_bg(job)
    def on_flush(self):
        self.run_bg(lambda: self.engine.flush_dns(lambda m: self.after(0,lambda m=m: self.write_log(m))))
    def on_restart(self):
        def job():
            self.engine.restart_wifi(lambda m: self.after(0,lambda m=m: self.write_log(m)))
            time.sleep(3); st=self.engine.current_status(); self.after(0,lambda: self.fill_status(st))
        self.run_bg(job)
    def on_reset(self):
        self.run_bg(lambda: self.engine.reset_stack(lambda m: self.after(0,lambda m=m: self.write_log(m))))

def main():
    if os.name!='nt':
        print('This app is for Windows 11.')
    if os.name=='nt' and not is_admin():
        try:
            relaunch_as_admin(); return
        except Exception:
            pass
    App().mainloop()

if __name__=='__main__':
    main()
