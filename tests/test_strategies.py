import unittest

from app.broker.base import Candle
from app.strategies import (
    DEFAULT_STRATEGY_CONFIG,
    backtest_asset,
    calculate_bollinger_bands,
    candle_body_ratio,
    count_latest_bearish_candles,
    count_latest_bullish_candles,
    get_signal,
    highest_high_before_index,
    lowest_low_before_index,
    strategy_name_for_asset,
    strategy_casinos_put_resistance_wick_rejection,
    strategy_eth_sr_wick_rejection,
    strategy_sp500_sr_bb_exhaustion,
    strategy_usdjpy_streak_exhaustion_reversal,
)


def candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=index * 60, open=open_, high=high, low=low, close=close)


class StrategyHelperTests(unittest.TestCase):
    def test_candle_body_ratio_and_latest_streak_counts(self) -> None:
        candles = [
            candle(0, 10, 11, 9, 9.5),
            candle(1, 9.5, 10, 9, 9.2),
            candle(2, 9.2, 10, 9, 9.8),
            candle(3, 9.8, 10, 9, 10.0),
        ]

        self.assertAlmostEqual(candle_body_ratio(candles[0]), 0.25)
        self.assertEqual(count_latest_bearish_candles(candles, 1, 3), 2)
        self.assertEqual(count_latest_bullish_candles(candles, 3, 3), 2)
        self.assertEqual(highest_high_before_index(candles, 3, 2), 10)
        self.assertEqual(lowest_low_before_index(candles, 3, 2), 9)
        self.assertIsNotNone(calculate_bollinger_bands(candles, 3, 3, 2))

    def test_usdjpy_signal_uses_closed_current_candle_only(self) -> None:
        candles = [candle(i, 100 - i, 101 - i, 99 - i, 99.5 - i) for i in range(7)]
        next_candle = candle(7, 93, 120, 80, 120)
        signal = strategy_usdjpy_streak_exhaustion_reversal(candles + [next_candle], 6, DEFAULT_STRATEGY_CONFIG)
        changed_future = candle(7, 93, 90, 70, 70)
        signal_with_changed_future = strategy_usdjpy_streak_exhaustion_reversal(
            candles + [changed_future],
            6,
            DEFAULT_STRATEGY_CONFIG,
        )

        self.assertEqual(signal.action, "call")
        self.assertEqual(signal.reason, "usdjpy_call_bearish_streak_exhaustion")
        self.assertEqual(signal_with_changed_future.action, signal.action)
        self.assertEqual(signal_with_changed_future.reason, signal.reason)

    def test_casinos_put_rejection_signal(self) -> None:
        candles = [candle(i, 9.7, 10.0, 9.5, 9.8) for i in range(20)]
        candles.append(candle(20, 9.80, 10.0, 9.70, 9.72))
        signal = strategy_casinos_put_resistance_wick_rejection(candles, 20, DEFAULT_STRATEGY_CONFIG)

        self.assertEqual(signal.action, "put")
        self.assertEqual(signal.reason, "casinos_put_resistance_wick_rejection")

    def test_strategy_selector_and_backtest_for_new_assets(self) -> None:
        usdjpy = [candle(i, 100 - i, 101 - i, 99 - i, 99.5 - i) for i in range(7)]
        usdjpy.append(candle(7, 93, 94, 92, 93.5))
        self.assertEqual(get_signal("USDJPY-OTC", usdjpy, 6).action, "call")

        casinos = [candle(i, 9.7, 10.0, 9.5, 9.8) for i in range(20)]
        casinos.append(candle(20, 9.80, 10.0, 9.70, 9.72))
        casinos.append(candle(21, 9.72, 9.75, 9.50, 9.55))
        result = backtest_asset("CASINOS-OTC", casinos, DEFAULT_STRATEGY_CONFIG)

        self.assertEqual(result["strategy_name"], "put_resistance_wick_rejection")
        self.assertEqual(result["overall"]["total_trades"], 1)
        self.assertEqual(result["overall"]["wins"], 1)
        self.assertEqual(result["overall"]["put_count"], 1)

    def test_adaptive_fx_assets_use_asset_specific_strategy(self) -> None:
        candles = [candle(i, 100.0, 100.05, 99.95, 100.0) for i in range(90)]
        candles.append(candle(90, 100.02, 100.08, 99.94, 100.07))
        signal = get_signal("GBPJPY-OTC", candles, 90)

        self.assertEqual(strategy_name_for_asset("GBPJPY-OTC"), "adaptive_fx_sr_momentum")
        self.assertEqual(signal.action, "call")
        self.assertEqual(signal.reason, "adaptive_fx_call_support_wick_rejection")

    def test_eth_and_sp500_support_rejection_signals(self) -> None:
        eth = [candle(i, 15, 20, 10, 15.5) for i in range(150)]
        eth.append(candle(150, 15, 18, 10, 17.8))
        eth_signal = strategy_eth_sr_wick_rejection(eth, 150, DEFAULT_STRATEGY_CONFIG)
        self.assertEqual(eth_signal.action, "call")
        self.assertEqual(eth_signal.reason, "eth_call_support_wick_rejection")

        sp500 = [candle(i, 15, 20, 10, 15.5) for i in range(30)]
        sp500.append(candle(30, 15, 18, 10, 17.8))
        sp500_signal = strategy_sp500_sr_bb_exhaustion(sp500, 30, DEFAULT_STRATEGY_CONFIG)
        self.assertEqual(sp500_signal.action, "call")
        self.assertEqual(sp500_signal.reason, "sp500_call_support_wick_rejection")

        sp500.append(candle(31, 17.8, 18.2, 17.5, 18.0))
        result = backtest_asset("SP500-OTC", sp500, DEFAULT_STRATEGY_CONFIG)
        self.assertEqual(result["strategy_name"], "sp500_sr_bb_exhaustion")
        self.assertGreaterEqual(result["overall"]["total_trades"], 1)


if __name__ == "__main__":
    unittest.main()
