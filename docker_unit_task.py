"""Run the existing unit suite in the isolated test container, never on host."""
import json
import sys
import time
import unittest

sys.path.insert(0,"/app")

def run():
    started=time.monotonic()
    suite=unittest.defaultTestLoader.discover("/app/tests",top_level_dir="/app/tests")
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    return {"version":"docker-unit-v1","status":"ok" if result.wasSuccessful() and result.testsRun>0 else "error",
            "tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
            "skipped":len(result.skipped),"unexpected_successes":len(result.unexpectedSuccesses),
            "failed_tests":[str(test)[:240] for test,_ in (result.failures+result.errors)][:30],
            "elapsed_seconds":round(time.monotonic()-started,3)}

if __name__=="__main__":
    print("BTC_LAB_REPORT "+json.dumps(run(),ensure_ascii=True,allow_nan=False),flush=True)
