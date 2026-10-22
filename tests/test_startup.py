import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .test_records import DatabaseFixture,ROOT
from app.server import InstanceLock

class StartupTest(DatabaseFixture):
    def test_lifecycle_lock_is_exclusive_and_released(self):
        first=InstanceLock(Path(self.tmp.name))
        second=InstanceLock(Path(self.tmp.name))
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
        finally:
            first.release();second.release()

    def test_concurrent_start_reuses_one_server(self):
        folder=Path(self.tmp.name)/'concurrent';folder.mkdir()
        gate=folder/'start'
        code="import time;from pathlib import Path;from app.server import run;"+"\nwhile not Path("+repr(str(gate))+").exists():time.sleep(.01)\nrun(open_browser=False,data_dir="+repr(str(folder))+")"
        processes=[subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        connection=None
        try:
            gate.touch();deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if (folder/'runtime.json').exists() and sum(p.poll() is not None for p in processes)==1: break
                time.sleep(.05)
            self.assertEqual(sum(p.poll() is not None for p in processes),1,'第二次启动应复用运行中的实例并退出')
            info=json.loads((folder/'runtime.json').read_text())
            connection=http.client.HTTPConnection('127.0.0.1',info['port'],timeout=5)
            connection.request('GET','/api/bootstrap');boot=json.loads(connection.getresponse().read())
            connection.request('POST','/api/shutdown',b'{}',{'X-StockFold-Token':boot['token'],'Content-Type':'application/json'})
            self.assertEqual(connection.getresponse().status,200)
            outputs=[p.communicate(timeout=5) for p in processes]
            self.assertEqual(outputs[0][0].strip(),outputs[1][0].strip())
            self.assertTrue(all(p.returncode==0 for p in processes),outputs)
        finally:
            if connection: connection.close()
            for p in processes:
                if p.poll() is None:p.terminate()
                p.communicate(timeout=5)
