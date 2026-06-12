"""Quick backend boot test."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as m
all_routes = [r.path for r in m.app.routes if hasattr(r, 'path')]
rb_routes = [p for p in all_routes if '/report-builder' in p]
ds_routes = [p for p in all_routes if '/datasets' in p]
an_routes = [p for p in all_routes if '/analysis' in p]
auth_routes = [p for p in all_routes if '/auth' in p]
ws_routes = [p for p in all_routes if '/ws' in p or 'websocket' in str(p).lower()]

print(f"Backend OK")
print(f"  Total routes        : {len(all_routes)}")
print(f"  Auth routes         : {len(auth_routes)}")
print(f"  Dataset routes      : {len(ds_routes)}")
print(f"  Analysis routes     : {len(an_routes)}")
print(f"  Report Builder route: {len(rb_routes)}")
print(f"  WebSocket routes    : {len(ws_routes)}")
