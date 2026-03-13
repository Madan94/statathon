import json
import datetime
import numpy as np


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class AuditLogger:

    def __init__(self, logfile="audit_log.json"):
        self.logfile = logfile
        self.records = []

    def log(self, event_type, data, step=None):
        record = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "event": event_type,
            "data": data,
        }
        if step is not None:
            record["step"] = step
        self.records.append(record)
        with open(self.logfile, "a") as f:
            f.write(json.dumps(record, cls=NumpyEncoder) + "\n")

    def get_records(self, event_type=None):
        if event_type is None:
            return self.records
        return [r for r in self.records if r["event"] == event_type]

    def clear(self):
        self.records = []
        open(self.logfile, "w").close()