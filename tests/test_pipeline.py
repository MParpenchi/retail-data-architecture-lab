import tempfile
import unittest
from pathlib import Path
from src.pipeline import build, validate, analytics

class RetailPipelineTests(unittest.TestCase):
    def test_reproducibility_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            build(customers=12,orders=50,seed=9,root=root)
            self.assertEqual(validate(root),50)
            metrics,months,cats=analytics(root)
            self.assertEqual(metrics['orders']+metrics['cancelled_orders'],50)
            self.assertGreaterEqual(len(months),1)
            self.assertAlmostEqual(sum(c['revenue_eur'] for c in cats),metrics['revenue_eur'],places=1)
            original=(root/'data'/'orders.jsonl').read_bytes()
            build(customers=12,orders=50,seed=9,root=root)
            self.assertEqual(original,(root/'data'/'orders.jsonl').read_bytes())

if __name__=='__main__':unittest.main()
