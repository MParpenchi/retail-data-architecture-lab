"""Same order-lookup workload: SQLite JOIN vs sequential JSONL scan; not DB vs DB."""
import json
import sqlite3
import statistics
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL='''SELECT o.order_id,o.customer_id,o.status,i.product_id,i.quantity,i.unit_price_eur FROM orders o JOIN order_items i ON i.order_id=o.order_id WHERE o.order_id=?'''

def run(repetitions=60, order_id=3200):
    cn=sqlite3.connect(ROOT/'data'/'retail.sqlite')
    sql_ms=[];scan_ms=[]
    for _ in range(repetitions):
        t=time.perf_counter_ns();rows=cn.execute(SQL,(order_id,)).fetchall();sql_ms.append((time.perf_counter_ns()-t)/1e6)
        t=time.perf_counter_ns();doc=None
        with (ROOT/'data'/'orders.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                item=json.loads(line)
                if item['order_id']==order_id: doc=item;break
        scan_ms.append((time.perf_counter_ns()-t)/1e6)
        if not rows or doc is None or len(rows)!=len(doc['items']):raise RuntimeError('Mismatch')
    cn.close()
    result={'workload':'single-order lookup','sqlite_indexed_join_median_ms':round(statistics.median(sql_ms),4),'jsonl_sequential_scan_median_ms':round(statistics.median(scan_ms),4),'repetitions':repetitions,'caveat':'SQLite indexed query vs unindexed JSONL file scan; NOT a SQL-vs-NoSQL performance comparison.'}
    (ROOT/'outputs').mkdir(exist_ok=True)
    (ROOT/'outputs'/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result
if __name__=='__main__':run()
