"""Reproducible retail dataset: relational OLTP, aggregate JSONL, and BI reporting."""
import argparse
import csv
import json
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = [(f'P{i:03}',cat,round(price,2)) for i,(cat,price) in enumerate(
    [(cat,base+(i%11)*2.75) for cat,base in [('Books',12),('Electronics',45),('Home',20),('Beauty',9),('Sports',24)] for i in range(20)],1)]
REGIONS = ['Milan','Rome','Turin','Bologna','Florence','Naples']

DDL = '''
PRAGMA foreign_keys = ON;
CREATE TABLE customers(customer_id INTEGER PRIMARY KEY, city TEXT NOT NULL, signup_date TEXT NOT NULL);
CREATE TABLE products(product_id TEXT PRIMARY KEY, category TEXT NOT NULL, price_eur REAL NOT NULL);
CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id), placed_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('completed','cancelled')));
CREATE TABLE order_items(order_id INTEGER NOT NULL REFERENCES orders(order_id), line_no INTEGER NOT NULL, product_id TEXT NOT NULL REFERENCES products(product_id), quantity INTEGER NOT NULL CHECK(quantity>0), unit_price_eur REAL NOT NULL, PRIMARY KEY(order_id,line_no));
CREATE INDEX idx_orders_customer ON orders(customer_id,placed_at);
CREATE INDEX idx_orders_placed ON orders(placed_at);
CREATE INDEX idx_items_product ON order_items(product_id);
'''

def build(customers=900, orders=6500, seed=42, root=ROOT):
    if customers < 1 or orders < 1: raise ValueError('customers/orders must be positive')
    randomizer = random.Random(seed)
    data = root/'data'; data.mkdir(parents=True,exist_ok=True)
    db = data/'retail.sqlite'; jsonl = data/'orders.jsonl'
    if db.exists(): db.unlink()
    cn = sqlite3.connect(db)
    cn.executescript(DDL)
    base = datetime(2025,1,1)
    cn.executemany('INSERT INTO customers VALUES(?,?,?)',((i,randomizer.choice(REGIONS),(base-timedelta(days=randomizer.randint(0,700))).date().isoformat()) for i in range(1,customers+1)))
    cn.executemany('INSERT INTO products VALUES(?,?,?)',PRODUCTS)
    orders_rows=[]; item_rows=[]
    with jsonl.open('w',encoding='utf-8') as f:
        for oid in range(1,orders+1):
            cid = randomizer.randint(1,customers)
            dt = base+timedelta(days=randomizer.randrange(365),hours=randomizer.randrange(24),minutes=randomizer.randrange(60))
            status='cancelled' if randomizer.random()<.065 else 'completed'
            lines=[]
            for j in range(1,randomizer.randint(1,5)+1):
                product_id,category,price=randomizer.choice(PRODUCTS)
                qty=randomizer.randint(1,3)
                lines.append({'product_id':product_id,'category':category,'quantity':qty,'unit_price_eur':price})
                item_rows.append((oid,j,product_id,qty,price))
            orders_rows.append((oid,cid,dt.isoformat(timespec='minutes'),status))
            # Order boundary chosen because checkout and order retrieval work at order granularity.
            f.write(json.dumps({'order_id':oid,'customer_id':cid,'placed_at':dt.isoformat(timespec='minutes'),'status':status,'items':lines},ensure_ascii=False)+'\n')
    cn.executemany('INSERT INTO orders VALUES(?,?,?,?)',orders_rows)
    cn.executemany('INSERT INTO order_items VALUES(?,?,?,?,?)',item_rows)
    cn.commit(); cn.close()
    return {'customers':customers,'orders':orders,'order_items':len(item_rows),'seed':seed}

# Counting only completed sales is a business rule, not a technical database requirement.
KPI_SQL='''WITH order_totals AS (
 SELECT o.order_id,o.customer_id,o.placed_at,o.status,ROUND(SUM(i.quantity*i.unit_price_eur),2) total
 FROM orders o JOIN order_items i ON i.order_id=o.order_id GROUP BY o.order_id
) SELECT COUNT(*) orders,ROUND(SUM(total),2) revenue_eur,ROUND(AVG(total),2) aov_eur,
 COUNT(DISTINCT customer_id) unique_customers FROM order_totals WHERE status='completed' '''
