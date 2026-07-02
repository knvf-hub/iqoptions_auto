import unittest

from app.telegram_integration import candidate_symbols_for_active, normalize_active, parse_signal


class TelegramParserTests(unittest.TestCase):
    def test_sala_blitz_active_label_maps_to_otc_pair(self) -> None:
        message = """
        👑 Thailand ⚡

        ⚡ Fuso horário UTC+7 ⚡

        Active: ⚡ Blitz | PEN/USD OTC
        Expiration: M1
        Direction: VENDA
        Time: 08:17
        """
        parsed = parse_signal(message)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.active_raw, "PEN/USD OTC")
        self.assertEqual(parsed.direction, "put")
        self.assertEqual(parsed.expiration, "M1")
        self.assertEqual(normalize_active(parsed.active_raw), "PENUSD-OTC")
        self.assertEqual(candidate_symbols_for_active(parsed.active_raw)[0], "PENUSD-OTC")

    def test_sala_binary_active_label_maps_to_otc_pair(self) -> None:
        message = """
        👑 Thailand ⚡

        ⚡ Fuso horário UTC+7 ⚡

        Active: 🇫🇷 Binária | ONDOUSD OTC
        Expiration: M1
        Direction: COMPRA
        Time: 08:46
        """
        parsed = parse_signal(message)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.active_raw, "ONDOUSD OTC")
        self.assertEqual(parsed.direction, "call")
        self.assertEqual(normalize_active(parsed.active_raw), "ONDOUSD-OTC")
        self.assertEqual(candidate_symbols_for_active(parsed.active_raw)[0], "ONDOUSD-OTC")

    def test_existing_sala_active_format_still_maps(self) -> None:
        parsed = parse_signal(
            """
            Active: EUR/USD (OTC)
            Expiration: M1
            Direction: CALL
            Time: 09:01
            """
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.active_raw, "EUR/USD (OTC)")
        self.assertEqual(normalize_active(parsed.active_raw), "EURUSD-OTC")
        self.assertEqual(candidate_symbols_for_active(parsed.active_raw)[0], "EURUSD-OTC")


if __name__ == "__main__":
    unittest.main()
