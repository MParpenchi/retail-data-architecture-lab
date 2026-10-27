"""Optional real NoSQL step: import documents and read indexed order aggregates."""
import json
import os
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    try:from pymongo import MongoClient,InsertOne
    except ImportError:raise SystemExit('Install pymongo: pip install pymongo')
    client=MongoClient(os.getenv('MONGO_URI','mongodb://localhost:27017/'),serverSelectionTimeoutMS=3000)
    client.admin.command('ping')
    collection=client['retail_lab']['orders']
    collection.drop()
    batch=[]
    for line in (ROOT/'data'/'orders.jsonl').open(encoding='utf-8'):
        batch.append(InsertOne(json.loads(line)))
        if len(batch)>=1000:collection.bulk_write(batch,ordered=False);batch=[]
    if batch:collection.bulk_write(batch,ordered=False)
    collection.create_index('order_id',unique=True)
    collection.create_index('customer_id')
    t=time.perf_counter_ns();doc=collection.find_one({'order_id':3200},{'_id':0});ms=(time.perf_counter_ns()-t)/1e6
    print(json.dumps({'document_count':collection.count_documents({}),'example_order_items':len(doc['items']),'indexed_single_find_ms_example':round(ms,3),'note':'One measured request; not statistically reliable or cross-system benchmark.'},indent=2))
    client.close()
if __name__=='__main__':main()