MONTH_SQL='''SELECT substr(o.placed_at,1,7) month,ROUND(SUM(i.quantity*i.unit_price_eur),2) revenue_eur
 FROM orders o JOIN order_items i ON i.order_id=o.order_id WHERE o.status='completed'
 GROUP BY substr(o.placed_at,1,7) ORDER BY month'''
CATEGORY_SQL='''SELECT p.category,ROUND(SUM(i.quantity*i.unit_price_eur),2) revenue_eur
 FROM orders o JOIN order_items i ON i.order_id=o.order_id JOIN products p ON p.product_id=i.product_id
 WHERE o.status='completed' GROUP BY p.category ORDER BY revenue_eur DESC'''


def analytics(root=ROOT):
    cn=sqlite3.connect(root/'data'/'retail.sqlite')
    cn.row_factory=sqlite3.Row
    metrics=dict(cn.execute(KPI_SQL).fetchone())
    metrics['cancelled_orders']=cn.execute("SELECT COUNT(*) FROM orders WHERE status='cancelled'").fetchone()[0]
    metrics['repeat_customers']=cn.execute("SELECT COUNT(*) FROM (SELECT customer_id FROM orders WHERE status='completed' GROUP BY customer_id HAVING COUNT(*)>1)").fetchone()[0]
    months=[dict(r) for r in cn.execute(MONTH_SQL)]
    cats=[dict(r) for r in cn.execute(CATEGORY_SQL)]
    out=root/'outputs';out.mkdir(parents=True,exist_ok=True)
    (out/'kpis.json').write_text(json.dumps(metrics,indent=2)+'\n',encoding='utf-8')
    for filename,rows in [('monthly_revenue.csv',months),('category_revenue.csv',cats)]:
        with (out/filename).open('w',newline='',encoding='utf-8') as file:
            writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    cn.close()
    return metrics,months,cats


def validate(root=ROOT):
    cn=sqlite3.connect(root/'data'/'retail.sqlite')
    relational={}
    for oid, cid, dt, status in cn.execute('SELECT order_id,customer_id,placed_at,status FROM orders'):
        relational[oid]=(cid,dt,status)
    if cn.execute('PRAGMA foreign_key_check').fetchall(): raise AssertionError('Broken foreign keys')
    with (root/'data'/'orders.jsonl').open(encoding='utf-8') as f:
        count=0
        for line in f:
            document=json.loads(line);oid=document['order_id'];count+=1
            if (document['customer_id'],document['placed_at'],document['status']) != relational[oid]:
                raise AssertionError(f'Order header mismatch {oid}')
            db_lines=cn.execute('SELECT product_id,quantity,unit_price_eur FROM order_items WHERE order_id=? ORDER BY line_no',(oid,)).fetchall()
            if [(d['product_id'],d['quantity'],d['unit_price_eur']) for d in document['items']]!=db_lines:
                raise AssertionError(f'Order lines mismatch {oid}')
    cn.close()
    if count!=len(relational):raise AssertionError('Order count mismatch')
    return count


def plot(root=ROOT):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    _,months,cats=analytics(root)
    fig, axes=plt.subplots(1,2,figsize=(12,4.4))
    axes[0].plot([m['month'] for m in months],[m['revenue_eur'] for m in months],marker='o')
    axes[0].set_title('Monthly completed-order revenue');axes[0].set_ylabel('EUR');axes[0].tick_params(axis='x',rotation=45)
    axes[1].barh([c['category'] for c in reversed(cats)],[c['revenue_eur'] for c in reversed(cats)])
    axes[1].set_title('Revenue by product category');axes[1].set_xlabel('EUR')
    fig.suptitle('Retail Analytics | Synthetic Data',fontsize=13)
    fig.tight_layout();fig.savefig(root/'outputs'/'dashboard.png',dpi=160);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--customers',type=int,default=900);p.add_argument('--orders',type=int,default=6500);p.add_argument('--seed',type=int,default=42);p.add_argument('--skip-plot',action='store_true')
    args=p.parse_args()
    print('Built:',build(args.customers,args.orders,args.seed))
    print('Validated order aggregates:',validate())
    print('Business KPIs:',analytics()[0])
    if not args.skip_plot:
        try:plot();print('Wrote outputs/dashboard.png')
        except ImportError:print('Install matplotlib for optional chart')
