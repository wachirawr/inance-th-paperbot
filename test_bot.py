import os
import tempfile
import unittest
from unittest import mock
import bot

class PaperBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = mock.patch.object(bot,'DB',bot.Path(self.tmp.name)/'paperbot.db')
        self.db.start()
        self.cfg = {'symbols':['BTCTHB','ETHTHB','SOLTHB'],'trade_symbol':'BTCTHB','poll_seconds':60,'initial_cash':100000.0,
                    'order_thb':2000.0,'fee_rate':0.0025,'slip_rate':0.0005,'stop_loss':.02,'take_profit':.04,'interval':'15m',
                    'telegram_token':'','telegram_chat_id':''}
        self.conn=bot.connect(self.cfg)
    def tearDown(self):
        self.conn.close()
        self.db.stop()
        self.tmp.cleanup()
    def test_books(self):
        self.assertEqual(bot.parse_book({'bidPrice':'100.1','askPrice':'100.2'}),(100.1,100.2))
        with self.assertRaises(ValueError):
            bot.parse_book({'bidPrice':'102','askPrice':'100'})
    def test_up_crossover(self):
        # Last candle moves short above long.
        a = [100.0]*21 + [120.0]
        self.assertEqual(bot.crossover(a),'BUY')
    def test_down_crossover(self):
        a = [100.0]*21 + [80.0]
        self.assertEqual(bot.crossover(a),'SELL')
    def test_reject_nonpaper(self):
        with mock.patch.dict(os.environ,{'MODE':'LIVE'}):
            with self.assertRaises(ValueError): bot.conf()
    def test_roundtrip_costs_and_persistence(self):
        self.assertIsNotNone(bot.trade(self.conn,self.cfg,'BUY',100,101,'TEST'))
        self.assertGreater(float(bot.value(self.conn,'qty')),0)
        self.assertLess(float(bot.value(self.conn,'cash')),100000)
        buy_total=float(bot.value(self.conn,'entry_total'))
        self.assertGreater(buy_total,2000)
        bot.trade(self.conn,self.cfg,'SELL',100,101,'TEST')
        self.assertEqual(float(bot.value(self.conn,'qty')),0)
        self.assertLess(float(bot.value(self.conn,'cash')),100000)
        self.conn.close()
        self.conn=bot.connect(self.cfg)
        self.assertLess(float(bot.value(self.conn,'cash')),100000)
    def test_closed_candles(self):
        now=10000000
        rows=[[0,'1','1','1','100','1',now-10000], [0,'1','1','1','90','1',now-1000]]
        self.assertEqual(len(bot.closed_candles(rows,now)),1)
    def test_one_cycle_no_real_calls(self):
        base=int(bot.time.time()*1000)
        # 22 candles with all identical price; no initial trade.
        rows=[(base-(23-i)*900000, 100.0) for i in range(22)]
        with mock.patch.object(bot,'fetch_book',return_value=(100.0,101.0)),mock.patch.object(bot,'fetch_candles',return_value=rows):
            bot.run_cycle(self.conn,self.cfg,send=False)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM samples').fetchone()[0],3)

if __name__=='__main__': unittest.main()
